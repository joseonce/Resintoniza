"""Comprime la distribución compilada de Resintoniza en un archivo ZIP.

Excluye deliberadamente cualquier carpeta o archivo de usuario y configuración
(ajustes.json, grabaciones/, perfiles/, cache/, logs/, navegador/) para que,
al descomprimir una actualización sobre una instalación existente, no se
sobreescriba nada del usuario.

Uso:
    python tools/comprimir.py
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from tdt import NOMBRE_APP, VERSION  # noqa: E402

ORIGEN = RAIZ / "build" / "Resintoniza"
DESTINO_ZIP = RAIZ / "build" / f"{NOMBRE_APP}.zip"
DESTINO_VERSION_ZIP = RAIZ / "build" / f"{NOMBRE_APP}-{VERSION}.zip"

# Carpetas y archivos de usuario o configuración que NUNCA deben incluirse
EXCLUIR_PREFIJOS = (
    "data/cache",
    "data/grabaciones",
    "data/perfiles",
    "data/logs",
    "data/navegador",
    "data\\cache",
    "data\\grabaciones",
    "data\\perfiles",
    "data\\logs",
    "data\\navegador",
)

EXCLUIR_NOMBRES = {
    "ajustes.json",
    "LEEME.txt",
    "thumbs.db",
    ".ds_store",
}

EXCLUIR_EXTENSIONES = {
    ".log",
    ".tmp",
    ".bak",
}


def debe_excluir(rel: Path) -> bool:
    rel_str = str(rel).replace("\\", "/")
    # Comprobar carpetas de usuario y configuración en data/
    for prefijo in EXCLUIR_PREFIJOS:
        if rel_str.startswith(prefijo.replace("\\", "/")):
            return True
    # Comprobar archivos de configuración en data/
    if rel_str.startswith("data/") and (rel.suffix.lower() == ".json" or "ajustes" in rel.name.lower()):
        return True
    # Archivos residuales o temporales
    if rel.name.lower() in EXCLUIR_NOMBRES:
        return True
    if rel.suffix.lower() in EXCLUIR_EXTENSIONES:
        return True
    return False


def comprimir() -> Path:
    if not ORIGEN.exists():
        raise SystemExit(f"No existe la carpeta compilada: {ORIGEN}. Ejecuta antes: python setup_cx.py build_exe")

    print(f"Comprimiendo desde: {ORIGEN}")
    print(f"Destino: {DESTINO_ZIP}")
    print("Excluyendo carpetas de usuario y configuración: data/cache, data/grabaciones, data/perfiles, data/logs, data/navegador y ajustes.json")

    archivos_incluidos = []
    archivos_excluidos = []

    for elemento in ORIGEN.rglob("*"):
        if not elemento.is_file():
            continue
        rel = elemento.relative_to(ORIGEN)
        if debe_excluir(rel):
            archivos_excluidos.append(rel)
        else:
            archivos_incluidos.append((elemento, rel))

    DESTINO_ZIP.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(DESTINO_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for absoluto, rel in archivos_incluidos:
            # En el zip usamos siempre barras normales
            arcname = str(rel).replace("\\", "/")
            zf.write(absoluto, arcname)

    # También crear copia con versión para distribución
    import shutil
    shutil.copy2(DESTINO_ZIP, DESTINO_VERSION_ZIP)

    tamano_mb = DESTINO_ZIP.stat().st_size / (1024 * 1024)
    print(f"\n¡Comprimido con éxito!")
    print(f"  Archivo generado: {DESTINO_ZIP} ({tamano_mb:.2f} MB)")
    print(f"  Copia versionada: {DESTINO_VERSION_ZIP}")
    print(f"  Archivos incluidos: {len(archivos_incluidos)}")
    print(f"  Archivos/carpetas de usuario excluidos: {len(archivos_excluidos)}")
    if archivos_excluidos:
        print("  Elementos excluidos protegidos:")
        for exc in archivos_excluidos:
            print(f"    - {exc}")

    return DESTINO_ZIP


if __name__ == "__main__":
    comprimir()
