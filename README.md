# Watts & Kilos — app personal para iPhone

Versión instalable (PWA) del artifact «Watts & Kilos». Funciona a pantalla completa desde el ícono de inicio, sin conexión, y guarda los datos **solo en el iPhone** (IndexedDB).

## Estructura

```
app/                  ← lo único que se publica
  index.html          generado por tools/build.py (no editar a mano)
  runtime.js          reemplaza window.claude: base local, Claude por API, compartir archivos
  ajustes.js          panel Ajustes, aviso de respaldo, service worker
  sw.js               modo sin conexión (subir VERSION al publicar cambios)
  manifest.webmanifest, icons/
src/
  base.html           la app original, sin datos personales (editar aquí la lógica y los textos)
tools/
  build.py            src/base.html + parts/ → app/index.html
  parts/              cabecera iOS, barra inferior, paneles Más/Ajustes, lógica de pestañas
migracion/            ← NO publicar (datos personales)
  original-artifact.html          copia del artifact al 2026-11-11
  watt-respaldo-2026-11-11.json   todos tus datos exportados del artifact
  datos/                          los mismos datos, un JSON por documento
```

## Cambiar la app

1. Cambios de lógica/diseño de la app → `src/base.html`; cambios de iPhone → `tools/parts/`.
2. `python3 tools/build.py`
3. Probar local: `cd app && python3 -m http.server 8765` → http://localhost:8765
4. Subir `VERSION` en `app/sw.js`, hacer commit y `git push`: GitHub Actions publica `app/` en https://juguetero.github.io/watt/

## Datos personales

El repo es público y genérico. Tu nombre, fecha de nacimiento, altura, contexto médico y los textos personalizados del plan viven en el **perfil** (`meta/perfil`), que se guarda en el iPhone y viaja dentro del respaldo JSON. Elementos con `data-perfil="clave"` en `src/base.html` se reemplazan por `perfil.textos.clave` al abrir la app. `migracion/` está en `.gitignore`.

## Primer uso en el iPhone

1. Abrir la URL en Safari → Compartir → **Agregar a inicio**.
2. Abrir desde el ícono W&K → Más → Ajustes → **Importar respaldo** → elegir `watt-respaldo-2026-11-11.json` (pasarlo por AirDrop o iCloud Drive).
3. Opcional: pegar la API key de Anthropic para estimar comidas y generar el informe.
4. Exportar un respaldo cada semana (la app avisa si pasan 7 días).

Importante: los datos de la app instalada y los de Safari son almacenamientos distintos; importa el respaldo **dentro de la app instalada**.
