"""Aviso de versiones nuevas de la propia aplicación.

La comprobación es opcional y se apoya en un archivo JSON publicado por quien
distribuye la aplicación, con esta forma::

    {"version": "1.1.0",
     "url": "https://ejemplo/resintoniza-1.1.0.zip",
     "notas": "Grabación programada y listas M3U.",
     "obligatoria": false}

Mientras no se configure una dirección en los ajustes no se conecta a ningún
sitio: la aplicación lo dice claramente en lugar de fingir que está al día.
"""
from __future__ import annotations

import logging
import re

from . import VERSION
from .datos import descargar_json, url_http

registro = logging.getLogger(__name__)


def numeros(version: str) -> tuple[int, ...]:
    """«1.10.2-beta» → (1, 10, 2). Sirve para comparar versiones."""
    trozos = re.findall(r"\d+", (version or "").split("+")[0])
    return tuple(int(t) for t in trozos[:4]) or (0,)


def es_mas_nueva(candidata: str, actual: str = VERSION) -> bool:
    nueva, vieja = numeros(candidata), numeros(actual)
    longitud = max(len(nueva), len(vieja))
    nueva += (0,) * (longitud - len(nueva))
    vieja += (0,) * (longitud - len(vieja))
    return nueva > vieja


def normalizar_url(url: str) -> str:
    """Convierte URLs web de GitHub en endpoints de la API de Releases."""
    limpia = (url or "").strip()
    if not limpia:
        return ""
    # Convierte ej. https://github.com/usuario/repo/releases... a https://api.github.com/repos/usuario/repo/releases/latest
    coincidencia = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/(?:releases|tree|blob).*)?/?$", limpia, re.IGNORECASE)
    if coincidencia:
        usuario, repo = coincidencia.group(1), coincidencia.group(2)
        return f"https://api.github.com/repos/{usuario}/{repo}/releases/latest"
    return limpia


def comprobar(url: str, actual: str = VERSION) -> dict:
    """Consulta el manifiesto. Devuelve un diccionario con el resultado.

    Claves: ``hay`` (bool), ``version``, ``url``, ``notas``, ``error`` y
    ``configurada`` (False si todavía no hay dirección de comprobación).
    """
    vacio = {"hay": False, "version": "", "url": "", "notas": "", "error": "", "configurada": bool(url)}
    if not url:
        return vacio
    url = normalizar_url(url)
    if not url_http(url):
        return {**vacio, "error": "La dirección de comprobación debe empezar por https:// o http://."}
    try:
        datos = descargar_json(url, timeout=15)
    except Exception as error:
        registro.info("No se pudo comprobar la versión: %s", error)
        return {**vacio, "error": str(error)}
    if not isinstance(datos, dict):
        return {**vacio, "error": "El archivo de versiones no tiene el formato esperado."}
    # Admite formato propio ('version') y la API de GitHub Releases ('tag_name')
    version = str(datos.get("version") or datos.get("tag_name") or "").strip()
    if version.lower().startswith("v") and len(version) > 1 and version[1].isdigit():
        version = version[1:]
    if not version:
        return {**vacio, "error": "El archivo de versiones no indica ninguna versión."}

    # Dirección de descarga: si es GitHub Releases, buscar el asset .zip
    destino = str(datos.get("url") or datos.get("html_url") or "").strip()
    if isinstance(datos.get("assets"), list):
        for asset in datos["assets"]:
            if isinstance(asset, dict) and str(asset.get("name", "")).lower().endswith(".zip"):
                download_url = str(asset.get("browser_download_url") or "").strip()
                if download_url:
                    destino = download_url
                    break

    notas = str(datos.get("notas") or datos.get("body") or "").strip()
    return {
        "hay": es_mas_nueva(version, actual),
        "version": version,
        "url": destino if url_http(destino) else "",
        "notas": notas,
        "error": "",
        "configurada": True,
    }


def resumen(resultado: dict, actual: str = VERSION) -> str:
    """Frase para la barra de estado y para el diálogo."""
    if not resultado.get("configurada"):
        return "La comprobación de versiones nuevas no está configurada; puedes indicar la dirección en Ajustes."
    if resultado.get("error"):
        return "No se pudo comprobar si hay una versión nueva: " + resultado["error"]
    if resultado.get("hay"):
        notas = " " + resultado["notas"] if resultado.get("notas") else ""
        return f"Hay una versión nueva: {resultado['version']} (tienes la {actual})." + notas
    return f"La aplicación está al día: versión {actual}."
