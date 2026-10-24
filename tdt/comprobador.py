"""Comprobar en segundo plano qué canales responden.

Con miles de canales en varias listas, muchos han dejado de emitir hace meses y
solo se descubre al intentar verlos. Aquí se le pide a cada emisión su
dirección (sin reproducir nada: una petición HTTP y unos kilobytes) y se dice
cuáles contestan, cuáles fallan y cuáles no se pueden comprobar así.

Los canales que se ven en la web oficial (Atresplayer, Mitele…) se resuelven
antes de comprobarlos: así se descubre enseguida si la lista ha cambiado la
dirección de un canal a un sitio que todavía no se sabe resolver.

No se abre ningún reproductor: es rápido, no gasta apenas datos y no molesta a
lo que se esté escuchando.
"""
from __future__ import annotations

import logging
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from . import proveedores

registro = logging.getLogger(__name__)
BYTES_PRUEBA = 4096
ESPERA = 8.0
HILOS = 8
ESTADOS = {"ok": "Responde", "error": "No responde", "omitido": "No se puede comprobar"}


TIPOS_COMPROBABLES = ("directo", "ext")


def comprobable(canal) -> bool:
    """Se comprueban las directas y las de web oficial; las demás piden extractor o navegador.

    Las de web oficial (``ext``) hay que resolverlas antes, y es justo lo que
    interesa vigilar: cuando la lista cambia la dirección de un canal a un
    dominio que no se reconoce, el canal deja de resolverse sin avisar.
    """
    emision = canal.emision_principal
    return emision is not None and emision.tipo in TIPOS_COMPROBABLES


def comprobar_canal(canal, espera: float = ESPERA) -> dict:
    """Pide unos kilobytes de la emisión principal del canal y dice qué contesta."""
    emision = canal.emision_principal
    salida = {"canal": canal.nombre, "tipo": canal.tipo, "estado": "omitido", "detalle": "", "ms": 0}
    if emision is None:
        salida["detalle"] = "el canal no tiene emisiones"
        return salida
    if emision.tipo not in TIPOS_COMPROBABLES:
        salida["detalle"] = f"emisión de tipo {emision.tipo}: hay que abrirla para saberlo"
        return salida
    if emision.tipo == "ext":
        try:
            fuente = proveedores.fuente_final(canal, emision, proveedores.resolver(emision.url))
        except proveedores.ProveedorNoSoportado:
            # Muchos canales (sobre todo de fuera) solo se ven con el reproductor de
            # su web: eso no es un fallo, simplemente no se puede comprobar desde aquí.
            salida["detalle"] = f"se ve con el reproductor de su web ({_servidor(emision.url)}): hay que abrirla para saberlo"
            return salida
        except Exception as error:  # noqa: BLE001 (red y formatos de terceros)
            salida["estado"] = "error"
            salida["detalle"] = f"su web no da el directo: {_motivo(error)}"
            return salida
    else:
        fuente = proveedores.fuente_directa(canal, emision)
    peticion = urllib.request.Request(fuente.url, headers=_cabeceras(fuente))
    comienzo = time.monotonic()
    try:
        with urllib.request.urlopen(peticion, timeout=espera) as respuesta:
            cuerpo = respuesta.read(BYTES_PRUEBA)
            salida["ms"] = int((time.monotonic() - comienzo) * 1000)
            salida["estado"] = "ok"
            salida["detalle"] = _detalle(respuesta, cuerpo)
            if fuente.url.lower().split("?")[0].endswith(".m3u8") and b"#EXTM3U" not in cuerpo:
                salida["estado"] = "error"
                salida["detalle"] = "contesta, pero no devuelve una lista de emisión"
    except urllib.error.HTTPError as error:
        salida["estado"] = "error"
        salida["detalle"] = f"el servidor responde {error.code}" + (" (bloqueado por zona o caducado)" if error.code in (403, 451) else "")
        salida["ms"] = int((time.monotonic() - comienzo) * 1000)
    except Exception as error:  # noqa: BLE001 (red: cualquier cosa puede pasar)
        salida["estado"] = "error"
        salida["detalle"] = _motivo(error)
        salida["ms"] = int((time.monotonic() - comienzo) * 1000)
    return salida


def _cabeceras(fuente) -> dict:
    cabeceras = {"User-Agent": fuente.user_agent or proveedores.UA_UAGB, "Accept": "*/*"}
    if fuente.origin:
        cabeceras["Origin"] = fuente.origin
    if fuente.referer:
        cabeceras["Referer"] = fuente.referer
    if fuente.cookie:
        cabeceras["Cookie"] = fuente.cookie
    return cabeceras


def _detalle(respuesta, cuerpo: bytes) -> str:
    tipo = respuesta.headers.get("Content-Type", "") if respuesta.headers else ""
    if b"#EXT-X-ENDLIST" in cuerpo:
        return "responde, pero la emisión está cerrada (no está en directo)"
    return f"responde correctamente ({tipo.split(';')[0] or 'sin tipo'})"


def _servidor(url: str) -> str:
    return urlparse(url).hostname or url[:60]


def _motivo(error: Exception) -> str:
    texto = str(error)
    if "timed out" in texto or isinstance(error, TimeoutError):
        return "no contesta a tiempo"
    if "Name or service not known" in texto or "getaddrinfo" in texto or "11001" in texto:
        return "el nombre del servidor no existe (puede ser un bloqueo del operador)"
    if "certificate" in texto.lower():
        return "problema con el certificado del servidor"
    return texto[:120] or "error de red"


def comprobar(canales, hilos: int = HILOS, espera: float = ESPERA, progreso=None, cancelar: threading.Event | None = None) -> list[dict]:
    """Comprueba una lista de canales en paralelo. ``progreso(hechos, total, resultado)``."""
    resultados: list[dict] = []
    total = len(canales)
    with ThreadPoolExecutor(max_workers=max(1, min(16, hilos))) as ejecutor:
        for resultado in ejecutor.map(lambda c: comprobar_canal(c, espera) if not (cancelar and cancelar.is_set()) else
                                      {"canal": c.nombre, "tipo": c.tipo, "estado": "omitido", "detalle": "cancelado", "ms": 0},
                                      canales):
            resultados.append(resultado)
            if progreso is not None:
                progreso(len(resultados), total, resultado)
    return resultados


def resumen(resultados: list[dict]) -> str:
    bien = sum(1 for r in resultados if r["estado"] == "ok")
    mal = sum(1 for r in resultados if r["estado"] == "error")
    fuera = sum(1 for r in resultados if r["estado"] == "omitido")
    partes = [f"{bien} responden", f"{mal} no responden"]
    if fuera:
        partes.append(f"{fuera} no se han podido comprobar")
    return f"Comprobados {len(resultados)} canales: " + ", ".join(partes) + "."
