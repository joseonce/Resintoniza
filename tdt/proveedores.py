"""Directos de las webs oficiales (Atresplayer, Mitele, DMAX, GOL, Dailymotion).

Adaptación de la clase ``q6.D`` del APK: se consultan las APIs públicas de
cada emisora en el momento de reproducir y se obtiene la dirección HLS/DASH
que la propia web usaría. Los códigos numéricos son los de ``A6.y.a``.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse, urlunparse

from .catalogo import UA_UAGB, Canal, Emision
from .datos import url_http

registro = logging.getLogger(__name__)
ORIGEN_MITELE = "https://www.mitele.es"
ORIGEN_RTPA = "https://www.rtpa.es"
ORIGEN_GOL = "https://play.goltelevision.com"
LIMITE_RESPUESTA = 4 * 1024 * 1024


class ErrorProveedor(RuntimeError):
    """La emisora no ha devuelto un directo utilizable."""


class ProveedorNoSoportado(ErrorProveedor):
    """El APK usa su navegador integrado para esta web; en Windows se abre el navegador."""


@dataclass(frozen=True)
class Fuente:
    """Dirección final y cabeceras con las que se reproduce."""

    url: str
    origin: str = ""
    referer: str = ""
    user_agent: str = ""
    descripcion: str = ""
    cookie: str = ""
    sin_rango: bool = False   # no pedir «Range» a este CDN: ver mitele()

    def cabeceras(self) -> list[str]:
        lista = []
        if self.origin:
            lista.append(f"Origin: {self.origin}")
        if self.cookie:
            lista.append(f"Cookie: {self.cookie}")
        if self.sin_rango:
            # Una cabecera con nombre y sin valor le dice a curl, que es quien
            # descarga en libmpv, que no mande esa cabecera en absoluto.
            lista.append("Range:")
        return lista


def cookie_de_sesion(url: str, origin: str = "", user_agent: str = "") -> str:
    """Pide la lista maestra y devuelve la cookie que fija el CDN (p. ej. ``hdntl`` de Akamai).

    Los reproductores HLS no repiten los parámetros de la dirección maestra en
    las sublistas, así que el CDN de Mediaset autoriza esas peticiones con una
    cookie. Se envía después como cabecera ``Cookie`` en cada petición.
    """
    encabezados = {"User-Agent": user_agent or UA_UAGB, "Accept": "*/*"}
    if origin:
        encabezados["Origin"] = origin
        encabezados["Referer"] = origin + "/"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=encabezados), timeout=15) as respuesta:
            respuesta.read(64 * 1024)
            galletas = respuesta.headers.get_all("Set-Cookie") or []
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return ""
    return "; ".join(g.split(";", 1)[0].strip() for g in galletas if "=" in g)


def es_dominio(url: str, *dominios: str) -> bool:
    """True si el servidor de ``url`` es uno de ``dominios`` o un subdominio suyo.

    Comparar el texto suelto no vale: «mitele» también está dentro de
    ``mitelefe.com``, que es la web argentina de Telefe y no tiene nada que ver.
    """
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in dominios)


# Cada emisora se reconoce por el DOMINIO de su web, no por un trozo del texto de
# la dirección. Así un cambio de subdominio o de marca dentro de la misma casa
# (Telecinco y Cuatro se mudaron de mitele.es a mediasetinfinity.es en sep 2026)
# no deja el canal sin resolutor, y «mitele» dentro de «mitelefe.com» —la web
# argentina de Telefe— ya no se confunde con Mediaset.
DOMINIOS_PROVEEDOR: dict[int, tuple[str, ...]] = {
    1: ("atresplayer.com",),
    10: ("mitele.es", "mediasetinfinity.es", "mediaset.es"),
    11: ("dmax.marca.com",),
    15: ("goltelevision.com",),
    20: ("livestream.com",),
    40: ("dailymotion.com",),
    100: ("realbetisbalompie.es",),
    102: ("7tvandalucia.es",),
    103: ("la7tv.es",),
    104: ("tvalmassora.com",),
    105: ("almatelecom.es",),
    106: ("rtpa.es",),
    109: ("cyltv.es", "rtvc.es"),
    110: ("cmmedia.es", "cadizcf.com", "canalextremadura.es"),
    111: ("earthtv.com",),
    201: ("telemicro.com.do",),
}
# Las tres que no distingue el dominio sino la ruta: la misma web sirve para
# varios canales. Se miran antes que los dominios.
RUTAS_PROVEEDOR: tuple[tuple[str, int], ...] = (
    ("kaltura.com/p/2346171/", 101),
    ("andorradifusio.ad/endirecte/atv", 107),
    ("andorradifusio.ad/endirecte/canalweb", 108),
)


def codigo_proveedor(url: str) -> int:
    """Clasificación de webs como en ``A6.y.a`` del APK."""
    for trozo, codigo in RUTAS_PROVEEDOR:
        if trozo in url:
            return codigo
    for codigo, dominios in DOMINIOS_PROVEEDOR.items():
        if es_dominio(url, *dominios):
            return codigo
    return -1


NOMBRES_PROVEEDOR = {1: "Atresplayer", 10: "Mitele", 11: "DMAX", 15: "GOL PLAY", 40: "Dailymotion"}


def _peticion(url: str, origin: str = "", cuerpo=None, cabeceras: dict | None = None, timeout: int = 15):
    if not url_http(url) or urlparse(url).scheme != "https":
        raise ErrorProveedor("La emisora devolvió una dirección no válida.")
    encabezados = {"User-Agent": UA_UAGB, "Accept": "application/json, text/plain, */*"}
    if origin:
        encabezados["Origin"] = origin
        encabezados["Referer"] = origin + "/"
    encabezados.update(cabeceras or {})
    datos = None
    if cuerpo is not None:
        encabezados["Content-Type"] = "application/json"
        datos = json.dumps(cuerpo).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=datos, headers=encabezados), timeout=timeout) as respuesta:
            crudo = respuesta.read(LIMITE_RESPUESTA + 1)
    except urllib.error.HTTPError as error:
        raise ErrorProveedor(f"La emisora no permite cargar el directo ahora mismo (HTTP {error.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ErrorProveedor(f"No se pudo conectar con la emisora: {getattr(error, 'reason', error)}") from None
    if len(crudo) > LIMITE_RESPUESTA:
        raise ErrorProveedor("La respuesta de la emisora es demasiado grande.")
    try:
        return json.loads(crudo.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise ErrorProveedor("La emisora devolvió una respuesta que no se pudo interpretar.") from None


def _obligatorio(datos, clave, tipo=str):
    valor = datos.get(clave) if isinstance(datos, dict) else None
    if not isinstance(valor, tipo) or not valor:
        raise ErrorProveedor("La emisora no ofrece ahora un directo compatible (falta el campo " + clave + ").")
    return valor


def _ultimo_segmento(url: str) -> str:
    return urlparse(url).path.rstrip("/").split("/")[-1]


def slug_directo(url: str) -> str:
    """Nombre del canal dentro de la dirección: el trozo que va detrás de «directo».

    Las webs mueven el directo de sitio (``mitele.es/directo/telecinco`` →
    ``mediasetinfinity.es/directo/telecinco/``) pero el nombre del canal es
    siempre el mismo y es lo único que piden sus APIs. Se busca detrás de
    «directo», «directos» o «en-directo», y si no aparece se usa el último
    trozo de la ruta, que es como estaba antes.
    """
    trozos = [t for t in urlparse(url).path.split("/") if t]
    for marca in ("directo", "directos", "en-directo"):
        if marca in trozos:
            posicion = trozos.index(marca) + 1
            if posicion < len(trozos):
                return trozos[posicion]
    return trozos[-1] if trozos else ""


# --- Atresplayer (código 1, q6.D.y) ----------------------------------------
def atresplayer(url: str, peticion=_peticion) -> Fuente:
    ubicacion = peticion("https://api.atresplayer.com/client/v1/ipLocation")
    if ubicacion.get("country") != "ES":
        raise ErrorProveedor("Atresplayer solo ofrece este directo desde España.")
    if "/directos/" not in url:
        raise ErrorProveedor("La dirección de Atresplayer no es un directo.")
    ruta = url.split("/directos/", 1)[1]
    pagina = peticion("https://api.atresplayer.com/client/v1/url?href=/directos/" + ruta)
    canal = peticion(_obligatorio(pagina, "href"))
    video = peticion(_obligatorio(canal, "urlVideo"))
    fuentes = _obligatorio(video, "sourcesLive", list)
    candidatas = [f for f in fuentes if isinstance(f, dict) and url_http(f.get("src"))]
    sin_drm = [f for f in candidatas if not f.get("drm") and not f.get("keySystems")]
    for fuente in sin_drm or candidatas:
        return Fuente(fuente["src"], descripcion="Directo de Atresplayer")
    raise ErrorProveedor("Atresplayer no ofrece ahora una fuente en directo.")


# --- Mitele / Mediaset (código 10, q6.D.C y r6.a) ---------------------------
# CDN de Mediaset que reparte el permiso de la sesión dentro de la lista maestra
# (ver elegir_fuente_mediaset). El otro obliga a repetir los parámetros a mano.
CDN_QUE_FIRMA_LA_LISTA = "livek.mediaset.es"


def elegir_fuente_mediaset(slug: str, dls) -> tuple[str, str]:
    """Mejor fuente HLS sin DRM: devuelve su dirección y la clave de su token.

    El CDN pesa más que la calidad. El permiso de Mediaset (``hdnts``) va en los
    parámetros de la dirección maestra, y ningún reproductor HLS los repite al
    pedir las sublistas. Fastly (``livek.mediaset.es``) lo resuelve reescribiendo
    la lista maestra: cada variante sale ya con su propio permiso (``hdntl``).
    Akamai (``directos.mediaset.es``) no lo hace y responde 403 a todas las
    sublistas, así que solo llega a cargar la lista maestra. Comprobado.
    """
    prioridad = {"linear": 4, "ssai-ctv": 3, "ssai": 2, "csai": 1}
    candidatas = []
    for indice, entrada in enumerate(dls if isinstance(dls, list) else []):
        if not isinstance(entrada, dict):
            continue
        stream = entrada.get("stream") or ""
        if entrada.get("format") != "hls" or entrada.get("drm", True) or not url_http(stream):
            continue
        if any(m in slug for m in ("telecinco", "cuatro", "energy", "fdf", "divinity", "viajes")) and "ctv.m3u8" in stream:
            continue
        orden = (CDN_QUE_FIRMA_LA_LISTA in stream, entrada.get("quality", "sd") == "hd",
                 prioridad.get(entrada.get("adtype", "unknown"), 0))
        # cerbero devuelve un token por fuente, con la posición (empezando en 1) como clave.
        candidatas.append((orden, stream, str(indice + 1)))
    if not candidatas:
        raise ErrorProveedor("Mitele no ofrece ahora una fuente HLS sin DRM.")
    candidatas.sort(key=lambda t: t[0], reverse=True)
    return candidatas[0][1], candidatas[0][2]


def mitele(url: str, peticion=_peticion) -> Fuente:
    slug = slug_directo(url)
    geo = peticion("https://cerbero.mediaset.es/geo", ORIGEN_MITELE)
    if geo.get("country") != "ES" and geo.get("isInEuropeanUnion") is not True:
        raise ErrorProveedor("Mitele no ofrece este directo en tu ubicación.")
    entrega = peticion(f"https://caronte.mediaset.es/delivery/channel/mmc/{slug}/mtweb", ORIGEN_MITELE)
    stream, clave_token = elegir_fuente_mediaset(slug, entrega.get("dls"))
    gbx = peticion(f"https://mab.mediaset.es/1.0.0/get?oid=mtmw&eid=/api/mtmw/v3/gbx/mtweb/{slug}", ORIGEN_MITELE)
    autorizacion = peticion(_obligatorio(entrega, "cerbero"), ORIGEN_MITELE, {"bbx": _obligatorio(entrega, "bbx"), "gbx": _obligatorio(gbx, "gbx")})
    # Hay un token por fuente y no valen unos por otros: el de la elegida o, si no está, el primero.
    # Los de Fastly caducan a las cuatro horas; los de Akamai, a los tres minutos.
    tokens = _obligatorio(autorizacion, "tokens", dict)
    token = _obligatorio(tokens.get(clave_token) if isinstance(tokens.get(clave_token), dict) else tokens.get("1"), "cdn")
    partes = urlparse(stream)
    consulta = "&".join(p for p in (partes.query, token.lstrip("?&")) if p)
    direccion = urlunparse(partes._replace(query=consulta))
    cookie = cookie_de_sesion(direccion, ORIGEN_MITELE) if peticion is _peticion else ""
    # ``sin_rango``: el CDN reescribe la lista maestra metiendo en cada variante el
    # permiso de la sesión (``hdntl``), pero solo cuando la responde entera. libmpv
    # pide «Range: bytes=0-», el CDN contesta 206 y devuelve la lista SIN permisos,
    # así que después cada sublista da 403 y no se oye ni se graba nada. Comprobado
    # con la misma dirección: sin «Range», 200 y las seis variantes firmadas; con
    # «Range», 206 y ninguna.
    return Fuente(direccion, origin=ORIGEN_MITELE, referer=ORIGEN_MITELE + "/", user_agent=UA_UAGB,
                  descripcion="Directo de Mitele", cookie=cookie, sin_rango=True)


# --- DMAX (código 11, q6.D.z) -----------------------------------------------
def dmax(url: str, peticion=_peticion) -> Fuente:
    token = peticion("https://public.aurora.enhanced.live/token?realm=es")
    atributos = _obligatorio(_obligatorio(token, "data", dict), "attributes", dict)
    portador = _obligatorio(atributos, "token")
    info = peticion("https://public.aurora.enhanced.live/playback/channelPlaybackInfo/1?usePreAuth=true", cabeceras={"Authorization": "Bearer " + portador})
    streaming = _obligatorio(_obligatorio(_obligatorio(info, "data", dict), "attributes", dict), "streaming", list)
    for entrada in streaming:
        if isinstance(entrada, dict) and entrada.get("type") == "hls" and url_http(entrada.get("url")):
            return Fuente(entrada["url"], descripcion="Directo de DMAX")
    raise ErrorProveedor("DMAX no ofrece ahora una fuente HLS.")


# --- GOL PLAY (código 15, q6.D.B) -------------------------------------------
def gol(url: str, peticion=_peticion) -> Fuente:
    datos = peticion("https://play.goltelevision.com/api/stream/live", ORIGEN_GOL)
    manifiesto = _obligatorio(datos, "manifest")
    if not url_http(manifiesto):
        raise ErrorProveedor("GOL devolvió un manifiesto no válido.")
    return Fuente(manifiesto, descripcion="Directo de GOL PLAY")


# --- Dailymotion (código 40, q6.D.A) -----------------------------------------
def dailymotion(url: str, peticion=_peticion) -> Fuente:
    identificador = url.split("/")[-1].split("?")[0]
    partes = urlparse(url)
    if "video=" in partes.query:
        identificador = partes.query.split("video=", 1)[1].split("&")[0]
    if not identificador:
        raise ErrorProveedor("No se reconoce el vídeo de Dailymotion.")
    datos = peticion("https://www.dailymotion.com/player/metadata/video/" + identificador)
    calidades = _obligatorio(datos, "qualities", dict)
    for _, lista in calidades.items():
        if isinstance(lista, list) and lista and isinstance(lista[0], dict) and url_http(lista[0].get("url")):
            return Fuente(lista[0]["url"], descripcion="Directo de Dailymotion")
    raise ErrorProveedor("Dailymotion no ofrece ahora una fuente en directo.")


# --- YouTube: canal en directo → vídeo concreto (A6.C del APK) ----------------
UA_MOVIL = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
PATRONES_YOUTUBE = [
    re.compile(r'<link rel="canonical" href="(https://www\.youtube\.com/watch\?v=[a-zA-Z0-9_-]{11}[^"]*)"', re.I),
    re.compile(r'"canonicalBaseUrl":"(/watch\?v=[a-zA-Z0-9_-]{11}[^"]*)"', re.I),
    re.compile(r'"urlCanonical":"(https://www\.youtube\.com/watch\?v=[a-zA-Z0-9_-]{11}[^"]*)"', re.I),
]


def _limpiar_html(texto: str) -> str:
    return texto.replace("\\u0026", "&").replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')


def video_en_directo_youtube(url: str, timeout: int = 15) -> str:
    """Identificador del vídeo que emite ahora un canal de YouTube, o "" si no hay directo.

    Reproduce ``A6.C`` del APK: se pide la página del canal con agente de móvil y
    se busca la dirección canónica ``watch?v=…``.
    """
    if not url_http(url):
        return ""
    encabezados = {"User-Agent": UA_MOVIL, "Accept-Language": "es-ES,es;q=0.9", "Accept": "text/html,application/xhtml+xml"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=encabezados), timeout=timeout) as respuesta:
            html = respuesta.read(3 * 1024 * 1024).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return ""
    for patron in PATRONES_YOUTUBE:
        encontrado = patron.search(html)
        if encontrado:
            direccion = _limpiar_html(encontrado.group(1))
            consulta = urlparse(direccion if direccion.startswith("http") else "https://www.youtube.com" + direccion)
            valor = parse_qs(consulta.query).get("v", [""])[0]
            if valor:
                return valor
    return ""


RESOLUTORES = {1: atresplayer, 10: mitele, 11: dmax, 15: gol, 40: dailymotion}
# Casas cuyas APIs solo necesitan el NOMBRE del canal, no su web: se les puede
# preguntar por un canal aunque la lista lo haya mudado a una dirección nueva.
# La dirección de aquí es la que entienden sus propios resolutores.
PLANTILLAS_POR_NOMBRE: tuple[tuple[int, str], ...] = (
    (10, "https://www.mitele.es/directo/{}"),
    (1, "https://www.atresplayer.com/directos/{}/"),
)
MARCAS_DE_DIRECTO = ("directo", "directos", "en-directo")


def nombre_de_canal(url: str) -> str:
    """Nombre del canal en la dirección, solo si la ruta dice que es un directo.

    Se usa para decidir si merece la pena preguntar por él a las casas
    conocidas; para eso hace falta estar seguro de que el trozo es el canal y no
    cualquier otra página, así que aquí no vale el respaldo de ``slug_directo``.
    """
    trozos = [t for t in urlparse(url).path.split("/") if t]
    for marca in MARCAS_DE_DIRECTO:
        if marca in trozos and trozos.index(marca) + 1 < len(trozos):
            return trozos[trozos.index(marca) + 1]
    return ""


def resolver_por_nombre(url: str, peticion=_peticion) -> Fuente | None:
    """Última oportunidad antes del navegador: preguntar por el canal a las casas conocidas.

    Las listas cambian la web de un canal cada cierto tiempo: en septiembre de
    2026, TDTChannels mudó Telecinco y Cuatro de ``mitele.es`` a
    ``mediasetinfinity.es`` y se quedaron sin resolutor, aunque el directo
    seguía saliendo de la misma API. Como esas APIs piden solo el nombre del
    canal («telecinco», «antena3»), aquí se les pregunta por él: si una lo
    reconoce, el directo se sigue obteniendo sin tocar el programa.
    """
    nombre = nombre_de_canal(url)
    if not nombre:
        return None
    for codigo, plantilla in PLANTILLAS_POR_NOMBRE:
        try:
            fuente = RESOLUTORES[codigo](plantilla.format(nombre), peticion)
        except Exception:  # noqa: BLE001 (era un intento a ciegas: si no, se sigue probando)
            continue
        registro.warning("%s no está en DOMINIOS_PROVEEDOR, pero «%s» lo resuelve %s: conviene añadir el dominio.",
                         url, nombre, NOMBRES_PROVEEDOR.get(codigo, codigo))
        return fuente
    return None


def resolver(url: str, peticion=_peticion) -> Fuente:
    """Devuelve la fuente reproducible para una emisión externa (``ext``)."""
    codigo = codigo_proveedor(url)
    resolutor = RESOLUTORES.get(codigo)
    if resolutor is None:
        fuente = resolver_por_nombre(url, peticion)
        if fuente is not None:
            return fuente
        raise ProveedorNoSoportado("No reconozco la web oficial de este canal, así que se abre en el navegador.")
    try:
        return resolutor(url, peticion)
    except (KeyError, TypeError, AttributeError, IndexError):
        raise ErrorProveedor("La emisora ha cambiado el formato de su servicio.") from None


def fuente_directa(canal: Canal, emision: Emision, url: str | None = None) -> Fuente:
    """Cabeceras para una emisión directa, como ``VideoPlayerService`` del APK."""
    direccion = url or emision.url
    codigo = codigo_proveedor(direccion)
    partes = urlparse(direccion)
    origin = f"{partes.scheme}://{partes.hostname}" if partes.hostname else ""
    if codigo == 10:
        origin = ORIGEN_MITELE
    elif codigo == 106:
        origin = ORIGEN_RTPA
    referer = canal.referer
    if codigo == 109:
        referer = "https://cdnapi.codev8.net/"
    elif codigo == 105:
        referer = "https://zonacliente.almatelecom.es/videos/canalimagen"
    elif codigo == 201:
        referer = "https://telemicro.com.do/players/5tv/"
    return Fuente(direccion, origin=origin, referer=referer, user_agent=canal.user_agent or UA_UAGB, descripcion=emision.etiqueta(1))


def fuente_final(canal: Canal, emision: Emision, resuelta: Fuente) -> Fuente:
    """Combina la fuente resuelta por el proveedor con las cabeceras del canal."""
    base = fuente_directa(canal, emision, resuelta.url)
    codigo = codigo_proveedor(emision.url)
    origin = resuelta.origin or (ORIGEN_MITELE if codigo == 10 else base.origin)
    return Fuente(resuelta.url, origin=origin, referer=resuelta.referer or base.referer, user_agent=resuelta.user_agent or base.user_agent,
                  descripcion=resuelta.descripcion or base.descripcion, cookie=resuelta.cookie, sin_rango=resuelta.sin_rango)
