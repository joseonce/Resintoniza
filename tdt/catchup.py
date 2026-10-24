"""Catch-up: ver un programa que ya se emitió.

Las listas que lo permiten declaran en cada canal un modo (``catchup``) y a
veces una plantilla (``catchup-source``). La dirección del programa pasado se
construye a partir de la del directo y de la hora de inicio y fin, que ya nos
da la guía de programación. Hay cuatro gramáticas extendidas:

- ``default`` / ``append``: se añaden parámetros a la dirección del directo,
  normalmente ``utc`` (inicio en segundos UTC) y ``lutc`` (hora actual).
- ``flussonic``: la ruta se reescribe a ``…/<inicio>-<duración>.m3u8``, con el
  inicio en segundos UTC y la duración en segundos.
- ``shift``: como ``default`` pero con un parámetro de desplazamiento.
- ``xc`` (Xtream Codes): ``/timeshift/usuario/clave/<duración en minutos>/
  <AAAA-MM-DD:HH-MM>/<id>.m3u8``, con la hora **local** del servidor.

Nada de esto es un estándar: son las convenciones que usan Kodi, TiviMate y
compañía, así que la plantilla del proveedor manda siempre que exista.
"""
from __future__ import annotations

import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Marcas admitidas en catchup-source, con la función que las convierte.
_MARCAS = {
    "utc": lambda inicio, fin, ahora: str(int(inicio)),
    "start": lambda inicio, fin, ahora: str(int(inicio)),
    "timestamp": lambda inicio, fin, ahora: str(int(inicio)),
    "end": lambda inicio, fin, ahora: str(int(fin)),
    "utcend": lambda inicio, fin, ahora: str(int(fin)),
    "lutc": lambda inicio, fin, ahora: str(int(ahora)),
    "now": lambda inicio, fin, ahora: str(int(ahora)),
    "timenow": lambda inicio, fin, ahora: str(int(ahora)),
    "duration": lambda inicio, fin, ahora: str(max(1, int(fin - inicio))),
    "offset": lambda inicio, fin, ahora: str(max(0, int(ahora - inicio))),
    "Y": lambda inicio, fin, ahora: time.strftime("%Y", time.localtime(inicio)),
    "m": lambda inicio, fin, ahora: time.strftime("%m", time.localtime(inicio)),
    "d": lambda inicio, fin, ahora: time.strftime("%d", time.localtime(inicio)),
    "H": lambda inicio, fin, ahora: time.strftime("%H", time.localtime(inicio)),
    "M": lambda inicio, fin, ahora: time.strftime("%M", time.localtime(inicio)),
    "S": lambda inicio, fin, ahora: time.strftime("%S", time.localtime(inicio)),
}


def disponible(canal, inicio: float, fin: float, ahora: float | None = None) -> bool:
    """True si el canal declara catch-up y el programa ya terminó y sigue dentro del plazo."""
    ahora = ahora if ahora is not None else time.time()
    if not getattr(canal, "catchup", ""):
        return False
    if fin > ahora:
        return False
    dias = getattr(canal, "catchup_dias", 0) or 7
    return inicio >= ahora - dias * 24 * 3600


def _rellenar(plantilla: str, base: str, inicio: float, fin: float, ahora: float) -> str:
    """Sustituye las marcas ``{utc}``, ``${start}``, ``{Y}-{m}-{d}``… de una plantilla."""
    texto = plantilla.replace("${", "{")
    for marca, funcion in _MARCAS.items():
        clave = "{" + marca + "}"
        if clave in texto:
            texto = texto.replace(clave, funcion(inicio, fin, ahora))
    return texto if texto.startswith(("http://", "https://")) else _unir(base, texto)


def _unir(base: str, cola: str) -> str:
    """Une la dirección del directo con la cola de la plantilla (parámetros o ruta)."""
    if cola.startswith("?") or cola.startswith("&"):
        return _con_parametros(base, dict(parse_qsl(cola.lstrip("?&"), keep_blank_values=True)))
    partes = urlparse(base)
    return urlunparse(partes._replace(path=cola if cola.startswith("/") else partes.path.rsplit("/", 1)[0] + "/" + cola))


def _con_parametros(url: str, extra: dict) -> str:
    partes = urlparse(url)
    consulta = dict(parse_qsl(partes.query, keep_blank_values=True))
    consulta.update(extra)
    return urlunparse(partes._replace(query=urlencode(consulta)))


def _flussonic(url: str, inicio: float, fin: float) -> str:
    """``…/canal/index.m3u8`` → ``…/canal/<inicio>-<duración>.m3u8``."""
    partes = urlparse(url)
    trozos = [t for t in partes.path.split("/") if t]
    if not trozos:
        return url
    ultimo = trozos[-1]
    duracion = max(1, int(fin - inicio))
    extension = ".m3u8" if not ultimo.endswith(".ts") else ".ts"
    if ultimo.startswith(("index", "mono", "video", "playlist", "master")) or "." in ultimo:
        trozos[-1] = f"{int(inicio)}-{duracion}{extension}"
    else:
        trozos.append(f"{int(inicio)}-{duracion}{extension}")
    return urlunparse(partes._replace(path="/" + "/".join(trozos)))


def _xtream(url: str, inicio: float, fin: float) -> str:
    """``http://servidor/usuario/clave/1234.ts`` → ``…/timeshift/usuario/clave/<min>/<fecha>/1234.ts``."""
    partes = urlparse(url)
    trozos = [t for t in partes.path.split("/") if t]
    if len(trozos) < 3:
        return url
    identificador = trozos[-1]
    clave = trozos[-2]
    usuario = trozos[-3]
    minutos = max(1, int((fin - inicio) / 60))
    momento = time.strftime("%Y-%m-%d:%H-%M", time.localtime(inicio))
    return urlunparse(partes._replace(path=f"/timeshift/{usuario}/{clave}/{minutos}/{momento}/{identificador}"))


def url_programa(canal, url_directo: str, inicio: float, fin: float, ahora: float | None = None) -> str:
    """Dirección para ver el programa emitido entre ``inicio`` y ``fin``. "" si no se puede."""
    ahora = ahora if ahora is not None else time.time()
    modo = (getattr(canal, "catchup", "") or "").lower()
    if not modo or not url_directo:
        return ""
    plantilla = (getattr(canal, "catchup_fuente", "") or "").strip()
    if plantilla:
        return _rellenar(plantilla, url_directo, inicio, fin, ahora)
    if modo == "flussonic":
        return _flussonic(url_directo, inicio, fin)
    if modo == "xc":
        return _xtream(url_directo, inicio, fin)
    if modo == "shift":
        return _con_parametros(url_directo, {"utc": str(int(inicio)), "lutc": str(int(ahora))})
    # default y append: parámetros utc y lutc, lo que admite la mayoría de servidores.
    return _con_parametros(url_directo, {"utc": str(int(inicio)), "lutc": str(int(ahora))})
