"""Sonidos que identifican lo que pasa, sin tener que leer nada.

Un pitido corto al empezar, otro al parar, un tono grave si falla la emisión…
son más rápidos que una frase hablada y no interrumpen al lector de pantalla.
Los archivos se generan la primera vez en ``data/sonidos`` con el módulo
``wave`` de Python (nada que descargar) y se reproducen con ``winsound``.

Cada aviso se puede activar o desactivar por separado desde los ajustes.
"""
from __future__ import annotations

import logging
import math
import struct
import wave
from pathlib import Path

registro = logging.getLogger(__name__)
FRECUENCIA = 44100
AMPLITUD = 12000

# nombre → (descripción, [(hercios, milisegundos), …])
CATALOGO = {
    "inicio": ("Empieza la reproducción", [(660, 70), (880, 110)]),
    "parada": ("Se detiene la reproducción", [(660, 70), (440, 110)]),
    "error": ("La emisión falla", [(320, 160), (240, 220)]),
    "recordatorio": ("Aviso de un programa", [(880, 90), (0, 60), (880, 90), (0, 60), (1046, 140)]),
    "grabacion": ("Empieza o termina una grabación", [(523, 80), (784, 80), (1046, 140)]),
    "programada": ("Empieza o termina una grabación programada", [(392, 90), (523, 90), (659, 90), (784, 160)]),
    "cambio": ("Cambio de canal", [(784, 60)]),
    "limite": ("No se puede ir más allá (volumen al máximo, final de la lista)", [(300, 70)]),
}

activados = True
_avisos: dict[str, bool] = {}
_carpeta: Path | None = None


def configurar(activo: bool, avisos: dict | None = None, carpeta: Path | None = None) -> None:
    """Fija las preferencias. ``avisos`` es nombre → True/False para cada sonido."""
    global activados, _avisos, _carpeta
    activados = bool(activo)
    _avisos = {k: bool(v) for k, v in (avisos or {}).items() if k in CATALOGO}
    if carpeta is not None:
        _carpeta = Path(carpeta)


def _muestras(tonos) -> bytes:
    datos = bytearray()
    for hercios, milisegundos in tonos:
        total = int(FRECUENCIA * milisegundos / 1000)
        for indice in range(total):
            if hercios <= 0:
                valor = 0
            else:
                # Envolvente suave para que no chasquee al empezar y al acabar.
                envolvente = min(1.0, indice / (FRECUENCIA * 0.008), (total - indice) / (FRECUENCIA * 0.02))
                valor = int(AMPLITUD * envolvente * math.sin(2 * math.pi * hercios * indice / FRECUENCIA))
            datos += struct.pack("<h", max(-32767, min(32767, valor)))
    return bytes(datos)


def generar(carpeta: Path) -> list[Path]:
    """Crea los archivos que falten en ``carpeta``. Devuelve las rutas de todos."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas = []
    for nombre, (_descripcion, tonos) in CATALOGO.items():
        ruta = carpeta / (nombre + ".wav")
        rutas.append(ruta)
        if ruta.exists() and ruta.stat().st_size > 44:
            continue
        try:
            with wave.open(str(ruta), "wb") as archivo:
                archivo.setnchannels(1)
                archivo.setsampwidth(2)
                archivo.setframerate(FRECUENCIA)
                archivo.writeframes(_muestras(tonos))
        except OSError as error:
            registro.warning("No se pudo generar el sonido %s: %s", nombre, error)
    return rutas


def preparar(datos) -> Path:
    """Genera los sonidos en ``data/sonidos`` y deja esa carpeta como la activa."""
    global _carpeta
    _carpeta = datos.raiz / "sonidos"
    generar(_carpeta)
    return _carpeta


def activo(nombre: str) -> bool:
    return activados and _avisos.get(nombre, True) and nombre in CATALOGO


def reproducir(nombre: str) -> bool:
    """Suena el aviso ``nombre`` sin bloquear. Devuelve True si se ha lanzado."""
    if not activo(nombre) or _carpeta is None:
        return False
    ruta = _carpeta / (nombre + ".wav")
    if not ruta.exists():
        generar(_carpeta)
        if not ruta.exists():
            return False
    try:
        import winsound

        winsound.PlaySound(str(ruta), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        return True
    except Exception as error:
        registro.debug("No se pudo reproducir el sonido %s: %s", nombre, error)
        return False
