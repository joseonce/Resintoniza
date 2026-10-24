"""Copias de seguridad y perfiles de uso.

Una copia de seguridad es un archivo ZIP con los ajustes, los favoritos, el
orden personal, las plantillas de lectura, los recordatorios, las grabaciones
programadas y los perfiles guardados. Sirve para llevárselo a otro equipo o
para volver atrás si algo se estropea.

Un perfil es un juego completo de ajustes con nombre (por ejemplo «casa» y
«trabajo»), con sus favoritos y su orden. Cambiar de perfil guarda el actual y
carga el otro.
"""
from __future__ import annotations

import json
import logging
import re
import time
import zipfile
from pathlib import Path

from . import VERSION
from .datos import guardar_json_atomico, validar_ajustes

registro = logging.getLogger(__name__)
NOMBRE_AJUSTES = "ajustes.json"
NOMBRE_INFO = "resintoniza.json"
CARPETA_PERFILES = "perfiles"
EXTENSION = ".resintoniza.zip"


def carpeta_perfiles(datos) -> Path:
    ruta = datos.raiz / CARPETA_PERFILES
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _archivo_perfil(datos, nombre: str) -> Path:
    limpio = re.sub(r"[^A-Za-z0-9áéíóúüñÁÉÍÓÚÜÑ _\-]", "", (nombre or "").strip())[:40].strip()
    if not limpio:
        raise ValueError("El perfil necesita un nombre.")
    return carpeta_perfiles(datos) / (limpio + ".json")


def listar_perfiles(datos) -> list[str]:
    return sorted(ruta.stem for ruta in carpeta_perfiles(datos).glob("*.json"))


def guardar_perfil(datos, nombre: str) -> Path:
    """Guarda los ajustes actuales como perfil ``nombre``."""
    ruta = _archivo_perfil(datos, nombre)
    guardar_json_atomico(ruta, datos.ajustes)
    return ruta


def cargar_perfil(datos, nombre: str) -> dict:
    """Devuelve los ajustes del perfil, ya validados. Lanza ValueError si no sirve."""
    ruta = _archivo_perfil(datos, nombre)
    if not ruta.exists():
        raise ValueError(f"No existe el perfil «{nombre}».")
    return validar_ajustes(json.loads(ruta.read_text(encoding="utf-8-sig")))


def eliminar_perfil(datos, nombre: str) -> bool:
    ruta = _archivo_perfil(datos, nombre)
    if not ruta.exists():
        return False
    ruta.unlink()
    return True


def nombre_copia() -> str:
    return "resintoniza-" + time.strftime("%Y%m%d-%H%M") + EXTENSION


def crear_copia(datos, destino: Path) -> Path:
    """Escribe la copia de seguridad en ``destino`` y devuelve su ruta."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    info = {"aplicacion": "Resintoniza", "version": VERSION, "fecha": int(time.time())}
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as copia:
        copia.writestr(NOMBRE_INFO, json.dumps(info, ensure_ascii=False, indent=2))
        copia.writestr(NOMBRE_AJUSTES, json.dumps(datos.ajustes, ensure_ascii=False, indent=2))
        for perfil in carpeta_perfiles(datos).glob("*.json"):
            copia.write(perfil, f"{CARPETA_PERFILES}/{perfil.name}")
    return destino


def leer_copia(origen: Path) -> tuple[dict, list[str]]:
    """(ajustes validados, nombres de los perfiles incluidos). Lanza ValueError si no vale."""
    origen = Path(origen)
    try:
        with zipfile.ZipFile(origen) as copia:
            nombres = copia.namelist()
            if NOMBRE_AJUSTES not in nombres:
                raise ValueError("El archivo no contiene los ajustes de la aplicación.")
            ajustes = validar_ajustes(json.loads(copia.read(NOMBRE_AJUSTES).decode("utf-8-sig")))
            perfiles = [Path(n).stem for n in nombres if n.startswith(CARPETA_PERFILES + "/") and n.endswith(".json")]
        return ajustes, sorted(perfiles)
    except zipfile.BadZipFile as error:
        raise ValueError("El archivo no es una copia de seguridad válida.") from error


def restaurar(datos, origen: Path, con_perfiles: bool = True) -> dict:
    """Sustituye los ajustes por los de la copia. Devuelve los ajustes nuevos.

    Antes de tocar nada deja una copia del estado actual en la carpeta de datos.
    """
    ajustes, _perfiles = leer_copia(origen)
    guardar_json_atomico(datos.raiz / "ajustes-antes-de-restaurar.json", datos.ajustes)
    if con_perfiles:
        with zipfile.ZipFile(Path(origen)) as copia:
            for nombre in copia.namelist():
                if not nombre.startswith(CARPETA_PERFILES + "/") or not nombre.endswith(".json"):
                    continue
                destino = carpeta_perfiles(datos) / Path(nombre).name
                try:
                    destino.write_bytes(copia.read(nombre))
                except OSError as error:
                    registro.warning("No se pudo restaurar el perfil %s: %s", nombre, error)
    return ajustes
