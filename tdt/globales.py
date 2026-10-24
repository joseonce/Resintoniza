"""Interfaz invisible: manejar la reproducción con la aplicación en segundo plano.

Windows permite reservar combinaciones de teclas para un programa aunque no
tenga el foco (``RegisterHotKey``). Con eso, quien escucha la radio o la
televisión mientras trabaja en otra cosa puede pausar, cambiar de canal, subir
el volumen o preguntar qué suena sin volver a la ventana, que es lo que más se
agradece en un reproductor que se usa de fondo.

Las combinaciones se pueden cambiar en Ajustes; las predeterminadas llevan
Ctrl+Alt para no chocar con las de otros programas. Si una combinación ya está
ocupada por otra aplicación, se anota y se avisa, pero las demás siguen
funcionando.
"""
from __future__ import annotations

import logging

import wx

from . import teclas as modulo_teclas

registro = logging.getLogger(__name__)
PRIMER_ID = 0xB000

# acción → combinación predeterminada. Solo acciones que tengan sentido sin ver la pantalla.
DEFECTO = {
    "repro_pausa": "Ctrl+Alt+P",
    "repro_detener": "Ctrl+Alt+S",
    "repro_bajar_volumen": "Ctrl+Alt+DOWN",
    "repro_subir_volumen": "Ctrl+Alt+UP",
    "repro_anterior": "Ctrl+Alt+LEFT",
    "repro_siguiente": "Ctrl+Alt+RIGHT",
    "repro_silencio": "Ctrl+Alt+M",
    "repro_estado": "Ctrl+Alt+I",
    "repro_grabar": "Ctrl+Alt+G",
    "repro_favoritos": "Ctrl+Alt+F",
}
ACCIONES = list(DEFECTO)


def combinaciones(ajustes_windows: dict) -> dict[str, str]:
    """Combinaciones actuales: las predeterminadas más las personalizadas guardadas."""
    resultado = dict(DEFECTO)
    guardadas = ajustes_windows.get("teclasGlobales") if isinstance(ajustes_windows.get("teclasGlobales"), dict) else {}
    for accion, combo in guardadas.items():
        if accion in DEFECTO and isinstance(combo, str):
            resultado[accion] = modulo_teclas.normalizar(combo)
    return resultado


def valida(combo: str) -> bool:
    """Una tecla global debe llevar Ctrl o Alt: si no, secuestraría el teclado del sistema."""
    combo = modulo_teclas.normalizar(combo)
    if not combo:
        return True
    partes = combo.split("+")
    return "Ctrl" in partes or "Alt" in partes


class TeclasGlobales:
    """Registra las teclas en el sistema y avisa a la ventana cuando se pulsan."""

    def __init__(self, ventana):
        self.ventana = ventana
        self.registradas: dict[int, str] = {}
        self.fallidas: list[str] = []
        self.activa = False
        ventana.Bind(wx.EVT_HOTKEY, self._pulsada)

    def _pulsada(self, evento):
        accion = self.registradas.get(evento.GetId())
        if accion:
            wx.CallAfter(self.ventana.ejecutar, accion)

    def aplicar(self, activar: bool, ajustes_windows: dict) -> list[str]:
        """Activa o desactiva las teclas globales. Devuelve las que no se pudieron reservar."""
        self.quitar()
        self.activa = bool(activar)
        if not self.activa:
            return []
        mapa = combinaciones(ajustes_windows)
        for numero, (accion, combo) in enumerate(mapa.items()):
            clave = modulo_teclas.a_wx(combo) if combo else None
            if not clave or not valida(combo):
                continue
            modificadores, codigo = clave
            identificador = PRIMER_ID + numero
            try:
                if self.ventana.RegisterHotKey(identificador, modificadores, codigo):
                    self.registradas[identificador] = accion
                else:
                    self.fallidas.append(combo)
            except Exception as error:
                registro.debug("No se pudo registrar %s: %s", combo, error)
                self.fallidas.append(combo)
        registro.info("Teclas globales activas: %s", len(self.registradas))
        return list(self.fallidas)

    def quitar(self) -> None:
        for identificador in list(self.registradas):
            try:
                self.ventana.UnregisterHotKey(identificador)
            except Exception:
                pass
        self.registradas.clear()
        self.fallidas.clear()

    def resumen(self, ajustes_windows: dict) -> list[tuple[str, str]]:
        """(acción legible, tecla) para mostrar en la ayuda y en los ajustes."""
        mapa = combinaciones(ajustes_windows)
        return [(modulo_teclas.ETIQUETAS.get(a, a).replace("&", ""), modulo_teclas.legible(c)) for a, c in mapa.items()]
