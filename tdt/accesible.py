"""Controles accesibles: lista en columnas con navegación por celdas y voz.

``ListaAccesible`` es un ``wx.ListCtrl`` en modo informe, como el de
SocialRSS: guarda el texto completo de cada celda (Windows recorta a unos
511 caracteres), permite moverse por columnas con flecha izquierda y derecha
o Ctrl+1 a 9 leyendo "Fila, Columna, contenido" según las preferencias de
accesibilidad, lee la fila entera con Ctrl+0 y convierte Intro en activación
del elemento. Las columnas y su orden vienen de una plantilla de lectura.
"""
from __future__ import annotations

import wx

from . import plantillas, voz

# Preferencias de lectura por columnas (las fija la interfaz desde los ajustes).
preferencias = {"decirFila": True, "decirColumna": True, "decirCelda": True}


class ListaAccesible(wx.ListCtrl):
    def __init__(self, parent, nombre: str, clave_plantilla: str, ajustes_windows: dict | None = None, **kwargs):
        estilo = kwargs.pop("style", 0) | wx.LC_REPORT | wx.LC_SINGLE_SEL
        super().__init__(parent, style=estilo, name=nombre, **kwargs)
        self.SetName(nombre)
        self.clave_plantilla = clave_plantilla
        self.ajustes_windows = ajustes_windows
        self._celdas: dict[int, dict[int, str]] = {}
        self._valores: dict[int, dict] = {}
        self._columna = 0
        self.campos: list[str] = []
        self.texto_plantilla = ""
        self.aplicar_plantilla()
        # Intro se atiende en el gancho de teclas, no en EVT_KEY_DOWN: ver _al_pulsar_gancho.
        self.Bind(wx.EVT_CHAR_HOOK, self._al_pulsar_gancho)
        self.Bind(wx.EVT_KEY_DOWN, self._al_pulsar)

    # --- columnas ----------------------------------------------------------------------
    def aplicar_plantilla(self) -> None:
        """(Re)crea las columnas según la plantilla configurada."""
        self.texto_plantilla = plantillas.texto_plantilla(self.ajustes_windows or {}, self.clave_plantilla)
        columnas = plantillas.columnas(self.texto_plantilla)
        self.campos = [c for c, _ in columnas]
        self.ClearAll()
        self._celdas.clear()
        self._valores.clear()
        for indice, (_campo, titulo) in enumerate(columnas):
            self.InsertColumn(indice, titulo, width=260 if indice == 0 else 180)

    def ajustar_anchos(self) -> None:
        ancho_total = max(200, self.GetClientSize().width - 4)
        cuenta = max(1, self.GetColumnCount())
        primera = min(ancho_total, max(180, ancho_total // 2)) if cuenta > 1 else ancho_total
        resto = max(90, (ancho_total - primera) // max(1, cuenta - 1)) if cuenta > 1 else 0
        for indice in range(cuenta):
            self.SetColumnWidth(indice, primera if indice == 0 else resto)

    # --- filas -------------------------------------------------------------------------
    def rellenar(self, filas: list[dict], seleccionar: int = 0) -> None:
        """Sustituye todas las filas por ``filas`` (una lista de diccionarios campo → texto)."""
        self.Freeze()
        try:
            super().DeleteAllItems()
            self._celdas.clear()
            self._valores.clear()
            for numero, valores in enumerate(filas):
                self._insertar(numero, valores)
        finally:
            self.Thaw()
        if filas and 0 <= seleccionar < len(filas):
            self.seleccionar(seleccionar)

    def _insertar(self, numero: int, valores: dict) -> None:
        textos = [str(valores.get(campo, "") or "") for campo in self.campos] or [""]
        self.InsertItem(numero, textos[0])
        for columna, texto in enumerate(textos[1:], start=1):
            self.SetItem(numero, columna, texto)
        self._celdas[numero] = dict(enumerate(textos))
        self._valores[numero] = valores

    def actualizar_fila(self, numero: int, valores: dict) -> None:
        if not 0 <= numero < self.GetItemCount():
            return
        self._valores[numero] = valores
        for columna, campo in enumerate(self.campos):
            texto = str(valores.get(campo, "") or "")
            if self._celdas.get(numero, {}).get(columna) != texto:
                self.SetItem(numero, columna, texto)
                self._celdas.setdefault(numero, {})[columna] = texto

    def seleccionar(self, numero: int, enfocar: bool = False) -> None:
        if not 0 <= numero < self.GetItemCount():
            return
        self.Select(numero)
        self.Focus(numero)
        self.EnsureVisible(numero)
        if enfocar:
            self.SetFocus()

    def fila_actual(self) -> int:
        fila = self.GetFocusedItem()
        if fila == wx.NOT_FOUND:
            fila = self.GetFirstSelected()
        return fila

    def valores_actuales(self) -> dict | None:
        return self._valores.get(self.fila_actual())

    def texto_celda(self, fila: int, columna: int) -> str:
        return self._celdas.get(fila, {}).get(columna, "")

    def lectura_fila(self, fila: int) -> str:
        valores = self._valores.get(fila)
        if valores is None:
            return ""
        return plantillas.renderizar(self.texto_plantilla, valores)

    # --- voz ---------------------------------------------------------------------------
    def _decir_celda(self, fila: int, columna: int) -> None:
        decir_fila, decir_columna, decir_celda = preferencias["decirFila"], preferencias["decirColumna"], preferencias["decirCelda"]
        if not (decir_fila or decir_columna or decir_celda):
            decir_celda = True
        partes = []
        if decir_fila:
            partes.append(f"Fila {fila + 1}")
        if decir_columna and columna < self.GetColumnCount():
            partes.append(self.GetColumn(columna).GetText())
        if decir_celda:
            partes.append(self.texto_celda(fila, columna) or "vacío")
        voz.decir(", ".join(p for p in partes if p), interrumpir=True, inmediato=True)

    def _al_pulsar(self, evento):
        tecla = evento.GetKeyCode()
        modificadores = evento.GetModifiers()
        fila = self.fila_actual()
        columnas = self.GetColumnCount()
        if modificadores == wx.MOD_NONE and tecla == wx.WXK_SPACE:
            return
        if modificadores == wx.MOD_NONE and tecla in (wx.WXK_LEFT, wx.WXK_RIGHT) and fila != wx.NOT_FOUND:
            self._columna = max(0, self._columna - 1) if tecla == wx.WXK_LEFT else min(columnas - 1, self._columna + 1)
            self._decir_celda(fila, self._columna)
            return
        if fila == wx.NOT_FOUND:
            evento.Skip()
            return
        if modificadores == wx.MOD_CONTROL and ord("1") <= tecla <= ord("9"):
            columna = tecla - ord("1")
            if columna < columnas:
                self._columna = columna
                self._decir_celda(fila, columna)
            return
        if modificadores == wx.MOD_CONTROL and tecla == ord("0"):
            voz.decir(self.lectura_fila(fila) or "Fila vacía", interrumpir=True, inmediato=True)
            return
        evento.Skip()

    def _al_pulsar_gancho(self, evento):
        """Intro activa la fila. Se atiende aquí, en el gancho, y no en EVT_KEY_DOWN.

        Windows traduce cada pulsación en dos mensajes: la tecla y su carácter.
        Cuando Intro se atendía en EVT_KEY_DOWN, el carácter ya estaba puesto en
        la cola, y si la activación abre un menú contextual es el bucle del menú
        quien lo recoge: como no coincide con ninguna opción, Windows lo da por
        tecla equivocada y suena el pitido de error. El gancho llega antes de que
        el carácter llegue a generarse, así que el menú se abre en silencio.
        """
        if evento.GetKeyCode() not in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) or evento.GetModifiers() != wx.MOD_NONE:
            evento.Skip()
            return
        fila = self.fila_actual()
        if fila == wx.NOT_FOUND:
            evento.Skip()
            return
        activacion = wx.ListEvent(wx.wxEVT_LIST_ITEM_ACTIVATED, self.GetId())
        activacion.SetIndex(fila)
        activacion.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(activacion)

    def menu_contextual_en_fila(self, evento) -> int:
        """Devuelve la fila sobre la que abrir un menú contextual (ratón, teclado o Intro)."""
        # Con Intro llega un evento de lista, que no lleva posición del ratón.
        if evento is None or not hasattr(evento, "GetPosition"):
            return self.fila_actual()
        posicion = evento.GetPosition()
        if posicion != wx.DefaultPosition and posicion.x >= 0:
            fila, _banderas = self.HitTest(self.ScreenToClient(posicion))
            if fila != wx.NOT_FOUND:
                self.seleccionar(fila)
                return fila
        return self.fila_actual()
