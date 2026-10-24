"""Listas de canales y guía de programación.

Reproduce la lógica observada en el APK (clase ``o6.s``): las listas tienen
``countries → ambits → channels``; cada canal declara ``options`` y unas marcas
``extra_info`` que cambian cómo se abre cada emisión:

- ``EXTA``  añade una emisión "externa" con la web oficial (Atresplayer, Mitele…),
            que la aplicación resuelve con la API pública de la emisora.
- ``EXTB``  trata las opciones con formato web como emisiones externas.
- ``GEO``   probablemente solo disponible en España. ``REG`` requiere registro.
- ``NOEM``  no tiene emisión por Internet en abierto.
- ``UAG`` / ``UAGB``  agente de usuario de navegador para esa emisora.
- ``referer`` (campo del canal) cabecera Referer al reproducir.
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from .datos import url_http

URL_LISTAS = {
    "tv": ("https://www.tdtchannels.com/lists/tv.json", "https://www.ondachannels.com/lists/backup/tv.json"),
    "radio": ("https://www.tdtchannels.com/lists/radio.json", "https://www.ondachannels.com/lists/backup/radio.json"),
}
URL_GUIAS = {
    "tv": ("https://www.tdtchannels.com/epg/TV.json", "https://www.ondachannels.com/lists/backup/epg/TV.json"),
    "radio": ("https://www.tdtchannels.com/epg/RADIO.json", "https://www.ondachannels.com/lists/backup/epg/RADIO.json"),
}
NOMBRE_LISTA_OFICIAL = {"tv": "Lista pública · Televisión", "radio": "Lista pública · Radio"}
NOMBRE_TIPO = {"tv": "Televisión", "radio": "Radio"}
# Guía adicional en formato XMLTV: cubre canales que la guía principal no trae
# (Antena 3, laSexta, Neox, Nova, Mega, Atreseries, autonómicas…).
BASE_DOBLEM = "https://raw.githubusercontent.com/davidmuma/EPG_dobleM/master/"
GUIA_EXTRA = BASE_DOBLEM + "guiatv.xml.gz"
# Variantes publicadas por la misma guía: todas traen los mismos 634 canales y
# los mismos programas, y solo cambia cómo está escrito el texto. Las que llevan
# etiquetas de color de Kodi se limpian al leerlas, pero conviene elegir bien.
VARIANTES_GUIA = [
    ("Normal (recomendada)", BASE_DOBLEM + "guiatv.xml.gz"),
    ("Ligera (descripciones más cortas)", BASE_DOBLEM + "guiatv_light.xml.gz"),
    ("Títulos sin temporada ni episodio", BASE_DOBLEM + "guiatv_plex.xml.gz"),
    ("Con imágenes de fondo", BASE_DOBLEM + "guiafanart.xml.gz"),
    ("Con caracteres especiales", BASE_DOBLEM + "guiaiptv.xml"),
]
CANALES_DOBLEM = BASE_DOBLEM + "Varios/Canales_soportados.txt"
PREFIJO_NOMBRE = "nombre:"
IDIOMA_GUIA = "es"

# Etiquetas de color y formato de Kodi que traen algunas variantes de la guía:
# un lector de pantalla las leería como texto, así que se quitan.
ETIQUETAS_KODI = re.compile(r"\[/?(?:COLOR|B|I|UPPERCASE|LOWERCASE|CAPITALIZE|LIGHT|CR)[^\]]*\]", re.IGNORECASE)
SIMBOLOS_INICIALES = re.compile(r"^[\s·•*\-–—|]+")
EDADES = {"0": "todos los públicos", "TP": "todos los públicos", "SC": "sin calificar", "NR": "sin calificar",
          "7": "no recomendada para menores de 7 años", "12": "no recomendada para menores de 12 años",
          "16": "no recomendada para menores de 16 años", "18": "no recomendada para menores de 18 años"}

# Agentes de usuario que el APK asigna según las marcas UAGB / UAG.
UA_UAGB = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
UA_UAG = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 CrKey/1.44.191160"

PAISES = {"Spain": "España", "International": "Internacional", "Andorra": "Andorra", "France": "Francia", "Portugal": "Portugal", "Italy": "Italia", "Germany": "Alemania", "United Kingdom": "Reino Unido", "United States": "Estados Unidos", "Mexico": "México", "Argentina": "Argentina"}

CATEGORIAS_EPG = {
    "CULTURE": "Cultura", "DOCUMENTARY": "Documental", "ENTERTAINMENT": "Entretenimiento", "FILM": "Cine", "MOVIE": "Cine",
    "KIDS": "Infantil", "MUSIC": "Música", "NEWS": "Noticias", "OTHER": "Otros", "SERIES": "Series", "SPORTS": "Deportes", "SPORT": "Deportes",
    # Géneros DVB que usan las guías XMLTV completas, en inglés.
    "NEWS MAGAZINE": "Informativo", "NEWS / CURRENT AFFAIRS": "Noticias y actualidad", "MOVIE / DRAMA": "Cine y drama",
    "VARIETY SHOW": "Variedades", "CARTOONS / PUPPETS": "Dibujos animados", "MUSIC / BALLET / DANCE": "Música y danza",
    "SERIOUS / CLASSICAL / RELIGIOUS / HISTORICAL MOVIE / DRAMA": "Cine clásico o histórico", "COMEDY": "Comedia",
    "LEISURE HOBBIES": "Ocio y aficiones", "DETECTIVE / THRILLER": "Intriga", "ADVENTURE / WESTERN / WAR": "Aventuras y bélico",
    "SPORTS MAGAZINES": "Programa deportivo", "MAGAZINES / REPORTS / DOCUMENTARY": "Reportajes y documentales",
    "TOURISM / TRAVEL": "Viajes", "NATURE / ANIMALS / ENVIRONMENT": "Naturaleza", "FOOTBALL / SOCCER": "Fútbol",
    "FOOTBALL - CLUB": "Fútbol de clubes", "SCIENCE FICTION / FANTASY / HORROR": "Ciencia ficción y terror",
    "PRE-SCHOOL CHILDREN'S PROGRAMS": "Preescolar", "MOTOR SPORT": "Motor", "COOKING": "Cocina",
    "CHILDREN'S / YOUTH PROGRAMS": "Infantil y juvenil", "ARTS / CULTURE (WITHOUT MUSIC)": "Arte y cultura",
    "GAME SHOW / QUIZ / CONTEST": "Concursos", "ENTERTAINMENT PROGRAMS FOR 6 TO 14": "Infantil",
    "TALK SHOW": "Tertulia", "SOAP / MELODRAMA / FOLKLORIC": "Culebrón", "FITNESS": "Deporte y salud",
}
# Marcas de edad y valoración que algunas guías meten en el subtítulo: la
# información ya se extrae aparte, y en texto se leen fatal.
SIMBOLOS_SUBTITULO = re.compile(r"[①-⓿❶-➓]|★\s*[\d.,]+\s*/\s*\d+")

# Canales de Atresmedia: la lista pública no los incluye, pero el APK sabe
# resolver sus directos oficiales (Atresplayer). Se añaden con la marca EXTA.
ATRESMEDIA = (
    ("Antena 3", "antena3", "Antena3.TV"),
    ("laSexta", "lasexta", "LaSexta.TV"),
    ("Neox", "neox", "Neox.TV"),
    ("Nova", "nova", "Nova.TV"),
    ("Mega", "mega", "Mega.TV"),
    ("Atreseries", "atreseries", "Atreseries.TV"),
)


def plegar(texto: str) -> str:
    """Minúsculas sin tildes para buscar."""
    return "".join(c for c in unicodedata.normalize("NFKD", (texto or "").casefold()) if not unicodedata.combining(c))


def es_youtube(url: str) -> bool:
    return "youtube" in url or "youtu.be" in url


def es_directo(url: str) -> bool:
    """True si la dirección apunta a un flujo (HLS, DASH, MP3…) y no a una página web."""
    partes = urlparse(url.lower())
    ruta = partes.path
    if ruta.endswith((".html", ".htm", ".php", ".aspx")):
        return False
    return any(marca in ruta for marca in (".m3u8", ".mpd", ".mp3", ".aac", ".ts", ".mp4", "/stream", "/live", "/directo", "icecast", "shoutcast", "/playlist")) or ".m3u8" in partes.query


def identificador_youtube(url: str) -> tuple[str, str]:
    """(vídeo, canal) de una dirección de YouTube, como ``A6.n`` del APK."""
    partes = urlparse(url)
    anfitrion = (partes.hostname or "").lower()
    if "youtu.be" in anfitrion:
        return partes.path.strip("/").split("/")[0], ""
    if "youtube.com" not in anfitrion:
        return "", ""
    trozos = partes.path.split("/")
    consulta = parse_qs(partes.query)
    video = consulta.get("v", [""])[0]
    if not video and len(trozos) >= 3 and trozos[1] in ("embed", "shorts", "live") and trozos[2] != "live_stream":
        video = trozos[2]
    canal = ""
    if len(trozos) >= 4 and trozos[1] == "channel" and trozos[3] == "live":
        canal = trozos[2]
    elif len(trozos) >= 3 and trozos[1] == "embed" and trozos[2] == "live_stream":
        canal = consulta.get("channel", [""])[0]
    return video, canal


def url_youtube_incrustado(url: str) -> str:
    """Reproductor incrustado de YouTube (``A6.n.a`` del APK), para verlo dentro de la aplicación."""
    video, canal = identificador_youtube(url)
    if video:
        return f"https://www.youtube.com/embed/{video}?autoplay=1&playsinline=1&rel=0"
    if canal:
        return f"https://www.youtube.com/embed/live_stream?channel={canal}&autoplay=1"
    return url


def url_twitch_incrustado(url: str) -> str:
    """Página del canal de Twitch: su reproductor queda en el documento principal."""
    partes = urlparse(url)
    canal = parse_qs(partes.query).get("channel", [""])[0]
    if not canal and "twitch.tv" in (partes.hostname or ""):
        trozos = [t for t in partes.path.split("/") if t]
        canal = trozos[0] if trozos else ""
    return f"https://www.twitch.tv/{canal}" if canal else url


def url_youtube_navegable(url: str) -> str:
    """Convierte enlaces embed/canal de YouTube en direcciones para el navegador (A6.n.b)."""
    partes = urlparse(url)
    anfitrion = (partes.hostname or "").lower()
    if "youtu.be" in anfitrion and len(partes.path) > 1:
        return "https://www.youtube.com/watch?v=" + partes.path.strip("/").split("/")[0]
    if "youtube.com" in anfitrion:
        trozos = partes.path.split("/")
        video = parse_qs(partes.query).get("v", [""])[0]
        if video:
            return "https://www.youtube.com/watch?v=" + video
        if len(trozos) >= 3 and trozos[1] == "embed" and trozos[2] == "live_stream":
            canal = parse_qs(partes.query).get("channel", [""])[0]
            if canal:
                return f"https://www.youtube.com/channel/{canal}/live"
        if len(trozos) >= 3 and trozos[1] in ("embed", "shorts", "live") and trozos[2]:
            return "https://www.youtube.com/watch?v=" + trozos[2]
        if len(trozos) >= 4 and trozos[1] == "channel" and trozos[3] == "live":
            return f"https://www.youtube.com/channel/{trozos[2]}/live"
    return url


@dataclass(frozen=True)
class Emision:
    """Una forma de ver o escuchar un canal.

    ``tipo``: ``directo`` (se reproduce dentro de la aplicación), ``ext``
    (directo de la web oficial que hay que resolver), ``youtube``, ``twitch``
    o ``web`` (se abren en el navegador).
    """

    tipo: str
    url: str
    formato: str = ""
    geo: str | None = None
    resolucion: str | None = None
    idioma: str | None = None

    @property
    def navegador(self) -> bool:
        return self.tipo in ("youtube", "twitch", "web")

    @property
    def url_incrustada(self) -> str:
        """Dirección que hay que cargar para que el reproductor quede en la página principal."""
        if self.tipo == "youtube":
            return url_youtube_incrustado(self.url)
        if self.tipo == "twitch":
            return url_twitch_incrustado(self.url)
        return self.url

    def etiqueta(self, numero: int) -> str:
        partes = []
        if self.tipo == "web":
            return "Web oficial (navegador integrado)"
        if self.tipo == "ext":
            partes.append("Directo de la web oficial")
        elif self.tipo == "youtube":
            partes.append("YouTube (navegador integrado)")
        elif self.tipo == "twitch":
            partes.append("Twitch (navegador integrado)")
        else:
            partes.append(f"Directo {self.formato or 'stream'}")
        if self.resolucion:
            partes.append(self.resolucion.upper())
        if self.idioma:
            partes.append(self.idioma)
        if self.geo == "SP":
            partes.append("solo España")
        elif self.geo == "CAT":
            partes.append("solo Cataluña")
        elif self.geo == "ZONA":
            partes.append("restringido por zona")
        elif self.geo:
            partes.append(f"zona {self.geo}")
        return f"Emisión {numero}: " + " · ".join(partes)


@dataclass(frozen=True)
class Canal:
    nombre: str
    tipo: str
    pais: str
    ambito: str
    web: str
    logo: str
    epg_id: str
    emisiones: tuple[Emision, ...]
    geo: bool = False
    registro: bool = False
    sin_emision: bool = False
    referer: str = ""
    user_agent: str = ""
    origen: str = ""
    # Campos que aportan las listas M3U y las cuentas Xtream Codes.
    numero: int = 0            # tvg-chno: número de canal del proveedor
    idioma: str = ""           # tvg-language
    desfase: float = 0.0       # tvg-shift: horas de desfase de la guía
    catchup: str = ""          # "", default, append, flussonic, shift, xc
    catchup_fuente: str = ""   # catchup-source: plantilla de la dirección
    catchup_dias: int = 0      # días de programación pasada disponibles
    drm: bool = False          # emisión cifrada: libmpv no puede reproducirla
    identificador: str = ""    # identificador interno del proveedor (Xtream)
    intermitente: bool = False  # no emite las 24 horas (marca [Not 24/7] de iptv-org)

    @property
    def clave(self) -> str:
        return f"{self.tipo}|{self.nombre}"

    @property
    def reproducibles(self) -> list[Emision]:
        return [e for e in self.emisiones if not e.navegador]

    @property
    def emision_principal(self) -> Emision | None:
        """La que se usa al pulsar Reproducir: la primera directa o, si no hay, la primera."""
        return (self.reproducibles or list(self.emisiones) or [None])[0]

    def notas(self) -> list[str]:
        textos = []
        if self.drm:
            textos.append("Esta emisión está cifrada (DRM) y no se puede reproducir con el reproductor de la aplicación.")
        if self.catchup:
            dias = f" de los últimos {self.catchup_dias} días" if self.catchup_dias else ""
            textos.append(f"Este canal permite ver programas ya emitidos{dias} desde la programación.")
        if self.intermitente:
            textos.append("Este canal no emite las veinticuatro horas: puede que ahora no haya nada.")
        if self.sin_emision:
            textos.append("Este canal no tiene una emisión directa en la lista: se abre su web oficial en el navegador integrado, con el reproductor de la propia web (puede que no esté emitiendo).")
        principal = self.emision_principal
        if not self.reproducibles and principal is not None and principal.tipo in ("youtube", "twitch"):
            textos.append(f"Se ve con el reproductor de {'YouTube' if principal.tipo == 'youtube' else 'Twitch'} dentro de la aplicación; las teclas del reproductor lo manejan.")
        if self.geo:
            textos.append("Este canal probablemente solo esté disponible en España.")
        if self.registro:
            textos.append("Este canal requiere registrarse e iniciar sesión en su web oficial.")
        return textos


def _texto(valor) -> str:
    return valor.strip() if isinstance(valor, str) else ""


def _opcional(valor) -> str | None:
    return valor.strip() if isinstance(valor, str) and valor.strip() else None


def validar_lista(data) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("countries"), list):
        raise ValueError("Se esperaba una lista de canales en JSON con el campo countries.")


def _emisiones_canal(tipo: str, opciones, web: str, marcas: str) -> list[Emision]:
    emisiones: list[Emision] = []
    if tipo == "tv" and "EXTA" in marcas and url_http(web):
        emisiones.append(Emision("ext", web, "web"))
    for opcion in opciones if isinstance(opciones, list) else []:
        if not isinstance(opcion, dict):
            continue
        url = _texto(opcion.get("url"))
        formato = _texto(opcion.get("format")).lower()
        if not url:
            continue
        if formato == "youtube" and not url_http(url):
            url = "https://www.youtube.com/watch?v=" + url
        if not url_http(url):
            continue
        extra = dict(geo=_opcional(opcion.get("geo2")), resolucion=_opcional(opcion.get("res")), idioma=_opcional(opcion.get("lang")))
        if tipo == "radio":
            emisiones.append(Emision("directo", url, formato or "stream", **extra))
        elif "player.twitch.tv" in url or "twitch.tv" in url:
            emisiones.append(Emision("twitch", url, formato, **extra))
        elif "EXTB" in marcas and not es_directo(url):
            emisiones.append(Emision("ext", url, formato, **extra))
        elif formato == "youtube" or es_youtube(url):
            emisiones.append(Emision("youtube", url_youtube_navegable(url), "youtube", **extra))
        elif formato in ("m3u8", "stream", "mpd", "dash", "mp4", "mp3", "aac") or es_directo(url):
            emisiones.append(Emision("directo", url, formato or "stream", **extra))
        else:
            emisiones.append(Emision("web", url, formato or "web", **extra))
    if url_http(web):
        emisiones.append(Emision("web", web, "web"))
    return emisiones


def parsear_lista(data, tipo: str, origen: str) -> list[Canal]:
    """Convierte la lista JSON en canales. Lanza ValueError si no sirve."""
    if tipo not in ("tv", "radio"):
        raise ValueError("Tipo de lista desconocido.")
    validar_lista(data)
    canales: list[Canal] = []
    vistos: set[str] = set()
    for pais in data["countries"]:
        if not isinstance(pais, dict):
            continue
        nombre_pais = _texto(pais.get("name"))
        for ambito in pais.get("ambits") or []:
            if not isinstance(ambito, dict):
                continue
            nombre_ambito = _texto(ambito.get("name"))
            for crudo in ambito.get("channels") or []:
                if not isinstance(crudo, dict):
                    continue
                nombre = _texto(crudo.get("name"))
                if not nombre or nombre in vistos:
                    continue
                vistos.add(nombre)
                extra = crudo.get("extra_info")
                marcas = " ".join(x for x in extra if isinstance(x, str)) if isinstance(extra, list) else _texto(extra)
                web = _texto(crudo.get("web"))
                agente = UA_UAGB if "UAGB" in marcas else UA_UAG if "UAG" in marcas else ""
                canales.append(Canal(
                    nombre=nombre, tipo=tipo, pais=PAISES.get(nombre_pais, nombre_pais), ambito=nombre_ambito, web=web,
                    logo=_texto(crudo.get("logo")), epg_id=_texto(crudo.get("epg_id")),
                    emisiones=tuple(_emisiones_canal(tipo, crudo.get("options"), web, marcas)),
                    geo="GEO" in marcas, registro="REG" in marcas, sin_emision="NOEM" in marcas,
                    referer=_texto(crudo.get("referer")), user_agent=agente, origen=origen,
                ))
    if not canales:
        raise ValueError("La lista no contiene canales.")
    return canales


def canales_atresmedia(existentes: list[Canal]) -> list[Canal]:
    """Canales de Atresmedia que faltan en la lista oficial, con su directo de Atresplayer."""
    nombres = {plegar(c.nombre).replace(" ", "") for c in existentes if c.tipo == "tv"}
    nuevos = []
    for nombre, slug, epg in ATRESMEDIA:
        if plegar(nombre).replace(" ", "") in nombres:
            continue
        web = f"https://www.atresplayer.com/directos/{slug}/"
        nuevos.append(Canal(nombre, "tv", "España", "Generalistas", web, "", epg, (Emision("ext", web, "web"), Emision("web", web, "web")), geo=True, origen="Atresmedia · añadido por la aplicación"))
    return nuevos


def insertar_atresmedia(canales: list[Canal]) -> list[Canal]:
    """Coloca los canales de Atresmedia junto a los otros generalistas de España."""
    nuevos = canales_atresmedia(canales)
    if not nuevos:
        return canales
    posicion = 0
    for indice, canal in enumerate(canales):
        if canal.tipo == "tv" and canal.pais == "España" and canal.ambito == "Generalistas":
            posicion = indice + 1
            if plegar(canal.nombre) in ("la 2", "la2"):
                break
    return canales[:posicion] + nuevos + canales[posicion:]


def ambitos(canales: list[Canal], tipo: str) -> list[str]:
    resultado = []
    for canal in canales:
        if canal.tipo == tipo and canal.ambito not in resultado:
            resultado.append(canal.ambito)
    return resultado


def filtrar(canales: list[Canal], datos, tipo: str, texto: str = "", ambito: str = "", vista: str = "todos") -> list[Canal]:
    """Aplica búsqueda, ámbito, favoritos, ocultos y orden personal como el APK.

    ``vista``: ``todos``, ``favoritos`` u ``ocultos``. Además se respeta la
    preferencia ``hiddenChannelsVisibility`` (0 mostrar, 1 no mostrar, 2 solo ocultos).
    """
    palabras = plegar(texto).split()
    visibilidad = datos.usuario.get("hiddenChannelsVisibility", 0)
    comunidades_ocultas = set(datos.comunidades_ocultas(tipo))
    solo_favoritos = vista == "favoritos" or datos.solo_favoritos(tipo)
    resultado = []
    for indice, canal in enumerate(canales):
        if canal.tipo != tipo:
            continue
        if ambito and canal.ambito != ambito:
            continue
        if not ambito and canal.ambito in comunidades_ocultas:
            continue
        estado = datos.estado_canal(tipo, canal.nombre)
        if vista == "ocultos" or visibilidad == 2:
            if not estado["hide"]:
                continue
        elif visibilidad == 1 and estado["hide"]:
            continue
        if solo_favoritos and vista != "ocultos" and not estado["favorite"]:
            continue
        if palabras and not all(p in plegar(f"{canal.nombre} {canal.ambito} {canal.pais}") for p in palabras):
            continue
        posicion = estado["position"]
        # Los ocultos visibles van al final; después el orden personal y el de la lista.
        resultado.append((1 if estado["hide"] else 0, 0 if posicion is not None else 1, posicion if posicion is not None else 0, indice, canal))
    resultado.sort(key=lambda t: t[:4])
    return [t[4] for t in resultado]


# --- guía de programación --------------------------------------------------
@dataclass(frozen=True)
class Programa:
    inicio: int
    fin: int
    titulo: str
    descripcion: str = ""
    categoria: str = ""
    imagen: str = ""
    # Datos que aportan las guías XMLTV completas (géneros, año y valoración,
    # temporada y episodio, y la edad recomendada).
    subtitulo: str = ""
    episodio: str = ""
    edad: str = ""
    valoracion: str = ""

    def categoria_es(self) -> str:
        return CATEGORIAS_EPG.get(self.categoria.upper(), self.categoria.title()) if self.categoria else ""

    def detalles(self) -> list[tuple[str, str]]:
        """Datos adicionales del programa, para leerlos o mostrarlos en una ficha."""
        filas = []
        if self.categoria_es():
            filas.append(("Categoría", self.categoria_es()))
        if self.subtitulo:
            filas.append(("Detalles", self.subtitulo))
        if self.episodio:
            filas.append(("Episodio", self.episodio))
        if self.valoracion:
            filas.append(("Valoración", self.valoracion))
        if self.edad:
            filas.append(("Edad recomendada", self.edad))
        return filas

    def horario(self) -> str:
        return f"{time.strftime('%H:%M', time.localtime(self.inicio))}–{time.strftime('%H:%M', time.localtime(self.fin))}"

    def fecha(self) -> str:
        return time.strftime("%d/%m/%Y", time.localtime(self.inicio))

    def en_curso(self, ahora: float | None = None) -> bool:
        ahora = ahora or time.time()
        return self.inicio <= ahora < self.fin


def validar_guia(data) -> None:
    if not isinstance(data, list):
        raise ValueError("La guía no tiene el formato JSON esperado (lista de canales).")


def parsear_guia(data) -> dict[str, list[Programa]]:
    validar_guia(data)
    guia: dict[str, list[Programa]] = {}
    for canal in data:
        if not isinstance(canal, dict):
            continue
        programas = []
        for evento in canal.get("events") or []:
            if not isinstance(evento, dict):
                continue
            try:
                inicio, fin = int(evento["hi"]), int(evento["hf"])
            except (KeyError, TypeError, ValueError):
                continue
            if fin <= inicio:
                continue
            programas.append(Programa(inicio, fin, _texto(evento.get("t")) or "Sin título", _texto(evento.get("d")), _texto(evento.get("g")), _texto(evento.get("c"))))
        programas.sort(key=lambda p: p.inicio)
        guia[_texto(canal.get("name"))] = programas
    return guia


def clave_nombre(nombre: str) -> str:
    """Clave para emparejar guías de otras fuentes: sin tildes, signos ni «HD»."""
    limpio = plegar(nombre or "")
    limpio = re.sub(r"\b(hd|sd|fhd|uhd|4k|tv|television|televisio)\b", " ", limpio)
    return re.sub(r"[^a-z0-9]+", "", limpio)


def programas_canal(guia: dict[str, list[Programa]], canal: Canal) -> list[Programa]:
    """Programación del canal: por identificador de la guía oficial o por nombre."""
    if canal.epg_id:
        programas = guia.get(canal.epg_id)
        if programas:
            return programas
    return guia.get(PREFIJO_NOMBRE + clave_nombre(canal.nombre), [])


def limpiar_texto_guia(texto: str | None) -> str:
    """Quita las etiquetas de color de Kodi y los símbolos de adorno del texto de la guía."""
    limpio = ETIQUETAS_KODI.sub("", texto or "")
    lineas = [SIMBOLOS_INICIALES.sub("", linea).strip() for linea in limpio.splitlines()]
    return "\n".join(l for l in lineas if l).strip()


def _texto_preferido(elemento, etiqueta: str, idioma: str = IDIOMA_GUIA) -> str:
    """Texto de ``etiqueta`` en el idioma pedido; si no está, el primero que haya."""
    encontrados = elemento.findall(etiqueta)
    if not encontrados:
        return ""
    elegido = next((e for e in encontrados if (e.get("lang") or "").lower().startswith(idioma)), encontrados[0])
    limpio = limpiar_texto_guia(elegido.text)
    if limpio:
        return limpio
    for otro in encontrados:
        limpio = limpiar_texto_guia(otro.text)
        if limpio:
            return limpio
    return ""


def _episodio_xmltv(elemento) -> str:
    """«9.175.» del sistema xmltv_ns → «temporada 10, episodio 176»."""
    for numero in elemento.findall("episode-num"):
        sistema = (numero.get("system") or "").lower()
        texto = (numero.text or "").strip()
        if not texto:
            continue
        if sistema == "xmltv_ns":
            partes = [p.strip().split("/")[0].strip() for p in texto.split(".")]
            temporada = int(partes[0]) + 1 if len(partes) > 0 and partes[0].isdigit() else 0
            episodio = int(partes[1]) + 1 if len(partes) > 1 and partes[1].isdigit() else 0
            if temporada and episodio:
                return f"temporada {temporada}, episodio {episodio}"
            if episodio:
                return f"episodio {episodio}"
            if temporada:
                return f"temporada {temporada}"
        elif sistema in ("onscreen", "", "common"):
            return limpiar_texto_guia(texto)
    return ""


def _limpiar_subtitulo(texto: str) -> str:
    """Deja el subtítulo con los géneros y el año, sin las marcas de edad ni de nota.

    La edad y la valoración se extraen aparte de sus propias etiquetas, así que
    aquí solo estorban: «⑯» o «TP» sueltos no aportan nada al leerlos.
    """
    trozos = []
    for trozo in SIMBOLOS_SUBTITULO.sub("", texto or "").split("|"):
        trozo = trozo.strip(" ·|")
        if not trozo or trozo.upper().lstrip("+") in EDADES:
            continue
        trozos.append(trozo)
    return " · ".join(trozos)


def _generos_en_espanol(subtitulo: str) -> str:
    """Primer segmento del subtítulo cuando trae los géneros en español («Series,Comedia»)."""
    primero = (subtitulo.split("·")[0] if subtitulo else "").strip()
    if not primero or any(c.isdigit() for c in primero) or len(primero) > 60:
        return ""
    if primero.upper() in ("TP", "NR", "SC"):
        return ""
    return ", ".join(p.strip().capitalize() for p in primero.replace(",", "/").split("/") if p.strip())


def _valoracion_xmltv(elemento) -> str:
    valor = elemento.find("star-rating")
    if valor is None:
        return ""
    texto = limpiar_texto_guia(valor.findtext("value"))
    return texto.replace("/", " sobre ") if texto else ""


def _edad_xmltv(elemento) -> str:
    valor = elemento.find("rating")
    if valor is None:
        return ""
    texto = limpiar_texto_guia(valor.findtext("value"))
    if not texto:
        return ""
    return EDADES.get(texto.strip().rstrip("+").upper(), texto)


def parsear_xmltv(ruta, desde: float | None = None, hasta: float | None = None) -> dict[str, list[Programa]]:
    """Guía en formato XMLTV (por ejemplo la de EPG dobleM), indexada por nombre.

    Se aprovecha todo lo que trae cada programa: géneros y año (``sub-title``),
    temporada y episodio, edad recomendada, valoración e imagen. El texto se
    limpia de las etiquetas de color de Kodi que traen algunas variantes, que
    un lector de pantalla leería en voz alta.

    Solo se conservan los programas de la ventana pedida para no cargar en
    memoria semanas enteras de programación.
    """
    import gzip
    import xml.etree.ElementTree as ET
    from pathlib import Path

    ahora = time.time()
    desde = desde if desde is not None else ahora - 3 * 3600
    hasta = hasta if hasta is not None else ahora + 4 * 24 * 3600
    ruta = Path(ruta)
    abrir = gzip.open if ruta.suffix == ".gz" or ruta.name.endswith(".xml.gz") else open
    nombres: dict[str, list[str]] = {}
    programas: dict[str, list[Programa]] = {}
    with abrir(ruta, "rb") as flujo:
        for _evento, elemento in ET.iterparse(flujo, events=("end",)):
            if elemento.tag == "channel":
                identificador = elemento.get("id") or ""
                claves = {clave_nombre(identificador)}
                for nombre in elemento.findall("display-name"):
                    if nombre.text:
                        claves.add(clave_nombre(nombre.text))
                nombres[identificador] = [c for c in claves if c]
                elemento.clear()
            elif elemento.tag == "programme":
                inicio, fin = _hora_xmltv(elemento.get("start")), _hora_xmltv(elemento.get("stop"))
                if inicio and fin and fin > desde and inicio < hasta and fin > inicio:
                    titulo = _texto_preferido(elemento, "title")
                    if titulo:
                        imagen = elemento.find("icon")
                        subtitulo = _limpiar_subtitulo(_texto_preferido(elemento, "sub-title"))
                        # Los géneros en español del subtítulo se leen mejor que el género DVB en inglés;
                        # si se usan como categoría, no se repiten en el subtítulo.
                        generos = _generos_en_espanol(subtitulo)
                        categoria = generos or limpiar_texto_guia(elemento.findtext("category"))
                        if generos:
                            subtitulo = " · ".join(subtitulo.split(" · ")[1:])
                        programa = Programa(
                            int(inicio), int(fin), titulo,
                            _texto_preferido(elemento, "desc"),
                            categoria,
                            imagen.get("src", "") if imagen is not None else "",
                            subtitulo=subtitulo,
                            episodio=_episodio_xmltv(elemento),
                            edad=_edad_xmltv(elemento),
                            valoracion=_valoracion_xmltv(elemento),
                        )
                        for clave in nombres.get(elemento.get("channel") or "", []):
                            programas.setdefault(PREFIJO_NOMBRE + clave, []).append(programa)
                elemento.clear()
    for lista in programas.values():
        lista.sort(key=lambda p: p.inicio)
    return programas


def cobertura_guia(canales: list[Canal], guia: dict, tipo: str = "tv") -> tuple[list[Canal], list[Canal]]:
    """(canales con programación, canales sin ella) para saber qué cubre la guía."""
    con, sin = [], []
    for canal in canales:
        if canal.tipo != tipo:
            continue
        (con if programas_canal(guia, canal) else sin).append(canal)
    return con, sin


def parecidos(nombre: str, candidatos: list[str], maximo: int = 5) -> list[str]:
    """Nombres de la lista de la guía que se parecen a ``nombre``, para diagnosticar fallos."""
    import difflib

    clave = clave_nombre(nombre)
    if not clave:
        return []
    tabla = {clave_nombre(c): c for c in candidatos if clave_nombre(c)}
    exactos = [tabla[k] for k in tabla if k == clave]
    if exactos:
        return exactos[:maximo]
    cercanos = difflib.get_close_matches(clave, list(tabla), n=maximo, cutoff=0.72)
    contenidos = [tabla[k] for k in tabla if k not in cercanos and (clave in k or k in clave)]
    return [tabla[k] for k in cercanos] + contenidos[:maximo]


def _hora_xmltv(texto: str | None) -> float | None:
    """«20260907120000 +0200» → segundos desde 1970."""
    if not texto:
        return None
    partes = texto.strip().split()
    try:
        marca = datetime.strptime(partes[0][:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    desfase = 0
    if len(partes) > 1 and len(partes[1]) >= 5 and partes[1][0] in "+-":
        signo = 1 if partes[1][0] == "+" else -1
        try:
            desfase = signo * (int(partes[1][1:3]) * 3600 + int(partes[1][3:5]) * 60)
        except ValueError:
            desfase = 0
    return marca.replace(tzinfo=timezone.utc).timestamp() - desfase


def ahora_y_siguiente(programas: list[Programa], ahora: float | None = None) -> tuple[Programa | None, Programa | None]:
    ahora = ahora or time.time()
    actual = siguiente = None
    for programa in programas:
        if programa.inicio <= ahora < programa.fin:
            actual = programa
        elif programa.inicio > ahora:
            siguiente = programa
            break
    return actual, siguiente


def programas_desde(programas: list[Programa], ahora: float | None = None) -> list[Programa]:
    ahora = ahora or time.time()
    return [p for p in programas if p.fin > ahora]
