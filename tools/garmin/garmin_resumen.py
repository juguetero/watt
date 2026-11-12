#!/usr/bin/env python3
"""Convierte datos-garmin/raw/ en tablas limpias y en un respaldo importable por la app.

Salidas (todo en datos-garmin/, carpeta privada):
    resumen/diario.csv        una fila por día (pasos, FC reposo, sueño, estrés, VO2max, peso, FTP…)
    resumen/actividades.csv   una fila por actividad (duración, FC, potencia, NP, TSS, efectos…)
    watt-garmin-AAAA-MM-DD.json  para la app: Más → Ajustes → Importar respaldo (Combinar)

Uso: python3 tools/garmin/garmin_resumen.py   (solo librería estándar)
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
G = ROOT / "datos-garmin"
RAW = G / "raw"
OUT = G / "resumen"


def archivos(serie: str):
    for f in sorted((RAW / serie).glob("*.json")):
        try:
            yield json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue


def lista(x):
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        for k in ("data", "dailyWeightSummaries", "dateWeightList"):
            if isinstance(x.get(k), list):
                return x[k]
    return []


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


dias: dict[str, dict] = defaultdict(dict)


def put(fecha, campo, valor):
    if fecha and valor is not None:
        dias[fecha[:10]][campo] = valor


# ---------------------------------------------------------------- series diarias
for x in archivos("resumen_diario"):
    for d in lista(x):
        f = d.get("calendarDate")
        mv, cal, hr = d.get("movement") or {}, d.get("calories") or {}, d.get("heartRate") or {}
        im, st = d.get("intensityMinutes") or {}, d.get("stress") or {}
        put(f, "pasos", num((mv.get("steps") or {}).get("value")))
        put(f, "distancia_km", round(num((mv.get("steps") or {}).get("distanceInMeters")) / 1000, 2) if num((mv.get("steps") or {}).get("distanceInMeters")) else None)
        put(f, "pisos", num((mv.get("floorsAscended") or {}).get("value")))
        put(f, "kcal_total", num(cal.get("burnedTotal")))
        put(f, "kcal_activas", num(cal.get("burnedActive")))
        put(f, "kcal_reposo", num(cal.get("burnedResting")))
        put(f, "fc_reposo", num(hr.get("restingValue")))
        put(f, "fc_min", num(hr.get("minValue")))
        put(f, "fc_max", num(hr.get("maxValue")))
        put(f, "min_moderados", num(im.get("moderate")))
        put(f, "min_vigorosos", num(im.get("vigorous")))
        put(f, "estres_prom", num(st.get("avgLevel")))
        put(f, "estres_alto_min", round(num(st.get("highStressDurationInMillis")) / 60000) if num(st.get("highStressDurationInMillis")) else None)
        bb = d.get("bodyBattery") or {}
        put(f, "body_battery_max", num(bb.get("maxValue") or bb.get("highestValue")))
        put(f, "body_battery_min", num(bb.get("minValue") or bb.get("lowestValue")))

# Rellenos desde las series específicas (cuando el resumen no lo trae)
for x in archivos("fc_reposo"):
    for d in lista(x):
        f = d.get("calendarDate")
        if f and "fc_reposo" not in dias.get(f, {}):
            put(f, "fc_reposo", num(d.get("value")))
for x in archivos("pasos"):
    for d in lista(x):
        f = d.get("calendarDate")
        if f and "pasos" not in dias.get(f, {}):
            put(f, "pasos", num(d.get("totalSteps")))
for x in archivos("pisos"):
    for d in lista(x):
        f, v = d.get("calendarDate"), d.get("values") or {}
        if f and "pisos" not in dias.get(f, {}):
            put(f, "pisos", num(v.get("wellnessFloorsAscended")))

for x in archivos("sueno"):
    for d in lista(x):
        f, v = d.get("calendarDate"), d.get("values") or {}
        t = num(v.get("totalSleepTimeInSeconds"))
        if t:
            put(f, "sueno_h", round(t / 3600, 2))
            put(f, "sueno_profundo_min", round((num(v.get("deepTime")) or 0) / 60))
            put(f, "sueno_rem_min", round((num(v.get("remTime")) or 0) / 60))
            put(f, "sueno_despierto_min", round((num(v.get("awakeTime")) or 0) / 60))
            put(f, "sueno_score", num(v.get("sleepScoreQuality") or v.get("sleepScore")))
            put(f, "spo2_sueno", num(v.get("spO2")))

for x in archivos("vo2max"):
    for d in lista(x):
        gen = d.get("generic") or {}
        f = gen.get("calendarDate")
        put(f, "vo2max", num(gen.get("vo2MaxPreciseValue") or gen.get("vo2MaxValue")))
        put(f, "edad_fitness", num(gen.get("fitnessAge")))
        cyc = d.get("cycling") or {}
        if cyc:
            put(cyc.get("calendarDate"), "vo2max_ciclismo", num(cyc.get("vo2MaxPreciseValue") or cyc.get("vo2MaxValue")))

for x in archivos("peso"):
    for d in lista(x):
        lw = d.get("latestWeight") or {}
        w = num(lw.get("weight"))
        if w:
            f = d.get("summaryDate") or lw.get("calendarDate")
            put(f, "peso_kg", round(w / 1000, 2))
            put(f, "grasa_pct", num(lw.get("bodyFat")))
            put(f, "musculo_kg", round(num(lw.get("muscleMass")) / 1000, 2) if num(lw.get("muscleMass")) else None)

for serie, campo in (("ftp_ciclismo", "ftp_w"), ("potencia_peso", "w_kg")):
    for x in archivos(serie):
        for d in lista(x):
            put(d.get("from") or d.get("calendarDate"), campo, num(d.get("value")))

for x in archivos("estado_entrenamiento"):
    for dev, filas in ((x or {}).get("reportData") or {}).items():
        for d in filas or []:
            f = d.get("calendarDate")
            put(f, "carga_semanal", num(d.get("weeklyTrainingLoad")))
            put(f, "estado_entrenamiento", num(d.get("trainingStatus")))
            atl = (d.get("acuteTrainingLoadDTO") or {})
            put(f, "carga_aguda", num(atl.get("dailyTrainingLoadAcute")))
            put(f, "carga_cronica", num(atl.get("dailyTrainingLoadChronic")))

for x in archivos("hrv"):
    for d in lista((x or {}).get("hrvSummaries") if isinstance(x, dict) else x):
        put(d.get("calendarDate"), "hrv_noche", num(d.get("lastNightAvg")))
for x in archivos("preparacion"):
    for d in lista(x):
        put(d.get("calendarDate"), "preparacion", num(d.get("score")))

# ---------------------------------------------------------------- actividades
acts = json.loads((RAW / "actividades" / "lista.json").read_text(encoding="utf-8")) if (RAW / "actividades" / "lista.json").exists() else []
ACT_COLS = ["id", "fecha", "hora", "tipo", "nombre", "duracion_min", "movimiento_min", "distancia_km", "desnivel_m",
            "kcal", "fc_prom", "fc_max", "cadencia_prom", "potencia_prom", "potencia_np", "potencia_max",
            "max_5s", "max_1min", "max_5min", "max_20min", "max_60min", "tss", "if", "carga",
            "efecto_aerobico", "efecto_anaerobico", "etiqueta_efecto", "dispositivo"]
filas_act = []
for a in acts:
    t = a.get("startTimeLocal") or ""
    filas_act.append({
        "id": a.get("activityId"), "fecha": t[:10], "hora": t[11:16],
        "tipo": (a.get("activityType") or {}).get("typeKey"), "nombre": a.get("activityName"),
        "duracion_min": round(a["duration"] / 60, 1) if num(a.get("duration")) else None,
        "movimiento_min": round(a["movingDuration"] / 60, 1) if num(a.get("movingDuration")) else None,
        "distancia_km": round(a["distance"] / 1000, 2) if num(a.get("distance")) else None,
        "desnivel_m": num(a.get("elevationGain")), "kcal": num(a.get("calories")),
        "fc_prom": num(a.get("averageHR")), "fc_max": num(a.get("maxHR")),
        "cadencia_prom": num(a.get("averageBikingCadenceInRevPerMinute") or a.get("averageRunningCadenceInStepsPerMinute")),
        "potencia_prom": num(a.get("avgPower")), "potencia_np": num(a.get("normPower")), "potencia_max": num(a.get("maxPower")),
        "max_5s": num(a.get("maxAvgPower_5")), "max_1min": num(a.get("maxAvgPower_60")), "max_5min": num(a.get("maxAvgPower_300")),
        "max_20min": num(a.get("maxAvgPower_1200") or a.get("max20MinPower")), "max_60min": num(a.get("maxAvgPower_3600")),
        "tss": num(a.get("trainingStressScore")), "if": num(a.get("intensityFactor")), "carga": num(a.get("activityTrainingLoad")),
        "efecto_aerobico": num(a.get("aerobicTrainingEffect")), "efecto_anaerobico": num(a.get("anaerobicTrainingEffect")),
        "etiqueta_efecto": a.get("trainingEffectLabel"), "dispositivo": a.get("deviceId"),
    })
filas_act.sort(key=lambda r: (r["fecha"], r["hora"]))

# ---------------------------------------------------------------- escribir
OUT.mkdir(parents=True, exist_ok=True)
cols = ["fecha"] + sorted({k for d in dias.values() for k in d})
orden = ["fecha", "pasos", "pisos", "distancia_km", "kcal_total", "kcal_activas", "kcal_reposo", "fc_reposo", "fc_min", "fc_max",
         "min_moderados", "min_vigorosos", "estres_prom", "estres_alto_min", "sueno_h", "sueno_profundo_min", "sueno_rem_min",
         "sueno_despierto_min", "sueno_score", "spo2_sueno", "hrv_noche", "preparacion", "body_battery_max", "body_battery_min",
         "vo2max", "vo2max_ciclismo", "edad_fitness", "peso_kg", "grasa_pct", "musculo_kg", "ftp_w", "w_kg",
         "carga_semanal", "carga_aguda", "carga_cronica", "estado_entrenamiento"]
cols = [c for c in orden if c in cols] + [c for c in cols if c not in orden]
con_datos = {f: d for f, d in dias.items() if any(v is not None for v in d.values())}
with open(OUT / "diario.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=cols)
    w.writeheader()
    for f in sorted(con_datos):
        w.writerow({"fecha": f, **con_datos[f]})
with open(OUT / "actividades.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=ACT_COLS)
    w.writeheader()
    w.writerows(filas_act)

# Respaldo para la app: colección "garmin" (la app usa pasos/escalones; el resto queda guardado)
hoy = date.today().isoformat()
app = {}
for f, d in sorted(con_datos.items()):
    doc = {"fecha": f, "fuente": "garmin-connect"}
    if d.get("pasos") is not None:
        doc["pasos"] = d["pasos"]
    if d.get("pisos") is not None:
        doc["escalones"] = d["pisos"]
    for k in ("fc_reposo", "sueno_h", "estres_prom", "kcal_activas", "min_moderados", "min_vigorosos", "vo2max", "peso_kg"):
        if d.get(k) is not None:
            doc[k] = d[k]
    if len(doc) > 2:
        app[f] = doc
respaldo = {"app": "watts-kilos", "formato": 1, "exportado": datetime.now().isoformat(timespec="seconds"),
            "colecciones": {"garmin": app}}
(G / f"watt-garmin-{hoy}.json").write_text(json.dumps(respaldo, ensure_ascii=False), encoding="utf-8")

print(f"diario.csv: {len(con_datos)} días ({min(con_datos, default='-')} → {max(con_datos, default='-')}), {len(cols) - 1} columnas")
print(f"actividades.csv: {len(filas_act)} actividades")
print(f"watt-garmin-{hoy}.json: {len(app)} días para la app")
