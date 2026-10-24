"""Listas M3U y M3U8: el formato que usa el resto del mundo IPTV.

Un archivo M3U extendido empieza por ``#EXTM3U`` y describe cada canal con una
línea ``#EXTINF`` seguida de la dirección de su emisión::

    #EXTM3U url-tvg="https://ejemplo/guia.xml.gz"
    #EXTINF:-1 tvg-id="La1.es" tvg-logo="…" group-title="Generalistas",La 1
    #EXTVLCOPT:http-user-agent=Mozilla/5.0
    https://ejemplo/la1/master.m3u8

No es un estándar formal: son convenciones de Kodi, TiviMate, OTT Navigator y
compañía, así que aquí se lee con tolerancia y se ignora lo que no se entiende.
Se admiten los atributos ``tvg-id`` (enlace con la guía XMLTV), ``tvg-name``,
``tvg-logo``, ``tvg-chno`` (número de canal), ``group-title`` (categoría),
``tvg-language``, ``tvg-country``, ``tvg-shift`` (desfase de la guía) y la
familia ``catchup`` para ver programas ya emitidos, además de las directivas
``#EXTGRP``, ``#EXTVLCOPT`` (cabeceras por canal) y ``#KODIPROP`` (que sirve
para avisar de las emisiones con DRM, que no se pueden reproducir).
"""
from __future__ import annotations

import re

from .catalogo import Canal, Emision, es_directo, es_youtube, url_youtube_navegable

ATRIBUTO = re.compile(r'([A-Za-z0-9_\-]+)\s*=\s*"([^"]*)"')
CABECERAS_VLC = {
    "http-user-agent": "user_agent",
    "http-referrer": "referer",
    "http-referer": "referer",
}
CLAVES_DRM = ("license_type", "license_key", "inputstream.adaptive.license", "widevine", "playready")
MODOS_CATCHUP = ("default", "append", "flussonic", "shift", "xc")
# Marcas que muchas listas (iptv-org entre ellas) añaden al nombre del canal:
# «3Cat Info (1080p) [Geo-blocked]». Se convierten en datos del canal para que
# el nombre quede limpio, se empareje con la guía y se lea bien.
CALIDAD = re.compile(r"\s*\((\d{3,4}p|[24]k|sd|hd|fhd|uhd)\)\s*", re.IGNORECASE)
AVISOS = re.compile(r"\s*\[([^\]]+)\]\s*")


def es_m3u(texto: str) -> bool:
    """True si el texto parece una lista M3U (basta con que traiga una línea ``#EXTINF``)."""
    cabeza = (texto or "")[:8192].lstrip("﻿ \t\r\n")
    return cabeza.startswith("#EXTM3U") or "#EXTINF" in cabeza


def _atributos(texto: str) -> dict[str, str]:
    return {clave.lower(): valor.strip() for clave, valor in ATRIBUTO.findall(texto or "")}


def _entero(valor) -> int:
    try:
        return int(float(str(valor).strip()))
    except (TypeError, ValueError):
        return 0


def _decimal(valor) -> float:
    try:
        return float(str(valor).strip().replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def cabecera(texto: str) -> dict[str, str]:
    """Atributos de la línea ``#EXTM3U`` (por ejemplo ``url-tvg`` con la guía XMLTV)."""
    for linea in (texto or "").splitlines():
        linea = linea.strip().lstrip("﻿")
        if linea.upper().startswith("#EXTM3U"):
            return _atributos(linea)
        if linea and not linea.startswith("#"):
            break
    return {}


def guia_declarada(texto: str) -> str:
    """Dirección de la guía XMLTV que declara la propia lista, si la trae."""
    atributos = cabecera(texto)
    for clave in ("url-tvg", "x-tvg-url", "tvg-url"):
        valor = atributos.get(clave, "").split(",")[0].strip()
        if valor.startswith(("http://", "https://")):
            return valor
    return ""


def _emision(url: str, atributos: dict, geo: bool = False) -> Emision:
    """Clasifica la dirección igual que en las listas JSON, para reutilizar todo lo demás."""
    idioma = atributos.get("tvg-language") or None
    resolucion = atributos.get("tvg-quality") or None
    zona = "ZONA" if geo else None
    if "twitch.tv" in url:
        return Emision("twitch", url, "twitch", geo=zona, idioma=idioma, resolucion=resolucion)
    if es_youtube(url):
        return Emision("youtube", url_youtube_navegable(url), "youtube", geo=zona, idioma=idioma, resolucion=resolucion)
    bajo = url.lower()
    if es_directo(url) or bajo.startswith(("rtmp", "rtsp", "udp", "rtp", "mms")):
        formato = "m3u8" if ".m3u8" in bajo else ("mpd" if ".mpd" in bajo else "stream")
        return Emision("directo", url, formato, geo=zona, idioma=idioma, resolucion=resolucion)
    return Emision("web", url, "web", geo=zona, idioma=idioma, resolucion=resolucion)


def separar_marcas(nombre: str) -> tuple[str, str, bool, bool]:
    """«3Cat Info (1080p) [Geo-blocked]» → («3Cat Info», «1080p», geo, intermitente)."""
    calidad = ""
    coincidencia = CALIDAD.search(nombre or "")
    if coincidencia:
        calidad = coincidencia.group(1).lower()
        nombre = CALIDAD.sub(" ", nombre, count=1)
    geo = intermitente = False
    for aviso in AVISOS.findall(nombre or ""):
        bajo = aviso.lower()
        if "geo" in bajo:
            geo = True
        elif "24/7" in bajo or "not 24" in bajo:
            intermitente = True
    nombre = AVISOS.sub(" ", nombre or "")
    return re.sub(r"\s+", " ", nombre).strip(" -·"), calidad, geo, intermitente


def _modo_catchup(valor: str) -> str:
    valor = (valor or "").strip().lower()
    equivalencias = {"flussonic-hls": "flussonic", "flussonic-ts": "flussonic", "timeshift": "flussonic", "vod": "append"}
    valor = equivalencias.get(valor, valor)
    return valor if valor in MODOS_CATCHUP else ""


def parsear_m3u(texto: str, tipo: str = "tv", origen: str = "", limite: int = 20000) -> list[Canal]:
    """Convierte una lista M3U en canales. Lanza ValueError si no hay ninguno.

    ``tipo`` puede ser ``tv``, ``radio`` o ``auto`` (mira el atributo ``radio``
    de cada entrada y el nombre del grupo).
    """
    if not es_m3u(texto):
        raise ValueError("El archivo no parece una lista M3U: no tiene ninguna línea #EXTINF.")
    canales: list[Canal] = []
    vistos: set[str] = set()
    pendiente: dict | None = None
    for linea in (texto or "").splitlines():
        linea = linea.strip().lstrip("﻿")
        if not linea:
            continue
        if linea.startswith("#EXTINF"):
            cuerpo = linea[len("#EXTINF"):].lstrip(":")
            nombre = cuerpo.split(",", 1)[1].strip() if "," in cuerpo else ""
            atributos = _atributos(cuerpo)
            pendiente = {"nombre": nombre or atributos.get("tvg-name", ""), "atributos": atributos, "vlc": {}, "drm": False, "grupo": ""}
            continue
        if pendiente is None:
            continue
        if linea.startswith("#EXTGRP"):
            pendiente["grupo"] = linea.split(":", 1)[1].strip() if ":" in linea else ""
            continue
        if linea.startswith("#EXTVLCOPT"):
            opcion = linea.split(":", 1)[1] if ":" in linea else ""
            clave, _, valor = opcion.partition("=")
            destino = CABECERAS_VLC.get(clave.strip().lower(), "")
            if destino:
                pendiente["vlc"][destino] = valor.strip()
            continue
        if linea.startswith(("#KODIPROP", "#EXTHTTP")):
            if any(marca in linea.lower() for marca in CLAVES_DRM):
                pendiente["drm"] = True
            continue
        if linea.startswith("#"):
            continue
        # Línea con la dirección: cierra la entrada.
        entrada, pendiente = pendiente, None
        url = linea.strip()
        atributos = entrada["atributos"]
        nombre, calidad, geo, intermitente = separar_marcas(entrada["nombre"] or "")
        if not url or not nombre:
            continue
        if calidad and not atributos.get("tvg-quality"):
            atributos["tvg-quality"] = calidad
        clave = nombre.casefold()
        if clave in vistos:
            continue
        vistos.add(clave)
        if tipo == "auto":
            texto_grupo = (atributos.get("group-title", "") + " " + entrada["grupo"]).lower()
            es_radio = atributos.get("radio", "").lower() == "true" or "radio" in texto_grupo
            tipo_canal = "radio" if es_radio else "tv"
        else:
            tipo_canal = tipo
        modo = _modo_catchup(atributos.get("catchup") or atributos.get("catchup-type"))
        fuente_catchup = atributos.get("catchup-source", "")
        if not modo and fuente_catchup:
            modo = "default"
        canales.append(Canal(
            nombre=nombre,
            tipo=tipo_canal,
            pais=atributos.get("tvg-country", ""),
            ambito=atributos.get("group-title") or entrada["grupo"] or "Sin categoría",
            web="",
            logo=atributos.get("tvg-logo", ""),
            epg_id=atributos.get("tvg-id", ""),
            emisiones=(_emision(url, atributos, geo),),
            referer=entrada["vlc"].get("referer", ""),
            user_agent=entrada["vlc"].get("user_agent", ""),
            origen=origen,
            numero=_entero(atributos.get("tvg-chno") or atributos.get("channel-number") or atributos.get("tvg-num")),
            idioma=atributos.get("tvg-language", ""),
            desfase=_decimal(atributos.get("tvg-shift")),
            catchup=modo,
            catchup_fuente=fuente_catchup,
            catchup_dias=_entero(atributos.get("catchup-days")),
            drm=entrada["drm"],
            intermitente=intermitente,
        ))
        if len(canales) >= limite:
            break
    if not canales:
        raise ValueError("La lista M3U no contiene ningún canal.")
    return canales


def escribir_m3u(canales) -> str:
    """Genera una lista M3U con los canales dados (para exportar favoritos)."""
    lineas = ["#EXTM3U"]
    for canal in canales:
        emision = canal.emision_principal
        if emision is None:
            continue
        atributos = [f'tvg-id="{canal.epg_id}"', f'tvg-name="{canal.nombre}"']
        if canal.logo:
            atributos.append(f'tvg-logo="{canal.logo}"')
        if canal.numero:
            atributos.append(f'tvg-chno="{canal.numero}"')
        atributos.append(f'group-title="{canal.ambito}"')
        lineas.append("#EXTINF:-1 " + " ".join(atributos) + "," + canal.nombre)
        if canal.user_agent:
            lineas.append("#EXTVLCOPT:http-user-agent=" + canal.user_agent)
        if canal.referer:
            lineas.append("#EXTVLCOPT:http-referrer=" + canal.referer)
        lineas.append(emision.url)
    return "\n".join(lineas) + "\n"
