#!/usr/bin/env python3
"""Descarga todo el historial de Garmin Connect a datos-garmin/ (carpeta privada, fuera del repo).

Uso:
    tools/garmin/.venv/bin/python tools/garmin/garmin_sync.py            # todo, reanudable
    tools/garmin/.venv/bin/python tools/garmin/garmin_sync.py --desde 2020-01-01
    tools/garmin/.venv/bin/python tools/garmin/garmin_sync.py --sin-fit  # sin archivos FIT originales

Credenciales: Llavero de macOS, servicio "garminconnect" (cuenta = tu email). Solo se usan
la primera vez; después se reutilizan los tokens de ~/.garminconnect.
Es reanudable: guarda lo ya descargado en datos-garmin/estado.json y en una nueva ejecución
solo pide lo que falta (y siempre refresca las últimas semanas).
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "datos-garmin"
RAW = OUT / "raw"
STATE = OUT / "estado.json"
TOKENS = Path("~/.garminconnect").expanduser()
KEYCHAIN_SERVICE = "garminconnect"
PAUSA = 0.8          # segundos entre llamadas: ritmo humano, evita bloqueos
REFRESCO_DIAS = 21   # los tramos que tocan las últimas 3 semanas se vuelven a pedir siempre

log = logging.getLogger("garmin")


# ----------------------------------------------------------------------------- utilidades
def iso(d: date) -> str:
    return d.isoformat()


def guardar(path: Path, data) -> None:
    if data is None and "actividades" in path.parts:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def cargar_estado() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"tramos": {}, "actividades": {}, "errores": {}}


def credenciales() -> tuple[str, str]:
    """Lee email y contraseña del Llavero de macOS (nunca de un archivo)."""
    try:
        info = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE],
                              capture_output=True, text=True, check=True).stdout
        pwd = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except subprocess.CalledProcessError:
        sys.exit("No encontré la contraseña en el Llavero. Ejecuta una vez en Terminal:\n"
                 f'  security add-generic-password -s {KEYCHAIN_SERVICE} -a "TU_EMAIL_GARMIN" -w\n'
                 "(te pedirá la contraseña dos veces, sin mostrarla)")
    email = next((ln.split("=", 1)[1].strip().strip('"') for ln in info.splitlines()
                  if '"acct"' in ln), None)
    if not email or not pwd:
        sys.exit("La entrada del Llavero no tiene email o contraseña.")
    return email, pwd


def conectar() -> Garmin:
    if (TOKENS / "garmin_tokens.json").exists():
        try:
            g = Garmin()
            g.login(str(TOKENS))
            log.info("Sesión reanudada con tokens guardados.")
            return g
        except (GarminConnectAuthenticationError, GarminConnectConnectionError) as e:
            log.warning("Tokens no válidos (%s); entro con usuario y contraseña.", type(e).__name__)
    email, pwd = credenciales()
    g = Garmin(email, pwd)
    g.login(str(TOKENS))
    TOKENS.chmod(0o700)
    log.info("Sesión iniciada; tokens guardados en %s", TOKENS)
    return g


class Llamador:
    """Ejecuta llamadas con pausa, reintentos ante límite de tasa y registro de errores."""

    def __init__(self, estado: dict):
        self.estado = estado
        self.n = 0
        self.fallo = False   # True si la última llamada terminó en error (no en "sin datos")

    def __call__(self, nombre: str, fn, *args, **kw):
        self.fallo = False
        for intento in range(4):
            time.sleep(PAUSA)
            self.n += 1
            try:
                return fn(*args, **kw)
            except GarminConnectTooManyRequestsError:
                espera = 60 * (intento + 1)
                log.warning("Límite de Garmin en %s; espero %ss…", nombre, espera)
                time.sleep(espera)
            except GarminConnectNotFoundError:
                return None
            except GarminConnectAuthenticationError:
                raise
            except Exception as e:  # endpoint no soportado por tu reloj/cuenta, 400, etc.
                self.estado["errores"][nombre] = f"{type(e).__name__}: {str(e)[:200]}"
                self.fallo = True
                log.debug("%s falló: %s", nombre, e)
                return None
        raise GarminConnectTooManyRequestsError(f"Límite persistente en {nombre}")


# ----------------------------------------------------------------------------- qué se descarga
# Series por rango de fechas: (carpeta, días por tramo, función)
SERIES = [
    ("resumen_diario",        28, lambda g, s, e: g.get_daily_summaries(s, e)),
    ("pasos",                 28, lambda g, s, e: g.get_daily_steps(s, e)),
    ("pisos",                 28, lambda g, s, e: g.get_daily_floors_stats(s, e)),
    ("calorias",              28, lambda g, s, e: g.get_calories_daily(s, e)),
    ("fc_diaria",             28, lambda g, s, e: g.get_daily_heart_rate_stats(s, e)),
    ("fc_reposo",             28, lambda g, s, e: g.get_rhr_daily(s, e)),
    ("estres",                28, lambda g, s, e: g.get_daily_stress_stats(s, e)),
    ("body_battery",          28, lambda g, s, e: g.get_daily_body_battery_stats(s, e)),
    ("minutos_intensidad",    28, lambda g, s, e: g.get_daily_intensity_minutes_stats(s, e)),
    ("respiracion",           28, lambda g, s, e: g.get_daily_respiration_stats(s, e)),
    ("sueno",                 28, lambda g, s, e: g.get_sleep_daily(s, e)),
    ("hrv",                   28, lambda g, s, e: g.get_hrv_data_range(s, e)),
    ("preparacion",           28, lambda g, s, e: g.get_training_readiness_range(s, e)),
    ("estado_entrenamiento",  28, lambda g, s, e: g.get_weekly_training_status(s, e)),
    ("vo2max",                28, lambda g, s, e: g.get_max_metrics_range(s, e)),
    ("edad_fitness",          28, lambda g, s, e: g.get_fitness_age_daily(s, e)),
    ("resistencia",           28, lambda g, s, e: g.get_endurance_score(s, e, aggregation="daily")),
    ("hill_score",            28, lambda g, s, e: g.get_hill_score(s, e)),
    ("ftp_ciclismo",          90, lambda g, s, e: g.get_functional_threshold_power_range(s, e, sport="CYCLING")),
    ("potencia_peso",         90, lambda g, s, e: g.get_power_to_weight_range(s, e)),
    ("capacidad_ciclismo",    90, lambda g, s, e: g.get_cycling_ability_range(s, e)),
    ("peso",                  90, lambda g, s, e: g.get_weigh_ins(s, e)),
    ("composicion",           90, lambda g, s, e: g.get_body_composition(s, e)),
    ("biometria",             90, lambda g, s, e: g.get_biometric_stats(s, e)),
    ("presion",               90, lambda g, s, e: g.get_blood_pressure(s, e)),
    ("curva_potencia_anual", 365, lambda g, s, e: g.get_power_curve(s, e, sport="cycling")),
]

# Fotos del perfil completo (se reescriben en cada ejecución)
PERFIL = [
    ("perfil_base",         lambda g: g.get_user_profile_base()),
    ("info_personal",       lambda g: g.get_personal_information()),
    ("perfil_usuario",      lambda g: g.get_user_profile()),
    ("totales_vida",        lambda g: g.get_lifetime_totals()),
    ("estadisticas",        lambda g: g.get_user_statistics()),
    ("biometria_actual",    lambda g: g.get_current_biometrics()),
    ("ftp_actual",          lambda g: g.get_cycling_ftp()),
    ("zonas_fc",            lambda g: g.get_heart_rate_zones_v2()),
    ("zonas_potencia",      lambda g: g.get_power_zones()),
    ("dispositivos",        lambda g: g.get_devices()),
    ("records_personales",  lambda g: g.get_personal_record(include_history=True)),
    ("primer_peso",         lambda g: g.get_first_weight()),
    ("ultimo_sync",         lambda g: g.get_sync_timestamp()),
]


def tramos(desde: date, hasta: date, dias: int):
    d = desde
    while d <= hasta:
        fin = min(d + timedelta(days=dias - 1), hasta)
        yield d, fin
        d = fin + timedelta(days=1)


# ----------------------------------------------------------------------------- pasos
def bajar_perfil(g, call):
    for nombre, fn in PERFIL:
        data = call(f"perfil.{nombre}", fn, g)
        if data is not None:
            guardar(RAW / "perfil" / f"{nombre}.json", data)


def bajar_lista_actividades(g, call) -> list[dict]:
    todas, inicio = [], 0
    while True:
        pag = call("actividades.lista", g.get_activities, inicio, 100) or []
        if isinstance(pag, dict):
            pag = pag.get("activityList") or []
        if not pag:
            break
        todas.extend(pag)
        inicio += len(pag)
        log.info("  %d actividades listadas…", len(todas))
    guardar(RAW / "actividades" / "lista.json", todas)
    return todas


def fecha_inicio_auto(actividades: list[dict]) -> date:
    fechas = []
    for a in actividades:
        s = (a.get("startTimeLocal") or "")[:10]
        if len(s) == 10:
            fechas.append(s)
    perfil = RAW / "perfil" / "primer_peso.json"
    if perfil.exists():
        txt = perfil.read_text()
        for clave in ('"calendarDate": "', '"date": "'):
            i = txt.find(clave)
            if i >= 0:
                fechas.append(txt[i + len(clave): i + len(clave) + 10])
    validas = [f for f in fechas if f[:2] in ("19", "20")]
    if not validas:
        return date(2012, 1, 1)
    return max(date.fromisoformat(min(validas)) - timedelta(days=30), date(2008, 1, 1))


def bajar_series(g, call, estado, desde: date, hasta: date):
    limite_refresco = hasta - timedelta(days=REFRESCO_DIAS)
    for nombre, dias, fn in SERIES:
        hechos = set(estado["tramos"].get(nombre, []))
        pendientes = [(s, e) for s, e in tramos(desde, hasta, dias)
                      if iso(s) not in hechos or e >= limite_refresco]
        if not pendientes:
            continue
        log.info("%-22s %3d tramos", nombre, len(pendientes))
        fallos_seguidos = 0
        for s, e in pendientes:
            data = call(f"{nombre}.{iso(s)}", fn, g, iso(s), iso(e))
            if call.fallo:
                fallos_seguidos += 1
                if fallos_seguidos >= 4:
                    log.info("  %s no está disponible para tu cuenta; lo salto.", nombre)
                    break
                continue
            fallos_seguidos = 0
            estado["errores"].pop(f"{nombre}.{iso(s)}", None)
            guardar(RAW / nombre / f"{iso(s)}.json", data)
            if e < limite_refresco:
                hechos.add(iso(s))
            estado["tramos"][nombre] = sorted(hechos)
        guardar(STATE, estado)


def bajar_actividades(g, call, estado, actividades: list[dict], con_fit: bool):
    pendientes = [a for a in actividades if str(a.get("activityId")) not in estado["actividades"]]
    log.info("Detalle de actividades: %d pendientes de %d", len(pendientes), len(actividades))
    for i, a in enumerate(pendientes, 1):
        aid = str(a["activityId"])
        tipo = ((a.get("activityType") or {}).get("typeKey") or "").lower()
        carpeta = RAW / "actividades" / aid
        guardar(carpeta / "resumen.json", call("act.resumen", g.get_activity, aid))
        guardar(carpeta / "zonas_fc.json", call("act.zonas_fc", g.get_activity_hr_in_timezones, aid))
        guardar(carpeta / "vueltas.json", call("act.vueltas", g.get_activity_splits, aid))
        if a.get("avgPower") or "cycling" in tipo or "biking" in tipo:
            guardar(carpeta / "zonas_potencia.json", call("act.zonas_pot", g.get_activity_power_in_timezones, aid))
            guardar(carpeta / "curva_potencia.json", call("act.curva_pot", g.get_activity_power_curve, aid))
        if "strength" in tipo or "fuerza" in tipo:
            guardar(carpeta / "series_fuerza.json", call("act.series", g.get_activity_exercise_sets, aid))
        if con_fit:
            fit = call("act.fit", g.download_activity, aid, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
            if fit:
                (OUT / "fit").mkdir(parents=True, exist_ok=True)
                (OUT / "fit" / f"{aid}.zip").write_bytes(fit)
        estado["actividades"][aid] = (a.get("startTimeLocal") or "")[:10]
        if i % 10 == 0 or i == len(pendientes):
            guardar(STATE, estado)
            log.info("  %d/%d actividades", i, len(pendientes))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", help="fecha inicial YYYY-MM-DD (por defecto: tu primera actividad)")
    ap.add_argument("--sin-fit", action="store_true", help="no descargar archivos FIT originales")
    ap.add_argument("--sin-actividades", action="store_true", help="solo datos diarios y perfil")
    ap.add_argument("-v", action="store_true", help="más detalle")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for ruidoso in ("urllib3", "garminconnect", "curl_cffi"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    OUT.mkdir(exist_ok=True)
    estado = cargar_estado()
    call = Llamador(estado)
    t0 = time.time()
    try:
        g = conectar()
        log.info("Perfil…")
        bajar_perfil(g, call)
        log.info("Lista de actividades…")
        actividades = bajar_lista_actividades(g, call)
        desde = date.fromisoformat(args.desde) if args.desde else fecha_inicio_auto(actividades)
        hasta = date.today()
        log.info("Series diarias desde %s hasta %s", desde, hasta)
        bajar_series(g, call, estado, desde, hasta)
        if not args.sin_actividades:
            bajar_actividades(g, call, estado, actividades, con_fit=not args.sin_fit)
    except GarminConnectAuthenticationError as e:
        sys.exit(f"Garmin rechazó el inicio de sesión: {e}")
    except GarminConnectTooManyRequestsError as e:
        log.error("Garmin está limitando las consultas (%s). Lo descargado quedó guardado; vuelve a ejecutar más tarde.", e)
    finally:
        estado["ultima_ejecucion"] = datetime.now().isoformat(timespec="seconds")
        guardar(STATE, estado)
    log.info("Listo: %d llamadas en %.0f min. Datos en %s", call.n, (time.time() - t0) / 60, OUT)
    if estado["errores"]:
        tipos = sorted({k.split(".")[0] for k in estado["errores"]})
        log.info("Sin datos o no soportado en: %s", ", ".join(tipos))


if __name__ == "__main__":
    main()
