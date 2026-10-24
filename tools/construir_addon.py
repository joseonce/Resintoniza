# -*- coding: utf-8 -*-
"""Empaqueta el complemento de NVDA (``nvda_addon/``) en un archivo .nvda-addon.

Un .nvda-addon no es más que un ZIP con el ``manifest.ini`` en la raíz y las
carpetas de código del complemento. Se genera en ``data/bin`` para que:

- la compilación lo incluya (``setup_cx.py`` copia toda la carpeta ``data``), y
- el botón de Herramientas pueda instalarlo, generándolo al vuelo si falta al
  ejecutar desde el código fuente.

Uso: ``python tools/construir_addon.py`` o ``construir_addon()`` desde la app.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ORIGEN = RAIZ / "nvda_addon"
NOMBRE = "resintonizaListViewFix"


def _version() -> str:
    """Versión de la aplicación, para mantener sincronizado el manifiesto."""
    try:
        texto = (RAIZ / "tdt" / "__init__.py").read_text(encoding="utf-8")
        coincidencia = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', texto)
        if coincidencia:
            return coincidencia.group(1)
    except OSError:
        pass
    return "1.0.0"


def construir_addon(destino: Path | str | None = None, origen: Path | str | None = None) -> Path:
    """Genera el archivo .nvda-addon y devuelve su ruta."""
    carpeta_origen = Path(origen) if origen else ORIGEN
    carpeta_destino = Path(destino) if destino else RAIZ / "data" / "bin"
    carpeta_destino.mkdir(parents=True, exist_ok=True)
    manifiesto = (carpeta_origen / "manifest.ini").read_text(encoding="utf-8")
    manifiesto = re.sub(r"(?m)^version\s*=.*$", "version = " + _version(), manifiesto)
    ruta = carpeta_destino / (NOMBRE + ".nvda-addon")
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as paquete:
        paquete.writestr("manifest.ini", manifiesto)
        base = carpeta_origen / "globalPlugins"
        for archivo in sorted(base.rglob("*")):
            if archivo.is_dir() or archivo.suffix in (".pyc", ".pyo") or "__pycache__" in archivo.parts:
                continue
            paquete.write(archivo, str(archivo.relative_to(carpeta_origen)).replace("\\", "/"))
    return ruta


if __name__ == "__main__":
    print("Complemento de NVDA generado en:", construir_addon())
