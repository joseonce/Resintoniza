"""Diálogos de las funciones de cliente IPTV.

Aquí están las ventanas que no forman parte del esqueleto original: cuentas de
proveedor, grabaciones, búsqueda en toda la guía, historial, perfiles, envío a
la tele, canales duplicados, bloqueo por PIN y salto por número de canal.
Todas siguen el mismo patrón: lista accesible con plantilla de lectura, menú
contextual, botones con su tecla y Escape para cerrar.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import wx

from . import NOMBRE_APP, actualizacion, casting, catalogo, comprobador, grabacion, organizar, respaldo, voz, xtream
from .accesible import ListaAccesible
from .catalogo import NOMBRE_TIPO
from .widgets import (aviso, boton, campo, copiar_portapapeles, fila_archivo, fila_comprobacion, fila_cuenta,
                      fila_en_curso, fila_grabacion, fila_historial, fila_programa, fila_regla, menu_desde, nombrar,
                      pregunta, tabla_html, dialogo_html, texto_detalle_programa)

registro = logging.getLogger(__name__)
TIPOS = ("tv", "radio")
MINUTOS_MARGEN = [0, 1, 2, 5, 10]


class DialogoLista(wx.Dialog):
    """Añadir una lista de canales: JSON, M3U de Internet o archivo del equipo."""

    def __init__(self, parent):
        super().__init__(parent, title="Añadir lista de canales", size=(640, 560), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=(
            "Puedes añadir listas de canales en formato M3U o M3U8, que es el habitual en IPTV,\n"
            "o en el mismo formato JSON de las listas incluidas. Puede ser una dirección de Internet\n"
            "o un archivo guardado en el equipo.")), 0, wx.ALL, 12)

        def campo_vertical(etiqueta, crear, proporcion=0):
            """Etiqueta encima del control: así el lector de pantalla la lee al entrar."""
            texto = wx.StaticText(self, label=etiqueta)
            caja.Add(texto, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
            control = crear()
            nombrar(control, etiqueta.replace("&", "").rstrip(":"))
            caja.Add(control, proporcion, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            return control

        self.nombre = campo_vertical("&Nombre de la lista:", lambda: wx.TextCtrl(self))
        self.url = campo_vertical("&Dirección de Internet (https://…):", lambda: wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 56)))
        # Cuadros de varias líneas: los de una sola línea a veces no reciben el
        # foco al tabular y el lector de pantalla se los salta.
        self.ruta = campo_vertical("&Archivo del equipo (o pulsa Examinar):", lambda: wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 56)))
        caja.Add(boton(self, "&Examinar…", lambda e: self.examinar()), 0, wx.LEFT | wx.BOTTOM, 12)
        self.tipo = campo_vertical("&Tipo:", lambda: wx.Choice(self, choices=["Televisión", "Radio", "Detectarlo automáticamente"]))
        self.tipo.SetSelection(0)
        self.formato = campo_vertical("&Formato:", lambda: wx.Choice(self, choices=["Detectarlo automáticamente", "M3U o M3U8", "JSON"]))
        self.formato.SetSelection(0)
        caja.AddStretchSpacer()
        botones = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindow(wx.ID_OK).SetLabel("&Añadir")
        self.FindWindow(wx.ID_CANCEL).SetLabel("&Cancelar")
        caja.Add(botones, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(caja)
        self.nombre.SetFocus()

    def examinar(self):
        with wx.FileDialog(self, "Elegir una lista", wildcard="Listas (*.m3u;*.m3u8;*.json)|*.m3u;*.m3u8;*.json|Todos (*.*)|*.*", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            ruta = dialogo.GetPath()
        self.ruta.SetValue(ruta)
        if not self.nombre.GetValue().strip():
            self.nombre.SetValue(os.path.splitext(os.path.basename(ruta))[0])

    def valor(self) -> dict:
        tipos = ["tv", "radio", "auto"]
        formatos = ["auto", "m3u", "json"]
        return {
            "nombre": self.nombre.GetValue().strip(),
            # Los cuadros son de varias líneas: se une lo escrito por si se ha pegado con salto de línea.
            "url": " ".join(self.url.GetValue().split()).strip(),
            "ruta": " ".join(self.ruta.GetValue().split()).strip(),
            "tipo": tipos[max(0, self.tipo.GetSelection())],
            "formato": formatos[max(0, self.formato.GetSelection())],
        }


class DialogoIptvOrg(wx.Dialog):
    """Añade una lista del catálogo público de iptv-org por país, idioma o categoría."""

    TIPOS = [("País", "pais"), ("Idioma", "idioma"), ("Categoría", "categoria")]

    def __init__(self, parent):
        super().__init__(parent, title="Catálogo de iptv-org", size=(640, 520), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        from . import iptvorg

        self.iptvorg = iptvorg
        self.ventana = parent
        self.entradas: list[tuple[str, str]] = []
        self.resultado: dict | None = None
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=(
            "iptv-org recopila canales publicados libremente en Internet, agrupados por país, idioma y categoría.\n"
            "Elige un grupo y se añadirá su lista, que se lee como cualquier otra lista M3U.")), 0, wx.ALL, 10)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.tipo = campo(self, fila, "&Agrupar por:", lambda: wx.Choice(self, choices=[t[0] for t in self.TIPOS]), 0, False)
        self.tipo.SetSelection(0)
        self.tipo.Bind(wx.EVT_CHOICE, lambda e: self.cargar())
        self.medio = campo(self, fila, "Añadir &como:", lambda: wx.Choice(self, choices=["Televisión", "Radio", "Detectarlo automáticamente"]), 0, False)
        self.medio.SetSelection(0)
        caja.Add(fila, 0, wx.EXPAND | wx.ALL, 10)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.busqueda = campo(self, fila, "&Buscar:", lambda: wx.TextCtrl(self), 1)
        self.busqueda.Bind(wx.EVT_TEXT, lambda e: self.filtrar())
        caja.Add(fila, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.lista = nombrar(wx.ListBox(self), "Grupos disponibles en iptv-org")
        self.lista.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.anadir())
        caja.Add(self.lista, 1, wx.EXPAND | wx.ALL, 10)
        self.estado = nombrar(wx.TextCtrl(self, value="Consultando el catálogo…", style=wx.TE_READONLY), "Estado")
        caja.Add(self.estado, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        botones = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Añadir esta lista", lambda e: self.anadir()), boton(self, "Añadir &todos los canales", lambda e: self.anadir_todo()), wx.Button(self, wx.ID_CANCEL, "C&errar")):
            botones.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(botones, 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.lista.SetFocus()
        wx.CallAfter(self.cargar)

    def tipo_actual(self) -> str:
        return self.TIPOS[max(0, self.tipo.GetSelection())][1]

    def cargar(self):
        self.estado.SetValue("Consultando el catálogo de iptv-org…")
        wx.BeginBusyCursor()
        try:
            self.entradas = self.iptvorg.indice(self.tipo_actual())
        finally:
            wx.EndBusyCursor()
        self.filtrar()
        self.estado.SetValue(f"{len(self.entradas)} grupos disponibles. No todos tienen lista publicada: se comprueba al añadir.")

    def filtrar(self):
        from .catalogo import plegar

        texto = plegar(self.busqueda.GetValue())
        self.mostrados = [e for e in self.entradas if not texto or texto in plegar(e[0])]
        self.lista.Set([f"{nombre} ({codigo})" for nombre, codigo in self.mostrados] or ["Sin resultados"])
        if self.mostrados:
            self.lista.SetSelection(0)

    def seleccion(self):
        indice = self.lista.GetSelection()
        return self.mostrados[indice] if 0 <= indice < len(self.mostrados) else None

    def _guardar(self, url: str, nombre: str, canales: int):
        tipos = ["tv", "radio", "auto"]
        self.resultado = {"nombre": nombre, "url": url, "ruta": "", "tipo": tipos[max(0, self.medio.GetSelection())], "formato": "m3u"}
        self.EndModal(wx.ID_OK)
        self.ventana.guardar_lista(self.resultado, f"Lista «{nombre}» añadida con {canales} canales.")

    def anadir(self):
        elegido = self.seleccion()
        if elegido is None:
            return
        nombre, codigo = elegido
        url = self.iptvorg.url_lista(self.tipo_actual(), codigo)
        self.estado.SetValue(f"Comprobando la lista de {nombre}…")
        voz.decir(f"Comprobando la lista de {nombre}")
        wx.BeginBusyCursor()
        try:
            existe, canales = self.iptvorg.existe(url)
        finally:
            wx.EndBusyCursor()
        if not existe:
            self.estado.SetValue(f"iptv-org no publica ninguna lista para {nombre}.")
            voz.decir(f"iptv-org no publica ninguna lista para {nombre}")
            return
        self._guardar(url, self.iptvorg.nombre_lista(self.tipo_actual(), nombre), canales)

    def anadir_todo(self):
        if not pregunta(self, "La lista completa de iptv-org tiene decenas de miles de canales de todo el mundo y tarda en cargarse.\n\n¿Añadirla de todos modos?"):
            return
        self._guardar(self.iptvorg.url_completa(), "iptv-org · todos los canales", 0)


class DialogoDns(wx.Dialog):
    """DNS alternativo, para cuando el operador bloquea el acceso a una emisión.

    Los bloqueos que se aplican durante los partidos de fútbol se ejecutan
    también por DNS y dejan sin servicio a emisiones que no tienen nada que
    ver. Aquí se puede poner un DNS público con DNS sobre HTTPS y volver
    después a la configuración de siempre, que se guarda antes de tocar nada.
    """

    def __init__(self, parent):
        super().__init__(parent, title="DNS alternativo para bloqueos del operador", size=(700, 560), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        from . import dns_xdp

        self.dns = dns_xdp
        self.ventana = parent
        self.datos = parent.datos
        self.adaptadores: list[str] = []
        self.virtuales: dict[str, bool] = {}
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=(
            "Algunos bloqueos de los operadores se aplican por DNS y dejan sin servicio emisiones que no\n"
            "tienen nada que ver. Cambiando el DNS del equipo por uno público con DNS sobre HTTPS suele\n"
            "volver el acceso. Windows pedirá permiso, y tu configuración anterior se guarda para poder volver.")), 0, wx.ALL, 10)
        caja.Add(wx.StaticText(self, label="&Conexión de red:"), 0, wx.LEFT | wx.TOP, 10)
        self.lista = nombrar(wx.ListBox(self), "Conexiones de red")
        self.lista.Bind(wx.EVT_LISTBOX, lambda e: self.actualizar_estado())
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        caja.Add(wx.StaticText(self, label="&Estado de la conexión:"), 0, wx.LEFT | wx.TOP, 10)
        self.estado = nombrar(wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 130)), "Estado de la conexión")
        caja.Add(self.estado, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        botones = wx.WrapSizer(wx.HORIZONTAL)
        self.boton_activar = boton(self, "&Activar el DNS alternativo", lambda e: self.activar())
        self.boton_restaurar = boton(self, "&Restaurar mi configuración", lambda e: self.restaurar())
        for control in (self.boton_activar, self.boton_restaurar, boton(self, "&Comprobar ahora", lambda e: self.actualizar_estado(True)),
                        boton(self, "&Importar configuración guardada…", lambda e: self.importar()),
                        boton(self, "&Guardar copia de mi configuración…", lambda e: self.exportar()),
                        wx.Button(self, wx.ID_CANCEL, "C&errar")):
            botones.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(botones, 0, wx.ALL, 10)
        self.SetSizer(caja)
        wx.CallAfter(self.cargar)
        self.lista.SetFocus()

    # --- configuración guardada por la herramienta original -------------------
    def importar(self, ruta=None):
        """Trae el ``xdp_configuracion_original.json`` de xdp_manager para poder restaurar."""
        if ruta is None:
            with wx.FileDialog(self, "Elegir la configuración guardada por xdp_manager",
                               wildcard="Configuración de xdp_manager (*.json)|*.json|Todos (*.*)|*.*",
                               style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialogo:
                if dialogo.ShowModal() != wx.ID_OK:
                    return
                ruta = dialogo.GetPath()
        try:
            importados = self.dns.importar_configuracion(self.datos, ruta, sustituir=True)
        except Exception as error:
            aviso(self, str(error), icono=wx.ICON_WARNING)
            return
        self.datos.guardar()
        if importados:
            detalles = "; ".join(f"{n}: {self.dns.resumen_configuracion(self.dns.original_de(self.datos, n))}" for n in importados)
            self.ventana.estado(f"Configuración de red importada: {detalles}.")
            voz.decir(f"Importada la configuración de {', '.join(importados)}")
        else:
            self.ventana.estado("Esa configuración no añadía nada nuevo.")
        self.actualizar_estado()

    def exportar(self):
        """Guarda en un archivo la copia de la configuración de red original."""
        with wx.FileDialog(self, "Guardar copia de la configuración de red",
                           wildcard="Configuración de red (*.json)|*.json", defaultFile="dns-original.json",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            destino = dialogo.GetPath()
        try:
            ruta = self.dns.exportar_original(self.datos, destino)
        except Exception as error:
            aviso(self, str(error), icono=wx.ICON_WARNING)
            return
        self.ventana.estado(f"Copia de la configuración de red guardada en {ruta}.")
        voz.decir("Copia de la configuración de red guardada")

    def ofrecer_importar(self):
        """Si aún no hay copia y se encuentra la de xdp_manager, se ofrece traerla."""
        if self.dns.original_de(self.datos, self.adaptador()):
            return
        for ruta in self.dns.candidatos_configuracion(self.datos):
            try:
                import json

                convertido = self.dns.convertir_configuracion(json.loads(Path(ruta).read_text(encoding="utf-8-sig")))
            except Exception:
                continue
            if not convertido:
                continue
            detalles = "\n".join(f"  {n}: {self.dns.resumen_configuracion(e)}" for n, e in convertido.items())
            if pregunta(self, ("Se ha encontrado la configuración de red que guardó xdp_manager:\n\n"
                               f"{ruta}\n{detalles}\n\n"
                               "Si la importas, al restaurar se dejará exactamente lo que tenías antes.\n\n¿Importarla?"),
                        "Configuración guardada"):
                self.importar(ruta)
            return

    def cargar(self):
        self.estado.SetValue("Consultando las conexiones de red…")
        wx.BeginBusyCursor()
        try:
            self.adaptadores = self.dns.adaptadores()
        except Exception as error:
            self.adaptadores = []
            self.estado.SetValue(f"No se pudo consultar la red: {error}")
        finally:
            wx.EndBusyCursor()
        preferida = self.datos.windows.get("dnsAdaptador") or ""
        self.lista.Set(self.adaptadores or ["No se han encontrado conexiones de red"])
        if self.adaptadores:
            self.lista.SetSelection(self.adaptadores.index(preferida) if preferida in self.adaptadores else 0)
            self.actualizar_estado()
            wx.CallAfter(self.ofrecer_importar)

    def adaptador(self) -> str:
        indice = self.lista.GetSelection()
        return self.adaptadores[indice] if 0 <= indice < len(self.adaptadores) else ""

    def es_virtual(self, nombre: str) -> bool:
        """Si la conexión es virtual se avisa; se pregunta una vez por conexión."""
        if nombre not in self.virtuales:
            try:
                self.virtuales[nombre] = self.dns.es_virtual(nombre)
            except Exception:
                self.virtuales[nombre] = False
        return self.virtuales[nombre]

    def actualizar_estado(self, decir: bool = False):
        nombre = self.adaptador()
        if not nombre:
            return
        wx.BeginBusyCursor()
        try:
            informacion = self.dns.estado(nombre)
        finally:
            wx.EndBusyCursor()
        lineas = [self.dns.texto_estado(informacion)]
        if self.es_virtual(nombre):
            lineas.append("Ojo: esta es una conexión virtual (WSL, Hyper-V, una máquina virtual…). "
                          "Cambiar su DNS no arregla los bloqueos de tu conexión a Internet; elige el Wi-Fi o el cable.")
        guardado = self.dns.original_de(self.datos, nombre)
        if guardado:
            lineas.append("Al restaurar se dejará como estaba: " + self.dns.resumen_configuracion(guardado) + ".")
            fecha = guardado.get("fecha")
            cuando = f" (guardada el {time.strftime('%d/%m/%Y a las %H:%M', time.localtime(fecha))})" if fecha else ""
            lineas.append(f"La copia está en {self.dns.ruta_original(self.datos)}{cuando}, y quedan copias fechadas en {self.dns.carpeta_copias(self.datos)}.")
        elif informacion.get("activo"):
            router = ", ".join(informacion.get("dhcp") or []) or "los que dé el router"
            lineas.append(f"No hay copia guardada: al restaurar se dejará en automático ({router}). "
                          "Si guardaste la configuración con xdp_manager, usa Importar configuración guardada.")
        lineas.append(f"Servidor alternativo: {self.dns.SERVIDOR}, con DNS sobre HTTPS en {self.dns.PLANTILLA_DOH}.")
        self.estado.SetValue("\n".join(lineas))
        self.boton_activar.Enable(not informacion.get("activo"))
        self.boton_restaurar.Enable(bool(informacion.get("activo") or guardado))
        if decir:
            voz.decir(lineas[0])

    def activar(self):
        nombre = self.adaptador()
        if not nombre:
            return
        if not pregunta(self, (f"Se va a poner el DNS alternativo ({self.dns.SERVIDOR}) en «{nombre}».\n\n"
                               "Windows pedirá permiso de administrador. Tu configuración actual se guarda para poder volver a ella\n"
                               "cuando quieras desde este mismo diálogo.\n\n¿Continuar?"), "DNS alternativo"):
            return
        self._ejecutar(lambda: self.dns.activar(self.datos, nombre), nombre)

    def restaurar(self):
        nombre = self.adaptador()
        if not nombre:
            return
        guardado = self.dns.original_de(self.datos, nombre)
        detalle = "Volverá a los DNS " + (self.dns.resumen_configuracion(guardado) if guardado else "automáticos del router")
        if not pregunta(self, f"{detalle}.\n\nWindows pedirá permiso de administrador. ¿Continuar?", "Restaurar la configuración"):
            return
        self._ejecutar(lambda: self.dns.restaurar(self.datos, nombre), nombre)

    def _ejecutar(self, accion, nombre: str):
        self.estado.SetValue("Esperando a que Windows confirme el permiso…")
        wx.Yield()
        try:
            mensaje = accion()
        except self.dns.PermisoDenegado as error:
            self.estado.SetValue(str(error))
            voz.decir(str(error))
            self.actualizar_estado()
            return
        except Exception as error:
            registro.exception("Error cambiando la configuración de DNS")
            self.estado.SetValue(f"No se pudo cambiar la configuración: {error}")
            aviso(self, f"No se pudo cambiar la configuración de red:\n{error}\n\n"
                       f"Tu configuración anterior sigue guardada en {self.dns.ruta_original(self.datos)}.", icono=wx.ICON_ERROR)
            self.actualizar_estado()
            return
        self.datos.windows["dnsAdaptador"] = nombre
        self.datos.guardar()
        self.ventana.estado(mensaje)
        voz.decir(mensaje)
        self.actualizar_estado()


class DialogoGuias(wx.Dialog):
    """Guías de programación: variante de la guía ampliada y guías propias."""

    def __init__(self, parent):
        super().__init__(parent, title="Guías de programación", size=(700, 480), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        self.datos = parent.datos
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=(
            "La guía ampliada cubre los canales que la guía de las listas no trae. Todas sus variantes tienen los mismos\n"
            "canales y programas: solo cambia cómo está escrito el texto.")), 0, wx.ALL, 10)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        actual = self.datos.windows.get("guiaExtraVariante") or catalogo.VARIANTES_GUIA[0][1]
        self.variante = campo(self, fila, "&Variante:", lambda: wx.Choice(self, choices=[v[0] for v in catalogo.VARIANTES_GUIA]), 1)
        self.variante.SetSelection(next((i for i, v in enumerate(catalogo.VARIANTES_GUIA) if v[1] == actual), 0))
        caja.Add(fila, 0, wx.EXPAND | wx.ALL, 10)
        caja.Add(wx.StaticText(self, label="Guías XMLTV propias (una por línea, direcciones https):"), 0, wx.LEFT | wx.TOP, 10)
        self.propias = nombrar(wx.TextCtrl(self, value="\n".join(self.datos.windows.get("guiasPropias") or []), style=wx.TE_MULTILINE, size=(-1, 120)), "Guías XMLTV propias")
        caja.Add(self.propias, 1, wx.EXPAND | wx.ALL, 10)
        caja.Add(wx.StaticText(self, label=(
            "Se emparejan con los canales por su identificador de guía y por el nombre, sin tildes ni «HD».")), 0, wx.LEFT | wx.RIGHT, 10)
        botones = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Cobertura de la guía…", lambda e: self.cobertura()), wx.Button(self, wx.ID_OK, "&Guardar"), wx.Button(self, wx.ID_CANCEL, "&Cancelar")):
            botones.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(botones, 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.variante.SetFocus()

    def cobertura(self):
        self.ventana.ver_cobertura()

    def aplicar(self):
        variante = catalogo.VARIANTES_GUIA[max(0, self.variante.GetSelection())][1]
        self.datos.windows["guiaExtraVariante"] = "" if variante == catalogo.VARIANTES_GUIA[0][1] else variante
        propias = []
        for linea in self.propias.GetValue().splitlines():
            linea = linea.strip()
            if linea.startswith(("http://", "https://")):
                propias.append(linea)
        self.datos.windows["guiasPropias"] = propias[:5]
        self.datos.guardar()


class DialogoCuenta(wx.Dialog):
    """Datos de acceso de un proveedor Xtream Codes."""

    def __init__(self, parent, cuenta: xtream.Cuenta | None = None):
        super().__init__(parent, title="Cuenta de proveedor")
        self.resultado: xtream.Cuenta | None = None
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=(
            "Datos que da el proveedor: la dirección del servidor con su puerto, el usuario y la contraseña.\n"
            "La contraseña se guarda cifrada con la protección de datos de Windows, nunca en claro.")), 0, wx.ALL, 12)
        rejilla = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        rejilla.AddGrowableCol(1, 1)

        def fila(etiqueta, crear):
            texto = wx.StaticText(self, label=etiqueta)
            control = crear()
            nombrar(control, etiqueta.replace("&", "").rstrip(":"))
            rejilla.Add(texto, 0, wx.ALIGN_CENTER_VERTICAL)
            rejilla.Add(control, 1, wx.EXPAND)
            return control

        self.nombre = fila("&Nombre:", lambda: wx.TextCtrl(self, value=cuenta.nombre if cuenta else ""))
        self.servidor = fila("&Servidor (http://ejemplo.tv:8080):", lambda: wx.TextCtrl(self, value=cuenta.servidor if cuenta else "", size=(400, -1)))
        self.usuario = fila("&Usuario:", lambda: wx.TextCtrl(self, value=cuenta.usuario if cuenta else ""))
        self.contrasena = fila("&Contraseña:", lambda: wx.TextCtrl(self, value=cuenta.contrasena if cuenta else "", style=wx.TE_PASSWORD))
        self.tipo = fila("&Aparece en:", lambda: wx.Choice(self, choices=["Televisión", "Radio"]))
        self.tipo.SetSelection(TIPOS.index(cuenta.tipo) if cuenta else 0)
        caja.Add(rejilla, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.estado = nombrar(wx.TextCtrl(self, value="", style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 60)), "Resultado de la comprobación")
        caja.Add(self.estado, 0, wx.EXPAND | wx.ALL, 12)
        fila_botones = wx.BoxSizer(wx.HORIZONTAL)
        fila_botones.Add(boton(self, "&Probar la conexión", lambda e: self.probar()), 0, wx.RIGHT, 6)
        caja.Add(fila_botones, 0, wx.LEFT | wx.BOTTOM, 12)
        botones = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindow(wx.ID_OK).SetLabel("&Guardar")
        self.FindWindow(wx.ID_CANCEL).SetLabel("&Cancelar")
        self.Bind(wx.EVT_BUTTON, self.guardar, id=wx.ID_OK)
        caja.Add(botones, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(caja)
        self.nombre.SetFocus()

    def _cuenta(self) -> xtream.Cuenta:
        return xtream.Cuenta.crear(self.nombre.GetValue(), self.servidor.GetValue(), self.usuario.GetValue(), self.contrasena.GetValue(), TIPOS[max(0, self.tipo.GetSelection())])

    def probar(self):
        cuenta = self._cuenta()
        if not cuenta.servidor or not cuenta.usuario:
            aviso(self, "Faltan el servidor o el usuario.", icono=wx.ICON_WARNING)
            return
        self.estado.SetValue("Conectando con el servidor…")
        voz.decir("Conectando con el servidor")
        wx.Yield()
        try:
            informacion = xtream.informacion(cuenta)
        except Exception as error:
            self.estado.SetValue(f"No se pudo conectar: {error}")
            voz.decir(f"No se pudo conectar: {error}")
            return
        texto = (f"Cuenta {informacion['estado']}, caduca el {informacion['caduca_texto']}. "
                 f"{informacion['activas']} de {informacion['conexiones']} conexiones en uso.")
        self.estado.SetValue(texto)
        voz.decir(texto)

    def guardar(self, _evento):
        cuenta = self._cuenta()
        if not cuenta.servidor or not cuenta.usuario:
            aviso(self, "Hacen falta al menos el servidor y el usuario.", icono=wx.ICON_WARNING)
            return
        self.resultado = cuenta
        self.EndModal(wx.ID_OK)


class DialogoCuentas(wx.Dialog):
    """Cuentas de proveedor guardadas: añadir, editar, comprobar y quitar."""

    def __init__(self, parent):
        super().__init__(parent, title="Cuentas de proveedor", size=(760, 460), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        self.datos = parent.datos
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=(
            "Cuentas Xtream Codes. Sus canales se añaden a las listas de Televisión o Radio, "
            "y sus películas y series aparecen en la pestaña correspondiente.")), 0, wx.ALL, 10)
        self.lista = ListaAccesible(self, "Cuentas de proveedor. Intro edita; Suprimir quita", "cuentas", self.datos.windows)
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.editar())
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self.menu)
        self.lista.Bind(wx.EVT_KEY_DOWN, self.tecla)
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        fila = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Añadir…", lambda e: self.anadir()), boton(self, "&Editar…", lambda e: self.editar()),
                        boton(self, "&Comprobar", lambda e: self.comprobar()), boton(self, "&Quitar", lambda e: self.quitar()),
                        wx.Button(self, wx.ID_CANCEL, "C&errar")):
            fila.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(fila, 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.rellenar()
        self.lista.ajustar_anchos()
        self.lista.SetFocus()

    def cuentas(self) -> list[xtream.Cuenta]:
        return [c for c in (xtream.Cuenta.desde_json(e) for e in self.datos.windows.get("cuentas") or []) if c is not None]

    def rellenar(self, seleccionar: int = 0):
        cuentas = self.cuentas()
        filas = [fila_cuenta(c) for c in cuentas]
        self.lista.rellenar(filas or [{"nombre": "No hay ninguna cuenta. Usa Añadir para configurar la de tu proveedor.", "servidor": "", "estado": ""}], seleccionar)

    def cuenta_actual(self) -> xtream.Cuenta | None:
        return (self.lista.valores_actuales() or {}).get("_cuenta")

    def _guardar(self, cuentas: list[xtream.Cuenta]):
        self.datos.windows["cuentas"] = [c.a_json() for c in cuentas]
        self.datos.guardar()

    def anadir(self):
        with DialogoCuenta(self) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK or dialogo.resultado is None:
                return
        self._guardar(self.cuentas() + [dialogo.resultado])
        self.rellenar()
        self.ventana.estado(f"Cuenta «{dialogo.resultado.nombre}» añadida. Actualiza las listas para ver sus canales.")

    def editar(self):
        actual = self.cuenta_actual()
        if actual is None:
            return
        with DialogoCuenta(self, actual) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK or dialogo.resultado is None:
                return
        cuentas = [dialogo.resultado if c.servidor == actual.servidor and c.usuario == actual.usuario else c for c in self.cuentas()]
        self._guardar(cuentas)
        self.rellenar()
        self.ventana.estado("Cuenta actualizada.")

    def comprobar(self):
        cuenta = self.cuenta_actual()
        if cuenta is None:
            return
        self.ventana.estado(f"Comprobando la cuenta «{cuenta.nombre}»…")
        wx.Yield()
        try:
            informacion = xtream.informacion(cuenta)
        except Exception as error:
            aviso(self, f"No se pudo conectar con «{cuenta.nombre}»:\n{error}", icono=wx.ICON_WARNING)
            return
        filas = [("Estado", informacion["estado"]), ("Caduca", informacion["caduca_texto"]),
                 ("Conexiones", f"{informacion['activas']} de {informacion['conexiones']}"),
                 ("Servidor", informacion["servidor"]), ("Cuenta de prueba", "sí" if informacion["prueba"] else "no")]
        texto = "\n".join(f"{k}: {v}" for k, v in filas)
        dialogo_html(self, f"Cuenta {cuenta.nombre}", tabla_html(f"Cuenta {cuenta.nombre}", filas), texto)

    def quitar(self):
        cuenta = self.cuenta_actual()
        if cuenta is None:
            return
        if not pregunta(self, f"¿Quitar la cuenta «{cuenta.nombre}»?"):
            return
        self._guardar([c for c in self.cuentas() if not (c.servidor == cuenta.servidor and c.usuario == cuenta.usuario)])
        self.rellenar()
        self.ventana.estado("Cuenta quitada. Actualiza las listas para que desaparezcan sus canales.")

    def tecla(self, evento):
        if evento.GetKeyCode() == wx.WXK_DELETE:
            self.quitar()
        else:
            evento.Skip()

    def menu(self, evento):
        fila = self.lista.menu_contextual_en_fila(evento)
        menu_desde(self, [("&Editar…\tIntro", self.editar), ("&Comprobar la cuenta", self.comprobar), None, ("&Quitar\tSupr", self.quitar)], self.lista, fila)


class DialogoGrabaciones(wx.Dialog):
    """Lo que se está grabando ahora, lo programado y los archivos ya grabados."""

    def __init__(self, parent):
        super().__init__(parent, title="Grabaciones", size=(860, 680), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        self.datos = parent.datos
        self.claves_curso: list[str] = []
        self.cerrado = False
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label="Grabaciones en curso (se actualizan solas). Suprimir detiene la que esté seleccionada:"), 0, wx.ALL, 10)
        self.curso = ListaAccesible(self, "Grabaciones en curso. Intro abre las opciones, Suprimir detiene", "grabaciones_curso", self.datos.windows)
        self.curso.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.menu_curso)
        self.curso.Bind(wx.EVT_CONTEXT_MENU, self.menu_curso)
        self.curso.Bind(wx.EVT_KEY_DOWN, self.tecla_curso)
        caja.Add(self.curso, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        caja.Add(wx.StaticText(self, label="Grabaciones programadas desde la guía. Se graban mientras la aplicación esté abierta:"), 0, wx.LEFT | wx.TOP, 10)
        self.programadas = ListaAccesible(self, "Grabaciones programadas. Intro abre las opciones, Suprimir cancela", "grabaciones", self.datos.windows)
        self.programadas.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.menu_programada)
        self.programadas.Bind(wx.EVT_CONTEXT_MENU, self.menu_programada)
        self.programadas.Bind(wx.EVT_KEY_DOWN, self.tecla_programada)
        caja.Add(self.programadas, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.espacio = wx.StaticText(self, label="")
        caja.Add(self.espacio, 0, wx.LEFT | wx.TOP, 10)
        caja.Add(wx.StaticText(self, label="Archivos grabados:"), 0, wx.LEFT | wx.TOP, 10)
        self.archivos = ListaAccesible(self, "Archivos grabados. Intro reproduce", "grabaciones", self.datos.windows)
        self.archivos.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.reproducir())
        self.archivos.Bind(wx.EVT_CONTEXT_MENU, self.menu_archivo)
        caja.Add(self.archivos, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        fila = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Detener la grabación", lambda e: self.detener()), boton(self, "&Reproducir", lambda e: self.reproducir()),
                        boton(self, "&Cancelar la programada", lambda e: self.cancelar()),
                        boton(self, "Re&cortar…", lambda e: self.recortar()), boton(self, "&Proteger", lambda e: self.proteger()),
                        boton(self, "&Eliminar el archivo", lambda e: self.eliminar()), boton(self, "Abrir la &carpeta", lambda e: self.abrir_carpeta()),
                        wx.Button(self, wx.ID_CANCEL, "C&errar")):
            fila.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(fila, 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.rellenar()
        for lista in (self.curso, self.programadas, self.archivos):
            lista.ajustar_anchos()
        voz.decir(self.resumen_hablado(), interrumpir=True)
        # Los tiempos y el tamaño cambian solos, pero sin rehacer la lista: se
        # cambia el texto de cada celda, así el lector de pantalla no pierde el foco.
        self.reloj = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self.refrescar(), self.reloj)
        self.reloj.Start(2000)
        self.Bind(wx.EVT_CLOSE, self.al_cerrar)
        (self.curso if self.claves_curso else self.programadas).SetFocus()

    # --- contenido -----------------------------------------------------------
    def filas_curso(self) -> list[dict]:
        return [fila_en_curso(r) for r in self.ventana.grabaciones_en_curso()]

    def filas_programadas(self) -> list[dict]:
        en_curso = {r["clave"]: r for r in self.ventana.grabaciones_en_curso()}
        filas = []
        for entrada in grabacion.listar(self.datos):
            valores = fila_grabacion(entrada)
            resumen = en_curso.get(self.ventana.clave_programada(entrada))
            if resumen is not None:
                queda = "" if resumen["restante"] is None else f", quedan {grabacion.duracion_hablada(resumen['restante'])}"
                valores["estado"] = f"Grabando desde hace {grabacion.duracion_hablada(resumen['transcurrido'])}{queda}"
            filas.append(valores)
        return filas

    def rellenar(self):
        filas = self.filas_curso()
        self.claves_curso = [f["_curso"]["clave"] for f in filas]
        self.curso.rellenar(filas or [{"canal": "", "titulo": "No se está grabando nada ahora mismo", "estado": "", "transcurrido": "", "restante": "", "tamano": ""}])
        self.programadas.rellenar(self.filas_programadas() or [{"fecha": "", "canal": "", "titulo": "No hay grabaciones programadas", "estado": ""}])
        archivos = grabacion.archivos(self.datos)
        self.archivos.rellenar([fila_archivo(a) for a in archivos] or [{"fecha": "", "titulo": "Todavía no hay grabaciones", "duracion": "", "estado": ""}])
        ocupado = sum(a["tamano"] for a in archivos) / 1e9
        sobran = len(grabacion.sobrantes(self.datos))
        texto = (f"{len(archivos)} grabaciones guardadas ({ocupado:.2f} gigabytes). "
                 f"Quedan {grabacion.espacio_libre(self.datos):.1f} gigabytes libres en el disco.")
        if sobran:
            texto += f" Las reglas de limpieza dejarían fuera {sobran}."
        self.espacio.SetLabel(texto)

    def resumen_hablado(self) -> str:
        """Lo que se dice al abrir el diálogo: en curso, programadas y guardadas."""
        en_curso = len(self.claves_curso)
        pendientes = sum(1 for g in grabacion.listar(self.datos) if g.get("estado") == "pendiente")
        guardadas = len(grabacion.archivos(self.datos))
        partes = [f"{en_curso} grabación en curso" if en_curso == 1 else f"{en_curso} grabaciones en curso",
                  f"{pendientes} programada" + ("s" if pendientes != 1 else ""),
                  f"{guardadas} archivo" + ("s" if guardadas != 1 else "") + " guardado" + ("s" if guardadas != 1 else "")]
        return "Grabaciones: " + ", ".join(partes) + "."

    def refrescar(self):
        """Cada dos segundos: si son las mismas grabaciones, solo cambia el texto."""
        if self.cerrado:
            return
        filas = self.filas_curso()
        claves = [f["_curso"]["clave"] for f in filas]
        if claves != self.claves_curso:
            self.rellenar()
            return
        for numero, valores in enumerate(filas):
            self.curso.actualizar_fila(numero, valores)
        for numero, valores in enumerate(self.filas_programadas()):
            self.programadas.actualizar_fila(numero, valores)

    def al_cerrar(self, evento):
        self.cerrado = True
        self.reloj.Stop()
        evento.Skip()

    def terminar(self, resultado):
        self.cerrado = True
        self.reloj.Stop()
        self.EndModal(resultado)

    def Destroy(self):  # noqa: N802 (lo llama wx)
        """Parar el reloj antes de destruir la ventana: si no, puede dispararse sin ella."""
        self.cerrado = True
        try:
            self.reloj.Stop()
        except Exception:
            pass
        return super().Destroy()

    # --- selección -----------------------------------------------------------
    def curso_actual(self):
        return (self.curso.valores_actuales() or {}).get("_curso")

    def programada_actual(self):
        return (self.programadas.valores_actuales() or {}).get("_grabacion")

    def archivo_actual(self):
        return (self.archivos.valores_actuales() or {}).get("_archivo")

    # --- acciones ------------------------------------------------------------
    def detener(self, resumen=None):
        """Para ya una grabación en curso, la de la lista de arriba o la programada elegida."""
        resumen = resumen or self.curso_actual()
        if resumen is None:
            entrada = self.programada_actual()
            if entrada is None or entrada.get("estado") != "grabando":
                aviso(self, "Elige una grabación en curso para detenerla.")
                return
            self.ventana.detener_programada(entrada)
            self.rellenar()
            return
        if not pregunta(self, f"¿Detener la grabación de {resumen['canal']}?\nSe guarda lo grabado hasta ahora ({grabacion.tamano_hablado(resumen['tamano'])})."):
            return
        self.ventana.estado(self.ventana.parar_grabacion_fondo(resumen["clave"]))
        self.rellenar()

    def cancelar(self):
        entrada = self.programada_actual()
        if not entrada:
            return
        if entrada.get("estado") == "grabando":
            self.detener()
            return
        lista = self.datos.windows["grabaciones"]
        if entrada in lista:
            lista.remove(entrada)
            self.datos.guardar()
            self.rellenar()
            self.ventana.estado(f"Grabación de «{entrada['titulo']}» cancelada.")

    def reproducir(self):
        archivo = self.archivo_actual()
        if not archivo:
            return
        self.terminar(wx.ID_OK)
        self.ventana.reproducir_archivo(archivo["ruta"], archivo["nombre"])

    def eliminar(self):
        archivo = self.archivo_actual()
        if not archivo:
            return
        if archivo.get("protegida"):
            aviso(self, "Esa grabación está protegida. Quítale la protección antes de borrarla.", icono=wx.ICON_WARNING)
            return
        if not pregunta(self, f"¿Eliminar «{archivo['nombre']}»?\nEsta acción no se puede deshacer."):
            return
        try:
            archivo["ruta"].unlink()
        except OSError as error:
            aviso(self, f"No se pudo eliminar: {error}", icono=wx.ICON_ERROR)
            return
        self.rellenar()
        self.ventana.estado("Grabación eliminada.")

    def proteger(self):
        """Marca la grabación para que la limpieza automática no la toque."""
        archivo = self.archivo_actual()
        if not archivo:
            return
        protegidas = self.datos.windows.setdefault("grabacionesProtegidas", [])
        nombre = archivo["ruta"].name
        if nombre in protegidas:
            protegidas.remove(nombre)
            mensaje = f"«{archivo['nombre']}» ya no está protegida."
        else:
            protegidas.append(nombre)
            mensaje = f"«{archivo['nombre']}» protegida: la limpieza automática no la borrará."
        self.datos.guardar()
        self.rellenar()
        self.ventana.estado(mensaje)

    def recortar(self):
        """Quita el principio o el final de una grabación, sin recodificar nada."""
        archivo = self.archivo_actual()
        if not archivo:
            return
        self.ventana.recortar_grabacion(archivo, self)
        self.rellenar()

    def limpiar(self):
        """Aplica ya las reglas de limpieza, enseñando antes qué se va a borrar."""
        fuera = grabacion.sobrantes(self.datos)
        if not fuera:
            aviso(self, "No sobra ninguna grabación con las reglas de limpieza que tienes puestas.\n"
                        "Se configuran en Ajustes, en la pestaña Grabación.")
            return
        total = sum(a["tamano"] for a in fuera) / 1e9
        nombres = "\n".join(f"· {a['nombre']}" for a in fuera[:12])
        if len(fuera) > 12:
            nombres += f"\n… y {len(fuera) - 12} más"
        if not pregunta(self, f"Las reglas de limpieza dejan fuera {len(fuera)} grabaciones ({total:.2f} gigabytes):\n\n{nombres}\n\n¿Borrarlas?"):
            return
        borradas = grabacion.limpiar_carpeta(self.datos)
        self.rellenar()
        self.ventana.estado(f"Limpieza: {len(borradas)} grabaciones borradas.")

    def abrir_carpeta(self):
        try:
            os.startfile(str(grabacion.carpeta(self.datos)))
        except OSError:
            aviso(self, f"Carpeta de grabaciones: {grabacion.carpeta(self.datos)}")

    def tecla_curso(self, evento):
        if evento.GetKeyCode() == wx.WXK_DELETE:
            self.detener()
        else:
            evento.Skip()

    def tecla_programada(self, evento):
        if evento.GetKeyCode() == wx.WXK_DELETE:
            self.cancelar()
        else:
            evento.Skip()

    def menu_curso(self, evento):
        fila = self.curso.menu_contextual_en_fila(evento)
        resumen = self.curso_actual()
        menu_desde(self, [
            ("&Detener esta grabación\tSupr", self.detener),
            ("Abrir la &carpeta", self.abrir_carpeta),
            ("&Copiar el nombre del archivo", (lambda: copiar_portapapeles(resumen["archivo"])) if resumen and resumen.get("archivo") else None),
        ], self.curso, fila)

    def menu_programada(self, evento):
        fila = self.programadas.menu_contextual_en_fila(evento)
        entrada = self.programada_actual()
        grabando = bool(entrada) and entrada.get("estado") == "grabando"
        menu_desde(self, [
            ("&Detener ahora esta grabación", self.detener if grabando else None),
            ("&Cancelar esta grabación\tSupr", self.cancelar),
        ], self.programadas, fila)

    def menu_archivo(self, evento):
        fila = self.archivos.menu_contextual_en_fila(evento)
        archivo = self.archivo_actual()
        recortable = bool(archivo) and grabacion.recortable(archivo["ruta"])
        menu_desde(self, [
            ("&Reproducir\tIntro", self.reproducir),
            ("Re&cortar el principio o el final…", self.recortar if recortable else None),
            ("Quitar la &protección" if archivo and archivo.get("protegida") else "&Proteger de la limpieza", self.proteger if archivo else None),
            ("Copiar la r&uta", (lambda: copiar_portapapeles(str(archivo["ruta"]))) if archivo else None),
            ("Abrir la &carpeta", self.abrir_carpeta),
            None,
            ("&Limpiar según las reglas…", self.limpiar),
            ("&Eliminar", self.eliminar),
        ], self.archivos, fila)


class DialogoBuscarGuia(wx.Dialog):
    """Busca un título en la programación de todos los canales."""

    def __init__(self, parent, texto_inicial: str = ""):
        super().__init__(parent, title="Buscar en toda la guía", size=(860, 580), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        self.resultados: list[tuple] = []
        caja = wx.BoxSizer(wx.VERTICAL)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.busqueda = campo(self, fila, "&Buscar (título o descripción):", lambda: wx.TextCtrl(self, value=texto_inicial, style=wx.TE_PROCESS_ENTER), 2)
        self.busqueda.Bind(wx.EVT_TEXT_ENTER, lambda e: self.buscar())
        fila.Add(boton(self, "&Buscar", lambda e: self.buscar()), 0)
        caja.Add(fila, 0, wx.EXPAND | wx.ALL, 10)
        self.cuenta = wx.StaticText(self, label="Escribe algo y pulsa Intro.")
        caja.Add(self.cuenta, 0, wx.LEFT | wx.RIGHT, 10)
        self.lista = ListaAccesible(self, "Resultados de la búsqueda. Intro abre las opciones", "busqueda_guia", parent.datos.windows)
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.menu(e))
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self.menu)
        self.lista.Bind(wx.EVT_LIST_ITEM_FOCUSED, lambda e: (e.Skip(), self.mostrar()))
        caja.Add(self.lista, 2, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        caja.Add(wx.StaticText(self, label="Detalles:"), 0, wx.LEFT | wx.TOP, 10)
        self.detalle = nombrar(wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 100)), "Detalles del programa")
        caja.Add(self.detalle, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        botones = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Ver canal", lambda e: self.ver_canal()), boton(self, "&Recordatorio…", lambda e: self.recordatorio()),
                        boton(self, "&Grabar…", lambda e: self.grabar()), wx.Button(self, wx.ID_CANCEL, "C&errar")):
            botones.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(botones, 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.busqueda.SetFocus()
        if texto_inicial:
            wx.CallAfter(self.buscar)

    def buscar(self):
        texto = self.busqueda.GetValue().strip()
        if len(texto) < 2:
            self.cuenta.SetLabel("Escribe al menos dos letras.")
            voz.decir("Escribe al menos dos letras")
            return
        self.resultados = organizar.buscar_en_guia(self.ventana.canales, self.ventana.guia, texto)
        ahora = time.time()
        filas = [fila_programa(programa, canal, ahora) for canal, programa in self.resultados]
        self.lista.rellenar(filas or [{"titulo": "Sin resultados", "canal": "", "hora": ""}], 0)
        self.lista.ajustar_anchos()
        total = len(self.resultados)
        mensaje = f"{total} resultado{'s' if total != 1 else ''} para «{texto}»." if total else f"Ningún programa coincide con «{texto}»."
        self.cuenta.SetLabel(mensaje)
        self.ventana.estado(mensaje, decir=False)
        voz.decir(mensaje)
        self.mostrar()

    def par_actual(self):
        valores = self.lista.valores_actuales() or {}
        programa, canal = valores.get("_programa"), valores.get("_canal")
        return (canal, programa) if programa is not None and canal is not None else (None, None)

    def mostrar(self):
        canal, programa = self.par_actual()
        if programa is None:
            self.detalle.SetValue("")
            return
        self.detalle.SetValue(texto_detalle_programa(canal, programa))

    def ver_canal(self):
        canal, _programa = self.par_actual()
        if canal is not None:
            self.EndModal(wx.ID_OK)
            self.ventana.reproducir_canal(canal)

    def recordatorio(self):
        canal, programa = self.par_actual()
        if canal is not None and programa is not None:
            self.ventana.crear_recordatorio(canal, programa, self)

    def grabar(self):
        canal, programa = self.par_actual()
        if canal is not None and programa is not None:
            self.ventana.programar_grabacion(canal, programa, self)

    def menu(self, evento):
        canal, programa = self.par_actual()
        fila = self.lista.menu_contextual_en_fila(evento) if evento is not None and hasattr(evento, "GetPosition") else self.lista.fila_actual()
        opciones = [
            ("&Ver canal ahora", self.ver_canal if canal else None),
            ("&Recordatorio…", self.recordatorio if programa else None),
            ("&Grabar este programa…", self.grabar if programa else None),
            None,
            ("&Copiar título", (lambda: copiar_portapapeles(programa.titulo)) if programa else None),
        ]
        menu_desde(self, opciones, self.lista, fila)


class DialogoHistorial(wx.Dialog):
    """Últimos canales vistos, para volver a cualquiera de ellos."""

    def __init__(self, parent):
        super().__init__(parent, title="Historial de canales", size=(620, 460), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label="Canales vistos recientemente. Intro reproduce; Escape cierra."), 0, wx.ALL, 10)
        self.lista = ListaAccesible(self, "Historial de canales. Intro reproduce", "historial", parent.datos.windows)
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.reproducir())
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self.menu)
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        fila = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Reproducir", lambda e: self.reproducir()), boton(self, "&Vaciar el historial", lambda e: self.vaciar()), wx.Button(self, wx.ID_CANCEL, "C&errar")):
            fila.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(fila, 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.rellenar()
        self.lista.ajustar_anchos()
        self.lista.SetFocus()

    def rellenar(self):
        entradas = organizar.historial(self.ventana.datos)
        self.lista.rellenar([fila_historial(e) for e in entradas] or [{"nombre": "Todavía no has visto ningún canal", "tipo": "", "fecha": ""}], 0)

    def canal(self):
        entrada = (self.lista.valores_actuales() or {}).get("_entrada")
        if not entrada:
            return None
        return next((c for c in self.ventana.canales if c.tipo == entrada["tipo"] and c.nombre == entrada["nombre"]), None)

    def reproducir(self):
        canal = self.canal()
        if canal is None:
            self.ventana.estado("Ese canal ya no está en las listas cargadas.")
            return
        self.EndModal(wx.ID_OK)
        self.ventana.reproducir_canal(canal)

    def vaciar(self):
        if not pregunta(self, "¿Vaciar el historial de canales?"):
            return
        self.ventana.datos.windows["historial"] = []
        self.ventana.datos.guardar()
        self.rellenar()
        self.ventana.estado("Historial vaciado.")

    def menu(self, evento):
        fila = self.lista.menu_contextual_en_fila(evento)
        menu_desde(self, [("&Reproducir\tIntro", self.reproducir), ("&Vaciar el historial", self.vaciar)], self.lista, fila)


class DialogoNumero(wx.Dialog):
    """Salta al canal por su número, como el teclado de un mando."""

    def __init__(self, parent, maximo: int):
        super().__init__(parent, title="Ir al número de canal")
        self.numero = 0
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=f"Escribe el número del canal (hay {maximo} en la lista).\nTambién puedes teclear las cifras directamente sobre la lista."), 0, wx.ALL, 12)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.campo = campo(self, fila, "&Número:", lambda: wx.SpinCtrl(self, min=1, max=max(1, maximo), initial=1), 0, False)
        caja.Add(fila, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        botones = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindow(wx.ID_OK).SetLabel("&Ir")
        self.FindWindow(wx.ID_CANCEL).SetLabel("&Cancelar")
        caja.Add(botones, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(caja)
        self.campo.SetFocus()

    def valor(self) -> int:
        return int(self.campo.GetValue())


class DialogoPin(wx.Dialog):
    """Pide el PIN de control parental, o lo define la primera vez."""

    def __init__(self, parent, titulo: str = "Bloqueo por PIN", nuevo: bool = False):
        super().__init__(parent, title=titulo)
        self.nuevo = nuevo
        caja = wx.BoxSizer(wx.VERTICAL)
        texto = ("Escribe un PIN de al menos cuatro cifras y repítelo. Con él se bloquean canales o categorías enteras."
                 if nuevo else "Escribe el PIN para continuar.")
        caja.Add(wx.StaticText(self, label=texto), 0, wx.ALL, 12)
        rejilla = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        rejilla.AddGrowableCol(1, 1)
        rejilla.Add(wx.StaticText(self, label="&PIN:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.pin = nombrar(wx.TextCtrl(self, style=wx.TE_PASSWORD | wx.TE_PROCESS_ENTER), "PIN")
        rejilla.Add(self.pin, 1, wx.EXPAND)
        if nuevo:
            rejilla.Add(wx.StaticText(self, label="&Repetir el PIN:"), 0, wx.ALIGN_CENTER_VERTICAL)
            self.repetir = nombrar(wx.TextCtrl(self, style=wx.TE_PASSWORD), "Repetir el PIN")
            rejilla.Add(self.repetir, 1, wx.EXPAND)
        else:
            self.repetir = None
        caja.Add(rejilla, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        botones = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindow(wx.ID_OK).SetLabel("&Aceptar")
        self.FindWindow(wx.ID_CANCEL).SetLabel("&Cancelar")
        self.Bind(wx.EVT_BUTTON, self.aceptar, id=wx.ID_OK)
        self.pin.Bind(wx.EVT_TEXT_ENTER, lambda e: self.aceptar(None))
        caja.Add(botones, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(caja)
        self.SetMinSize((380, -1))
        self.pin.SetFocus()

    def valor(self) -> str:
        return self.pin.GetValue().strip()

    def aceptar(self, _evento):
        pin = self.valor()
        if self.nuevo:
            if len(pin) < 4 or not pin.isdigit():
                aviso(self, "El PIN debe tener al menos cuatro cifras.", icono=wx.ICON_WARNING)
                return
            if pin != self.repetir.GetValue().strip():
                aviso(self, "Los dos PIN no coinciden.", icono=wx.ICON_WARNING)
                return
        self.EndModal(wx.ID_OK)


class DialogoDuplicados(wx.Dialog):
    """Canales que aparecen en más de una lista."""

    def __init__(self, parent):
        super().__init__(parent, title="Canales duplicados", size=(720, 480), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        repetidos = organizar.duplicados(parent.canales)
        caja = wx.BoxSizer(wx.VERTICAL)
        total = sum(len(v) - 1 for v in repetidos.values())
        caja.Add(wx.StaticText(self, label=(
            f"{len(repetidos)} canal{'es' if len(repetidos) != 1 else ''} aparece{'n' if len(repetidos) != 1 else ''} en varias listas "
            f"({total} repetici{'ones' if total != 1 else 'ón'}).\n"
            "En Ajustes puedes decidir si se muestran todos o solo el primero de cada uno.")), 0, wx.ALL, 10)
        self.lista = ListaAccesible(self, "Canales duplicados", "listas", parent.datos.windows)
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        filas = []
        for _clave, canales in sorted(repetidos.items()):
            for canal in canales:
                filas.append({"nombre": canal.nombre, "tipo": NOMBRE_TIPO.get(canal.tipo, canal.tipo), "url": (canal.emision_principal.url if canal.emision_principal else ""), "fuente": canal.origen or "lista incluida"})
        self.lista.rellenar(filas or [{"nombre": "No hay canales duplicados", "tipo": "", "url": "", "fuente": ""}], 0)
        self.lista.ajustar_anchos()
        caja.Add(wx.Button(self, wx.ID_CANCEL, "C&errar"), 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.lista.SetFocus()


class DialogoPerfiles(wx.Dialog):
    """Perfiles de uso: juegos completos de ajustes con nombre."""

    def __init__(self, parent):
        super().__init__(parent, title="Perfiles de uso", size=(620, 440), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        self.datos = parent.datos
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=(
            "Cada perfil guarda sus favoritos, su orden, sus listas y sus ajustes.\n"
            "Al cambiar de perfil se guarda antes el que estés usando.")), 0, wx.ALL, 10)
        self.lista = nombrar(wx.ListBox(self), "Perfiles guardados")
        self.lista.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.cambiar())
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        fila = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Usar este perfil", lambda e: self.cambiar()), boton(self, "&Guardar como…", lambda e: self.guardar()),
                        boton(self, "&Actualizar el actual", lambda e: self.actualizar()), boton(self, "&Eliminar", lambda e: self.eliminar()),
                        wx.Button(self, wx.ID_CANCEL, "C&errar")):
            fila.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(fila, 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.rellenar()
        self.lista.SetFocus()

    def rellenar(self):
        actual = self.datos.windows.get("perfilActual") or ""
        nombres = respaldo.listar_perfiles(self.datos)
        self.lista.Set([f"{n} (en uso)" if n == actual else n for n in nombres] or ["No hay perfiles guardados"])
        self.nombres = nombres
        if nombres:
            self.lista.SetSelection(nombres.index(actual) if actual in nombres else 0)

    def nombre_actual(self) -> str:
        indice = self.lista.GetSelection()
        return self.nombres[indice] if 0 <= indice < len(self.nombres) else ""

    def guardar(self):
        with wx.TextEntryDialog(self, "Nombre del perfil:", "Guardar perfil", self.datos.windows.get("perfilActual") or "") as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            nombre = dialogo.GetValue().strip()
        if not nombre:
            return
        try:
            respaldo.guardar_perfil(self.datos, nombre)
        except (ValueError, OSError) as error:
            aviso(self, f"No se pudo guardar el perfil: {error}", icono=wx.ICON_ERROR)
            return
        self.datos.windows["perfilActual"] = nombre
        self.datos.guardar()
        self.rellenar()
        self.ventana.estado(f"Perfil «{nombre}» guardado.")

    def actualizar(self):
        nombre = self.datos.windows.get("perfilActual") or self.nombre_actual()
        if not nombre:
            self.guardar()
            return
        respaldo.guardar_perfil(self.datos, nombre)
        self.ventana.estado(f"Perfil «{nombre}» actualizado con los ajustes de ahora.")

    def cambiar(self):
        nombre = self.nombre_actual()
        if not nombre:
            return
        anterior = self.datos.windows.get("perfilActual") or ""
        if anterior and anterior != nombre:
            try:
                respaldo.guardar_perfil(self.datos, anterior)
            except (ValueError, OSError):
                registro.debug("No se pudo guardar el perfil anterior", exc_info=True)
        try:
            ajustes = respaldo.cargar_perfil(self.datos, nombre)
        except (ValueError, OSError) as error:
            aviso(self, f"No se pudo cargar el perfil: {error}", icono=wx.ICON_ERROR)
            return
        self.EndModal(wx.ID_OK)
        self.ventana.aplicar_ajustes_nuevos(ajustes, f"Perfil «{nombre}» en uso.", perfil=nombre)

    def eliminar(self):
        nombre = self.nombre_actual()
        if not nombre or not pregunta(self, f"¿Eliminar el perfil «{nombre}»?"):
            return
        respaldo.eliminar_perfil(self.datos, nombre)
        if self.datos.windows.get("perfilActual") == nombre:
            self.datos.windows["perfilActual"] = ""
            self.datos.guardar()
        self.rellenar()
        self.ventana.estado(f"Perfil «{nombre}» eliminado.")


class DialogoEnviar(wx.Dialog):
    """Busca televisores de la red y les manda la emisión que está sonando."""

    def __init__(self, parent, url: str, titulo: str):
        super().__init__(parent, title="Enviar a la tele", size=(600, 420), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        self.url = url
        self.titulo = titulo
        self.dispositivos: list = []
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=(
            f"Se enviará «{titulo}» a un aparato de la red.\n"
            "Aparecen los televisores y receptores DLNA, los Chromecast y los Fire TV o Android TV.")), 0, wx.ALL, 10)
        caja.Add(wx.StaticText(self, label="&Aparatos encontrados:"), 0, wx.LEFT | wx.TOP, 10)
        self.lista = nombrar(wx.ListBox(self), "Aparatos encontrados en la red")
        self.lista.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.enviar())
        self.lista.Bind(wx.EVT_LISTBOX, lambda e: self.describir())
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        caja.Add(wx.StaticText(self, label="&Estado:"), 0, wx.LEFT | wx.TOP, 10)
        self.estado = nombrar(wx.TextCtrl(self, value="Buscando aparatos…", style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 90)), "Estado de la búsqueda")
        caja.Add(self.estado, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        fila = wx.WrapSizer(wx.HORIZONTAL)
        self.boton_enviar = boton(self, "&Enviar", lambda e: self.enviar())
        for control in (self.boton_enviar, boton(self, "&Parar en el aparato", lambda e: self.parar()),
                        boton(self, "&Duplicar la pantalla (Fire TV)", lambda e: self.duplicar()),
                        boton(self, "&Buscar otra vez", lambda e: self.buscar()), wx.Button(self, wx.ID_CANCEL, "C&errar")):
            fila.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(fila, 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.lista.SetFocus()
        wx.CallAfter(self.buscar)

    def buscar(self):
        self.estado.SetValue("Buscando aparatos en la red…")
        voz.decir("Buscando aparatos en la red")
        threading.Thread(target=self._buscar_en_hilo, daemon=True).start()

    def _buscar_en_hilo(self):
        encontrados = casting.buscar()
        wx.CallAfter(self._encontrados, encontrados)

    def _encontrados(self, encontrados):
        if not self:
            return
        self.dispositivos = encontrados
        self.lista.Set([str(d) for d in encontrados] or ["No se ha encontrado ningún aparato"])
        if encontrados:
            self.lista.SetSelection(0)
        if encontrados:
            envio = sum(1 for d in encontrados if d.admite_envio)
            mensaje = f"{len(encontrados)} aparato{'s' if len(encontrados) != 1 else ''} en la red; {envio} admite{'n' if envio != 1 else ''} recibir la emisión."
        else:
            mensaje = ("No se ha encontrado ningún aparato. Comprueba que el televisor está encendido y en la misma red. "
                       + ("" if casting.chromecast_disponible() else "La búsqueda de Chromecast no está disponible en esta instalación."))
        self.estado.SetValue(mensaje)
        voz.decir(mensaje)
        self.describir()

    def dispositivo(self):
        indice = self.lista.GetSelection()
        return self.dispositivos[indice] if 0 <= indice < len(self.dispositivos) else None

    def describir(self):
        """Explica qué se puede hacer con el aparato elegido."""
        aparato = self.dispositivo()
        if aparato is None:
            self.boton_enviar.Enable(False)
            return
        self.boton_enviar.Enable(aparato.admite_envio)
        if aparato.admite_envio:
            self.estado.SetValue(f"{aparato.nombre} ({aparato.tipo_legible}) acepta la emisión: pulsa Enviar.")
        else:
            self.estado.SetValue(casting.instrucciones(aparato))

    def enviar(self):
        aparato = self.dispositivo()
        if aparato is None:
            return
        if not aparato.admite_envio:
            self.estado.SetValue(casting.instrucciones(aparato))
            voz.decir("Ese aparato no acepta enlaces directos; mira las instrucciones")
            return
        self.estado.SetValue(f"Enviando a {aparato.nombre}…")
        voz.decir(f"Enviando a {aparato.nombre}")
        wx.BeginBusyCursor()
        try:
            enviado = casting.enviar(aparato, self.url, self.titulo)
        finally:
            wx.EndBusyCursor()
        if enviado:
            self.estado.SetValue(f"Enviado a {aparato.nombre}. Si no aparece, comprueba que el aparato tiene acceso a Internet.")
            voz.decir(f"Enviado a {aparato.nombre}")
            self.ventana.estado(f"«{self.titulo}» enviado a {aparato.nombre}.")
        else:
            self.estado.SetValue(f"{aparato.nombre} no ha aceptado la emisión. Puede que el formato no le valga o que esté ocupado con otra aplicación.")
            voz.decir(f"{aparato.nombre} no ha aceptado la emisión")

    def parar(self):
        aparato = self.dispositivo()
        if aparato is None or not aparato.admite_envio:
            return
        casting.parar(aparato)
        self.estado.SetValue(f"Reproducción detenida en {aparato.nombre}.")
        voz.decir("Reproducción detenida en el aparato")

    def duplicar(self):
        """Abre el panel de Windows para duplicar la pantalla, que es lo que admite Fire TV."""
        if not pregunta(self, ("Se va a abrir el panel de Windows para duplicar la pantalla, lo mismo que la tecla Windows más K.\n\n"
                               "En el Fire TV hay que tener abierto «Duplicar pantalla» para que aparezca en la lista de Windows.\n\n¿Continuar?"),
                        "Duplicar la pantalla"):
            return
        if casting.duplicar_pantalla():
            self.estado.SetValue("Se ha abierto el panel de Windows: elige ahí el aparato. La emisión se verá tal cual suena en el equipo.")
            voz.decir("Panel de duplicar pantalla abierto")
        else:
            self.estado.SetValue("No se pudo abrir el panel de Windows. Puedes hacerlo con la tecla Windows más K.")


class DialogoActualizacion(wx.Dialog):
    """Comprueba si hay una versión nueva de la aplicación y la instala de forma segura."""

    def __init__(self, parent):
        super().__init__(parent, title="Versiones de la aplicación", size=(640, 420), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        self.datos = parent.datos
        self.resultado: dict = getattr(parent, "resultado_app", {}) or {}
        self._descargando = False
        self._cancelar = threading.Event()
        self._temp_zip: str | None = None

        caja = wx.BoxSizer(wx.VERTICAL)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.url = campo(self, fila, "&Dirección del archivo de versiones:", lambda: wx.TextCtrl(self, value=self.datos.windows.get("urlActualizaciones", "")), 1)
        caja.Add(fila, 0, wx.EXPAND | wx.ALL, 10)

        self.texto = nombrar(wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 130)), "Resultado de la comprobación")
        if self.resultado:
            mensaje = actualizacion.resumen(self.resultado)
            if self.resultado.get("url"):
                mensaje += "\nDescarga: " + self.resultado["url"]
            self.texto.SetValue(mensaje)
        else:
            self.texto.SetValue(actualizacion.resumen({"configurada": bool(self.datos.windows.get("urlActualizaciones"))}))
        caja.Add(self.texto, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.progreso = wx.Gauge(self, range=100, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        caja.Add(self.progreso, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.estado_descarga = wx.StaticText(self, label="")
        caja.Add(self.estado_descarga, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM, 6)

        botones = wx.WrapSizer(wx.HORIZONTAL)
        self.btn_comprobar = boton(self, "&Comprobar ahora", lambda e: self.comprobar())
        self.btn_actualizar = boton(self, "&Actualizar ahora", lambda e: self.actualizar())
        self.btn_abrir = boton(self, "A&brir en el navegador", lambda e: self.abrir())
        self.btn_cancelar = boton(self, "C&ancelar descarga", lambda e: self.cancelar_descarga())
        self.btn_cerrar = wx.Button(self, wx.ID_CANCEL, "C&errar")

        self.btn_cancelar.Hide()
        botones.Add(self.btn_comprobar, 0, wx.RIGHT | wx.BOTTOM, 4)
        botones.Add(self.btn_actualizar, 0, wx.RIGHT | wx.BOTTOM, 4)
        botones.Add(self.btn_abrir, 0, wx.RIGHT | wx.BOTTOM, 4)
        botones.Add(self.btn_cancelar, 0, wx.RIGHT | wx.BOTTOM, 4)
        botones.Add(self.btn_cerrar, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(botones, 0, wx.ALL, 10)

        self._actualizar_estado_botones()
        self.SetSizer(caja)
        self.Bind(wx.EVT_CLOSE, self.al_cerrar_dialogo)
        self.url.SetFocus()

    def _actualizar_estado_botones(self):
        hay_descarga = bool(self.resultado.get("hay") and self.resultado.get("url"))
        self.btn_actualizar.Enable(hay_descarga and not self._descargando)
        self.btn_abrir.Enable(bool(self.resultado.get("url")) and not self._descargando)
        self.btn_comprobar.Enable(not self._descargando)
        self.btn_cerrar.Enable(not self._descargando)
        if self._descargando:
            self.btn_cancelar.Show()
        else:
            self.btn_cancelar.Hide()
        self.Layout()

    def al_cerrar_dialogo(self, evento):
        if self._descargando:
            if pregunta(self, "¿Deseas cancelar la descarga de la actualización en curso?"):
                self.cancelar_descarga()
            else:
                return
        evento.Skip()

    def comprobar(self):
        direccion = actualizacion.normalizar_url(self.url.GetValue().strip())
        if direccion != self.url.GetValue().strip():
            self.url.SetValue(direccion)
        self.datos.windows["urlActualizaciones"] = direccion
        self.datos.guardar()
        self.texto.SetValue("Comprobando…")
        wx.Yield()
        self.resultado = actualizacion.comprobar(direccion)
        if hasattr(self.ventana, "resultado_app"):
            self.ventana.resultado_app = self.resultado
        mensaje = actualizacion.resumen(self.resultado)
        if self.resultado.get("url"):
            mensaje += "\nDescarga: " + self.resultado["url"]
        self.texto.SetValue(mensaje)
        self._actualizar_estado_botones()
        if self.resultado.get("hay") and self.resultado.get("url"):
            self.btn_actualizar.SetFocus()
            voz.decir(mensaje + " Pulsa Actualizar ahora para instalarla automáticamente.")
        else:
            voz.decir(mensaje)

    def actualizar(self):
        url_descarga = self.resultado.get("url")
        if not url_descarga:
            aviso(self, "No hay ninguna dirección de descarga disponible.")
            return
        if self._descargando:
            return
        self._descargando = True
        self._cancelar.clear()
        self._actualizar_estado_botones()
        self.progreso.SetValue(0)
        self.estado_descarga.SetLabel("Iniciando descarga de la actualización...")
        voz.decir(f"Iniciando descarga de la versión {self.resultado.get('version', '')}. Por favor, espera…")
        threading.Thread(target=self._hilo_descarga, args=(url_descarga,), daemon=True).start()

    def _hilo_descarga(self, url: str):
        import tempfile
        fd, temp_zip = tempfile.mkstemp(prefix="resintoniza_download_", suffix=".zip")
        os.close(fd)
        self._temp_zip = temp_zip

        def progreso(pct, descargado, total):
            wx.CallAfter(self._progreso_descarga, pct, descargado, total)

        try:
            actualizacion.descargar_actualizacion(url, temp_zip, callback_progreso=progreso, cancelar=self._cancelar)
            if self._cancelar.is_set():
                wx.CallAfter(self._descarga_cancelada)
            else:
                wx.CallAfter(self._descarga_completada, temp_zip)
        except Exception as error:
            try:
                os.remove(temp_zip)
            except OSError:
                pass
            wx.CallAfter(self._descarga_error, str(error))

    def _progreso_descarga(self, pct, descargado, total):
        self.progreso.SetValue(pct)
        mb_down = descargado / (1024 * 1024)
        mb_total = total / (1024 * 1024)
        self.estado_descarga.SetLabel(f"Descargando: {pct}% ({mb_down:.1f} MB de {mb_total:.1f} MB)...")
        if pct in (25, 50, 75):
            voz.decir(f"Descarga de la actualización al {pct} por ciento.")

    def _descarga_completada(self, temp_zip: str):
        self.progreso.SetValue(100)
        self.estado_descarga.SetLabel("¡Descarga completada! Preparando la instalación...")
        self._descargando = False
        self._actualizar_estado_botones()
        version_nueva = self.resultado.get("version", "nueva")
        mensaje = (
            f"La versión {version_nueva} se ha descargado correctamente.\n\n"
            "La aplicación se cerrará ahora para actualizar los archivos y se abrirá automáticamente al terminar.\n\n"
            "Tus canales, listas, grabaciones y configuraciones se conservarán intactos.\n"
            "Si ocurriera algún error durante la instalación, se restaurará automáticamente la versión actual."
        )
        voz.decir("Descarga completada con éxito. La aplicación se cerrará para aplicar la actualización.")
        wx.MessageBox(mensaje, f"Actualización lista - {NOMBRE_APP}", wx.OK | wx.ICON_INFORMATION, self)
        try:
            actualizacion.lanzar_instalador(temp_zip, ventana=self.ventana)
        except Exception as error:
            aviso(self, f"No se pudo iniciar el instalador:\n{error}\nLa versión actual sigue intacta.", icono=wx.ICON_ERROR)

    def _descarga_cancelada(self):
        self._descargando = False
        self.progreso.SetValue(0)
        self.estado_descarga.SetLabel("Descarga cancelada.")
        self._actualizar_estado_botones()
        voz.decir("Descarga cancelada.")

    def _descarga_error(self, error: str):
        self._descargando = False
        self.progreso.SetValue(0)
        self.estado_descarga.SetLabel("Error al descargar la actualización.")
        self._actualizar_estado_botones()
        voz.decir("Se ha producido un error durante la descarga de la actualización.")
        aviso(self, f"No se pudo descargar la nueva versión:\n{error}", icono=wx.ICON_ERROR)

    def cancelar_descarga(self):
        if self._descargando:
            self._cancelar.set()
            self.estado_descarga.SetLabel("Cancelando descarga...")

    def abrir(self):
        from .widgets import abrir_navegador

        if self.resultado.get("url"):
            abrir_navegador(self, self.resultado["url"])
        else:
            aviso(self, "Todavía no hay ninguna descarga que abrir. Comprueba primero si hay versión nueva.")


class DialogoTeclasGlobales(wx.Dialog):
    """Teclas que funcionan con la aplicación en segundo plano (interfaz invisible)."""

    def __init__(self, parent):
        super().__init__(parent, title="Teclas con la aplicación en segundo plano", size=(680, 460), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        from . import globales

        self.ventana = parent
        self.globales = globales
        self.datos = parent.datos
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=(
            "Estas teclas funcionan aunque estés en otro programa, siempre que la interfaz invisible esté activada en Ajustes.\n"
            "Deben llevar Ctrl o Alt. Si otra aplicación ya usa una, se avisa al activarlas.")), 0, wx.ALL, 10)
        self.lista = ListaAccesible(self, "Teclas en segundo plano. Intro cambia la tecla", "teclas", self.datos.windows)
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.cambiar())
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        fila = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Cambiar…", lambda e: self.cambiar()), boton(self, "&Restaurar todas", lambda e: self.restaurar()), wx.Button(self, wx.ID_CANCEL, "C&errar")):
            fila.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(fila, 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.rellenar()
        self.lista.ajustar_anchos()
        self.lista.SetFocus()

    def rellenar(self, conservar: str | None = None):
        from . import teclas as modulo_teclas

        mapa = self.globales.combinaciones(self.datos.windows)
        personalizadas = self.datos.windows.get("teclasGlobales") or {}
        filas = [{"accion": modulo_teclas.ETIQUETAS.get(a, a).replace("&", ""), "tecla": modulo_teclas.legible(c),
                  "estado": "personalizada" if a in personalizadas else "predeterminada", "_accion": a} for a, c in mapa.items()]
        indice = next((i for i, f in enumerate(filas) if f["_accion"] == conservar), 0)
        self.lista.rellenar(filas, indice)

    def cambiar(self):
        from .interfaz import DialogoCapturaTecla
        from . import teclas as modulo_teclas

        accion = (self.lista.valores_actuales() or {}).get("_accion")
        if not accion:
            return
        etiqueta = modulo_teclas.ETIQUETAS.get(accion, accion).replace("&", "")
        with DialogoCapturaTecla(self, etiqueta) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK or dialogo.combo is None:
                return
            combo = dialogo.combo
        if combo and not self.globales.valida(combo):
            aviso(self, "Una tecla que funciona en segundo plano debe llevar Ctrl o Alt.", icono=wx.ICON_WARNING)
            return
        guardadas = self.datos.windows.setdefault("teclasGlobales", {})
        if combo:
            guardadas[accion] = combo
        else:
            guardadas.pop(accion, None)
        self.datos.guardar()
        self.ventana.aplicar_teclas_globales()
        self.rellenar(accion)
        self.ventana.estado(f"{etiqueta}: {modulo_teclas.legible(combo)} en segundo plano.")

    def restaurar(self):
        self.datos.windows["teclasGlobales"] = {}
        self.datos.guardar()
        self.ventana.aplicar_teclas_globales()
        self.rellenar()
        self.ventana.estado("Teclas de segundo plano restauradas.")


class DialogoRegla(wx.Dialog):
    """Editor de una regla de grabación automática (lo que Tvheadend llama autorec)."""

    def __init__(self, parent, canales, regla: dict | None = None):
        super().__init__(parent, title="Regla de grabación", size=(700, 620), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.resultado: dict | None = None
        base = dict(regla or grabacion.regla_nueva())
        self.nombres = [""] + sorted({c.nombre for c in canales})
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=(
            "La aplicación mira la guía cada poco y programa sola lo que encaje con esta regla.\n"
            "Solo hace falta que esté abierta cuando llegue la hora de grabar.")), 0, wx.ALL, 12)
        rejilla = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        rejilla.AddGrowableCol(1, 1)

        def fila(etiqueta, crear):
            texto = wx.StaticText(self, label=etiqueta)
            control = crear()
            nombrar(control, etiqueta.replace("&", "").rstrip(":"))
            rejilla.Add(texto, 0, wx.ALIGN_CENTER_VERTICAL)
            rejilla.Add(control, 1, wx.EXPAND)
            return control

        self.texto = fila("&Texto que debe aparecer:", lambda: wx.TextCtrl(self, value=base["texto"], style=wx.TE_MULTILINE, size=(-1, 52)))
        self.campo = fila("&Dónde buscarlo:", lambda: wx.Choice(self, choices=list(grabacion.CAMPOS_REGLA.values())))
        self.campo.SetSelection(list(grabacion.CAMPOS_REGLA).index(base["campo"]))
        self.canal = fila("&Canal:", lambda: wx.Choice(self, choices=["Todos los canales"] + self.nombres[1:]))
        self.canal.SetSelection(self.nombres.index(base["canal"]) if base["canal"] in self.nombres else 0)
        self.favoritos = fila("Solo &favoritos:", lambda: wx.CheckBox(self, label="Buscarlo solo en los canales marcados como favoritos"))
        self.favoritos.SetValue(base["soloFavoritos"])
        self.repeticiones = fila("&Repeticiones:", lambda: wx.Choice(self, choices=list(grabacion.REPETICIONES.values())))
        self.repeticiones.SetSelection(list(grabacion.REPETICIONES).index(base["repeticiones"]))
        self.antes = fila("Empezar &antes (minutos):", lambda: wx.SpinCtrl(self, min=0, max=60, initial=base["antes"]))
        self.despues = fila("Terminar des&pués (minutos):", lambda: wx.SpinCtrl(self, min=0, max=60, initial=base["despues"]))
        self.dias = fila("Días de la &semana (ninguno: todos):", lambda: wx.CheckListBox(self, choices=[d.capitalize() for d in grabacion.DIAS_SEMANA]))
        for dia in base["dias"]:
            self.dias.Check(dia, True)
        self.desde = fila("Solo desde la &hora (HH:MM, vacío: sin límite):", lambda: wx.TextCtrl(self, value=base["desde"]))
        self.hasta = fila("Solo hasta la ho&ra (HH:MM, vacío: sin límite):", lambda: wx.TextCtrl(self, value=base["hasta"]))
        self.maximo = fila("&Máximo de grabaciones pendientes (0: sin tope):", lambda: wx.SpinCtrl(self, min=0, max=50, initial=base["maximo"]))
        self.activa = fila("Regla acti&va:", lambda: wx.CheckBox(self, label="Programar grabaciones con esta regla"))
        self.activa.SetValue(base["activa"])
        caja.Add(rejilla, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        botones = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindow(wx.ID_OK).SetLabel("&Guardar")
        self.FindWindow(wx.ID_CANCEL).SetLabel("&Cancelar")
        self.Bind(wx.EVT_BUTTON, self.guardar, id=wx.ID_OK)
        caja.Add(botones, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(caja)
        self.texto.SetFocus()

    def guardar(self, _evento):
        texto = self.texto.GetValue().strip()
        if not texto:
            aviso(self, "Escribe qué texto tiene que aparecer en el programa.", icono=wx.ICON_WARNING)
            self.texto.SetFocus()
            return
        desde, hasta = self.desde.GetValue().strip(), self.hasta.GetValue().strip()
        regla = {
            "texto": texto,
            "campo": list(grabacion.CAMPOS_REGLA)[max(0, self.campo.GetSelection())],
            "canal": self.nombres[self.canal.GetSelection()] if self.canal.GetSelection() > 0 else "",
            "tipo": "tv", "soloFavoritos": self.favoritos.GetValue(),
            "repeticiones": list(grabacion.REPETICIONES)[max(0, self.repeticiones.GetSelection())],
            "antes": self.antes.GetValue(), "despues": self.despues.GetValue(),
            "activa": self.activa.GetValue(), "dias": list(self.dias.GetCheckedItems()),
            "desde": desde, "hasta": hasta, "maximo": self.maximo.GetValue(),
        }
        limpias = grabacion.validar_reglas([regla])
        if not limpias:
            aviso(self, "Esa regla no es válida.", icono=wx.ICON_WARNING)
            return
        if (desde and not limpias[0]["desde"]) or (hasta and not limpias[0]["hasta"]):
            aviso(self, "Las horas se escriben como 21:30. Déjalas vacías si no quieres poner límite.", icono=wx.ICON_WARNING)
            self.desde.SetFocus()
            return
        self.resultado = limpias[0]
        self.EndModal(wx.ID_OK)


class DialogoReglas(wx.Dialog):
    """Reglas de grabación automática: graba siempre lo que lleve cierto título."""

    def __init__(self, parent):
        super().__init__(parent, title="Reglas de grabación automática", size=(900, 540), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        self.datos = parent.datos
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=(
            "Cada regla busca un texto en la guía y programa sola las grabaciones que encajen.\n"
            "Intro edita la regla, Suprimir la borra y Espacio la activa o la para.")), 0, wx.ALL, 10)
        self.lista = ListaAccesible(self, "Reglas de grabación. Intro edita, Suprimir borra, Espacio activa o para", "reglas", self.datos.windows)
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.editar())
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self.menu)
        self.lista.Bind(wx.EVT_KEY_DOWN, self.tecla)
        self.lista.Bind(wx.EVT_LIST_ITEM_FOCUSED, lambda e: (e.Skip(), self.mostrar()))
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        caja.Add(wx.StaticText(self, label="Detalle de la regla:"), 0, wx.LEFT | wx.TOP, 10)
        self.resumen = nombrar(wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 70)), "Detalle de la regla")
        caja.Add(self.resumen, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        fila = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Nueva regla…", lambda e: self.nueva()), boton(self, "&Editar…", lambda e: self.editar()),
                        boton(self, "&Borrar", lambda e: self.borrar()), boton(self, "&Aplicar ahora", lambda e: self.aplicar()),
                        wx.Button(self, wx.ID_CANCEL, "C&errar")):
            fila.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(fila, 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.rellenar()
        self.lista.ajustar_anchos()
        self.lista.SetFocus()

    def reglas(self) -> list[dict]:
        return self.datos.windows.setdefault("reglasGrabacion", [])

    def rellenar(self, seleccionar: int = 0):
        entradas = self.datos.windows.get("grabaciones") or []
        filas = []
        for regla in self.reglas():
            puestas = sum(1 for e in entradas if e.get("regla") == regla["texto"] and e.get("estado") == "pendiente")
            filas.append(fila_regla(regla, puestas))
        self.lista.rellenar(filas or [{"texto": "No hay ninguna regla todavía", "donde": "", "cuando": "",
                                       "repeticiones": "", "programadas": "", "estado": ""}], seleccionar)
        self.mostrar()

    def regla_actual(self):
        return (self.lista.valores_actuales() or {}).get("_regla")

    def mostrar(self):
        regla = self.regla_actual()
        self.resumen.SetValue(grabacion.texto_regla(regla) if regla else
                              "Con «Nueva regla» se graba siempre lo que lleve cierto título, por ejemplo «Telediario» en La 1.")

    def nueva(self):
        with DialogoRegla(self, self.ventana.canales) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK or dialogo.resultado is None:
                return
            self.reglas().append(dialogo.resultado)
        self.datos.guardar()
        self.ventana.aplicar_reglas(avisar=True)
        self.rellenar(len(self.reglas()) - 1)

    def editar(self):
        regla = self.regla_actual()
        if not regla:
            return
        indice = self.reglas().index(regla)
        with DialogoRegla(self, self.ventana.canales, regla) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK or dialogo.resultado is None:
                return
            self.reglas()[indice] = dialogo.resultado
        self.datos.guardar()
        self.ventana.aplicar_reglas(avisar=True)
        self.rellenar(indice)

    def borrar(self):
        regla = self.regla_actual()
        if not regla:
            return
        if not pregunta(self, f"¿Borrar la regla «{regla['texto']}»?\nLas grabaciones que ya haya programado se quedan como están."):
            return
        self.reglas().remove(regla)
        self.datos.guardar()
        self.rellenar()
        self.ventana.estado("Regla borrada.")

    def alternar(self):
        regla = self.regla_actual()
        if not regla:
            return
        regla["activa"] = not regla["activa"]
        self.datos.guardar()
        indice = self.reglas().index(regla)
        self.rellenar(indice)
        self.ventana.estado(f"Regla «{regla['texto']}» {'activada' if regla['activa'] else 'parada'}.")

    def aplicar(self):
        puestas = self.ventana.aplicar_reglas(avisar=True)
        self.rellenar()
        if not puestas:
            aviso(self, "No hay ningún programa nuevo en la guía que encaje con las reglas.")

    def tecla(self, evento):
        if evento.GetKeyCode() == wx.WXK_DELETE:
            self.borrar()
        elif evento.GetKeyCode() == wx.WXK_SPACE:
            self.alternar()
        else:
            evento.Skip()

    def menu(self, evento):
        fila = self.lista.menu_contextual_en_fila(evento)
        regla = self.regla_actual()
        menu_desde(self, [
            ("&Editar\tIntro", self.editar if regla else None),
            ("&Parar esta regla\tEspacio" if regla and regla["activa"] else "&Activar esta regla\tEspacio", self.alternar if regla else None),
            ("&Aplicar las reglas ahora", self.aplicar),
            None,
            ("&Borrar\tSupr", self.borrar if regla else None),
        ], self.lista, fila)


class DialogoComprobar(wx.Dialog):
    """Comprueba en segundo plano qué canales responden y cuáles están caídos."""

    def __init__(self, parent, canales, titulo: str = "Comprobar canales"):
        super().__init__(parent, title=titulo, size=(900, 580), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        self.datos = parent.datos
        self.canales = canales
        self.resultados: list[dict] = []
        self.cancelar_evento = threading.Event()
        self.trabajando = False
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=(
            f"Se van a comprobar {len(canales)} canales pidiendo unos kilobytes de cada emisión: no se reproduce nada\n"
            "y no molesta a lo que estés escuchando. Las emisiones de YouTube, Twitch o web hay que abrirlas para saberlo.")), 0, wx.ALL, 10)
        self.progreso = nombrar(wx.Gauge(self, range=max(1, len(canales))), "Progreso de la comprobación")
        caja.Add(self.progreso, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.mensaje = nombrar(wx.TextCtrl(self, value="Pulsa «Comprobar» para empezar.", style=wx.TE_READONLY), "Estado de la comprobación")
        caja.Add(self.mensaje, 0, wx.EXPAND | wx.ALL, 10)
        self.lista = ListaAccesible(self, "Resultado de la comprobación", "comprobacion", self.datos.windows)
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self.menu)
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        fila = wx.WrapSizer(wx.HORIZONTAL)
        self.boton_comprobar = boton(self, "&Comprobar", lambda e: self.comprobar())
        self.boton_ocultar = boton(self, "&Ocultar los que no responden", lambda e: self.ocultar_caidos())
        self.boton_ocultar.Disable()
        for control in (self.boton_comprobar, self.boton_ocultar, boton(self, "Copiar el &informe", lambda e: self.copiar()),
                        wx.Button(self, wx.ID_CANCEL, "C&errar")):
            fila.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(fila, 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.Bind(wx.EVT_CLOSE, self.al_cerrar)
        self.boton_comprobar.SetFocus()

    def comprobar(self):
        if self.trabajando:
            self.cancelar_evento.set()
            self.mensaje.SetValue("Deteniendo la comprobación…")
            return
        self.trabajando = True
        self.resultados = []
        self.cancelar_evento.clear()
        self.boton_comprobar.SetLabel("&Detener")
        self.mensaje.SetValue("Comprobando…")
        voz.decir(f"Comprobando {len(self.canales)} canales")
        threading.Thread(target=self._trabajo, daemon=True).start()

    def _trabajo(self):
        resultados = comprobador.comprobar(
            self.canales, progreso=lambda hechos, total, resultado: wx.CallAfter(self._paso, hechos, total, resultado),
            cancelar=self.cancelar_evento)
        wx.CallAfter(self._terminado, resultados)

    def _paso(self, hechos, total, resultado):
        if self.cancelar_evento.is_set() and not self.trabajando:
            return
        self.progreso.SetValue(min(hechos, total))
        self.mensaje.SetValue(f"Comprobados {hechos} de {total}: {resultado['canal']} · {comprobador.ESTADOS.get(resultado['estado'], '')}")

    def _terminado(self, resultados):
        self.trabajando = False
        self.resultados = resultados
        self.boton_comprobar.SetLabel("&Comprobar otra vez")
        self.lista.rellenar([fila_comprobacion(r) for r in resultados] or [{"nombre": "Sin resultados", "estado": "", "detalle": ""}])
        self.lista.ajustar_anchos()
        texto = comprobador.resumen(resultados)
        self.mensaje.SetValue(texto)
        self.boton_ocultar.Enable(any(r["estado"] == "error" for r in resultados))
        voz.decir(texto)
        self.lista.SetFocus()

    def caidos(self) -> list[dict]:
        return [r for r in self.resultados if r["estado"] == "error"]

    def ocultar_caidos(self):
        caidos = self.caidos()
        if not caidos:
            return
        if not pregunta(self, f"¿Ocultar los {len(caidos)} canales que no responden?\nSe pueden volver a mostrar con su tecla o desde Ajustes."):
            return
        for resultado in caidos:
            self.datos.fijar_estado_canal(resultado["tipo"], resultado["canal"], hide=True)
        self.datos.guardar()
        for panel in self.ventana.paneles.values():
            panel.refrescar()
        self.ventana.estado(f"{len(caidos)} canales que no responden se han ocultado.")
        self.boton_ocultar.Disable()

    def copiar(self):
        if not self.resultados:
            return
        lineas = [comprobador.resumen(self.resultados)] + [
            f"{r['canal']}: {comprobador.ESTADOS.get(r['estado'], '')} · {r['detalle']}" for r in self.resultados]
        copiar_portapapeles("\n".join(lineas))
        self.ventana.estado("Informe de la comprobación copiado al portapapeles.")

    def menu(self, evento):
        fila = self.lista.menu_contextual_en_fila(evento)
        resultado = (self.lista.valores_actuales() or {}).get("_resultado")
        menu_desde(self, [
            ("&Ocultar los que no responden", self.ocultar_caidos if self.caidos() else None),
            ("&Copiar el informe", self.copiar if self.resultados else None),
            ("Copiar el &detalle de este canal", (lambda: copiar_portapapeles(f"{resultado['canal']}: {resultado['detalle']}")) if resultado else None),
        ], self.lista, fila)

    def al_cerrar(self, evento):
        self.cancelar_evento.set()
        evento.Skip()


class DialogoAhora(wx.Dialog):
    """Lo que empieza dentro de poco, para grabarlo o ponerle un recordatorio de un tirón."""

    MINUTOS = [15, 30, 60, 120, 180]

    def __init__(self, parent):
        super().__init__(parent, title="Qué empieza ahora", size=(920, 580), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        self.datos = parent.datos
        self.resultados: list[tuple] = []
        caja = wx.BoxSizer(wx.VERTICAL)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.minutos = campo(self, fila, "Programas que empiezan en los pró&ximos:", lambda: wx.Choice(self, choices=[f"{m} minutos" for m in self.MINUTOS]), 0, expandir=False)
        self.minutos.SetSelection(2)
        self.minutos.Bind(wx.EVT_CHOICE, lambda e: self.rellenar())
        self.solo_favoritos = nombrar(wx.CheckBox(self, label="Solo en mis &favoritos"), "Solo en mis favoritos")
        self.solo_favoritos.SetValue(True)
        self.solo_favoritos.Bind(wx.EVT_CHECKBOX, lambda e: self.rellenar())
        fila.Add(self.solo_favoritos, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        caja.Add(fila, 0, wx.EXPAND | wx.ALL, 10)
        self.cuenta = wx.StaticText(self, label="")
        caja.Add(self.cuenta, 0, wx.LEFT | wx.RIGHT, 10)
        self.lista = ListaAccesible(self, "Programas que empiezan pronto. Intro abre las opciones", "busqueda_guia", self.datos.windows)
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.menu(e))
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self.menu)
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        botones = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Ver el canal", lambda e: self.ver()), boton(self, "&Grabar…", lambda e: self.grabar()),
                        boton(self, "&Recordatorio…", lambda e: self.recordatorio()), boton(self, "Crear re&gla…", lambda e: self.regla()),
                        wx.Button(self, wx.ID_CANCEL, "C&errar")):
            botones.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(botones, 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.rellenar()
        self.lista.ajustar_anchos()
        self.lista.SetFocus()

    def rellenar(self):
        minutos = self.MINUTOS[max(0, self.minutos.GetSelection())]
        self.resultados = self.ventana.programas_proximos(minutos, self.solo_favoritos.GetValue())
        filas = []
        for canal, programa in self.resultados:
            valores = fila_programa(programa, canal)
            filas.append(valores)
        self.lista.rellenar(filas or [{"titulo": "No empieza nada en ese rato", "hora": "", "canal": "", "estado": ""}])
        cuantos = len(self.resultados)
        texto = (f"{cuantos} programa" + ("s" if cuantos != 1 else "") + f" en los próximos {minutos} minutos.") if cuantos else \
            f"No empieza ningún programa en los próximos {minutos} minutos."
        self.cuenta.SetLabel(texto)
        voz.decir(texto, interrumpir=True)

    def actual(self):
        valores = self.lista.valores_actuales() or {}
        return valores.get("_canal"), valores.get("_programa")

    def ver(self):
        canal, _programa = self.actual()
        if canal is None:
            return
        self.EndModal(wx.ID_OK)
        self.ventana.reproducir_canal(canal)

    def grabar(self):
        canal, programa = self.actual()
        if canal is None:
            return
        self.ventana.programar_grabacion(canal, programa, self)
        self.rellenar()

    def recordatorio(self):
        canal, programa = self.actual()
        if canal is None:
            return
        self.ventana.crear_recordatorio(canal, programa, self)

    def regla(self):
        canal, programa = self.actual()
        if canal is None:
            return
        self.EndModal(wx.ID_OK)
        self.ventana.regla_desde_programa(canal, programa)

    def menu(self, evento):
        fila = self.lista.menu_contextual_en_fila(evento)
        canal, _programa = self.actual()
        menu_desde(self, [
            ("&Ver el canal", self.ver if canal else None),
            ("&Grabar este programa…", self.grabar if canal else None),
            ("&Recordatorio…", self.recordatorio if canal else None),
            ("Crear una re&gla con este título…", self.regla if canal else None),
        ], self.lista, fila)


class DialogoRecorte(wx.Dialog):
    """Elegir por dónde cortar una grabación (minutos y segundos)."""

    def __init__(self, parent, nombre: str, duracion: float):
        super().__init__(parent, title="Recortar la grabación", size=(620, 340))
        self.duracion = duracion
        self.inicio = 0.0
        self.fin = duracion
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=(
            f"{nombre}\nDura {grabacion.duracion_hablada(duracion)}.\n\n"
            "Se copia el trozo elegido a un archivo nuevo, sin recodificar y sin tocar el original.\n"
            "El corte cae en el paquete más cercano, así que puede bailar un segundo.")), 0, wx.ALL, 12)
        rejilla = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        rejilla.AddGrowableCol(1, 1)

        def fila(etiqueta, valor):
            texto = wx.StaticText(self, label=etiqueta)
            control = nombrar(wx.TextCtrl(self, value=valor), etiqueta.replace("&", "").rstrip(":"))
            rejilla.Add(texto, 0, wx.ALIGN_CENTER_VERTICAL)
            rejilla.Add(control, 1, wx.EXPAND)
            return control

        self.campo_inicio = fila("Empezar en (&minutos:segundos):", "0:00")
        self.campo_fin = fila("Terminar en (m&inutos:segundos):", self.formato(duracion))
        caja.Add(rejilla, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        botones = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindow(wx.ID_OK).SetLabel("&Recortar")
        self.FindWindow(wx.ID_CANCEL).SetLabel("&Cancelar")
        self.Bind(wx.EVT_BUTTON, self.aceptar, id=wx.ID_OK)
        caja.Add(botones, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(caja)
        self.campo_inicio.SetFocus()

    @staticmethod
    def formato(segundos: float) -> str:
        return f"{int(segundos // 60)}:{int(segundos % 60):02d}"

    @staticmethod
    def leer(texto: str) -> float | None:
        texto = (texto or "").strip().replace(",", ":").replace(".", ":")
        if not texto:
            return None
        partes = texto.split(":")
        try:
            numeros = [int(p) for p in partes]
        except ValueError:
            return None
        if len(numeros) == 1:
            return float(numeros[0])
        if len(numeros) == 2:
            return numeros[0] * 60 + numeros[1]
        if len(numeros) == 3:
            return numeros[0] * 3600 + numeros[1] * 60 + numeros[2]
        return None

    def aceptar(self, _evento):
        inicio, fin = self.leer(self.campo_inicio.GetValue()), self.leer(self.campo_fin.GetValue())
        if inicio is None or fin is None:
            aviso(self, "Escribe los tiempos como minutos:segundos, por ejemplo 2:30.", icono=wx.ICON_WARNING)
            return
        if fin <= inicio:
            aviso(self, "El final tiene que ir después del principio.", icono=wx.ICON_WARNING)
            return
        if fin > self.duracion + 1:
            aviso(self, f"La grabación solo dura {self.formato(self.duracion)}.", icono=wx.ICON_WARNING)
            return
        self.inicio, self.fin = inicio, min(fin, self.duracion)
        self.EndModal(wx.ID_OK)
