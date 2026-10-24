"""Cuentas Xtream Codes: el acceso con servidor, usuario y contraseña.

La mayoría de proveedores IPTV no dan un archivo de lista, sino unas
credenciales para una API muy sencilla::

    http://servidor:puerto/player_api.php?username=U&password=P&action=…

Las acciones que se usan aquí son ``get_live_categories``,
``get_live_streams``, ``get_vod_categories``, ``get_vod_streams``,
``get_series``, ``get_series_info``, ``get_short_epg`` y
``get_simple_data_table``. Las direcciones de reproducción se construyen a
partir de las credenciales:

- directo:   ``http://servidor/live/usuario/clave/<id>.m3u8``
- película:  ``http://servidor/movie/usuario/clave/<id>.<extensión>``
- episodio:  ``http://servidor/series/usuario/clave/<id>.<extensión>``

La contraseña nunca se guarda en claro: se cifra con la protección de datos de
Windows (ver ``tdt.cifrado``).
"""
from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import cifrado
from .catalogo import Canal, Emision, Programa
from .datos import USER_AGENT_APP

registro = logging.getLogger(__name__)
LIMITE = 48 * 1024 * 1024
TIEMPO_ESPERA = 30


class ErrorXtream(RuntimeError):
    """El servidor no ha respondido o ha rechazado las credenciales."""


@dataclass(frozen=True)
class Cuenta:
    """Datos de acceso a un proveedor. ``secreto`` es la contraseña ya cifrada."""

    nombre: str
    servidor: str
    usuario: str
    secreto: str
    tipo: str = "tv"

    @property
    def contrasena(self) -> str:
        return cifrado.descifrar(self.secreto)

    @property
    def base(self) -> str:
        return self.servidor.rstrip("/")

    def a_json(self) -> dict:
        return {"nombre": self.nombre, "servidor": self.servidor, "usuario": self.usuario, "secreto": self.secreto, "tipo": self.tipo}

    @classmethod
    def crear(cls, nombre: str, servidor: str, usuario: str, contrasena: str, tipo: str = "tv") -> "Cuenta":
        servidor = servidor.strip()
        if not servidor.startswith(("http://", "https://")):
            servidor = "http://" + servidor
        return cls(nombre.strip() or servidor, servidor.rstrip("/"), usuario.strip(), cifrado.cifrar(contrasena), tipo)

    @classmethod
    def desde_json(cls, entrada: dict) -> "Cuenta | None":
        if not isinstance(entrada, dict):
            return None
        servidor, usuario = str(entrada.get("servidor") or "").strip(), str(entrada.get("usuario") or "").strip()
        if not servidor.startswith(("http://", "https://")) or not usuario:
            return None
        return cls(str(entrada.get("nombre") or servidor), servidor.rstrip("/"), usuario, str(entrada.get("secreto") or ""), "radio" if entrada.get("tipo") == "radio" else "tv")


def _pedir(cuenta: Cuenta, parametros: dict, timeout: int = TIEMPO_ESPERA):
    consulta = {"username": cuenta.usuario, "password": cuenta.contrasena}
    consulta.update(parametros)
    url = f"{cuenta.base}/player_api.php?" + urllib.parse.urlencode(consulta)
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT_APP, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            crudo = respuesta.read(LIMITE + 1)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise ErrorXtream(f"No se pudo contactar con el servidor: {error}") from error
    if len(crudo) > LIMITE:
        raise ErrorXtream("La respuesta del servidor es demasiado grande.")
    try:
        return json.loads(crudo.decode("utf-8-sig", "replace"))
    except ValueError as error:
        raise ErrorXtream("El servidor no ha devuelto datos en formato JSON. Comprueba la dirección.") from error


def _texto(valor) -> str:
    if isinstance(valor, str):
        return valor.strip()
    if isinstance(valor, (int, float)):
        return str(valor)
    return ""


def _entero(valor) -> int:
    try:
        return int(float(str(valor).strip()))
    except (TypeError, ValueError):
        return 0


def _base64(valor) -> str:
    texto = _texto(valor)
    if not texto:
        return ""
    try:
        return base64.b64decode(texto + "=" * (-len(texto) % 4)).decode("utf-8", "replace").strip()
    except Exception:
        return texto


def informacion(cuenta: Cuenta) -> dict:
    """Datos de la cuenta: estado, caducidad y conexiones. Lanza ErrorXtream si falla."""
    datos = _pedir(cuenta, {})
    if not isinstance(datos, dict) or not isinstance(datos.get("user_info"), dict):
        raise ErrorXtream("El servidor no ha reconocido la cuenta.")
    usuario = datos["user_info"]
    if _texto(usuario.get("auth")) in ("0", "false") or _texto(usuario.get("status")).lower() in ("banned", "disabled", "expired"):
        raise ErrorXtream(f"El servidor ha rechazado la cuenta (estado: {_texto(usuario.get('status')) or 'sin autorizar'}).")
    caduca = _entero(usuario.get("exp_date"))
    return {
        "estado": _texto(usuario.get("status")) or "activa",
        "caduca": caduca,
        "caduca_texto": time.strftime("%d/%m/%Y", time.localtime(caduca)) if caduca else "sin fecha de caducidad",
        "conexiones": _texto(usuario.get("max_connections")) or "1",
        "activas": _texto(usuario.get("active_cons")) or "0",
        "servidor": _texto((datos.get("server_info") or {}).get("url")) or cuenta.base,
        "prueba": _texto(usuario.get("is_trial")) == "1",
    }


def _categorias(cuenta: Cuenta, accion: str) -> dict[str, str]:
    try:
        datos = _pedir(cuenta, {"action": accion})
    except ErrorXtream:
        return {}
    if not isinstance(datos, list):
        return {}
    return {_texto(c.get("category_id")): _texto(c.get("category_name")) for c in datos if isinstance(c, dict)}


def url_directo(cuenta: Cuenta, identificador: str, extension: str = "m3u8") -> str:
    return f"{cuenta.base}/live/{urllib.parse.quote(cuenta.usuario)}/{urllib.parse.quote(cuenta.contrasena)}/{identificador}.{extension}"


def url_pelicula(cuenta: Cuenta, identificador: str, extension: str = "mp4") -> str:
    return f"{cuenta.base}/movie/{urllib.parse.quote(cuenta.usuario)}/{urllib.parse.quote(cuenta.contrasena)}/{identificador}.{extension}"


def url_episodio(cuenta: Cuenta, identificador: str, extension: str = "mp4") -> str:
    return f"{cuenta.base}/series/{urllib.parse.quote(cuenta.usuario)}/{urllib.parse.quote(cuenta.contrasena)}/{identificador}.{extension}"


def canales(cuenta: Cuenta, limite: int = 20000) -> list[Canal]:
    """Canales en directo de la cuenta, ya convertidos al formato de la aplicación."""
    datos = _pedir(cuenta, {"action": "get_live_streams"})
    if not isinstance(datos, list):
        raise ErrorXtream("El servidor no ha devuelto la lista de canales.")
    nombres_categoria = _categorias(cuenta, "get_live_categories")
    resultado: list[Canal] = []
    vistos: set[str] = set()
    for entrada in datos:
        if not isinstance(entrada, dict):
            continue
        nombre = _texto(entrada.get("name"))
        identificador = _texto(entrada.get("stream_id"))
        if not nombre or not identificador:
            continue
        clave = nombre.casefold()
        if clave in vistos:
            continue
        vistos.add(clave)
        directo = _texto(entrada.get("direct_source")) or url_directo(cuenta, identificador)
        archivo = _entero(entrada.get("tv_archive"))
        resultado.append(Canal(
            nombre=nombre, tipo=cuenta.tipo, pais="", ambito=nombres_categoria.get(_texto(entrada.get("category_id")), "Sin categoría"),
            web="", logo=_texto(entrada.get("stream_icon")), epg_id=_texto(entrada.get("epg_channel_id")),
            emisiones=(Emision("directo", directo, "m3u8"),), origen=cuenta.nombre,
            numero=_entero(entrada.get("num")),
            catchup="xc" if archivo else "", catchup_dias=_entero(entrada.get("tv_archive_duration")),
            identificador=identificador,
        ))
        if len(resultado) >= limite:
            break
    if not resultado:
        raise ErrorXtream("La cuenta no tiene ningún canal en directo.")
    return resultado


def peliculas(cuenta: Cuenta, limite: int = 20000) -> list[dict]:
    """Películas de la cuenta: nombre, categoría, dirección y datos de ficha."""
    datos = _pedir(cuenta, {"action": "get_vod_streams"})
    if not isinstance(datos, list):
        return []
    nombres = _categorias(cuenta, "get_vod_categories")
    salida = []
    for entrada in datos[:limite]:
        if not isinstance(entrada, dict):
            continue
        identificador = _texto(entrada.get("stream_id"))
        nombre = _texto(entrada.get("name"))
        if not identificador or not nombre:
            continue
        extension = _texto(entrada.get("container_extension")) or "mp4"
        salida.append({
            "titulo": nombre, "categoria": nombres.get(_texto(entrada.get("category_id")), "Sin categoría"),
            "url": _texto(entrada.get("direct_source")) or url_pelicula(cuenta, identificador, extension),
            "imagen": _texto(entrada.get("stream_icon")), "valoracion": _texto(entrada.get("rating")),
            "anadida": _entero(entrada.get("added")), "identificador": identificador, "clase": "pelicula",
        })
    return salida


def series(cuenta: Cuenta, limite: int = 20000) -> list[dict]:
    """Series de la cuenta (sin episodios: se piden al abrir cada serie)."""
    datos = _pedir(cuenta, {"action": "get_series"})
    if not isinstance(datos, list):
        return []
    nombres = _categorias(cuenta, "get_series_categories")
    salida = []
    for entrada in datos[:limite]:
        if not isinstance(entrada, dict):
            continue
        identificador = _texto(entrada.get("series_id"))
        nombre = _texto(entrada.get("name"))
        if not identificador or not nombre:
            continue
        salida.append({
            "titulo": nombre, "categoria": nombres.get(_texto(entrada.get("category_id")), "Sin categoría"),
            "url": "", "imagen": _texto(entrada.get("cover")), "valoracion": _texto(entrada.get("rating")),
            "anadida": 0, "identificador": identificador, "clase": "serie",
            "descripcion": _texto(entrada.get("plot")),
        })
    return salida


def episodios(cuenta: Cuenta, serie: str) -> list[dict]:
    """Episodios de una serie, ordenados por temporada y número."""
    datos = _pedir(cuenta, {"action": "get_series_info", "series_id": serie})
    if not isinstance(datos, dict):
        return []
    salida = []
    temporadas = datos.get("episodes")
    if isinstance(temporadas, dict):
        grupos = temporadas.items()
    elif isinstance(temporadas, list):
        grupos = enumerate(temporadas)
    else:
        grupos = []
    for temporada, lista in grupos:
        for entrada in lista if isinstance(lista, list) else []:
            if not isinstance(entrada, dict):
                continue
            identificador = _texto(entrada.get("id"))
            if not identificador:
                continue
            extension = _texto(entrada.get("container_extension")) or "mp4"
            informacion_ep = entrada.get("info") if isinstance(entrada.get("info"), dict) else {}
            salida.append({
                "titulo": _texto(entrada.get("title")) or f"Episodio {_texto(entrada.get('episode_num'))}",
                "temporada": _entero(temporada), "episodio": _entero(entrada.get("episode_num")),
                "url": url_episodio(cuenta, identificador, extension),
                "descripcion": _texto(informacion_ep.get("plot")), "duracion": _texto(informacion_ep.get("duration")),
                "identificador": identificador, "clase": "episodio",
            })
    salida.sort(key=lambda e: (e["temporada"], e["episodio"]))
    return salida


def guia_canal(cuenta: Cuenta, identificador: str, limite: int = 40) -> list[Programa]:
    """Programación de un canal según el propio servidor (``get_short_epg``)."""
    try:
        datos = _pedir(cuenta, {"action": "get_short_epg", "stream_id": identificador, "limit": limite}, timeout=20)
    except ErrorXtream:
        return []
    listado = datos.get("epg_listings") if isinstance(datos, dict) else datos
    programas = []
    for entrada in listado if isinstance(listado, list) else []:
        if not isinstance(entrada, dict):
            continue
        inicio = _entero(entrada.get("start_timestamp"))
        fin = _entero(entrada.get("stop_timestamp"))
        if not inicio or fin <= inicio:
            continue
        titulo = _base64(entrada.get("title")) or "Sin título"
        programas.append(Programa(inicio, fin, titulo, _base64(entrada.get("description"))))
    programas.sort(key=lambda p: p.inicio)
    return programas


def guia(cuenta: Cuenta, canales_cuenta: list[Canal], maximo: int = 200) -> dict[str, list[Programa]]:
    """Programación de los primeros canales de la cuenta, indexada por nombre de canal."""
    from .catalogo import PREFIJO_NOMBRE, clave_nombre

    resultado: dict[str, list[Programa]] = {}
    for canal in canales_cuenta[:maximo]:
        if not canal.identificador:
            continue
        programas = guia_canal(cuenta, canal.identificador)
        if programas:
            resultado[PREFIJO_NOMBRE + clave_nombre(canal.nombre)] = programas
            if canal.epg_id:
                resultado[canal.epg_id] = programas
    return resultado
