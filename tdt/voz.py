"""Salida de voz directa al lector de pantalla (NVDA, JAWS, SAPI…).

Usa accessible_output2 como SocialRSS: un único hilo consume una cola de
mensajes y, en ráfagas (navegación rápida), solo se locuta el último mensaje
interrumpible. Si no hay lector de pantalla no pasa nada: la interfaz sigue
mostrando la misma información en pantalla.
"""
from __future__ import annotations

import logging
import queue
import threading
import time

registro = logging.getLogger(__name__)

_salida = None
_iniciada = False
_cola: "queue.Queue[tuple[str, bool]]" = queue.Queue()
_hilo_iniciado = False
_bloqueo = threading.Lock()

# Ajustes que fija la interfaz desde data/ajustes.json.
activada = True
braille = True
retardo_ms = 120


def iniciar() -> None:
    global _salida, _iniciada
    with _bloqueo:
        if _iniciada:
            return
        _iniciada = True
        try:
            from accessible_output2.outputs.auto import Auto

            _salida = Auto()
            registro.info("Salida de voz preparada con accessible_output2.")
        except Exception as error:
            registro.warning("Sin salida de voz directa: %s", error)
            _salida = None


def configurar(activa: bool, con_braille: bool = True, retardo: int = 120) -> None:
    global activada, braille, retardo_ms
    activada, braille, retardo_ms = bool(activa), bool(con_braille), max(0, min(600, int(retardo)))


def decir(texto: str, interrumpir: bool = True, inmediato: bool = False) -> None:
    """Locuta ``texto``. ``inmediato`` lo emite en el hilo actual sin retardo."""
    if not activada:
        return
    texto = (texto or "").strip()
    if not texto:
        return
    if not _iniciada:
        iniciar()
    if inmediato:
        _emitir(texto, interrumpir)
        return
    _asegurar_hilo()
    _cola.put((texto, interrumpir))


def _emitir(texto: str, interrumpir: bool) -> None:
    if _salida is None:
        return
    try:
        _salida.speak(texto, interrumpir)
        if braille:
            try:
                _salida.braille(texto)
            except Exception:
                pass
    except Exception as error:
        registro.debug("Error al locutar: %s", error)


def _asegurar_hilo() -> None:
    global _hilo_iniciado
    with _bloqueo:
        if _hilo_iniciado:
            return
        threading.Thread(target=_trabajador, name="VozTDT", daemon=True).start()
        _hilo_iniciado = True


def _trabajador() -> None:
    while True:
        texto, interrumpir = _cola.get()
        if interrumpir:
            try:
                while True:
                    siguiente, interrumpe = _cola.get_nowait()
                    texto, interrumpir = siguiente, interrumpe
                    if not interrumpe:
                        break
            except queue.Empty:
                pass
        if interrumpir and retardo_ms:
            time.sleep(retardo_ms / 1000.0)
        _emitir(texto, interrumpir)
