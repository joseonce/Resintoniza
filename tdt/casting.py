"""Enviar la emisión a un televisor de la red: DLNA, Chromecast y Fire TV.

Tres caminos, según lo que haya al otro lado:

- **DLNA o UPnP**: casi cualquier televisor moderno anuncia un servicio
  ``AVTransport``. Se descubre con una petición SSDP y se controla con dos
  mensajes SOAP, ``SetAVTransportURI`` y ``Play``, solo con la biblioteca
  estándar.
- **Chromecast** (y televisores con Google TV): protocolo propio de Google,
  con la biblioteca ``pychromecast``. Se le pasa la dirección del directo y lo
  reproduce el receptor por omisión.
- **Fire TV y Android TV**: se descubren por DIAL, pero no aceptan una
  dirección suelta. Se puede hacer dos cosas: instalar en el aparato una
  aplicación que reciba por DLNA (entonces aparece como DLNA y funciona igual
  que el resto), o duplicar la pantalla de Windows con Miracast, que Fire TV
  admite de fábrica.

Nada de esto se hace solo: siempre lo pide la persona desde el diálogo.
"""
from __future__ import annotations

import logging
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

registro = logging.getLogger(__name__)
GRUPO_SSDP = ("239.255.255.250", 1900)
ESPACIO_AVT = "urn:schemas-upnp-org:service:AVTransport:1"
ESPACIO_DIAL = "urn:dial-multiscreen-org:service:dial:1"
BUSQUEDA = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: {objetivo}\r\n\r\n"
)
METADATOS = (
    '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
    '<item id="1" parentID="0" restricted="1">'
    "<dc:title>{titulo}</dc:title>"
    "<upnp:class>object.item.videoItem</upnp:class>"
    '<res protocolInfo="http-get:*:{tipo}:*">{url}</res>'
    "</item></DIDL-Lite>"
)
NOMBRES_FIRE = ("fire tv", "firetv", "aftt", "aftm", "amazon")
# Chromecast descubiertos en esta sesión, para no volver a buscarlos al enviar.
_chromecasts: dict = {}


@dataclass(frozen=True)
class Dispositivo:
    """Un aparato de la red al que se puede enviar la emisión."""

    nombre: str
    clase: str            # "dlna", "chromecast" o "dial"
    control: str = ""     # dirección de control AVTransport (DLNA)
    anfitrion: str = ""   # dirección del aparato
    modelo: str = ""
    identificador: str = ""

    @property
    def tipo_legible(self) -> str:
        return {"dlna": "DLNA", "chromecast": "Chromecast", "dial": "Fire TV o Android TV"}.get(self.clase, self.clase)

    @property
    def admite_envio(self) -> bool:
        """True si se le puede mandar la dirección directamente."""
        return self.clase in ("dlna", "chromecast")

    def __str__(self) -> str:
        modelo = f", {self.modelo}" if self.modelo else ""
        return f"{self.nombre} ({self.tipo_legible}{modelo})" + ("" if self.admite_envio else " · no acepta enlaces directos")


def _escapar(texto: str) -> str:
    return (texto or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _localizaciones(objetivo: str, espera: float = 3.0) -> list[str]:
    """Direcciones de descripción de los aparatos que responden al descubrimiento."""
    encontradas: list[str] = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    except OSError as error:
        registro.info("No se pudo abrir el socket de descubrimiento: %s", error)
        return encontradas
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(espera)
        sock.sendto(BUSQUEDA.format(objetivo=objetivo).encode("ascii"), GRUPO_SSDP)
        while True:
            try:
                datos, _origen = sock.recvfrom(8192)
            except (socket.timeout, TimeoutError, OSError):
                break
            texto = datos.decode("utf-8", "replace")
            coincidencia = re.search(r"(?im)^location:\s*(\S+)\s*$", texto)
            if coincidencia and coincidencia.group(1) not in encontradas:
                encontradas.append(coincidencia.group(1))
    finally:
        sock.close()
    return encontradas


def _descripcion(url: str) -> tuple[str, str, str]:
    """(nombre visible, dirección de control AVTransport, modelo) del aparato descrito."""
    try:
        peticion = urllib.request.Request(url, headers={"User-Agent": "Resintoniza"})
        with urllib.request.urlopen(peticion, timeout=6) as respuesta:
            crudo = respuesta.read(512 * 1024)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return "", "", ""
    try:
        raiz = ET.fromstring(crudo)
    except ET.ParseError:
        return "", "", ""
    espacio = "{urn:schemas-upnp-org:device-1-0}"
    nombre = (raiz.findtext(f".//{espacio}friendlyName") or "").strip()
    modelo = (raiz.findtext(f".//{espacio}modelName") or "").strip()
    for servicio in raiz.iter(f"{espacio}service"):
        if "AVTransport" not in (servicio.findtext(f"{espacio}serviceType") or ""):
            continue
        control = (servicio.findtext(f"{espacio}controlURL") or "").strip()
        if control:
            return nombre or url, urllib.parse.urljoin(url, control), modelo
    return nombre, "", modelo


def _anfitrion(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return ""


def buscar_dlna(espera: float = 3.0) -> list[Dispositivo]:
    aparatos, vistos = [], set()
    for localizacion in _localizaciones(ESPACIO_AVT, espera):
        nombre, control, modelo = _descripcion(localizacion)
        if not control or control in vistos:
            continue
        vistos.add(control)
        aparatos.append(Dispositivo(nombre or "Aparato DLNA", "dlna", control=control, anfitrion=_anfitrion(localizacion), modelo=modelo))
    return aparatos


def buscar_dial(espera: float = 3.0) -> list[Dispositivo]:
    """Fire TV, Android TV y similares: se ven en la red aunque no acepten enlaces."""
    aparatos, vistos = [], set()
    for localizacion in _localizaciones(ESPACIO_DIAL, espera):
        anfitrion = _anfitrion(localizacion)
        if not anfitrion or anfitrion in vistos:
            continue
        vistos.add(anfitrion)
        nombre, control, modelo = _descripcion(localizacion)
        if control:
            # Trae AVTransport: se maneja como DLNA, que sí acepta la dirección.
            aparatos.append(Dispositivo(nombre or "Televisor", "dlna", control=control, anfitrion=anfitrion, modelo=modelo))
            continue
        aparatos.append(Dispositivo(nombre or "Aparato de televisión", "dial", anfitrion=anfitrion, modelo=modelo))
    return aparatos


def buscar_chromecast(espera: float = 6.0) -> list[Dispositivo]:
    """Chromecast, Google TV y altavoces con pantalla."""
    try:
        import pychromecast
    except Exception as error:
        registro.info("pychromecast no está disponible: %s", error)
        return []
    try:
        encontrados, explorador = pychromecast.get_chromecasts(timeout=espera)
    except Exception as error:
        registro.info("No se pudieron buscar Chromecasts: %s", error)
        return []
    aparatos = []
    try:
        for aparato in encontrados:
            info = aparato.cast_info
            identificador = str(info.uuid)
            _chromecasts[identificador] = aparato
            aparatos.append(Dispositivo(str(info.friendly_name), "chromecast", anfitrion=str(info.host),
                                        modelo=str(info.model_name or ""), identificador=identificador))
    finally:
        try:
            pychromecast.discovery.stop_discovery(explorador)
        except Exception:
            registro.debug("No se pudo cerrar el buscador de Chromecast", exc_info=True)
    return aparatos


def buscar(espera: float = 3.0) -> list[Dispositivo]:
    """Todos los aparatos de la red a los que se puede enviar o duplicar la emisión."""
    aparatos: list[Dispositivo] = []
    vistos: set[str] = set()
    for grupo in (buscar_dlna(espera), buscar_chromecast(max(espera, 5.0)), buscar_dial(espera)):
        for aparato in grupo:
            clave = f"{aparato.clase}|{aparato.anfitrion or aparato.control}"
            # Un mismo aparato puede responder por DIAL y por DLNA: manda el que acepta enlaces.
            if clave in vistos or (aparato.clase == "dial" and any(a.anfitrion == aparato.anfitrion and a.admite_envio for a in aparatos)):
                continue
            vistos.add(clave)
            aparatos.append(aparato)
    aparatos.sort(key=lambda d: (not d.admite_envio, d.nombre.lower()))
    return aparatos


def tipo_contenido(url: str) -> str:
    bajo = (url or "").lower()
    if ".m3u8" in bajo:
        return "application/x-mpegURL"
    if bajo.endswith(".ts"):
        return "video/mp2t"
    if bajo.endswith((".mp3", ".aac")):
        return "audio/mpeg"
    if bajo.endswith(".mpd"):
        return "application/dash+xml"
    return "video/mp4"


# --- DLNA -------------------------------------------------------------------
def _soap(control: str, accion: str, cuerpo: str) -> bool:
    sobre = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:{accion} xmlns:u="{ESPACIO_AVT}"><InstanceID>0</InstanceID>{cuerpo}</u:{accion}>'
        "</s:Body></s:Envelope>"
    )
    peticion = urllib.request.Request(
        control, data=sobre.encode("utf-8"),
        headers={"Content-Type": 'text/xml; charset="utf-8"', "SOAPACTION": f'"{ESPACIO_AVT}#{accion}"', "User-Agent": "Resintoniza"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=10) as respuesta:
            respuesta.read(64 * 1024)
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        registro.info("Error enviando %s a %s: %s", accion, control, error)
        return False


def _enviar_dlna(dispositivo: Dispositivo, url: str, titulo: str) -> bool:
    metadatos = METADATOS.format(titulo=_escapar(titulo or "Emisión"), url=_escapar(url), tipo=tipo_contenido(url))
    cuerpo = f"<CurrentURI>{_escapar(url)}</CurrentURI><CurrentURIMetaData>{_escapar(metadatos)}</CurrentURIMetaData>"
    if not _soap(dispositivo.control, "SetAVTransportURI", cuerpo):
        return False
    return _soap(dispositivo.control, "Play", "<Speed>1</Speed>")


# --- Chromecast --------------------------------------------------------------
def _aparato_chromecast(dispositivo: Dispositivo):
    """Recupera el Chromecast descubierto, o lo busca otra vez por su nombre."""
    aparato = _chromecasts.get(dispositivo.identificador)
    if aparato is not None:
        return aparato
    import pychromecast

    encontrados, explorador = pychromecast.get_listed_chromecasts(friendly_names=[dispositivo.nombre], timeout=8)
    try:
        if not encontrados:
            raise RuntimeError(f"No se ha encontrado «{dispositivo.nombre}» en la red.")
        aparato = encontrados[0]
        _chromecasts[str(aparato.cast_info.uuid)] = aparato
        return aparato
    finally:
        try:
            pychromecast.discovery.stop_discovery(explorador)
        except Exception:
            pass


def _enviar_chromecast(dispositivo: Dispositivo, url: str, titulo: str) -> bool:
    try:
        aparato = _aparato_chromecast(dispositivo)
        aparato.wait(timeout=15)
        control = aparato.media_controller
        control.play_media(url, tipo_contenido(url), title=titulo or "Emisión", stream_type="LIVE")
        control.block_until_active(timeout=15)
        return True
    except Exception as error:
        registro.info("No se pudo enviar al Chromecast %s: %s", dispositivo.nombre, error)
        return False


def _parar_chromecast(dispositivo: Dispositivo) -> bool:
    try:
        aparato = _aparato_chromecast(dispositivo)
        aparato.wait(timeout=10)
        aparato.media_controller.stop()
        aparato.quit_app()
        return True
    except Exception as error:
        registro.info("No se pudo parar el Chromecast %s: %s", dispositivo.nombre, error)
        return False


# --- Fire TV y Android TV ----------------------------------------------------
def duplicar_pantalla() -> bool:
    """Abre el panel de Windows para duplicar la pantalla (Miracast), como Windows+K.

    Es lo que admiten de fábrica los Fire TV: en el aparato hay que abrir
    «Duplicar pantalla» y aquí elegirlo en la lista que muestra Windows.
    """
    try:
        import ctypes

        usuario = ctypes.windll.user32
        WIN, K = 0x5B, 0x4B
        usuario.keybd_event(WIN, 0, 0, 0)
        usuario.keybd_event(K, 0, 0, 0)
        usuario.keybd_event(K, 0, 2, 0)
        usuario.keybd_event(WIN, 0, 2, 0)
        return True
    except Exception as error:
        registro.info("No se pudo abrir el panel de duplicar pantalla: %s", error)
        return False


def instrucciones(dispositivo: Dispositivo) -> str:
    """Qué hacer con un aparato que no acepta enlaces directos."""
    fire = any(marca in f"{dispositivo.nombre} {dispositivo.modelo}".lower() for marca in NOMBRES_FIRE)
    aparato = "Fire TV" if fire else "televisor"
    return (
        f"{dispositivo.nombre} se ve en la red, pero no acepta que se le mande una dirección directamente.\n\n"
        f"Dos maneras de verlo en ese {aparato}:\n"
        "1. Instalar en él una aplicación que reciba por DLNA o UPnP (por ejemplo un reproductor con receptor UPnP). "
        "Con esa aplicación abierta, el aparato aparecerá aquí como DLNA y podrás enviarle la emisión con el botón Enviar.\n"
        f"2. Duplicar la pantalla de Windows: en el {aparato}, abrir «Duplicar pantalla», y aquí usar el botón "
        "«Duplicar la pantalla», que abre el panel de Windows (lo mismo que la tecla Windows más K)."
    )


# --- interfaz común ----------------------------------------------------------
def enviar(dispositivo: Dispositivo, url: str, titulo: str = "") -> bool:
    """Manda la dirección al aparato y empieza a reproducir. False si no lo acepta."""
    if dispositivo.clase == "chromecast":
        return _enviar_chromecast(dispositivo, url, titulo)
    if dispositivo.clase == "dlna":
        return _enviar_dlna(dispositivo, url, titulo)
    return False


def parar(dispositivo: Dispositivo) -> bool:
    if dispositivo.clase == "chromecast":
        return _parar_chromecast(dispositivo)
    if dispositivo.clase == "dlna":
        return _soap(dispositivo.control, "Stop", "")
    return False


def chromecast_disponible() -> bool:
    try:
        import pychromecast  # noqa: F401

        return True
    except Exception:
        return False
