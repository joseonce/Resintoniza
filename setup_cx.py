"""Compilación con cx_Freeze.

    python setup_cx.py build_exe

Genera ``build/Resintoniza`` con el ejecutable, Python, wxPython, los
runtimes de Visual C++ (``include_msvcr``) y una copia limpia de ``data``
que solo contiene el reproductor (``data/mpv``). Los ajustes, la caché y
los registros se crean al usar la aplicación.

Junto al ejecutable solo se copia documentación de usuario: ``MANUAL.md``
y ``LICENCIAS.md``. El ``README.md`` y ``MEJORAS.md`` son del proyecto, no
de quien usa el programa, y no se incluyen.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from cx_Freeze import Executable, setup

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
from tdt import NOMBRE_APP, VERSION  # noqa: E402

DESTINO = RAIZ / "build" / "Resintoniza"
DATA_LIMPIA = RAIZ / "build" / "data-limpia"

# Copia limpia de data: la DLL del reproductor, el complemento de NVDA y los avisos sonoros.
shutil.rmtree(DATA_LIMPIA, ignore_errors=True)
(DATA_LIMPIA / "mpv").mkdir(parents=True, exist_ok=True)
origen = RAIZ / "data" / "mpv" / "libmpv-2.dll"
if not origen.exists():
    raise SystemExit("Falta data/mpv/libmpv-2.dll. Ejecuta antes: python main.py --preparar")
shutil.copy2(origen, DATA_LIMPIA / "mpv" / "libmpv-2.dll")
vulkan_origen = RAIZ / "data" / "mpv" / "vulkan-1.dll"
archivos_extra = [
    (str(DATA_LIMPIA), "data"),
    (str(RAIZ / "MANUAL.md"), "MANUAL.md"),
    (str(RAIZ / "LICENCIAS.md"), "LICENCIAS.md"),
    (str(RAIZ / "nvda_addon"), "nvda_addon"),
]
if vulkan_origen.exists():
    shutil.copy2(vulkan_origen, DATA_LIMPIA / "mpv" / "vulkan-1.dll")
    archivos_extra.append((str(vulkan_origen), "vulkan-1.dll"))
sys.path.insert(0, str(RAIZ))
from tools.construir_addon import construir_addon  # noqa: E402

construir_addon(DATA_LIMPIA / "bin")
from tdt import sonidos  # noqa: E402

sonidos.generar(DATA_LIMPIA / "sonidos")
for sub in ("cache", "logs", "grabaciones", "perfiles"):
    (DATA_LIMPIA / sub).mkdir(exist_ok=True)
    (DATA_LIMPIA / sub / "LEEME.txt").write_text("Carpeta creada por la aplicación. Se puede borrar.\n", encoding="utf-8")

import importlib

paquetes_candidatos = [
    "wx", "mpv", "tdt", "accessible_output2", "libloader", "platform_utils", "win32com", "win32api", "pywintypes", "pythoncom", "wx_accessible_webview",
    # Envío a Chromecast; el de DLNA y el descubrimiento de Fire TV no necesitan nada.
    "pychromecast", "zeroconf", "casttube", "google.protobuf", "requests", "urllib3", "idna", "certifi", "charset_normalizer", "ifaddr"
]
paquetes = []
for pkg in paquetes_candidatos:
    try:
        importlib.import_module(pkg)
        paquetes.append(pkg)
    except Exception:
        pass

opciones = {
    "build_exe": str(DESTINO),
    "packages": paquetes,
    # "email" NO se puede excluir: lo usa http.server, que sirve el reproductor de YouTube.
    "excludes": ["tkinter", "unittest", "test", "pydoc", "distutils", "setuptools", "cx_Freeze", "xmlrpc", "curses", "lib2to3", "wx.lib.pubsub", "wx.py", "wx.tools"],
    "includes": ["wx.adv", "wx.html2", "http.server", "email.utils", "xml.etree.ElementTree", "gzip", "wave", "zipfile", "winsound", "shutil", "subprocess", "concurrent.futures", "tools.construir_addon"],
    # Junto al ejecutable solo va documentación de usuario: el manual y las licencias.
    # README.md y MEJORAS.md son documentación técnica del proyecto y se quedan fuera.
    "include_files": archivos_extra,
    "include_msvcr": True,
    "optimize": 1,
    "silent_level": 1,
}

setup(
    name=NOMBRE_APP,
    version=VERSION,
    description="Televisión y radio en directo, accesible",
    options={"build_exe": opciones},
    executables=[Executable("main.py", base="gui", target_name="Resintoniza.exe", copyright="Componentes de terceros: ver LICENCIAS.md")],
)
