"""Multiventana: hasta cuatro canales a la vez, con el sonido de uno solo.

Es la función más valorada de los clientes IPTV de Android (TiviMate la llama
multi-view). Aquí cada hueco tiene **su propia instancia de libmpv** dibujando
en su panel, igual que hace la grabación en segundo plano: se comprobó que
varias conviven sin estorbarse.

Se maneja entero con el teclado y todo se dice en voz alta: 1 a 4 eligen qué
canal suena, Espacio pausa el que suena, las flechas cambian el volumen,
Intro deja solo ese canal en el reproductor principal y Escape cierra.
"""
from __future__ import annotations

import logging

import wx

from . import voz
from .reproductor import Reproductor

registro = logging.getLogger(__name__)
MAXIMO = 4
DISPOSICION = {1: (1, 1), 2: (1, 2), 3: (2, 2), 4: (2, 2)}


class Hueco:
    """Un canal del mosaico: su panel, su reproductor y su estado."""

    def __init__(self, canal, fuente, panel):
        self.canal = canal
        self.fuente = fuente
        self.panel = panel
        self.reproductor: Reproductor | None = None
        self.estado = "cargando"

    @property
    def nombre(self) -> str:
        return self.canal.nombre


class VentanaMosaico(wx.Frame):
    """Ventana con varios canales a la vez; solo suena el elegido."""

    def __init__(self, principal, seleccion: list[tuple], carpeta_mpv, volumen: int = 80, buffer: str = "normal"):
        super().__init__(principal, title=f"Multiventana · {len(seleccion)} canales", size=(1120, 700))
        self.principal = principal
        self.carpeta_mpv = carpeta_mpv
        self.volumen = volumen
        self.buffer = buffer
        self.activo = 0
        self.cerrando = False
        self.CreateStatusBar()
        panel = wx.Panel(self)
        filas, columnas = DISPOSICION.get(len(seleccion), (2, 2))
        rejilla = wx.GridSizer(filas, columnas, 4, 4)
        self.huecos: list[Hueco] = []
        for numero, (canal, fuente) in enumerate(seleccion[:MAXIMO], start=1):
            hueco_panel = wx.Panel(panel, style=wx.BORDER_SIMPLE)
            hueco_panel.SetBackgroundColour(wx.BLACK)
            hueco_panel.SetName(f"{numero}. {canal.nombre}")
            rejilla.Add(hueco_panel, 1, wx.EXPAND)
            self.huecos.append(Hueco(canal, fuente, hueco_panel))
        panel.SetSizer(rejilla)
        self.Bind(wx.EVT_CHAR_HOOK, self._teclas)
        self.Bind(wx.EVT_CLOSE, self._al_cerrar)
        self.Show()
        wx.CallAfter(self._arrancar)

    # --- arranque y parada ----------------------------------------------------
    def _arrancar(self):
        for numero, hueco in enumerate(self.huecos):
            try:
                hueco.reproductor = Reproductor(
                    hueco.panel.GetHandle(), self.carpeta_mpv,
                    lambda tipo, texto, n=numero: wx.CallAfter(self._evento, n, tipo, texto),
                    self.volumen, silencio=numero != self.activo, buffer=self.buffer)
                hueco.reproductor.reproducir(hueco.fuente)
            except Exception as error:  # noqa: BLE001
                registro.exception("No se pudo abrir el canal %s del mosaico", hueco.nombre)
                hueco.estado = "error"
                self.anunciar(f"{hueco.nombre} no se ha podido abrir: {error}")
        self.anunciar(self.ayuda())

    def ayuda(self) -> str:
        canales = ", ".join(f"{n}: {h.nombre}" for n, h in enumerate(self.huecos, start=1))
        return (f"Multiventana con {canales}. Suena {self.huecos[self.activo].nombre}. "
                "Las cifras eligen cuál suena, espacio pausa, flechas arriba y abajo el volumen, "
                "Intro deja solo ese canal en el reproductor y Escape cierra.")

    def _evento(self, numero: int, tipo: str, texto: str):
        if self.cerrando or numero >= len(self.huecos):
            return
        hueco = self.huecos[numero]
        if tipo == "error":
            hueco.estado = "error"
            self.anunciar(f"{hueco.nombre}: {texto}")
        elif tipo == "cargado":
            hueco.estado = "reproduciendo"
            self.SetStatusText(f"{hueco.nombre} cargado. {self.resumen()}")

    def resumen(self) -> str:
        return " · ".join(f"{n}: {h.nombre}{' (suena)' if n - 1 == self.activo else ''}" for n, h in enumerate(self.huecos, start=1))

    def anunciar(self, texto: str, decir: bool = True):
        self.SetStatusText(texto)
        if decir:
            voz.decir(texto, interrumpir=True)

    # --- mandos ---------------------------------------------------------------
    def elegir(self, numero: int):
        """Deja sonando solo ese hueco."""
        if not 0 <= numero < len(self.huecos):
            return
        self.activo = numero
        for indice, hueco in enumerate(self.huecos):
            if hueco.reproductor is not None:
                hueco.reproductor.silencio(indice != numero)
        self.anunciar(f"Suena {self.huecos[numero].nombre}. {self.resumen()}")

    def pausar(self):
        hueco = self.huecos[self.activo]
        if hueco.reproductor is None:
            return
        pausado = hueco.reproductor.pausar()
        self.anunciar(("En pausa: " if pausado else "Reproduciendo: ") + hueco.nombre)

    def cambiar_volumen(self, salto: int):
        self.volumen = max(0, min(100, self.volumen + salto))
        hueco = self.huecos[self.activo]
        if hueco.reproductor is not None:
            hueco.reproductor.volumen(self.volumen)
        self.anunciar(f"Volumen {self.volumen} por ciento en {hueco.nombre}")

    def al_reproductor(self):
        """Cierra el mosaico y deja ese canal en el reproductor de siempre."""
        canal = self.huecos[self.activo].canal
        self.Close()
        wx.CallAfter(self.principal.reproducir_canal, canal)

    def _teclas(self, evento):
        tecla = evento.GetKeyCode()
        if tecla == wx.WXK_ESCAPE:
            self.Close()
            return
        if ord("1") <= tecla <= ord("9"):
            self.elegir(tecla - ord("1"))
            return
        if tecla == wx.WXK_SPACE:
            self.pausar()
            return
        if tecla in (wx.WXK_UP, wx.WXK_DOWN):
            self.cambiar_volumen(5 if tecla == wx.WXK_UP else -5)
            return
        if tecla in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.al_reproductor()
            return
        if tecla == wx.WXK_F1:
            self.anunciar(self.ayuda())
            return
        evento.Skip()

    def _al_cerrar(self, evento):
        self.cerrando = True
        for hueco in self.huecos:
            if hueco.reproductor is not None:
                try:
                    hueco.reproductor.cerrar()
                except Exception:
                    registro.debug("Error cerrando un canal del mosaico", exc_info=True)
                hueco.reproductor = None
        self.principal.mosaico = None
        self.principal.estado("Multiventana cerrada.")
        evento.Skip()
        self.Destroy()
