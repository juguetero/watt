#!/usr/bin/env python3
"""Genera app/index.html a partir de src/base.html (la app original, sin datos personales)
aplicando los cambios para iPhone. Re-ejecutable: siempre parte de la base.

    python3 tools/build.py
"""
import pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'src' / 'base.html'
OUT = ROOT / 'app' / 'index.html'
PARTS = ROOT / 'tools' / 'parts'

body = SRC.read_text(encoding='utf-8')

def must_replace(text, old, new, count=1):
    n = text.count(old)
    if n != count:
        sys.exit(f'Se esperaban {count} ocurrencias, hay {n}: {old[:70]!r}')
    return text.replace(old, new)

def part(name):
    return (PARTS / name).read_text(encoding='utf-8')

# 2) Navegación: pestañas superiores → barra inferior estilo iOS
nav_old = re.search(r'  <nav class="tabs" role="tablist">.*?</nav>\n', body, re.S).group(0)
body = body.replace(nav_old, '')

# 3) Paneles nuevos (Más, Ajustes) + barra inferior, antes del cierre de .wrap
last_section_end = body.rfind('</section>') + len('</section>')
body = body[:last_section_end] + '\n\n' + part('panels.html') + body[last_section_end:]
script_idx = body.index('<script>')
body = body[:script_idx] + part('tabbar.html') + '\n<script src="runtime.js"></script>\n' + body[script_idx:]

# 4) Lógica de pestañas: cualquier elemento con data-tab navega
tabs_old = re.search(r"  // ---------- Tabs ----------\n.*?\n  \}\);\n", body, re.S).group(0)
body = body.replace(tabs_old, part('tabs.js'))

# 5) Textos que hablaban de "esta vista" de Claude
body = must_replace(body, "'La función de IA no está disponible en esta vista.'",
                    "'Agrega tu API key de Anthropic en Más → Ajustes para usar Claude.'", 2)
body = must_replace(body, "'La estimación con Claude no está disponible en esta vista. Usa la biblioteca o agrega filas a mano.'",
                    "'Para estimar con Claude agrega tu API key en Más → Ajustes. Mientras tanto usa la biblioteca o agrega filas a mano.'")
body = must_replace(body, "'Conectado — tus registros se guardan'", "'Guardado en este iPhone'")
body = must_replace(body, "'No diste permiso para usar Claude en esta página.'",
                    "'Falta la API key o no es válida (Más → Ajustes).'", 2)

# 6) Ajustes JS al final
body = must_replace(body, '</body></html>', '<script src="ajustes.js"></script>\n</body></html>')

head = part('head.html')
OUT.write_text(head + body, encoding='utf-8')
print(f'OK → {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)')
