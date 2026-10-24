"""Extracción de la dirección real de las emisiones.

El objetivo es que casi todos los canales se vean con el reproductor de la
aplicación (libmpv), que es el accesible, en lugar de dentro de una web:

- **YouTube**: se averigua qué vídeo emite el canal y se pide su lista HLS al
  servicio público del reproductor de YouTube (el mismo que usan sus
  aplicaciones móviles).
- **Twitch**: se pide la firma de reproducción y se compone la lista HLS.
- **Webs de emisoras**: se lee la página y sus archivos JavaScript buscando la
  lista HLS o DASH del directo.

Si algo falla se devuelve ``None`` y la aplicación abre la web como antes.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

from .catalogo import UA_UAGB, identificador_youtube
from .datos import url_http
from .proveedores import Fuente, video_en_directo_youtube

registro = logging.getLogger(__name__)

UA_ANDROID_YT = "com.google.android.youtube/20.10.38 (Linux; U; Android 14) gzip"
API_YOUTUBE = "https://www.youtube.com/youtubei/v1/player"
CLIENTE_YOUTUBE = {"clientName": "ANDROID", "clientVersion": "20.10.38", "androidSdkVersion": 34, "hl": "es", "gl": "ES", "userAgent": UA_ANDROID_YT}
API_TWITCH = "https://gql.twitch.tv/gql"
CLIENTE_TWITCH = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # identificador público del reproductor web
CONSULTA_TWITCH = (
    "query PlaybackAccessToken_Template($login: String!, $isLive: Boolean!, $vodID: ID!, $isVod: Boolean!, $playerType: String!) {"
    '  streamPlaybackAccessToken(channelName: $login, params: {platform: "web", playerBackend: "mediaplayer", playerType: $playerType}) @include(if: $isLive) {value signature __typename}'
    '  videoPlaybackAccessToken(id: $vodID, params: {platform: "web", playerBackend: "mediaplayer", playerType: $playerType}) @include(if: $isVod) {value signature __typename}}'
)
LIMITE_PAGINA = 6 * 1024 * 1024

# Las direcciones suelen venir escapadas dentro de JavaScript (https:\/\/...), así
# que se admiten barras invertidas y luego se limpian.
PATRON_FLUJO = re.compile(r"""https?:(?:\\?/){2}[^\s"'<>]+?\.(?:m3u8|mpd)(?:\?[^\s"'<>]*)?""", re.I)
PATRON_RELATIVO = re.compile(r"""["'](\\?/[^\s"'<>]+?\.(?:m3u8|mpd)(?:\?[^\s"'<>]*)?)["']""", re.I)
PATRON_SCRIPT = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.I)
ANUNCIOS = re.compile(r"doubleclick|googlesyndication|googletagmanager|google-analytics|imasdk|adservice|amazon-adsystem|adnxs|adsrvr|pagead|/ads?/|smartadserver|sascdn|teads|criteo|conviva|permutive|omtrdc|springserve|freewheel|fwmrm|spotx|ottera|/ad_|advert", re.I)


def _texto(url: str, cabeceras: dict | None = None, timeout: int = 15, limite: int = LIMITE_PAGINA) -> str:
    if not url_http(url):
        return ""
    encabezados = {"User-Agent": UA_UAGB, "Accept": "*/*", "Accept-Language": "es-ES,es;q=0.9"}
    encabezados.update(cabeceras or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=encabezados), timeout=timeout) as respuesta:
            return respuesta.read(limite).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        registro.debug("No se pudo leer %s: %s", url, error)
        return ""


def _json(url: str, cuerpo: dict, cabeceras: dict, timeout: int = 20):
    datos = json.dumps(cuerpo).encode("utf-8")
    encabezados = {"Content-Type": "application/json"}
    encabezados.update(cabeceras)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=datos, headers=encabezados), timeout=timeout) as respuesta:
            return json.loads(respuesta.read(8 * 1024 * 1024).decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        registro.debug("Servicio %s: %s", url, error)
        return None


# --- YouTube -----------------------------------------------------------------
def youtube_hls(video: str) -> str:
    """Lista HLS de un vídeo en directo de YouTube, o "" si no la ofrece."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video or ""):
        return ""
    cuerpo = {"videoId": video, "contentCheckOk": True, "racyCheckOk": True, "context": {"client": dict(CLIENTE_YOUTUBE)}}
    cabeceras = {"User-Agent": UA_ANDROID_YT, "X-YouTube-Client-Name": "3", "X-YouTube-Client-Version": CLIENTE_YOUTUBE["clientVersion"], "Origin": "https://www.youtube.com"}
    datos = _json(API_YOUTUBE, cuerpo, cabeceras)
    if not isinstance(datos, dict):
        return ""
    estado = (datos.get("playabilityStatus") or {}).get("status")
    if estado not in (None, "OK"):
        registro.info("YouTube no permite reproducir %s: %s", video, estado)
        return ""
    direccion = (datos.get("streamingData") or {}).get("hlsManifestUrl") or ""
    return direccion if url_http(direccion) else ""


def youtube(url: str) -> Fuente | None:
    """Fuente reproducible de una emisión de YouTube (canal en directo o vídeo)."""
    video, canal = identificador_youtube(url)
    if canal and not video:
        video = video_en_directo_youtube(url)
    if not video:
        return None
    manifiesto = youtube_hls(video)
    if not manifiesto:
        return None
    return Fuente(manifiesto, referer="https://www.youtube.com/", user_agent=UA_ANDROID_YT, descripcion="Directo de YouTube")


# --- Twitch ------------------------------------------------------------------
def canal_twitch(url: str) -> str:
    partes = urlparse(url)
    from urllib.parse import parse_qs

    canal = parse_qs(partes.query).get("channel", [""])[0]
    if not canal and "twitch.tv" in (partes.hostname or ""):
        trozos = [t for t in partes.path.split("/") if t]
        canal = trozos[0] if trozos else ""
    return canal if re.fullmatch(r"[A-Za-z0-9_]{2,40}", canal or "") else ""


def twitch(url: str) -> Fuente | None:
    """Lista HLS del directo de un canal de Twitch."""
    canal = canal_twitch(url)
    if not canal:
        return None
    consulta = {
        "operationName": "PlaybackAccessToken_Template",
        "query": CONSULTA_TWITCH,
        "variables": {"isLive": True, "login": canal, "isVod": False, "vodID": "", "playerType": "site"},
    }
    datos = _json(API_TWITCH, consulta, {"Client-ID": CLIENTE_TWITCH, "User-Agent": UA_UAGB, "Origin": "https://www.twitch.tv", "Referer": "https://www.twitch.tv/"})
    ficha = (datos or {}).get("data", {}).get("streamPlaybackAccessToken") or {}
    firma, testigo = ficha.get("signature"), ficha.get("value")
    if not firma or not testigo:
        return None
    from urllib.parse import urlencode

    parametros = urlencode({"allow_source": "true", "allow_audio_only": "true", "fast_bread": "true", "p": "1234567", "player_backend": "mediaplayer", "sig": firma, "token": testigo, "type": "any"})
    manifiesto = f"https://usher.ttvnw.net/api/channel/hls/{canal}.m3u8?{parametros}"
    # Si el canal no está emitiendo, el servicio responde 404 y se abre la web.
    if not comprobar(manifiesto, "https://www.twitch.tv/", UA_UAGB):
        return None
    return Fuente(manifiesto, origin="https://www.twitch.tv", referer="https://www.twitch.tv/", user_agent=UA_UAGB, descripcion="Directo de Twitch")


# --- webs de emisoras --------------------------------------------------------
def _limpiar(direccion: str) -> str:
    return direccion.replace("\\/", "/").replace("\\u0026", "&").replace("&amp;", "&").strip()


def _candidatos(texto: str, base: str) -> list[str]:
    salida = []
    for encontrado in PATRON_FLUJO.findall(texto or "") + PATRON_RELATIVO.findall(texto or ""):
        direccion = _limpiar(encontrado)
        if ANUNCIOS.search(direccion):
            continue
        direccion = urljoin(base, direccion)
        if url_http(direccion) and direccion not in salida:
            salida.append(direccion)
    return salida


def comprobar(direccion: str, referer: str, agente: str) -> bool:
    """La lista responde y parece una lista de reproducción de verdad."""
    cabeceras = {"User-Agent": agente, "Referer": referer, "Accept": "*/*"}
    if referer:
        partes = urlparse(referer)
        cabeceras["Origin"] = f"{partes.scheme}://{partes.hostname}"
    texto = _texto(direccion, cabeceras, timeout=12, limite=256 * 1024)
    if not texto:
        return False
    return "#EXTM3U" in texto or "<MPD" in texto or "urn:mpeg:dash" in texto


def buscar_en_web(pagina: str, agente: str = "", profundidad: int = 1) -> Fuente | None:
    """Lee la web de la emisora (y sus scripts) buscando la lista del directo."""
    agente = agente or UA_UAGB
    html = _texto(pagina, {"User-Agent": agente})
    if not html:
        return None
    partes = urlparse(pagina)
    origen = f"{partes.scheme}://{partes.hostname}" if partes.hostname else ""
    candidatos = _candidatos(html, pagina)
    if profundidad > 0:
        # Muchas webs dejan la dirección en su JavaScript de configuración.
        for script in PATRON_SCRIPT.findall(html)[:12]:
            direccion = urljoin(pagina, script)
            if not url_http(direccion) or ANUNCIOS.search(direccion):
                continue
            if urlparse(direccion).hostname != partes.hostname:
                continue
            candidatos += [c for c in _candidatos(_texto(direccion, {"User-Agent": agente, "Referer": pagina}, timeout=10, limite=2 * 1024 * 1024), direccion) if c not in candidatos]
            if candidatos:
                break
    for candidato in candidatos[:6]:
        if comprobar(candidato, pagina, agente):
            return Fuente(candidato, origin=origen, referer=pagina, user_agent=agente, descripcion="Directo encontrado en la web oficial")
    return None


def extraer(tipo: str, url: str, agente: str = "") -> Fuente | None:
    """Intenta obtener una fuente reproducible con libmpv para esta emisión."""
    try:
        if tipo == "youtube":
            return youtube(url)
        if tipo == "twitch":
            return twitch(url)
        if tipo in ("ext", "web"):
            return buscar_en_web(url, agente)
    except Exception:
        registro.exception("Error extrayendo la emisión de %s", url)
    return None
