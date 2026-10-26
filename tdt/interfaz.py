"""Interfaz wxPython en español, pensada para teclado y lectores de pantalla.

Estructura: una ventana con pestañas Televisión, Radio, Guía e Información
(como la navegación del APK) y, a la derecha, el reproductor compartido.
Las listas son ``ListaAccesible`` (columnas configurables mediante plantillas
de lectura, navegación por celdas con voz) y todos los elementos tienen menú
contextual (tecla Aplicaciones o Mayús+F10). Cada acción está también en el
menú principal con su atajo de teclado.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

import wx
import wx.adv

from . import AUTOR, LEMA, NOMBRE_APP, VERSION
from . import accesible, actualizacion, casting, catalogo, catchup, datos as modulo_datos, dialogos, extractor
from . import globales, grabacion, m3u, mosaico, navegador, organizar, plantillas, proveedores, respaldo, sonidos
from . import tareas, teclas as modulo_teclas, voz, xtream
from .servidor import servidor
from .accesible import ListaAccesible
from .catalogo import NOMBRE_LISTA_OFICIAL, NOMBRE_TIPO, URL_GUIAS, URL_LISTAS, Canal, Emision, Programa
from .reproductor import BUFERES, CALIDADES, VELOCIDADES, Reproductor, libmpv_en_memoria, version_libmpv_cargada
from .widgets import (BUSCADORES, DIAS, abrir_navegador, aviso, boton, campo, configurar_notebook_accesible, copiar_portapapeles, dialogo_html,
                      dialogo_texto, fila_canal, fila_emision, fila_lista, fila_programa, fila_recordatorio,
                      fila_vod, markdown_a_html, menu_desde, nombrar, pregunta, tabla_html, texto_detalle_programa)

registro = logging.getLogger(__name__)
TIPOS = ("tv", "radio")
OPCIONES_TEMPORIZADOR = [("Desactivado", 0), ("5 minutos", 5), ("10 minutos", 10), ("15 minutos", 15), ("30 minutos", 30), ("45 minutos", 45), ("1 hora", 60), ("2 horas", 120), ("3 horas", 180), ("4 horas", 240)]
SUBTITULOS = [("Desactivados", "off"), ("Español", "es"), ("Inglés", "en"), ("Catalán", "ca"), ("Gallego", "gl"), ("Euskera", "eu")]
TEMAS = [("Según el sistema", "2"), ("Oscuro", "1"), ("Claro", "0")]
OCULTOS = [("Mostrar los canales ocultos al final", 0), ("No mostrar los canales ocultos", 1), ("Mostrar solo los canales ocultos", 2)]
AL_CERRAR = [("Preguntar cada vez", "0"), ("Cerrar y detener la reproducción", "1"), ("Seguir reproduciendo en la bandeja del sistema", "2")]
MODOS_IMAGEN = [("Ajustar (imagen completa)", "ajustar"), ("Llenar (estirar)", "llenar"), ("Zoom (recortar bordes)", "zoom")]
FRECUENCIAS = [("No actualizar: usar las listas guardadas", "nunca"), ("Actualizar cada vez que se abre", "siempre"), ("Actualizar una vez al día", "diaria"), ("Actualizar una vez a la semana", "semanal")]
TEXTO_FRECUENCIA = {clave: nombre for nombre, clave in FRECUENCIAS}
MINUTOS_RECORDATORIO = [1, 5, 10, 15, 30, 60]
MODOS_GRABACION = [
    ("En segundo plano: no ocupa el reproductor", True),
    ("Con el reproductor: sintoniza el canal y graba lo que suena", False),
]
FORMATOS_GRABACION_TV = [
    ("MPEG-TS (.ts, formato original)", "ts"),
    ("MP4 (.mp4, mayor compatibilidad)", "mp4"),
]
UNA_SEMANA = 7 * 24 * 3600
RETROCESO = 30  # segundos que retrocede la pausa del directo
ESPERAS_REINTENTO = (3, 8, 20)  # segundos entre reintentos cuando se corta la emisión


def _etiqueta_grabar(ventana, canal) -> str:
    """Texto del menú contextual: depende del modo y de si ese canal ya se graba."""
    gestor = ventana.grabaciones_fondo
    if gestor is not None and gestor.activa(ventana.clave_manual(canal)):
        return "Dejar de &grabar este canal"
    return "&Grabar este canal en segundo plano" if ventana.modo_fondo() else "&Grabar este canal"


# --- diálogos ---------------------------------------------------------------
class DialogoDescarga(wx.Dialog):
    """Descarga libmpv en un hilo mostrando el progreso."""

    def __init__(self, parent, datos, en_uso: bool = False):
        super().__init__(parent, title="Reproductor libmpv", size=(560, 220))
        self.datos = datos
        self.en_uso = en_uso
        self.error = ""
        self.resultado = None
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label="Se va a descargar la última versión de libmpv (unos 31 MB) en la carpeta data/mpv." + ("\nComo el reproductor está cargado, se instalará al reiniciar la aplicación." if en_uso else "")), 0, wx.ALL, 12)
        self.mensaje = nombrar(wx.TextCtrl(self, value="Preparando…", style=wx.TE_READONLY), "Progreso de la descarga")
        caja.Add(self.mensaje, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.barra = nombrar(wx.Gauge(self, range=100), "Barra de progreso")
        caja.Add(self.barra, 0, wx.EXPAND | wx.ALL, 12)
        self.cerrar = wx.Button(self, wx.ID_CANCEL, "&Cerrar")
        self.cerrar.Disable()
        caja.Add(self.cerrar, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(caja)
        threading.Thread(target=self._trabajo, daemon=True).start()

    def _trabajo(self):
        try:
            self.resultado = modulo_datos.descargar_libmpv(self.datos, progreso=lambda m, f: wx.CallAfter(self._progreso, m, f), en_uso=self.en_uso)
        except Exception as error:
            registro.exception("Error descargando libmpv")
            self.error = str(error)
        wx.CallAfter(self._terminado)

    def _progreso(self, mensaje, fraccion):
        self.mensaje.SetValue(mensaje)
        voz.decir(mensaje, interrumpir=True)
        if fraccion is not None:
            self.barra.SetValue(int(fraccion * 100))

    def _terminado(self):
        if self.error:
            self.mensaje.SetValue("Error: " + self.error)
            voz.decir("Error: " + self.error)
            self.cerrar.Enable()
            self.cerrar.SetFocus()
        else:
            self.EndModal(wx.ID_OK)


class DialogoAjustes(wx.Dialog):
    def __init__(self, parent, datos):
        super().__init__(parent, title="Ajustes", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.datos = datos
        usuario, windows, acc = datos.usuario, datos.windows, datos.windows["accesibilidad"]
        caja = wx.BoxSizer(wx.VERTICAL)
        self.libro = configurar_notebook_accesible(wx.Notebook(self), "Secciones de ajustes")
        caja.Add(self.libro, 1, wx.EXPAND | wx.ALL, 10)

        def pagina(titulo):
            panel = wx.Panel(self.libro)
            rejilla = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
            rejilla.AddGrowableCol(1, 1)
            panel.SetSizer(rejilla)
            self.libro.AddPage(panel, titulo)
            return panel, rejilla

        def fila(panel, rejilla, etiqueta, crear):
            texto = wx.StaticText(panel, label=etiqueta)
            control = crear()
            nombrar(control, etiqueta.replace("&", "").rstrip(":"))
            rejilla.Add(texto, 0, wx.ALIGN_CENTER_VERTICAL)
            rejilla.Add(control, 1, wx.EXPAND)
            return control

        def eleccion(panel, opciones, valor):
            control = wx.Choice(panel, choices=[o[0] for o in opciones])
            valores = [o[1] for o in opciones]
            control.SetSelection(valores.index(valor) if valor in valores else 0)
            return control

        def casilla(panel, rejilla, etiqueta, texto, valor):
            control = fila(panel, rejilla, etiqueta, lambda: wx.CheckBox(panel, label=texto))
            control.SetValue(bool(valor))
            return control

        general, rejilla = pagina("General")
        self.tema = fila(general, rejilla, "&Tema:", lambda: eleccion(general, TEMAS, usuario["darkMode"]))
        self.contraste = casilla(general, rejilla, "Alto &contraste:", "Fondo negro y texto en amarillo", windows["altoContraste"])
        self.letra = fila(general, rejilla, "Tamaño de &letra (8 a 28):", lambda: wx.SpinCtrl(general, min=8, max=28, initial=windows["tamanoLetra"]))
        self.ocultos = fila(general, rejilla, "Canales &ocultos:", lambda: eleccion(general, OCULTOS, usuario["hiddenChannelsVisibility"]))
        self.cerrar = fila(general, rejilla, "Al cerrar la &ventana:", lambda: eleccion(general, AL_CERRAR, usuario["closeOnExit"]))
        self.minimizar_bandeja = casilla(general, rejilla, "&Minimizar a la bandeja:", "Ocultar la ventana en la bandeja del sistema al minimizar (en vez de a la barra de tareas)", windows.get("minimizarABandeja", False))
        self.iniciar_minimizado = casilla(general, rejilla, "Iniciar &minimizado:", "Arrancar la aplicación minimizada (o en la bandeja si está activa)", windows.get("iniciarMinimizado", False))
        self.iniciar_windows = casilla(general, rejilla, "Iniciar con &Windows:", "Arrancar automáticamente al iniciar sesión en el equipo", windows.get("iniciarConWindows", False))
        self.actualizar = fila(general, rejilla, "Al &iniciar:", lambda: eleccion(general, FRECUENCIAS, windows["frecuenciaActualizacion"]))
        self.guia_extra = casilla(general, rejilla, "&Guía ampliada:", "Añadir una guía adicional para los canales sin programación (Antena 3, autonómicas…)", windows["guiaExtra"])
        self.comprobar_mpv = casilla(general, rejilla, "Reproductor lib&mpv:", "Buscar versiones nuevas al iniciar (una vez por semana)", windows["comprobarMpv"])

        reproductor, rejilla = pagina("Reproductor")
        self.subtitulos = fila(reproductor, rejilla, "&Subtítulos preferidos:", lambda: eleccion(reproductor, SUBTITULOS, usuario["playerSubtitle"]))
        self.imagen = fila(reproductor, rejilla, "Tamaño de la &imagen:", lambda: eleccion(reproductor, MODOS_IMAGEN, windows["modoImagen"]))
        self.calidad = fila(reproductor, rejilla, "&Calidad de las emisiones:", lambda: eleccion(reproductor, CALIDADES, windows["calidad"]))
        self.buffer = fila(reproductor, rejilla, "&Búfer de recepción:", lambda: eleccion(reproductor, BUFERES, windows["bufferRecepcion"]))
        self.mostrar_video = casilla(reproductor, rejilla, "Ventana de &vídeo:", "Abrirla sola cuando la emisión trae imagen (si no, se abre con su tecla)", windows["mostrarVideo"])
        self.solo_audio = casilla(reproductor, rejilla, "Modo solo a&udio:", "No descargar el vídeo: ahorra datos y proceso", windows["soloAudio"])
        self.audiodescripcion = casilla(reproductor, rejilla, "Audio&descripción:", "Preferir la pista de audiodescripción cuando la emisión la traiga", windows["audiodescripcion"])
        self.nivelador = casilla(reproductor, rejilla, "&Nivelar el volumen:", "Igualar el volumen entre canales, para que cambiar de emisora no dé saltos", windows.get("nivelarVolumen", False))
        self.timeshift = fila(reproductor, rejilla, "&Pausa del directo (minutos guardados, 0 desactiva):", lambda: wx.SpinCtrl(reproductor, min=0, max=60, initial=windows["timeshiftMinutos"]))
        self.reintentos = casilla(reproductor, rejilla, "&Reintentos:", "Volver a intentarlo automáticamente si se corta la emisión", windows["reintentos"])
        self.alternativa = casilla(reproductor, rejilla, "Emisión &alternativa:", "Si una emisión falla, probar la siguiente del mismo canal", windows["emisionAlternativa"])
        disponible = navegador.motor_disponible()
        self.web_en_app = casilla(reproductor, rejilla, "Canales &web en la app:", "Abrir las webs de las emisoras en el navegador integrado (Edge)" + ("" if disponible else " — no disponible en este equipo"), usuario["browserEmbedWeb"])
        self.youtube_en_app = casilla(reproductor, rejilla, "&YouTube en la app:", "Abrir YouTube y Twitch en el navegador integrado" + ("" if disponible else " — no disponible en este equipo"), usuario["browserEmbedYoutube"])

        grabaciones, rejilla = pagina("Grabación")
        carpeta_actual = windows["carpetaGrabaciones"] or str(datos.raiz / "grabaciones")
        self.carpeta_grabaciones = fila(grabaciones, rejilla, "Carpeta de &grabaciones:", lambda: wx.TextCtrl(grabaciones, value=carpeta_actual))
        rejilla.Add(wx.StaticText(grabaciones, label=""), 0)
        rejilla.Add(boton(grabaciones, "&Examinar…", lambda e: self.elegir_carpeta()), 0)
        self.modo_grabacion = fila(grabaciones, rejilla, "&Cómo grabar:", lambda: eleccion(grabaciones, MODOS_GRABACION, bool(windows.get("grabacionSegundoPlano", True))))
        self.maximo_fondo = fila(grabaciones, rejilla, "Grabaciones a la ve&z en segundo plano (1 a 8):", lambda: wx.SpinCtrl(grabaciones, min=1, max=8, initial=int(windows.get("maximoGrabacionesFondo", 3))))
        rejilla.Add(wx.StaticText(grabaciones, label="En segundo plano se abre un reproductor aparte, sin imagen ni sonido: puedes escuchar un canal mientras se graban otros,\ny pausar, cambiar de canal o detener no afecta a lo que se está grabando. Cada grabación descarga su propia emisión."), 0, wx.TOP, 8)
        rejilla.Add((0, 0))
        rejilla.Add(wx.StaticText(grabaciones, label="Con el reproductor se graba lo mismo que estás viendo, sin descargarlo dos veces, pero el reproductor queda ocupado."), 0)
        rejilla.Add((0, 0))
        self.formato_grabacion = fila(grabaciones, rejilla, "Formato de grabación de &TV:", lambda: eleccion(grabaciones, FORMATOS_GRABACION_TV, windows.get("formatoGrabacionTV", "ts")))
        rejilla.Add(wx.StaticText(grabaciones, label="En emisiones HLS/MPEG-TS puedes elegir .ts (original de la emisión) o .mp4 (mayor compatibilidad con otros dispositivos).\nEn el resto de formatos no HLS se usa Matroska (.mkv). No se recodifica nada."), 0)
        rejilla.Add((0, 0))
        self.solo_audio_grabacion = casilla(grabaciones, rejilla, "Grabar solo el a&udio:", "Sin imagen: ocupa una décima parte (medido: 2 megabytes por minuto en vez de 22)", windows.get("grabarSoloAudio", False))
        self.margen_antes = fila(grabaciones, rejilla, "Empezar &antes de la hora (minutos):", lambda: wx.SpinCtrl(grabaciones, min=0, max=60, initial=int(windows.get("margenAntes", 0))))
        self.margen_despues = fila(grabaciones, rejilla, "Seguir grabando des&pués (minutos):", lambda: wx.SpinCtrl(grabaciones, min=0, max=60, initial=int(windows.get("margenDespues", 2))))
        rejilla.Add(wx.StaticText(grabaciones, label="Cada canal puede tener su propio margen (los que siempre empiezan tarde):"), 0, wx.TOP, 8)
        rejilla.Add(boton(grabaciones, "&Márgenes por canal…", lambda e: self.margenes_canal()), 0, wx.TOP, 8)
        self.carpeta_por_programa = casilla(grabaciones, rejilla, "Carpeta por pro&grama:", "Guardar cada programa en su propia subcarpeta", windows.get("carpetaPorPrograma", False))
        self.minimo_libre = fila(grabaciones, rejilla, "Espacio &libre mínimo para grabar (gigabytes):", lambda: wx.SpinCtrl(grabaciones, min=0, max=500, initial=int(windows.get("minimoLibreGB", 2))))
        rejilla.Add(wx.StaticText(grabaciones, label="Si el disco baja de ese límite, las grabaciones se paran solas y se avisa. Un directo en alta definición ocupa unos 22 megabytes por minuto."), 0)
        rejilla.Add((0, 0))
        self.retencion_dias = fila(grabaciones, rejilla, "Borrar las grabaciones de más de (&días, 0 no borra):", lambda: wx.SpinCtrl(grabaciones, min=0, max=3650, initial=int(windows.get("retencionDias", 0))))
        self.retencion_programa = fila(grabaciones, rejilla, "Dejar solo las últimas de cada pr&ograma (0 no borra):", lambda: wx.SpinCtrl(grabaciones, min=0, max=100, initial=int(windows.get("retencionPorPrograma", 0))))
        self.retencion_gigas = fila(grabaciones, rejilla, "No pasar de (giga&bytes en la carpeta, 0 sin tope):", lambda: wx.SpinCtrl(grabaciones, min=0, max=100000, initial=int(windows.get("retencionGigas", 0))))
        rejilla.Add(wx.StaticText(grabaciones, label="La limpieza no toca las grabaciones marcadas como protegidas (menú contextual en la lista de grabaciones)."), 0)
        rejilla.Add((0, 0))
        self.al_terminar = fila(grabaciones, rejilla, "Al &terminar la última grabación:", lambda: eleccion(grabaciones, [(t, c) for c, t in tareas.ACCIONES_FINAL.items()], windows.get("alTerminarGrabacion", "nada")))
        self.tarea_windows = casilla(grabaciones, rejilla, "Abrir con &Windows:", "Crear tareas en el Programador de Windows para abrir la aplicación (y despertar el equipo) antes de cada grabación", windows.get("tareaWindows", False))
        self.orden_posterior = fila(grabaciones, rejilla, "Orden al terminar una grabación (%f es el archi&vo):", lambda: wx.TextCtrl(grabaciones, value=windows.get("ordenPosterior", "")))
        rejilla.Add(wx.StaticText(grabaciones, label="Se deja vacío si no quieres nada. Sirve para convertir, mover o avisar; se lanza y no se espera a que termine."), 0)
        rejilla.Add(boton(grabaciones, "&Reglas de grabación automática…", lambda e: parent.ejecutar("herr_reglas")), 0, wx.TOP, 8)

        organizacion, rejilla = pagina("Organización")
        self.duplicados = casilla(organizacion, rejilla, "Canales &duplicados:", "Al mezclar varias listas, mostrar solo la primera aparición de cada canal", windows["quitarDuplicados"])
        self.numeracion = casilla(organizacion, rejilla, "&Números de canal:", "Teclear cifras en la lista salta a ese número, como en un mando", windows["numeroCanal"])
        rejilla.Add(wx.StaticText(organizacion, label="Control parental:"), 0, wx.TOP, 8)
        rejilla.Add(boton(organizacion, "Bloqueo por &PIN…", lambda e: parent.ejecutar("herr_pin")), 0, wx.TOP, 8)
        rejilla.Add(wx.StaticText(organizacion, label="Cuentas de proveedor:"), 0, wx.TOP, 8)
        rejilla.Add(boton(organizacion, "&Cuentas Xtream Codes…", lambda e: parent.ejecutar("herr_cuentas")), 0, wx.TOP, 8)
        rejilla.Add(wx.StaticText(organizacion, label="Perfiles y copias:"), 0, wx.TOP, 8)
        rejilla.Add(boton(organizacion, "Perfiles de &uso…", lambda e: parent.ejecutar("herr_perfiles")), 0, wx.TOP, 8)
        self.carpeta_nube = fila(organizacion, rejilla, "Carpeta para &sincronizar (OneDrive, Dropbox…):", lambda: wx.TextCtrl(organizacion, value=windows.get("carpetaSincronizacion", "")))
        rejilla.Add(wx.StaticText(organizacion, label="Con una carpeta de la nube se pueden llevar los ajustes y los favoritos a otro equipo."), 0, wx.TOP, 8)
        rejilla.Add(boton(organizacion, "E&xaminar…", lambda e: self.elegir_carpeta_nube()), 0, wx.TOP, 8)

        accesibilidad, rejilla = pagina("Accesibilidad")
        self.voz = casilla(accesibilidad, rejilla, "&Voz directa:", "Enviar avisos al lector de pantalla (NVDA, JAWS, SAPI)", acc["voz"])
        self.braille = casilla(accesibilidad, rejilla, "&Braille:", "Enviar también los avisos a la línea braille", acc["braille"])
        self.retardo = fila(accesibilidad, rejilla, "&Retardo de la voz en milisegundos (0 a 600):", lambda: wx.SpinCtrl(accesibilidad, min=0, max=600, initial=acc["retardoVoz"]))
        self.anunciar_estado = casilla(accesibilidad, rejilla, "&Estado de la reproducción:", "Decir «Reproduciendo», «En pausa», errores…", acc["anunciarEstado"])
        self.anunciar_avisos = casilla(accesibilidad, rejilla, "&Avisos:", "Decir los mensajes de la barra de estado (favoritos, volumen…)", acc["anunciarAvisos"])
        rejilla.Add(wx.StaticText(accesibilidad, label="Al moverte por las columnas de las listas (flechas izquierda y derecha, o Ctrl+1 a 9):"), 0, wx.TOP, 8)
        rejilla.Add((0, 0))
        self.decir_fila = casilla(accesibilidad, rejilla, "Número de &fila:", "Decir el número de fila («Fila 3»)", acc["decirFila"])
        self.decir_columna = casilla(accesibilidad, rejilla, "Nombre de la &columna:", "Decir el nombre de la columna («Canal», «Ahora»…)", acc["decirColumna"])
        self.decir_celda = casilla(accesibilidad, rejilla, "Contenido de la cel&da:", "Decir el contenido de la celda", acc["decirCelda"])
        rejilla.Add(wx.StaticText(accesibilidad, label="Qué columnas tiene cada lista y en qué orden se leen:"), 0, wx.TOP, 8)
        rejilla.Add(boton(accesibilidad, "Editor de &plantillas de lectura…", lambda e: self.editar_plantillas()), 0, wx.TOP, 8)
        self.anunciar_programa = casilla(accesibilidad, rejilla, "Al sintonizar:", "Decir qué están dando ahora en el canal", windows["anunciarPrograma"])
        self.sonidos = casilla(accesibilidad, rejilla, "&Sonidos:", "Avisar con un pitido al empezar, al parar, al fallar la emisión y al grabar", windows["sonidos"])
        self.aviso_grabacion = fila(accesibilidad, rejilla, "Decir cada cuántos minutos qué se está gra&bando (0 nunca):", lambda: wx.SpinCtrl(accesibilidad, min=0, max=120, initial=int(windows.get("avisoGrabacionMinutos", 0))))
        rejilla.Add(wx.StaticText(accesibilidad, label="Qué sonidos suenan:"), 0, wx.TOP, 8)
        rejilla.Add(boton(accesibilidad, "Elegir &sonidos…", lambda e: self.elegir_sonidos()), 0, wx.TOP, 8)
        self.invisible = casilla(accesibilidad, rejilla, "Interfaz &invisible:", "Manejar la reproducción con teclas del sistema aunque estés en otro programa", windows["interfazInvisible"])
        rejilla.Add(wx.StaticText(accesibilidad, label="Teclas que funcionan en segundo plano:"), 0, wx.TOP, 8)
        rejilla.Add(boton(accesibilidad, "&Teclas en segundo plano…", lambda e: parent.ejecutar("herr_teclas_globales")), 0, wx.TOP, 8)
        rejilla.Add(wx.StaticText(accesibilidad, label="Lectura completa de las listas con NVDA:"), 0, wx.TOP, 8)
        rejilla.Add(boton(accesibilidad, "Instalar el complemento de &NVDA…", lambda e: parent.ejecutar("herr_addon")), 0, wx.TOP, 8)

        avanzado, rejilla = pagina("Actualizaciones")
        self.comprobar_app = casilla(avanzado, rejilla, "&Versiones nuevas:", "Comprobar al iniciar si hay una versión nueva de la aplicación", windows["comprobarActualizaciones"])
        self.url_app = fila(avanzado, rejilla, "&Dirección del archivo de versiones:", lambda: wx.TextCtrl(avanzado, value=windows["urlActualizaciones"]))
        rejilla.Add(wx.StaticText(avanzado, label="Sin dirección no se conecta a ningún sitio para comprobarlo."), 0, wx.TOP, 8)
        rejilla.Add(boton(avanzado, "Comprobar &ahora…", lambda e: parent.ejecutar("herr_actualizar_app")), 0, wx.TOP, 8)

        botones = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindow(wx.ID_OK).SetLabel("&Guardar")
        self.FindWindow(wx.ID_CANCEL).SetLabel("&Cancelar")
        caja.Add(botones, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(caja)
        self.SetMinSize((640, 520))
        self.plantillas_cambiadas = False
        wx.CallAfter(self.libro.SetFocus)

    def editar_plantillas(self):
        with DialogoPlantillas(self, self.datos) as dialogo:
            if dialogo.ShowModal() == wx.ID_OK:
                self.plantillas_cambiadas = True

    def elegir_carpeta(self):
        with wx.DirDialog(self, "Carpeta para las grabaciones", self.carpeta_grabaciones.GetValue()) as dialogo:
            if dialogo.ShowModal() == wx.ID_OK:
                self.carpeta_grabaciones.SetValue(dialogo.GetPath())

    def elegir_carpeta_nube(self):
        with wx.DirDialog(self, "Carpeta para sincronizar la configuración", self.carpeta_nube.GetValue()) as dialogo:
            if dialogo.ShowModal() == wx.ID_OK:
                self.carpeta_nube.SetValue(dialogo.GetPath())

    def margenes_canal(self):
        """Márgenes de grabación propios de un canal (los que empiezan siempre tarde)."""
        nombres = sorted({c.nombre for c in self.GetParent().canales}) if hasattr(self.GetParent(), "canales") else []
        if not nombres:
            aviso(self, "Todavía no hay canales cargados.")
            return
        with wx.SingleChoiceDialog(self, "¿De qué canal quieres cambiar los márgenes?", "Márgenes por canal", nombres) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            canal = nombres[dialogo.GetSelection()]
        margenes = self.datos.windows.setdefault("margenesCanal", {})
        antes, despues = margenes.get(canal, [self.margen_antes.GetValue(), self.margen_despues.GetValue()])
        with wx.NumberEntryDialog(self, f"Minutos que se empieza antes en {canal}:", "Minutos antes", "Margen de inicio", antes, 0, 60) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            antes = dialogo.GetValue()
        with wx.NumberEntryDialog(self, f"Minutos que se sigue grabando después en {canal}:", "Minutos después", "Margen final", despues, 0, 60) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            despues = dialogo.GetValue()
        margenes[canal] = [antes, despues]
        self.datos.guardar()
        aviso(self, f"{canal}: se empezará {antes} minutos antes y se seguirá {despues} minutos después.")

    def elegir_sonidos(self):
        """Activa o desactiva cada aviso sonoro por separado."""
        nombres = list(sonidos.CATALOGO)
        etiquetas = [f"{sonidos.CATALOGO[n][0]}" for n in nombres]
        activos = self.datos.windows.get("avisosSonido") or {}
        with wx.MultiChoiceDialog(self, "Marca los avisos que quieres oír:", "Sonidos", etiquetas) as dialogo:
            dialogo.SetSelections([i for i, n in enumerate(nombres) if activos.get(n, True)])
            if dialogo.ShowModal() != wx.ID_OK:
                return
            elegidos = set(dialogo.GetSelections())
        self.datos.windows["avisosSonido"] = {n: (i in elegidos) for i, n in enumerate(nombres)}
        self.datos.guardar()
        sonidos.configurar(self.sonidos.GetValue(), self.datos.windows["avisosSonido"])
        sonidos.reproducir("inicio")

    def aplicar(self) -> None:
        usuario, windows, acc = self.datos.usuario, self.datos.windows, self.datos.windows["accesibilidad"]
        usuario["darkMode"] = TEMAS[self.tema.GetSelection()][1]
        windows["altoContraste"] = self.contraste.GetValue()
        windows["tamanoLetra"] = self.letra.GetValue()
        usuario["hiddenChannelsVisibility"] = OCULTOS[self.ocultos.GetSelection()][1]
        usuario["closeOnExit"] = AL_CERRAR[self.cerrar.GetSelection()][1]
        windows["minimizarABandeja"] = self.minimizar_bandeja.GetValue()
        windows["iniciarMinimizado"] = self.iniciar_minimizado.GetValue()
        antiguo_windows = bool(windows.get("iniciarConWindows", False))
        nuevo_windows = self.iniciar_windows.GetValue()
        windows["iniciarConWindows"] = nuevo_windows
        if nuevo_windows != antiguo_windows:
            tareas.configurar_arranque_windows(nuevo_windows)
        windows["frecuenciaActualizacion"] = FRECUENCIAS[self.actualizar.GetSelection()][1]
        windows["actualizarAlIniciar"] = windows["frecuenciaActualizacion"] != "nunca"
        windows["guiaExtra"] = self.guia_extra.GetValue()
        windows["comprobarMpv"] = self.comprobar_mpv.GetValue()
        usuario["playerSubtitle"] = SUBTITULOS[self.subtitulos.GetSelection()][1]
        windows["modoImagen"] = MODOS_IMAGEN[self.imagen.GetSelection()][1]
        usuario["browserEmbedWeb"] = self.web_en_app.GetValue()
        usuario["browserEmbedYoutube"] = self.youtube_en_app.GetValue()
        acc["voz"] = self.voz.GetValue()
        acc["braille"] = self.braille.GetValue()
        acc["retardoVoz"] = self.retardo.GetValue()
        acc["anunciarEstado"] = self.anunciar_estado.GetValue()
        acc["anunciarAvisos"] = self.anunciar_avisos.GetValue()
        acc["decirFila"] = self.decir_fila.GetValue()
        acc["decirColumna"] = self.decir_columna.GetValue()
        acc["decirCelda"] = self.decir_celda.GetValue()
        windows["calidad"] = CALIDADES[self.calidad.GetSelection()][1]
        windows["bufferRecepcion"] = BUFERES[self.buffer.GetSelection()][1]
        windows["soloAudio"] = self.solo_audio.GetValue()
        windows["mostrarVideo"] = self.mostrar_video.GetValue()
        windows["audiodescripcion"] = self.audiodescripcion.GetValue()
        windows["timeshiftMinutos"] = self.timeshift.GetValue()
        windows["reintentos"] = self.reintentos.GetValue()
        windows["emisionAlternativa"] = self.alternativa.GetValue()
        carpeta = self.carpeta_grabaciones.GetValue().strip()
        windows["carpetaGrabaciones"] = "" if carpeta == str(self.datos.raiz / "grabaciones") else carpeta
        windows["grabacionSegundoPlano"] = MODOS_GRABACION[self.modo_grabacion.GetSelection()][1]
        windows["maximoGrabacionesFondo"] = self.maximo_fondo.GetValue()
        windows["formatoGrabacionTV"] = FORMATOS_GRABACION_TV[self.formato_grabacion.GetSelection()][1]
        windows["grabarSoloAudio"] = self.solo_audio_grabacion.GetValue()
        windows["margenAntes"] = self.margen_antes.GetValue()
        windows["margenDespues"] = self.margen_despues.GetValue()
        windows["carpetaPorPrograma"] = self.carpeta_por_programa.GetValue()
        windows["minimoLibreGB"] = self.minimo_libre.GetValue()
        windows["retencionDias"] = self.retencion_dias.GetValue()
        windows["retencionPorPrograma"] = self.retencion_programa.GetValue()
        windows["retencionGigas"] = self.retencion_gigas.GetValue()
        windows["alTerminarGrabacion"] = list(tareas.ACCIONES_FINAL)[self.al_terminar.GetSelection()]
        windows["tareaWindows"] = self.tarea_windows.GetValue()
        windows["ordenPosterior"] = self.orden_posterior.GetValue().strip()
        windows["nivelarVolumen"] = self.nivelador.GetValue()
        windows["carpetaSincronizacion"] = self.carpeta_nube.GetValue().strip()
        windows["avisoGrabacionMinutos"] = self.aviso_grabacion.GetValue()
        windows["quitarDuplicados"] = self.duplicados.GetValue()
        windows["numeroCanal"] = self.numeracion.GetValue()
        windows["anunciarPrograma"] = self.anunciar_programa.GetValue()
        windows["sonidos"] = self.sonidos.GetValue()
        windows["interfazInvisible"] = self.invisible.GetValue()
        windows["comprobarActualizaciones"] = self.comprobar_app.GetValue()
        windows["urlActualizaciones"] = self.url_app.GetValue().strip()


class DialogoPlantillas(wx.Dialog):
    """Editor de plantillas de lectura: columnas de cada lista y su orden (como SocialRSS)."""

    def __init__(self, parent, datos):
        super().__init__(parent, title="Editor de plantillas de lectura", size=(720, 640), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.datos = datos
        self.valores = {p["clave"]: plantillas.texto_plantilla(datos.windows, p["clave"]) for p in plantillas.PLANTILLAS}
        self.actual = plantillas.PLANTILLAS[0]
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label="Cada campo entre llaves es una columna de la lista, en ese orden. El lector lee la fila columna a columna; Ctrl+0 lee la fila entera con este texto."), 0, wx.ALL, 8)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.lista = campo(self, fila, "&Plantilla a editar:", lambda: wx.Choice(self, choices=[p["nombre"] for p in plantillas.PLANTILLAS]), 1)
        self.lista.SetSelection(0)
        self.lista.Bind(wx.EVT_CHOICE, lambda e: self.cargar(plantillas.PLANTILLAS[self.lista.GetSelection()]))
        caja.Add(fila, 0, wx.EXPAND | wx.ALL, 8)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.modelo = campo(self, fila, "&Modelo rápido (rellena el texto):", lambda: wx.Choice(self), 1)
        self.modelo.Bind(wx.EVT_CHOICE, self.aplicar_modelo)
        caja.Add(fila, 0, wx.EXPAND | wx.ALL, 8)
        caja.Add(wx.StaticText(self, label="&Texto de la plantilla:"), 0, wx.LEFT, 8)
        self.texto = nombrar(wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 70)), "Texto de la plantilla")
        self.texto.Bind(wx.EVT_TEXT, lambda e: self.actualizar_vista())
        caja.Add(self.texto, 0, wx.EXPAND | wx.ALL, 8)
        caja.Add(wx.StaticText(self, label="&Campos disponibles (Intro o doble clic para insertar):"), 0, wx.LEFT, 8)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.campos = nombrar(wx.ListBox(self), "Campos disponibles")
        self.campos.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.insertar_campo())
        self.campos.Bind(wx.EVT_KEY_DOWN, self.tecla_campos)
        fila.Add(self.campos, 1, wx.EXPAND | wx.RIGHT, 8)
        columna = wx.BoxSizer(wx.VERTICAL)
        for control in (boton(self, "&Insertar campo", lambda e: self.insertar_campo()), boton(self, "&Leer la vista previa", lambda e: voz.decir(self.vista.GetValue(), interrumpir=True)), boton(self, "&Restaurar esta", lambda e: self.restaurar(False)), boton(self, "Restaurar t&odas", lambda e: self.restaurar(True))):
            columna.Add(control, 0, wx.EXPAND | wx.BOTTOM, 6)
        fila.Add(columna, 0)
        caja.Add(fila, 1, wx.EXPAND | wx.ALL, 8)
        caja.Add(wx.StaticText(self, label="Vista pre&via con datos de ejemplo:"), 0, wx.LEFT, 8)
        self.vista = nombrar(wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 60)), "Vista previa de la plantilla")
        caja.Add(self.vista, 0, wx.EXPAND | wx.ALL, 8)
        self.columnas = wx.StaticText(self, label="")
        caja.Add(self.columnas, 0, wx.LEFT | wx.RIGHT, 8)
        botones = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindow(wx.ID_OK).SetLabel("&Guardar")
        self.FindWindow(wx.ID_CANCEL).SetLabel("&Cancelar")
        self.Bind(wx.EVT_BUTTON, self.guardar, id=wx.ID_OK)
        caja.Add(botones, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(caja)
        self.cargar(self.actual)
        self.lista.SetFocus()

    def cargar(self, definicion):
        self.actual = definicion
        self.modelo.Set(["(elige un modelo)"] + [nombre for nombre, _ in definicion["presets"]])
        self.modelo.SetSelection(0)
        self.campos.Set([f"{{{campo}}}: {descripcion}" for campo, descripcion in definicion["campos"]])
        if self.campos.GetCount():
            self.campos.SetSelection(0)
        self.texto.ChangeValue(self.valores[definicion["clave"]])
        self.actualizar_vista()

    def aplicar_modelo(self, _evento):
        indice = self.modelo.GetSelection() - 1
        if 0 <= indice < len(self.actual["presets"]):
            self.texto.SetValue(self.actual["presets"][indice][1])
            voz.decir("Modelo aplicado: " + self.vista.GetValue())

    def insertar_campo(self):
        indice = self.campos.GetSelection()
        if indice < 0:
            return
        campo_nombre = self.actual["campos"][indice][0]
        self.texto.WriteText("{" + campo_nombre + "}")
        self.texto.SetFocus()
        voz.decir(f"Campo {campo_nombre} insertado")

    def tecla_campos(self, evento):
        if evento.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.insertar_campo()
        else:
            evento.Skip()

    def actualizar_vista(self):
        texto = self.texto.GetValue()
        self.valores[self.actual["clave"]] = texto
        if plantillas.plantilla_valida(self.actual["clave"], texto):
            self.vista.SetValue(plantillas.ejemplo(self.actual["clave"], texto))
            self.columnas.SetLabel("Columnas: " + ", ".join(titulo for _, titulo in plantillas.columnas(texto)))
        else:
            self.vista.SetValue("La plantilla necesita al menos un campo válido entre llaves.")
            self.columnas.SetLabel("Columnas: ninguna válida")

    def restaurar(self, todas: bool):
        for definicion in plantillas.PLANTILLAS if todas else [self.actual]:
            self.valores[definicion["clave"]] = definicion["default"]
        self.texto.SetValue(self.valores[self.actual["clave"]])
        voz.decir("Plantillas restauradas" if todas else "Plantilla restaurada")

    def guardar(self, _evento):
        invalidas = [p["nombre"] for p in plantillas.PLANTILLAS if not plantillas.plantilla_valida(p["clave"], self.valores[p["clave"]])]
        if invalidas:
            aviso(self, "Revisa estas plantillas, no tienen ningún campo válido: " + ", ".join(invalidas), icono=wx.ICON_WARNING)
            return
        guardadas = self.datos.windows["accesibilidad"]["plantillas"]
        for definicion in plantillas.PLANTILLAS:
            texto = self.valores[definicion["clave"]].strip()
            if texto == definicion["default"]:
                guardadas.pop(definicion["clave"], None)
            else:
                guardadas[definicion["clave"]] = texto
        self.datos.guardar()
        self.EndModal(wx.ID_OK)


class DialogoAmbitos(wx.Dialog):
    """Comunidades y categorías visibles (tvCommunitiesRemoved del APK)."""

    def __init__(self, parent, tipo: str, ambitos: list[str], ocultos: list[str]):
        super().__init__(parent, title=f"Categorías visibles en {NOMBRE_TIPO[tipo]}", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER, size=(460, 520))
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label="Marca las categorías o comunidades que quieres ver en la lista de canales:"), 0, wx.ALL, 12)
        self.lista = nombrar(wx.CheckListBox(self, choices=ambitos), "Categorías visibles")
        for indice, nombre in enumerate(ambitos):
            self.lista.Check(indice, nombre not in ocultos)
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        fila.Add(boton(self, "Marcar &todas", lambda e: [self.lista.Check(i, True) for i in range(self.lista.GetCount())]), 0, wx.RIGHT, 6)
        fila.Add(boton(self, "&Desmarcar todas", lambda e: [self.lista.Check(i, False) for i in range(self.lista.GetCount())]), 0)
        caja.Add(fila, 0, wx.ALL, 12)
        botones = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindow(wx.ID_OK).SetLabel("&Guardar")
        self.FindWindow(wx.ID_CANCEL).SetLabel("&Cancelar")
        caja.Add(botones, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(caja)
        self.lista.SetFocus()

    def ocultos(self) -> list[str]:
        return [self.lista.GetString(i) for i in range(self.lista.GetCount()) if not self.lista.IsChecked(i)]


class DialogoRecordatorios(wx.Dialog):
    def __init__(self, parent, datos):
        super().__init__(parent, title="Recordatorios", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER, size=(680, 440))
        self.datos = datos
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label="Avisos programados (se muestran mientras la aplicación está abierta):"), 0, wx.ALL, 12)
        self.lista = ListaAccesible(self, "Recordatorios. Suprimir elimina; menú contextual con Mayús+F10", "recordatorios", datos.windows)
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self.menu)
        self.lista.Bind(wx.EVT_KEY_DOWN, self.tecla)
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        fila.Add(boton(self, "&Eliminar", lambda e: self.eliminar()), 0, wx.RIGHT, 6)
        fila.Add(wx.Button(self, wx.ID_CANCEL, "&Cerrar"), 0)
        caja.Add(fila, 0, wx.ALL, 12)
        self.SetSizer(caja)
        self.rellenar()
        self.lista.ajustar_anchos()
        self.lista.SetFocus()

    def rellenar(self):
        recordatorios = sorted(self.datos.windows["recordatorios"], key=lambda r: r["inicio"])
        self.lista.rellenar([fila_recordatorio(r) for r in recordatorios])
        if not recordatorios:
            self.lista.rellenar([{"fecha": "", "canal": "", "titulo": "No hay recordatorios", "minutos": ""}])

    def tecla(self, evento):
        if evento.GetKeyCode() == wx.WXK_DELETE:
            self.eliminar()
        else:
            evento.Skip()

    def menu(self, evento):
        fila = self.lista.menu_contextual_en_fila(evento)
        menu_desde(self, [("&Eliminar recordatorio\tSupr", self.eliminar)], self.lista, fila)

    def eliminar(self):
        valores = self.lista.valores_actuales() or {}
        recordatorio = valores.get("_recordatorio")
        if recordatorio and recordatorio in self.datos.windows["recordatorios"]:
            self.datos.windows["recordatorios"].remove(recordatorio)
            self.datos.guardar()
            voz.decir("Recordatorio eliminado")
            self.rellenar()


class DialogoProgramacion(wx.Dialog):
    """Programación completa de un canal con lista accesible y menú contextual."""

    def __init__(self, parent: "VentanaPrincipal", canal: Canal):
        super().__init__(parent, title=f"Programación de {canal.nombre}", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER, size=(820, 600))
        self.ventana = parent
        self.canal = canal
        self.programas = catalogo.programas_canal(parent.guia.get(canal.tipo, {}), canal)
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label=f"Programación de {canal.nombre} ({len(self.programas)} programas). Intro o el menú contextual abren las acciones."), 0, wx.ALL, 10)
        self.lista = ListaAccesible(self, f"Programación de {canal.nombre}", "programacion", parent.datos.windows)
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.menu(e))
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self.menu)
        self.lista.Bind(wx.EVT_LIST_ITEM_FOCUSED, lambda e: self.mostrar())
        self.lista.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda e: self.mostrar())
        caja.Add(self.lista, 2, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        caja.Add(wx.StaticText(self, label="Detalles del programa:"), 0, wx.LEFT | wx.TOP, 10)
        self.detalle = nombrar(wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 110)), "Detalles del programa")
        caja.Add(self.detalle, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        fila = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Ver canal", lambda e: self.ver_canal()), boton(self, "&Recordatorio…", lambda e: self.recordatorio()), boton(self, "&Grabar…", lambda e: self.grabar()), boton(self, "&Más información…", lambda e: self.menu(None)), boton(self, "&Copiar", lambda e: copiar_portapapeles(self.detalle.GetValue())), wx.Button(self, wx.ID_CANCEL, "C&errar")):
            fila.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(fila, 0, wx.ALL, 10)
        self.SetSizer(caja)
        ahora = time.time()
        filas = [fila_programa(p, canal, ahora) for p in self.programas]
        actual = next((i for i, p in enumerate(self.programas) if p.fin > ahora), 0)
        if not filas:
            filas = [{"hora": "", "titulo": "Este canal no tiene programación disponible", "estado": ""}]
        self.lista.rellenar(filas, actual)
        self.lista.ajustar_anchos()
        self.mostrar()
        self.lista.SetFocus()

    def programa(self) -> Programa | None:
        return (self.lista.valores_actuales() or {}).get("_programa")

    def mostrar(self):
        programa = self.programa()
        if not programa:
            self.detalle.SetValue("")
            return
        self.detalle.SetValue(texto_detalle_programa(self.canal, programa))

    def ver_canal(self):
        self.ventana.reproducir_canal(self.canal)

    def recordatorio(self):
        programa = self.programa()
        if programa:
            self.ventana.crear_recordatorio(self.canal, programa, self)

    def grabar(self):
        programa = self.programa()
        if programa:
            self.ventana.programar_grabacion(self.canal, programa, self)

    def regla(self):
        """Graba siempre este programa: crea una regla con su título."""
        programa = self.programa()
        if programa:
            self.EndModal(wx.ID_OK)
            self.ventana.regla_desde_programa(self.canal, programa)

    def ver_pasado(self):
        programa = self.programa()
        if programa:
            self.ventana.reproducir_catchup(self.canal, programa, self)

    def menu(self, evento):
        programa = self.programa()
        fila = self.lista.menu_contextual_en_fila(evento) if evento is not None and hasattr(evento, "GetPosition") else self.lista.fila_actual()
        pasado = programa is not None and catchup.disponible(self.canal, programa.inicio, programa.fin)
        opciones = [("&Ver canal ahora", self.ver_canal), ("&Recordatorio…", self.recordatorio if programa else None),
                    ("&Grabar este programa…", self.grabar if programa else None),
                    ("Grabarlo &siempre (crear una regla)…", self.regla if programa else None),
                    ("Ver este programa &emitido", self.ver_pasado if pasado else None), None]
        if programa:
            consulta = quote_plus(programa.titulo)
            opciones += [(etiqueta, (lambda u=url: abrir_navegador(self, u + consulta))) for etiqueta, url in BUSCADORES]
            opciones += [None, ("&Copiar título", lambda: copiar_portapapeles(programa.titulo)), ("Copiar &detalles", lambda: copiar_portapapeles(self.detalle.GetValue()))]
        menu_desde(self, opciones, self.lista, fila)


# --- paneles ---------------------------------------------------------------
class PanelCanales(wx.Panel):
    """Pestaña de Televisión o Radio: búsqueda, filtros, canales y emisiones."""

    def __init__(self, parent, ventana: "VentanaPrincipal", tipo: str):
        super().__init__(parent)
        self.ventana = ventana
        self.tipo = tipo
        self.visibles: list[Canal] = []
        self.canal: Canal | None = None
        caja = wx.BoxSizer(wx.VERTICAL)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.busqueda = campo(self, fila, "&Buscar:", lambda: wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER), 2)
        self.busqueda.SetHint("Nombre, categoría o país")
        self.busqueda.Bind(wx.EVT_TEXT, lambda e: self.refrescar())
        self.busqueda.Bind(wx.EVT_TEXT_ENTER, lambda e: self.lista.SetFocus())
        self.ambito = campo(self, fila, "&Categoría:", lambda: wx.Choice(self, choices=["Todas"]), 1)
        self.ambito.SetSelection(0)
        self.ambito.Bind(wx.EVT_CHOICE, lambda e: self.refrescar())
        self.vista = campo(self, fila, "&Ver:", lambda: wx.Choice(self, choices=["Todos", "Favoritos", "Ocultos"]), 1)
        self.vista.SetSelection(1 if ventana.datos.solo_favoritos(tipo) else 0)
        self.vista.Bind(wx.EVT_CHOICE, self.cambiar_vista)
        caja.Add(fila, 0, wx.EXPAND | wx.ALL, 8)
        self.cuenta = wx.StaticText(self, label="Cargando canales…")
        caja.Add(self.cuenta, 0, wx.LEFT | wx.RIGHT, 8)
        self.marcador = organizar.Marcador()
        self.lista = ListaAccesible(self, f"Canales de {NOMBRE_TIPO[tipo].lower()}. Intro reproduce; teclea el número de canal; menú contextual con la tecla Aplicaciones", "canales_" + tipo, ventana.datos.windows)
        self.lista.Bind(wx.EVT_KEY_DOWN, self.tecla_lista)
        self.lista.Bind(wx.EVT_LIST_ITEM_FOCUSED, self.seleccionar)
        self.lista.Bind(wx.EVT_LIST_ITEM_SELECTED, self.seleccionar)
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.ventana.reproducir_seleccion(self))
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self.menu_canal)
        caja.Add(self.lista, 3, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        caja.Add(wx.StaticText(self, label="Emisiones del canal:"), 0, wx.LEFT | wx.TOP, 8)
        self.emisiones = ListaAccesible(self, "Emisiones del canal. Intro reproduce la emisión", "emisiones", ventana.datos.windows)
        self.emisiones.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.ventana.reproducir_seleccion(self))
        self.emisiones.Bind(wx.EVT_CONTEXT_MENU, self.menu_emision)
        caja.Add(self.emisiones, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        caja.Add(wx.StaticText(self, label="Información del canal:"), 0, wx.LEFT | wx.TOP, 8)
        self.info = nombrar(wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 70)), "Información del canal seleccionado")
        caja.Add(self.info, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        botones = wx.WrapSizer(wx.HORIZONTAL)
        self.boton_reproducir = boton(self, "&Reproducir", lambda e: self.ventana.reproducir_seleccion(self))
        self.boton_web = boton(self, "&Web oficial", lambda e: self.ventana.abrir_web(self.canal))
        self.boton_favorito = boton(self, "Añadir a &favoritos", lambda e: self.ventana.alternar_favorito(self))
        self.boton_ocultar = boton(self, "&Ocultar", lambda e: self.ventana.alternar_oculto(self))
        self.boton_guia = boton(self, "&Programación", lambda e: self.ventana.ver_programacion(self.canal))
        for control in (self.boton_reproducir, self.boton_web, self.boton_favorito, self.boton_ocultar, self.boton_guia):
            botones.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(botones, 0, wx.ALL, 8)
        self.SetSizer(caja)
        self.Bind(wx.EVT_SIZE, self.al_cambiar_tamano)

    def al_cambiar_tamano(self, evento):
        evento.Skip()
        wx.CallAfter(self.lista.ajustar_anchos)
        wx.CallAfter(self.emisiones.ajustar_anchos)

    def cambiar_vista(self, _evento):
        self.ventana.datos.fijar_solo_favoritos(self.tipo, self.vista.GetSelection() == 1)
        self.ventana.datos.guardar()
        self.refrescar()

    def actualizar_ambitos(self, canales):
        actual = self.ambito.GetStringSelection()
        nombres = ["Todas"] + catalogo.ambitos(canales, self.tipo)
        self.ambito.Set(nombres)
        self.ambito.SetSelection(nombres.index(actual) if actual in nombres else 0)

    def aplicar_plantillas(self):
        self.lista.aplicar_plantilla()
        self.emisiones.aplicar_plantilla()
        self.refrescar()

    def tecla_lista(self, evento):
        """Cifras: saltar al número de canal, como en un mando a distancia."""
        codigo = evento.GetKeyCode()
        if evento.GetModifiers() != wx.MOD_NONE or not self.ventana.datos.windows.get("numeroCanal", True):
            evento.Skip()
            return
        cifra = ""
        if ord("0") <= codigo <= ord("9"):
            cifra = chr(codigo)
        elif wx.WXK_NUMPAD0 <= codigo <= wx.WXK_NUMPAD9:
            cifra = str(codigo - wx.WXK_NUMPAD0)
        if not cifra:
            evento.Skip()
            return
        numero = self.marcador.pulsar(cifra)
        indice = organizar.buscar_numero(self.visibles, numero)
        if 0 <= indice < len(self.visibles):
            self.lista.seleccionar(indice)
            self.mostrar_canal(self.visibles[indice])
            voz.decir(f"{numero}: {self.visibles[indice].nombre}", interrumpir=True, inmediato=True)
        else:
            voz.decir(f"{numero}: no hay canal con ese número", interrumpir=True, inmediato=True)

    def refrescar(self, conservar: bool = True):
        datos = self.ventana.datos
        anterior = self.canal.nombre if (self.canal and conservar) else ""
        vista = ("todos", "favoritos", "ocultos")[max(0, self.vista.GetSelection())]
        ambito = self.ambito.GetStringSelection() if self.ambito.GetSelection() > 0 else ""
        self.visibles = catalogo.filtrar(self.ventana.canales, datos, self.tipo, self.busqueda.GetValue(), ambito, vista)
        guia = self.ventana.guia.get(self.tipo, {})
        filas = [fila_canal(canal, datos, guia, posicion, organizar.bloqueado(datos, canal)) for posicion, canal in enumerate(self.visibles)]
        total = len(self.visibles)
        indice = next((i for i, c in enumerate(self.visibles) if c.nombre == anterior), 0)
        self.lista.rellenar(filas, indice)
        self.lista.ajustar_anchos()
        self.cuenta.SetLabel(f"{total} canal{'es' if total != 1 else ''}" + (" (filtrados)" if self.busqueda.GetValue().strip() or ambito else ""))
        self.mostrar_canal(self.visibles[indice] if total else None)
        self.Layout()

    def refrescar_ahora(self):
        """Actualiza las columnas de programación sin recargar la lista."""
        if not any(campo_ in self.lista.campos for campo_ in ("ahora", "siguiente")):
            return
        guia = self.ventana.guia.get(self.tipo, {})
        for numero, canal in enumerate(self.visibles):
            self.lista.actualizar_fila(numero, fila_canal(canal, self.ventana.datos, guia, numero, organizar.bloqueado(self.ventana.datos, canal)))

    def seleccionar(self, evento):
        evento.Skip()
        indice = evento.GetIndex()
        canal = self.visibles[indice] if 0 <= indice < len(self.visibles) else None
        if canal is not self.canal:
            self.mostrar_canal(canal)

    def mostrar_canal(self, canal: Canal | None):
        self.canal = canal
        datos = self.ventana.datos
        if canal is None:
            self.emisiones.rellenar([])
            self.info.SetValue("No hay canales que mostrar. Cambia la búsqueda o los filtros.")
            self.boton_favorito.SetLabel("Añadir a &favoritos")
            self.boton_ocultar.SetLabel("&Ocultar")
            return
        filas = [fila_emision(e, i + 1) for i, e in enumerate(canal.emisiones)]
        self.emisiones.rellenar(filas or [{"numero": "Sin emisiones por Internet", "tipo": ""}], 0)
        self.emisiones.ajustar_anchos()
        estado = datos.estado_canal(self.tipo, canal.nombre)
        self.boton_favorito.SetLabel("Quitar de &favoritos" if estado["favorite"] else "Añadir a &favoritos")
        self.boton_ocultar.SetLabel("Mostrar (&ocultar no)" if estado["hide"] else "&Ocultar")
        lineas = [f"{canal.nombre} · {canal.ambito} · {canal.pais}"]
        programas = catalogo.programas_canal(self.ventana.guia.get(self.tipo, {}), canal)
        actual, siguiente = catalogo.ahora_y_siguiente(programas)
        if actual:
            lineas.append(f"Ahora ({actual.horario()}): {actual.titulo}")
        if siguiente:
            lineas.append(f"Después ({siguiente.horario()}): {siguiente.titulo}")
        if not programas and canal.epg_id:
            lineas.append("Este canal no tiene programación disponible.")
        lineas.extend(canal.notas())
        if canal.origen and "Lista pública ·" not in canal.origen:
            lineas.append(f"Lista: {canal.origen}")
        self.info.SetValue("\n".join(lineas))

    def emision_seleccionada(self) -> Emision | None:
        if not self.canal or not self.canal.emisiones:
            return None
        valores = self.emisiones.valores_actuales() or {}
        return valores.get("_emision") or self.canal.emisiones[0]

    # --- menús contextuales ----------------------------------------------------------
    def menu_canal(self, evento):
        fila = self.lista.menu_contextual_en_fila(evento)
        canal = self.visibles[fila] if 0 <= fila < len(self.visibles) else self.canal
        if canal is None:
            return
        self.mostrar_canal(canal)
        ventana = self.ventana
        t = ventana.teclas
        estado = ventana.datos.estado_canal(canal.tipo, canal.nombre)
        submenu = wx.Menu()
        for numero, emision in enumerate(canal.emisiones, start=1):
            elemento = submenu.Append(wx.ID_ANY, emision.etiqueta(numero).replace("&", "&&"))
            ventana.Bind(wx.EVT_MENU, lambda e, em=emision: ventana.reproducir(canal, em), elemento)
        if not canal.emisiones:
            submenu.Append(wx.ID_ANY, "Sin emisiones").Enable(False)
        opciones = [
            (t.etiqueta_menu("canal_reproducir", "&Reproducir (Intro)"), lambda: ventana.reproducir_seleccion(self)),
            ("&Emisiones", submenu),
            (t.etiqueta_menu("canal_web"), (lambda: ventana.abrir_web(canal)) if canal.web else None),
            None,
            (t.etiqueta_menu("canal_programacion"), lambda: ventana.ver_programacion(canal)),
            (t.etiqueta_menu("canal_guia"), lambda: ventana.ir_a_guia(canal)),
            None,
            (t.etiqueta_menu("canal_favorito", "Quitar de &favoritos" if estado["favorite"] else "Añadir a &favoritos"), lambda: ventana.alternar_favorito(self)),
            (t.etiqueta_menu("canal_ocultar", "&Mostrar canal" if estado["hide"] else "&Ocultar canal"), lambda: ventana.alternar_oculto(self)),
            None,
            (t.etiqueta_menu("canal_subir"), lambda: ventana.mover(-1, self)),
            (t.etiqueta_menu("canal_bajar"), lambda: ventana.mover(1, self)),
            (t.etiqueta_menu("canal_quitar_orden"), (lambda: ventana.mover(0, self)) if estado["position"] is not None else None),
            None,
            (t.etiqueta_menu("canal_bloquear", "&Desbloquear con PIN" if organizar.bloqueado(ventana.datos, canal) else "&Bloquear con PIN"), lambda: ventana.alternar_bloqueo(canal)),
            (t.etiqueta_menu("repro_grabar", _etiqueta_grabar(ventana, canal)), lambda: ventana.grabar_canal(canal)),
            (t.etiqueta_menu("repro_enviar", "&Enviar a la tele…"), lambda: (ventana.reproducir_canal(canal), wx.CallLater(1500, ventana.enviar_a_tele))),
            None,
            ("Copiar &nombre", lambda: copiar_portapapeles(canal.nombre)),
            (t.etiqueta_menu("canal_copiar"), lambda: ventana.copiar_enlace(self)),
            (t.etiqueta_menu("canal_info"), lambda: voz.decir(self.info.GetValue(), interrumpir=True)),
        ]
        menu_desde(ventana, opciones, self.lista, fila)

    def menu_emision(self, evento):
        fila = self.emisiones.menu_contextual_en_fila(evento)
        emision = (self.emisiones.valores_actuales() or {}).get("_emision")
        if not self.canal or emision is None:
            return
        ventana = self.ventana
        opciones = [
            ("&Reproducir esta emisión\tIntro", lambda: ventana.reproducir(self.canal, emision)),
            ("Abrir en el navegador &integrado", lambda: navegador.abrir(ventana, emision.url, self.canal.nombre, True)),
            ("Abrir en el &navegador externo", lambda: abrir_navegador(self, emision.url)),
            ("&Copiar enlace", lambda: (copiar_portapapeles(emision.url), ventana.estado("Enlace copiado en el portapapeles."))),
        ]
        menu_desde(ventana, opciones, self.emisiones, fila)


class PanelGuia(wx.Panel):
    def __init__(self, parent, ventana: "VentanaPrincipal"):
        super().__init__(parent)
        self.ventana = ventana
        self.canales: list[Canal] = []
        self.programas: list[Programa] = []
        caja = wx.BoxSizer(wx.VERTICAL)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.medio = campo(self, fila, "&Medio:", lambda: wx.Choice(self, choices=["Televisión", "Radio"]), 0, False)
        self.medio.SetSelection(0)
        self.medio.Bind(wx.EVT_CHOICE, lambda e: self.rellenar_canales())
        self.canal = campo(self, fila, "&Canal:", lambda: wx.Choice(self), 1)
        self.canal.Bind(wx.EVT_CHOICE, lambda e: self.rellenar_programas())
        caja.Add(fila, 0, wx.EXPAND | wx.ALL, 8)
        self.solo_favoritos = nombrar(wx.CheckBox(self, label="Solo canales &favoritos"), "Solo canales favoritos")
        self.solo_favoritos.Bind(wx.EVT_CHECKBOX, lambda e: self.rellenar_canales())
        caja.Add(self.solo_favoritos, 0, wx.LEFT | wx.BOTTOM, 8)
        caja.Add(wx.StaticText(self, label="Programación desde ahora:"), 0, wx.LEFT, 8)
        self.lista = ListaAccesible(self, "Programación. Intro o el menú contextual abren las opciones del programa", "programacion", ventana.datos.windows)
        self.lista.Bind(wx.EVT_LIST_ITEM_FOCUSED, lambda e: (e.Skip(), self.mostrar_programa()))
        self.lista.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda e: (e.Skip(), self.mostrar_programa()))
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.menu_programa(e))
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self.menu_programa)
        caja.Add(self.lista, 3, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        caja.Add(wx.StaticText(self, label="Detalles del programa:"), 0, wx.LEFT | wx.TOP, 8)
        self.detalle = nombrar(wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 110)), "Detalles del programa")
        caja.Add(self.detalle, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        botones = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Ver canal", lambda e: self.ver_canal()), boton(self, "&Recordatorio…", lambda e: self.recordatorio()), boton(self, "&Grabar…", lambda e: self.grabar()), boton(self, "&Buscar en la guía…", lambda e: self.ventana.ejecutar("herr_buscar_guia")), boton(self, "Más &información…", lambda e: self.menu_programa(None)), boton(self, "&Copiar", lambda e: copiar_portapapeles(self.detalle.GetValue()))):
            botones.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(botones, 0, wx.ALL, 8)
        self.SetSizer(caja)
        self.Bind(wx.EVT_SIZE, lambda e: (e.Skip(), wx.CallAfter(self.lista.ajustar_anchos)))

    @property
    def tipo(self) -> str:
        return TIPOS[max(0, self.medio.GetSelection())]

    def rellenar_canales(self, preferido: Canal | None = None):
        datos = self.ventana.datos
        guia = self.ventana.guia.get(self.tipo, {})
        self.canales = [c for c in catalogo.filtrar(self.ventana.canales, datos, self.tipo) if catalogo.programas_canal(guia, c)]
        if self.solo_favoritos.GetValue():
            self.canales = [c for c in self.canales if datos.estado_canal(self.tipo, c.nombre)["favorite"]]
        self.canal.Set([c.nombre for c in self.canales] or ["Sin programación disponible"])
        indice = 0
        if preferido:
            indice = next((i for i, c in enumerate(self.canales) if c.nombre == preferido.nombre), 0)
        self.canal.SetSelection(indice)
        self.rellenar_programas()

    def canal_actual(self) -> Canal | None:
        indice = self.canal.GetSelection()
        return self.canales[indice] if 0 <= indice < len(self.canales) else None

    def rellenar_programas(self):
        canal = self.canal_actual()
        ahora = time.time()
        self.programas = catalogo.programas_desde(catalogo.programas_canal(self.ventana.guia.get(self.tipo, {}), canal), ahora) if canal else []
        filas = [fila_programa(p, canal, ahora) for p in self.programas]
        self.lista.rellenar(filas or [{"hora": "", "titulo": "Este canal no tiene programación disponible", "estado": ""}], 0)
        self.lista.ajustar_anchos()
        self.mostrar_programa()

    def programa_actual(self) -> Programa | None:
        return (self.lista.valores_actuales() or {}).get("_programa")

    def mostrar_programa(self):
        programa = self.programa_actual()
        if not programa:
            self.detalle.SetValue("")
            return
        self.detalle.SetValue(texto_detalle_programa(self.canal_actual(), programa))

    def ver_canal(self):
        canal = self.canal_actual()
        if canal:
            self.ventana.reproducir_canal(canal)

    def recordatorio(self):
        programa, canal = self.programa_actual(), self.canal_actual()
        if programa and canal:
            self.ventana.crear_recordatorio(canal, programa, self)

    def grabar(self):
        programa, canal = self.programa_actual(), self.canal_actual()
        if programa and canal:
            self.ventana.programar_grabacion(canal, programa, self)

    def regla(self):
        programa, canal = self.programa_actual(), self.canal_actual()
        if programa and canal:
            self.ventana.regla_desde_programa(canal, programa)

    def ver_pasado(self):
        programa, canal = self.programa_actual(), self.canal_actual()
        if programa and canal:
            self.ventana.reproducir_catchup(canal, programa, self)

    def menu_programa(self, evento):
        programa = self.programa_actual()
        canal = self.canal_actual()
        fila = self.lista.menu_contextual_en_fila(evento) if evento is not None and hasattr(evento, "GetPosition") else self.lista.fila_actual()
        pasado = programa is not None and canal is not None and catchup.disponible(canal, programa.inicio, programa.fin)
        opciones = [("&Ver canal ahora", self.ver_canal), ("&Recordatorio…", self.recordatorio if programa else None),
                    ("&Grabar este programa…", self.grabar if programa else None),
                    ("Grabarlo &siempre (crear una regla)…", self.regla if programa else None),
                    ("Ver este programa &emitido", self.ver_pasado if pasado else None),
                    ("&Programación completa del canal…", (lambda: self.ventana.ver_programacion(canal)) if canal else None), None]
        if programa:
            consulta = quote_plus(programa.titulo)
            opciones += [(etiqueta, (lambda u=url: abrir_navegador(self, u + consulta))) for etiqueta, url in BUSCADORES]
            opciones += [None, ("&Copiar título", lambda: copiar_portapapeles(programa.titulo)), ("Copiar &detalles", lambda: copiar_portapapeles(self.detalle.GetValue()))]
        menu_desde(self.ventana, opciones, self.lista, fila)


class PanelVod(wx.Panel):
    """Películas y series de las cuentas de proveedor que las ofrezcan."""

    def __init__(self, parent, ventana: "VentanaPrincipal"):
        super().__init__(parent)
        self.ventana = ventana
        self.elementos: list[dict] = []
        self.mostrados: list[dict] = []
        self.serie_abierta: dict | None = None
        self.cargando = False
        self.generacion = 0
        caja = wx.BoxSizer(wx.VERTICAL)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.cuenta = campo(self, fila, "&Cuenta:", lambda: wx.Choice(self, choices=["Sin cuentas configuradas"]), 1)
        self.cuenta.SetSelection(0)
        self.cuenta.Bind(wx.EVT_CHOICE, lambda e: self.cargar())
        self.clase = campo(self, fila, "&Contenido:", lambda: wx.Choice(self, choices=["Películas", "Series"]), 0, False)
        self.clase.SetSelection(0)
        self.clase.Bind(wx.EVT_CHOICE, lambda e: self.cargar())
        caja.Add(fila, 0, wx.EXPAND | wx.ALL, 8)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.busqueda = campo(self, fila, "&Buscar:", lambda: wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER), 2)
        self.busqueda.Bind(wx.EVT_TEXT, lambda e: self.filtrar())
        self.busqueda.Bind(wx.EVT_TEXT_ENTER, lambda e: self.lista.SetFocus())
        self.categoria = campo(self, fila, "Cate&goría:", lambda: wx.Choice(self, choices=["Todas"]), 1)
        self.categoria.SetSelection(0)
        self.categoria.Bind(wx.EVT_CHOICE, lambda e: self.filtrar())
        caja.Add(fila, 0, wx.EXPAND | wx.ALL, 8)
        self.cuenta_texto = wx.StaticText(self, label="Configura una cuenta de proveedor en Herramientas, Canales y listas, para ver aquí sus películas y series.")
        caja.Add(self.cuenta_texto, 0, wx.LEFT | wx.RIGHT, 8)
        self.lista = ListaAccesible(self, "Películas y series. Intro reproduce o abre los episodios", "vod", ventana.datos.windows)
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.activar())
        self.lista.Bind(wx.EVT_LIST_ITEM_FOCUSED, lambda e: (e.Skip(), self.mostrar()))
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self.menu)
        caja.Add(self.lista, 3, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        caja.Add(wx.StaticText(self, label="Detalles:"), 0, wx.LEFT | wx.TOP, 8)
        self.detalle = nombrar(wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 80)), "Detalles del contenido")
        caja.Add(self.detalle, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        botones = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Reproducir", lambda e: self.activar()), boton(self, "&Volver a la lista", lambda e: self.volver()), boton(self, "&Actualizar", lambda e: self.cargar(True))):
            botones.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(botones, 0, wx.ALL, 8)
        self.SetSizer(caja)
        self.Bind(wx.EVT_SIZE, lambda e: (e.Skip(), wx.CallAfter(self.lista.ajustar_anchos)))

    # --- datos ---------------------------------------------------------------
    def cuentas(self) -> list:
        return self.ventana.cuentas()

    def actualizar_cuentas(self):
        cuentas = self.cuentas()
        self.cuenta.Set([c.nombre for c in cuentas] or ["Sin cuentas configuradas"])
        self.cuenta.SetSelection(0)
        self.cuenta_texto.SetLabel("Configura una cuenta de proveedor en Herramientas, Canales y listas, para ver aquí sus películas y series." if not cuentas else "Elige la cuenta y el tipo de contenido, y pulsa Actualizar.")
        if not cuentas:
            self.lista.rellenar([{"titulo": "No hay ninguna cuenta de proveedor configurada", "tipo": "", "categoria": ""}])

    def cuenta_actual(self):
        cuentas = self.cuentas()
        indice = self.cuenta.GetSelection()
        return cuentas[indice] if 0 <= indice < len(cuentas) else None

    def cargar(self, forzar: bool = False):
        cuenta = self.cuenta_actual()
        if cuenta is None or self.cargando:
            return
        self.serie_abierta = None
        self.cargando = True
        self.generacion += 1
        generacion = self.generacion
        clase = "series" if self.clase.GetSelection() == 1 else "peliculas"
        self.cuenta_texto.SetLabel(f"Consultando {'las series' if clase == 'series' else 'las películas'} de {cuenta.nombre}…")
        self.ventana.estado(self.cuenta_texto.GetLabel())
        threading.Thread(target=self._cargar_en_hilo, args=(generacion, cuenta, clase), daemon=True).start()

    def _cargar_en_hilo(self, generacion, cuenta, clase):
        try:
            elementos = xtream.series(cuenta) if clase == "series" else xtream.peliculas(cuenta)
            error = ""
        except Exception as fallo:
            registro.info("Error consultando %s: %s", clase, fallo)
            elementos, error = [], str(fallo)
        wx.CallAfter(self._cargado, generacion, elementos, error)

    def _cargado(self, generacion, elementos, error):
        self.cargando = False
        if generacion != self.generacion or self.ventana.cerrando:
            return
        self.elementos = elementos
        categorias = ["Todas"] + sorted({e.get("categoria", "") for e in elementos if e.get("categoria")})
        self.categoria.Set(categorias)
        self.categoria.SetSelection(0)
        if error:
            self.cuenta_texto.SetLabel("No se pudo consultar el catálogo: " + error)
            self.ventana.estado("No se pudo consultar el catálogo: " + error)
        else:
            self.cuenta_texto.SetLabel(f"{len(elementos)} elemento{'s' if len(elementos) != 1 else ''} en el catálogo.")
            self.ventana.estado(self.cuenta_texto.GetLabel())
        self.filtrar()

    def filtrar(self):
        texto = catalogo.plegar(self.busqueda.GetValue()).split()
        categoria = self.categoria.GetStringSelection() if self.categoria.GetSelection() > 0 else ""
        self.mostrados = [e for e in self.elementos
                          if (not categoria or e.get("categoria") == categoria)
                          and all(p in catalogo.plegar(e.get("titulo", "")) for p in texto)]
        filas = [fila_vod(e) for e in self.mostrados]
        vacio = "No hay resultados con ese filtro." if self.elementos else "Todavía no se ha cargado ningún catálogo."
        self.lista.rellenar(filas or [{"titulo": vacio, "tipo": "", "categoria": ""}], 0)
        self.lista.ajustar_anchos()
        self.mostrar()

    def elemento_actual(self) -> dict | None:
        return (self.lista.valores_actuales() or {}).get("_elemento")

    def mostrar(self):
        elemento = self.elemento_actual()
        if not elemento:
            self.detalle.SetValue("")
            return
        lineas = [elemento.get("titulo", ""), elemento.get("categoria", "")]
        if elemento.get("valoracion"):
            lineas.append("Valoración: " + elemento["valoracion"])
        if elemento.get("descripcion"):
            lineas.append(elemento["descripcion"])
        self.detalle.SetValue("\n".join(l for l in lineas if l))

    def activar(self):
        elemento = self.elemento_actual()
        if not elemento:
            return
        if elemento.get("clase") == "serie":
            self.abrir_serie(elemento)
            return
        if not elemento.get("url"):
            self.ventana.estado("Ese elemento no tiene una dirección de reproducción.")
            return
        self.ventana.reproducir_vod(elemento)

    def abrir_serie(self, serie: dict):
        cuenta = self.cuenta_actual()
        if cuenta is None:
            return
        self.ventana.estado(f"Consultando los episodios de {serie['titulo']}…")
        wx.BeginBusyCursor()
        try:
            episodios = xtream.episodios(cuenta, serie["identificador"])
        except Exception as error:
            episodios = []
            self.ventana.estado(f"No se pudieron obtener los episodios: {error}")
        finally:
            wx.EndBusyCursor()
        if not episodios:
            self.ventana.estado(f"{serie['titulo']} no tiene episodios disponibles.")
            return
        self.serie_abierta = serie
        for episodio in episodios:
            episodio["categoria"] = f"{serie['titulo']} · temporada {episodio['temporada']}"
        self.mostrados = episodios
        self.lista.rellenar([fila_vod(e) for e in episodios], 0)
        self.lista.ajustar_anchos()
        self.cuenta_texto.SetLabel(f"{serie['titulo']}: {len(episodios)} episodios. Usa Volver a la lista para salir.")
        self.ventana.estado(self.cuenta_texto.GetLabel())
        self.lista.SetFocus()

    def volver(self):
        if self.serie_abierta is None:
            return
        self.serie_abierta = None
        self.filtrar()
        self.lista.SetFocus()

    def menu(self, evento):
        fila = self.lista.menu_contextual_en_fila(evento)
        elemento = self.elemento_actual()
        opciones = [
            ("&Reproducir\tIntro", self.activar if elemento else None),
            ("&Episodios de la serie", (lambda: self.abrir_serie(elemento)) if elemento and elemento.get("clase") == "serie" else None),
            ("&Volver a la lista", self.volver if self.serie_abierta else None),
            None,
            ("&Copiar enlace", (lambda: copiar_portapapeles(elemento["url"])) if elemento and elemento.get("url") else None),
        ]
        menu_desde(self.ventana, opciones, self.lista, fila)


class PanelInformacion(wx.Panel):
    def __init__(self, parent, ventana: "VentanaPrincipal"):
        super().__init__(parent)
        self.ventana = ventana
        caja = wx.BoxSizer(wx.VERTICAL)
        self.texto = nombrar(wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 150)), "Información de la aplicación")
        caja.Add(self.texto, 2, wx.EXPAND | wx.ALL, 8)
        caja.Add(wx.StaticText(self, label="Listas de reproducción:"), 0, wx.LEFT, 8)
        self.listas = ListaAccesible(self, "Listas de reproducción. Menú contextual con la tecla Aplicaciones", "listas", ventana.datos.windows)
        self.listas.Bind(wx.EVT_CONTEXT_MENU, self.menu)
        self.listas.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.menu(e))
        caja.Add(self.listas, 2, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        botones = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Añadir lista…", lambda e: self.ventana.anadir_lista()), boton(self, "&Cuentas de proveedor…", lambda e: self.ventana.ejecutar("herr_cuentas")), boton(self, "&Quitar lista", lambda e: self.quitar_lista()), boton(self, "Copia de &seguridad…", lambda e: self.ventana.ejecutar("herr_respaldo")), boton(self, "Aviso &legal y fuentes", lambda e: self.ventana.ejecutar("ayuda_legal")), boton(self, "Carpeta de &datos", lambda e: self.abrir_datos())):
            botones.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(botones, 0, wx.ALL, 8)
        self.SetSizer(caja)
        self.Bind(wx.EVT_SIZE, lambda e: (e.Skip(), wx.CallAfter(self.listas.ajustar_anchos)))
        self.rellenar()

    def rellenar(self):
        datos = self.ventana.datos
        ultima = datos.windows.get("ultimaComprobacion") or 0
        marca = time.strftime("%d/%m/%Y %H:%M", time.localtime(ultima)) if ultima else "todavía no"
        lineas = [
            f"{NOMBRE_APP} {VERSION}",
            f"{LEMA}. Desarrollado por {AUTOR}.",
            "Esta aplicación no emite ni distribuye ningún contenido. Al reproducir un canal se conecta al servidor de la emisora, que emite bajo sus propios términos.",
            f"Última sincronización con el servidor: {marca}. Al iniciar: {TEXTO_FRECUENCIA.get(datos.windows.get('frecuenciaActualizacion', 'nunca'), '').lower()}.",
            f"Canales cargados: {sum(1 for c in self.ventana.canales if c.tipo == 'tv')} de televisión y {sum(1 for c in self.ventana.canales if c.tipo == 'radio')} de radio.",
            f"Reproductor: {self.ventana.version_mpv or ('libmpv en data/mpv' if modulo_datos.ruta_libmpv(datos) else 'libmpv no instalado')}.",
            f"Carpeta de datos: {datos.raiz}",
        ]
        cuentas = datos.windows.get("cuentas") or []
        if cuentas:
            lineas.append(f"Cuentas de proveedor configuradas: {len(cuentas)}.")
        grabaciones = grabacion.archivos(datos)
        if grabaciones:
            total = sum(g["tamano"] for g in grabaciones) / 1e6
            lineas.append(f"Grabaciones guardadas: {len(grabaciones)} ({total:.0f} megabytes) en {grabacion.carpeta(datos)}.")
        en_curso = self.ventana.grabaciones_en_curso()
        if en_curso:
            detalle = "; ".join(f"{g['canal']} desde hace {grabacion.duracion_hablada(g['transcurrido'])}" for g in en_curso)
            lineas.append(f"Grabando ahora en segundo plano: {detalle}. Se paran desde Herramientas, Grabación, Grabaciones.")
        perfil = datos.windows.get("perfilActual")
        if perfil:
            lineas.append(f"Perfil en uso: {perfil}.")
        if self.ventana.avisos_carga:
            lineas.append("Avisos: " + " ".join(self.ventana.avisos_carga))
        self.texto.SetValue("\n".join(lineas))
        filas = [fila_lista(NOMBRE_LISTA_OFICIAL[t], URL_LISTAS[t][0], t, False) for t in TIPOS]
        for lista in datos.windows["listas"]:
            filas.append(fila_lista(lista["nombre"], lista.get("url") or lista.get("ruta", ""), lista["tipo"], True))
        for entrada in cuentas:
            filas.append(fila_lista(entrada["nombre"], entrada["servidor"], entrada.get("tipo", "tv"), True, "cuenta"))
        self.listas.rellenar(filas, 0)
        self.listas.ajustar_anchos()

    def menu(self, evento):
        fila = self.listas.menu_contextual_en_fila(evento) if hasattr(evento, "GetPosition") else self.listas.fila_actual()
        valores = self.listas.valores_actuales() or {}
        opciones = [("&Añadir lista…", self.ventana.anadir_lista), ("&Quitar esta lista", self.quitar_lista if valores.get("_propia") else None), None, ("&Copiar dirección", (lambda: copiar_portapapeles(valores["_url"])) if valores.get("_url") else None), ("Abrir en el &navegador", (lambda: abrir_navegador(self, valores["_url"])) if valores.get("_url") else None)]
        menu_desde(self.ventana, opciones, self.listas, fila)

    def quitar_lista(self):
        valores = self.listas.valores_actuales() or {}
        if not valores.get("_url"):
            return
        if not valores.get("_propia"):
            aviso(self, "Las listas oficiales no se pueden quitar.")
            return
        if valores.get("_clase") == "cuenta":
            self.ventana.ejecutar("herr_cuentas")
            return
        if pregunta(self, f"¿Quitar la lista «{valores['nombre']}»?"):
            direccion = valores["_url"]
            self.ventana.datos.windows["listas"] = [l for l in self.ventana.datos.windows["listas"] if l.get("url") != direccion and l.get("ruta") != direccion]
            self.ventana.datos.guardar()
            self.ventana.cargar(refrescar=False)

    def abrir_datos(self):
        try:
            import os
            os.startfile(str(self.ventana.datos.raiz))
        except OSError:
            aviso(self, f"Carpeta de datos: {self.ventana.datos.raiz}")


# --- diálogos de teclas y favoritos -----------------------------------------------
class DialogoCapturaTecla(wx.Dialog):
    """Espera una pulsación y la devuelve en ``combo`` (Escape cancela, Retroceso quita la tecla)."""

    def __init__(self, parent, accion_texto: str):
        super().__init__(parent, title="Pulsa la nueva tecla")
        self.combo = None
        caja = wx.BoxSizer(wx.VERTICAL)
        texto = wx.StaticText(self, label=f"Pulsa la combinación para «{accion_texto}».\nEscape cancela; Retroceso deja la acción sin tecla.")
        caja.Add(texto, 0, wx.ALL, 16)
        self.campo = nombrar(wx.TextCtrl(self, value="", style=wx.TE_READONLY | wx.TE_CENTRE), "Combinación de teclas: pulsa la tecla que quieras")
        caja.Add(self.campo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        self.SetSizerAndFit(caja)
        self.SetMinSize((420, -1))
        self.campo.Bind(wx.EVT_KEY_DOWN, self._tecla)
        self.Bind(wx.EVT_CHAR_HOOK, self._tecla)
        self.campo.SetFocus()
        voz.decir("Pulsa la combinación de teclas nueva", interrumpir=True)

    def _tecla(self, evento):
        codigo = evento.GetKeyCode()
        if codigo == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        if codigo in (wx.WXK_BACK, wx.WXK_DELETE) and evento.GetModifiers() == wx.MOD_NONE:
            self.combo = ""
            self.EndModal(wx.ID_OK)
            return
        combo = modulo_teclas.evento_a_combo(evento)
        if combo:
            self.combo = combo
            self.campo.SetValue(modulo_teclas.legible(combo))
            self.EndModal(wx.ID_OK)


class DialogoTeclas(wx.Dialog):
    """Editor de teclas: lista accesible por secciones, cambiar, quitar y restaurar."""

    def __init__(self, parent: "VentanaPrincipal"):
        super().__init__(parent, title="Personalizar teclas", size=(760, 560), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        self.teclas = parent.teclas
        caja = wx.BoxSizer(wx.VERTICAL)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.seccion = campo(self, fila, "&Sección:", lambda: wx.Choice(self, choices=modulo_teclas.SECCIONES), 1)
        self.seccion.SetSelection(0)
        self.seccion.Bind(wx.EVT_CHOICE, lambda e: self.rellenar())
        caja.Add(fila, 0, wx.EXPAND | wx.ALL, 8)
        caja.Add(wx.StaticText(self, label="Acciones (Intro cambia la tecla; las del reproductor valen en toda la aplicación y solo admiten teclas de función o con Ctrl o Alt):"), 0, wx.LEFT | wx.RIGHT, 8)
        self.lista = ListaAccesible(self, "Acciones y teclas", "teclas", parent.datos.windows)
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.cambiar())
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self.menu)
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        botones = wx.WrapSizer(wx.HORIZONTAL)
        for control in (boton(self, "&Cambiar…", lambda e: self.cambiar()), boton(self, "&Quitar tecla", lambda e: self.quitar()), boton(self, "&Restaurar esta", lambda e: self.restaurar("una")), boton(self, "Restaurar &sección", lambda e: self.restaurar("seccion")), boton(self, "Restaurar &todas", lambda e: self.restaurar("todas")), wx.Button(self, wx.ID_CANCEL, "C&errar")):
            botones.Add(control, 0, wx.RIGHT | wx.BOTTOM, 4)
        caja.Add(botones, 0, wx.ALL, 8)
        self.SetSizer(caja)
        self.rellenar()
        self.lista.ajustar_anchos()
        self.lista.SetFocus()

    def rellenar(self, conservar: str | None = None):
        seccion = modulo_teclas.SECCIONES[max(0, self.seccion.GetSelection())]
        acciones = self.teclas.acciones_de(seccion)
        filas = [{"accion": self.teclas.etiqueta(a, False), "tecla": modulo_teclas.legible(self.teclas.combo(a)), "estado": "personalizada" if self.teclas.es_personalizada(a) else "predeterminada", "_accion": a} for a in acciones]
        indice = next((i for i, a in enumerate(acciones) if a == conservar), 0)
        self.lista.rellenar(filas, indice)

    def accion_actual(self) -> str | None:
        return (self.lista.valores_actuales() or {}).get("_accion")

    def aplicar(self, accion: str, combo: str):
        etiqueta = self.teclas.etiqueta(accion, False)
        if combo and self.teclas.es_reservada(combo):
            aviso(self, f"{modulo_teclas.legible(combo)} está reservada para las listas y los campos de texto; no se puede asignar.", icono=wx.ICON_WARNING)
            return
        if combo and accion in modulo_teclas.ACCIONES_GLOBALES and not modulo_teclas.valida_global(combo):
            aviso(self, "Las teclas del reproductor funcionan en toda la aplicación: usa una tecla de función (F1 a F12) o una combinación con Ctrl o Alt.", icono=wx.ICON_WARNING)
            return
        choca = self.teclas.conflicto(accion, combo) if combo else None
        if choca and not pregunta(self, f"{modulo_teclas.legible(combo)} ya la usa «{self.teclas.etiqueta(choca, False)}».\n¿Quitársela y asignarla a «{etiqueta}»?"):
            return
        if choca:
            self.teclas.establecer(choca, "")
        self.teclas.establecer(accion, combo)
        self.ventana.aplicar_teclas()
        self.rellenar(accion)
        self.ventana.estado(f"{etiqueta}: {modulo_teclas.legible(combo)}.")

    def cambiar(self):
        accion = self.accion_actual()
        if not accion:
            return
        with DialogoCapturaTecla(self, self.teclas.etiqueta(accion, False)) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK or dialogo.combo is None:
                return
            combo = dialogo.combo
        self.aplicar(accion, combo)

    def quitar(self):
        accion = self.accion_actual()
        if accion:
            self.aplicar(accion, "")

    def restaurar(self, alcance: str):
        accion = self.accion_actual()
        if alcance == "una" and accion:
            self.teclas.restaurar(accion=accion)
        elif alcance == "seccion":
            self.teclas.restaurar(seccion=modulo_teclas.SECCIONES[max(0, self.seccion.GetSelection())])
        elif alcance == "todas":
            if not pregunta(self, "¿Restaurar todas las teclas a sus valores predeterminados?"):
                return
            self.teclas.restaurar()
        self.ventana.aplicar_teclas()
        self.rellenar(accion)
        self.ventana.estado("Teclas restauradas.")

    def menu(self, evento):
        fila = self.lista.menu_contextual_en_fila(evento)
        menu_desde(self, [("&Cambiar tecla…\tIntro", self.cambiar), ("&Quitar tecla", self.quitar), ("&Restaurar esta", lambda: self.restaurar("una"))], self.lista, fila)


class DialogoFavoritos(wx.Dialog):
    """Diálogo rápido de favoritos (tecla F1): Intro reproduce el canal elegido."""

    def __init__(self, parent: "VentanaPrincipal"):
        super().__init__(parent, title="Canales favoritos", size=(720, 480), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.ventana = parent
        datos = parent.datos
        self.canales = [c for c in parent.canales if datos.estado_canal(c.tipo, c.nombre)["favorite"]]
        caja = wx.BoxSizer(wx.VERTICAL)
        caja.Add(wx.StaticText(self, label="Favoritos de televisión y radio. Intro reproduce; Escape cierra."), 0, wx.ALL, 10)
        self.lista = ListaAccesible(self, "Canales favoritos. Intro reproduce", "favoritos", datos.windows)
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.reproducir())
        self.lista.Bind(wx.EVT_CONTEXT_MENU, self.menu)
        caja.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        fila.Add(boton(self, "&Reproducir", lambda e: self.reproducir()), 0, wx.RIGHT, 6)
        fila.Add(boton(self, "&Quitar de favoritos", lambda e: self.quitar()), 0, wx.RIGHT, 6)
        fila.Add(wx.Button(self, wx.ID_CANCEL, "&Cerrar"), 0)
        caja.Add(fila, 0, wx.ALL, 10)
        self.SetSizer(caja)
        self.rellenar()
        self.lista.ajustar_anchos()
        self.lista.SetFocus()

    def rellenar(self):
        filas = []
        for canal in self.canales:
            valores = fila_canal(canal, self.ventana.datos, self.ventana.guia.get(canal.tipo, {}))
            filas.append({"nombre": canal.nombre, "tipo": NOMBRE_TIPO[canal.tipo], "ahora": valores["ahora"], "categoria": canal.ambito, "_canal": canal})
        self.lista.rellenar(filas or [{"nombre": "No tienes ningún favorito. Añade alguno con Ctrl+D en la lista de canales.", "tipo": "", "ahora": ""}], 0)

    def canal(self) -> Canal | None:
        return (self.lista.valores_actuales() or {}).get("_canal")

    def reproducir(self):
        canal = self.canal()
        if canal:
            self.EndModal(wx.ID_OK)
            self.ventana.reproducir_canal(canal)

    def quitar(self):
        canal = self.canal()
        if not canal:
            return
        self.ventana.datos.fijar_estado_canal(canal.tipo, canal.nombre, favorite=False)
        self.ventana.datos.guardar()
        self.canales.remove(canal)
        self.rellenar()
        self.ventana.paneles[canal.tipo].refrescar()
        self.ventana.estado(f"{canal.nombre}: quitado de favoritos.")

    def menu(self, evento):
        fila = self.lista.menu_contextual_en_fila(evento)
        canal = self.canal()
        menu_desde(self, [("&Reproducir\tIntro", self.reproducir), ("&Programación…", (lambda: self.ventana.ver_programacion(canal)) if canal else None), ("&Quitar de favoritos", self.quitar)], self.lista, fila)


class VentanaVideo(wx.Frame):
    """Ventana donde se ve la imagen, solo cuando se pide.

    De fábrica **no se abre sola**: el sonido va por su cuenta y quien no
    necesite la imagen no se encuentra con una ventana que no hace nada. Se
    abre y se cierra con la tecla de vídeo, y cuando está abierta tiene texto
    que explica qué se puede hacer y dos botones, además de Escape para
    cerrarla y espacio para pausar.
    """

    def __init__(self, ventana_principal):
        super().__init__(ventana_principal, title=f"Vídeo · {NOMBRE_APP}", size=(900, 560))
        self.ventana_principal = ventana_principal
        self.completa = False
        panel = wx.Panel(self)
        caja = wx.BoxSizer(wx.VERTICAL)
        self.video = nombrar(wx.Panel(panel, style=wx.BORDER_NONE), "Imagen de la emisión")
        self.video.SetBackgroundColour(wx.BLACK)
        self.video.Bind(wx.EVT_LEFT_DCLICK, lambda e: self.alternar_completa())
        caja.Add(self.video, 1, wx.EXPAND)
        caja.Add(wx.StaticText(panel, label="&Qué se puede hacer aquí:"), 0, wx.LEFT | wx.TOP, 8)
        self.info = nombrar(wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 56)), "Qué se puede hacer en la ventana de vídeo")
        caja.Add(self.info, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        fila.Add(boton(panel, "&Cerrar esta ventana", lambda e: self.ocultar()), 0, wx.RIGHT, 6)
        fila.Add(boton(panel, "&Pantalla completa", lambda e: self.alternar_completa()), 0)
        caja.Add(fila, 0, wx.LEFT | wx.BOTTOM, 8)
        panel.SetSizer(caja)
        self.panel = panel
        self.Bind(wx.EVT_CHAR_HOOK, self._teclas)
        self.Bind(wx.EVT_CLOSE, self._al_cerrar)

    def _teclas(self, evento):
        if evento.GetKeyCode() == wx.WXK_ESCAPE and evento.GetModifiers() == wx.MOD_NONE:
            self.ocultar()
            return
        if evento.GetKeyCode() == wx.WXK_SPACE and evento.GetModifiers() == wx.MOD_NONE and not isinstance(wx.Window.FindFocus(), wx.Button):
            self.ventana_principal.pausar()
            return
        evento.Skip()

    def _al_cerrar(self, evento):
        # Nunca se destruye mientras exista el reproductor: libmpv dibuja en este panel.
        if evento.CanVeto() and not self.ventana_principal.cerrando:
            evento.Veto()
            self.ocultar()
            return
        self.Destroy()

    def _texto_ayuda(self) -> str:
        teclas = self.ventana_principal.teclas
        return (f"Escape cierra esta ventana y el sonido sigue. Espacio pausa. "
                f"{modulo_teclas.legible(teclas.combo('repro_pantalla_completa'))} pone la imagen a pantalla completa "
                f"y {modulo_teclas.legible(teclas.combo('repro_video'))} muestra u oculta esta ventana. "
                "Las demás teclas del reproductor también funcionan aquí.")

    def mostrar(self, titulo: str = "", activar: bool = True):
        """Muestra la ventana. Con ``activar`` en falso no se lleva el foco."""
        if titulo:
            self.SetTitle(f"{titulo} · {NOMBRE_APP}")
        self.info.SetValue(self._texto_ayuda())
        if not self.IsShown():
            if activar:
                self.Show()
            else:
                self.ShowWithoutActivating()
        if activar:
            self.Raise()

    def ocultar(self, avisar: bool = True):
        """Esconde la ventana de vídeo. Con ``avisar=False`` no dice nada.

        Quien la oculta porque se ha detenido la reproducción ya dice lo suyo;
        decir ahí «el sonido continúa» era mentira y despistaba.
        """
        if self.completa:
            self.alternar_completa()
        self.Hide()
        principal = self.ventana_principal
        principal.Raise()
        panel = principal.panel_activo()
        (panel.lista if panel is not None else principal).SetFocus()
        if not avisar:
            return
        sonando = principal.reproductor is not None and principal.reproductor.activo
        principal.estado("Ventana de vídeo oculta; el sonido continúa." if sonando else "Ventana de vídeo oculta.")

    def alternar_completa(self):
        self.completa = not self.completa
        self.mostrar()
        self.ShowFullScreen(self.completa, wx.FULLSCREEN_ALL)
        self.video.SetFocus()
        principal = self.ventana_principal
        if self.completa:
            principal.estado(f"Pantalla completa. Escape o {modulo_teclas.legible(principal.teclas.combo('repro_pantalla_completa'))} para salir; espacio pausa.")
        else:
            principal.estado("Pantalla normal.")


class FiltroTeclas(wx.EventFilter):
    """Teclas del reproductor (F1 a F12) en toda la aplicación, también con diálogos abiertos."""

    def __init__(self, ventana: "VentanaPrincipal"):
        super().__init__()
        self.ventana = ventana
        wx.EvtHandler.AddFilter(self)

    def FilterEvent(self, evento):
        try:
            if evento.GetEventType() == wx.wxEVT_KEY_DOWN and not self.ventana.cerrando:
                if isinstance(wx.GetActiveWindow(), DialogoCapturaTecla):
                    return self.Event_Skip
                # El navegador integrado gestiona sus propias teclas. Cuando el foco
                # está en la página, quien actúa es su script; aquí solo se bloquea el
                # efecto que Windows daría a esa tecla (F6 cambiaría de panel).
                foco = wx.Window.FindFocus()
                ventana = wx.GetTopLevelParent(foco) if foco is not None else None
                if isinstance(ventana, navegador.VentanaNavegador):
                    combo = modulo_teclas.evento_a_combo(evento)
                    propias = [ventana.ventana_principal.teclas.combo("nav_zonas")] if ventana.ventana_principal else []
                    propias += [self.ventana.teclas.combo(a) for a in modulo_teclas.ACCIONES_GLOBALES]
                    if combo and combo in propias and ventana.foco_en_pagina():
                        return self.Event_Processed
                    return self.Event_Skip

                # Atajo universal para cambiar de pestaña (Ctrl+Tab, Ctrl+Shift+Tab, Ctrl+AvPág, Ctrl+RePág)
                tecla = evento.GetKeyCode()
                mod = evento.GetModifiers()
                if (mod == wx.MOD_CONTROL and tecla in (wx.WXK_TAB, wx.WXK_PAGEDOWN)) or \
                   (mod == (wx.MOD_CONTROL | wx.MOD_SHIFT) and tecla == wx.WXK_TAB) or \
                   (mod == wx.MOD_CONTROL and tecla == wx.WXK_PAGEUP):
                    libro = None
                    if ventana is not None:
                        libro = getattr(ventana, "libro", None)
                    if not isinstance(libro, wx.Notebook):
                        activa = wx.GetActiveWindow()
                        libro = getattr(activa, "libro", None) if activa is not None else None
                    if not isinstance(libro, wx.Notebook):
                        libro = getattr(self.ventana, "libro", None)
                    if isinstance(libro, wx.Notebook) and libro.GetPageCount() > 1:
                        direccion = -1 if (mod & wx.MOD_SHIFT or tecla == wx.WXK_PAGEUP) else 1
                        nueva = (libro.GetSelection() + direccion) % libro.GetPageCount()
                        libro.SetSelection(nueva)
                        return self.Event_Processed

                accion = self.ventana.teclas.accion_global(evento)
                if accion:
                    wx.CallAfter(self.ventana.ejecutar, accion)
                    return self.Event_Processed
        except Exception:
            registro.exception("Error en el filtro de teclas")
        return self.Event_Skip

    def quitar(self):
        try:
            wx.EvtHandler.RemoveFilter(self)
        except Exception:
            pass


# --- ventana principal ---------------------------------------------------------
class VentanaPrincipal(wx.Frame):
    def __init__(self, datos: modulo_datos.Datos, autocargar: bool = True):
        super().__init__(None, title=f"{NOMBRE_APP} · Televisión y radio", size=(1280, 840))
        self.SetMinSize((900, 620))
        self.datos = datos
        self.teclas = modulo_teclas.Teclas(datos.windows)
        self.canales: list[Canal] = []
        self.guia: dict[str, dict] = {"tv": {}, "radio": {}}
        self.avisos_carga: list[str] = []
        self.reproductor: Reproductor | None = None
        self.version_mpv = ""
        self.canal_actual: Canal | None = None
        self.emision_actual: Emision | None = None
        self.canal_anterior: Canal | None = None
        self.navegador = None
        self.navegador_activo = None
        self.generacion = 0
        self.generacion_reproduccion = 0
        self.carga_en_curso = False
        self.pantalla_completa = False
        self.ventana_video = None
        self.temporizador_fin: float | None = None
        self.icono_bandeja = None
        self.cerrando = False
        self.ultimo_minuto = int(time.time() // 60)
        self.grabador = None
        self.video_avisado = False
        self.recargar_por_buffer = False
        self.grabacion_programada: dict | None = None
        self.grabaciones_fondo: grabacion.GestorFondo | None = None   # se crea al grabar por primera vez
        self.programadas_fondo: dict[str, dict] = {}                  # clave de grabación → entrada programada
        self.mosaico = None                       # ventana de multiventana, si está abierta
        self.archivo_reproduciendo: str | None = None   # grabación guardada que se está viendo
        self.ultimo_espacio = 0.0                 # última comprobación del espacio en disco
        self.ultimo_aviso_grabacion = 0.0         # último aviso hablado de las grabaciones
        self.ultima_posicion = 0.0                # última vez que se anotó por dónde va la grabación
        self.ultimas_reglas = 0.0                 # última vez que se aplicaron las reglas
        self.teclas_globales: globales.TeclasGlobales | None = None
        self.intentos = 0
        self.reintento_pendiente = None
        self.emisiones_probadas: set[str] = set()
        self.aplicar_accesibilidad()
        self.CreateStatusBar()
        self.definir_acciones()
        self.construir_menu()
        self.construir_interfaz()
        self.aplicar_apariencia()
        self.filtro_teclas = FiltroTeclas(self)
        self.Bind(wx.EVT_CLOSE, self.al_cerrar)
        self.Bind(wx.EVT_ICONIZE, self.al_minimizar)
        self.Bind(wx.EVT_CHAR_HOOK, self._al_pulsar_ventana)
        self.reloj = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.tic, self.reloj)
        self.reloj.Start(1000)
        self.paneles["tv"].busqueda.SetFocus()
        if datos.aviso:
            wx.CallAfter(aviso, self, datos.aviso, "Ajustes recuperados", wx.ICON_WARNING)
        self.teclas_globales = globales.TeclasGlobales(self)
        self.aplicar_teclas_globales(avisar=False)
        if autocargar:
            wx.CallAfter(self.cargar, modulo_datos.toca_actualizar(self.datos.windows))
            wx.CallAfter(self.comprobar_mpv_al_iniciar)
            wx.CallAfter(self.comprobar_app_al_iniciar)

    # --- acciones y menús (dinámicos: salen del catálogo de teclas) --------------------
    def definir_acciones(self):
        self.acciones = {
            "archivo_actualizar": lambda: self.cargar(True),
            "archivo_lista": self.anadir_lista,
            "archivo_cuenta": self.anadir_cuenta,
            "archivo_iptvorg": self.anadir_iptvorg,
            "archivo_exportar": self.exportar,
            "archivo_importar": self.importar,
            "archivo_exportar_m3u": self.exportar_m3u,
            "archivo_bandeja": self.a_bandeja,
            "archivo_salir": self.salir,
            "buscar": self.enfocar_busqueda,
            "canal_reproducir": self.reproducir_seleccion,
            "canal_web": self.abrir_web,
            "canal_programacion": self.ver_programacion,
            "canal_guia": self.ir_a_guia,
            "canal_favorito": self.alternar_favorito,
            "canal_ocultar": self.alternar_oculto,
            "canal_copiar": self.copiar_enlace,
            "canal_info": self.leer_info_canal,
            "canal_subir": lambda: self.mover(-1),
            "canal_bajar": lambda: self.mover(1),
            "canal_quitar_orden": lambda: self.mover(0),
            "canal_bloquear": lambda: self.alternar_bloqueo(),
            "canal_numero": self.ir_a_numero,
            "repro_favoritos": self.dialogo_favoritos,
            "repro_pausa": self.pausar,
            "repro_recargar": self.recargar,
            "repro_detener": self.detener,
            "repro_bajar_volumen": lambda: self.cambiar_volumen(-5),
            "repro_subir_volumen": lambda: self.cambiar_volumen(5),
            "repro_anterior": lambda: self.zapping(-1),
            "repro_siguiente": lambda: self.zapping(1),
            "repro_silencio": self.alternar_silencio,
            "repro_video": self.mostrar_video,
            "repro_pantalla_completa": self.alternar_pantalla_completa,
            "repro_estado": self.decir_estado,
            "repro_volver": self.volver_anterior,
            "repro_audio": lambda: self.elegir_pista("audio"),
            "repro_subtitulos": lambda: self.elegir_pista("sub"),
            "repro_tamano": self.elegir_modo_imagen,
            "repro_temporizador": self.temporizador,
            "repro_grabar": self.alternar_grabacion,
            "repro_retroceder": self.retroceder_directo,
            "repro_directo": self.volver_al_directo,
            "repro_calidad": self.elegir_calidad,
            "repro_estadisticas": self.ver_estadisticas,
            "repro_solo_audio": self.alternar_solo_audio,
            "repro_enviar": self.enviar_a_tele,
            "repro_historial": self.ver_historial,
            "repro_mosaico": self.abrir_mosaico,
            "repro_nivelador": self.alternar_nivelador,
            "repro_velocidad": self.elegir_velocidad,
            "repro_desfase": self.ajustar_desfase,
            "herr_ajustes": self.ajustes,
            "herr_teclas": self.editar_teclas,
            "herr_teclas_globales": self.editar_teclas_globales,
            "herr_plantillas": self.editar_plantillas,
            "herr_categorias": self.ambitos_visibles,
            "herr_recordatorios": lambda: DialogoRecordatorios(self, self.datos).ShowModal(),
            "herr_buscar_guia": self.buscar_en_guia,
            "herr_guias": self.configurar_guias,
            "herr_cobertura": self.ver_cobertura,
            "herr_grabaciones": self.ver_grabaciones,
            "herr_reglas": self.gestionar_reglas,
            "herr_ahora": self.ver_ahora,
            "herr_comprobar": self.comprobar_canales,
            "herr_sincronizar": self.sincronizar_nube,
            "herr_cuentas": self.gestionar_cuentas,
            "herr_duplicados": self.ver_duplicados,
            "herr_pin": self.configurar_pin,
            "herr_dns": self.configurar_dns,
            "herr_perfiles": self.gestionar_perfiles,
            "herr_respaldo": self.copia_seguridad,
            "herr_addon": self.instalar_addon,
            "herr_actualizar_app": self.comprobar_app,
            "herr_mpv": lambda: self.comprobar_mpv(manual=True),
            "herr_cache": self.limpiar_cache,
            "ayuda_uso": self.ayuda,
            "ayuda_manual": self.manual,
            "ayuda_teclas": self.ayuda_teclas,
            "ayuda_registro": self.ver_registro,
            "ayuda_legal": self.aviso_legal,
            "ayuda_acerca": self.acerca_de,
        }

    def ejecutar(self, accion: str):
        """Ejecuta una acción del catálogo (menús, menús contextuales y teclas globales)."""
        manejador = self.acciones.get(accion)
        if manejador is None:
            return
        try:
            manejador()
        except Exception:
            registro.exception("Error al ejecutar %s", accion)
            self.estado(f"No se pudo completar la acción {self.teclas.etiqueta(accion, False)}.")

    MENUS = [
        ("&Archivo", ["archivo_actualizar", "archivo_lista", "archivo_iptvorg", "archivo_cuenta", None, "archivo_exportar", "archivo_importar", "archivo_exportar_m3u", None, "archivo_bandeja", "archivo_salir"]),
        ("&Canal", ["canal_reproducir", "canal_web", "canal_programacion", "canal_guia", "canal_favorito", "canal_ocultar", "canal_copiar", "canal_info", None, "canal_numero", "canal_subir", "canal_bajar", "canal_quitar_orden", None, "canal_bloquear"]),
        ("&Reproducción", ["repro_favoritos", "repro_pausa", "repro_recargar", "repro_detener", None, "repro_bajar_volumen", "repro_subir_volumen", "repro_silencio", None, "repro_anterior", "repro_siguiente", "repro_volver", "repro_historial", None, "repro_video", "repro_pantalla_completa", "repro_mosaico", "repro_solo_audio", "repro_audio", "repro_subtitulos", "repro_tamano", "repro_calidad", "repro_nivelador", "repro_velocidad", "repro_desfase", None, "repro_grabar", "repro_retroceder", "repro_directo", "repro_enviar", None, "repro_temporizador", "repro_estadisticas", "repro_estado"]),
        ("&Herramientas", [
            "buscar", "herr_ajustes", None,
            ("&Guía y recordatorios", ["herr_buscar_guia", "herr_ahora", "herr_recordatorios", None, "herr_guias", "herr_cobertura"]),
            ("G&rabación", ["herr_grabaciones", "herr_reglas"]),
            ("&Canales y listas", ["herr_cuentas", "herr_categorias", "herr_duplicados"]),
            ("Acc&esibilidad y teclas", ["herr_teclas", "herr_teclas_globales", "herr_plantillas"]),
            ("&Privacidad", ["herr_pin", "herr_perfiles"]),
            ("C&opias de seguridad", ["herr_respaldo", "herr_sincronizar"]),
            ("&Solucionar problemas", ["herr_comprobar", "herr_dns", "herr_cache"]),
            ("&Mantenimiento", ["herr_actualizar_app", "herr_mpv", "herr_addon"]),
        ]),
        ("A&yuda", ["ayuda_uso", "ayuda_manual", "ayuda_teclas", None, "ayuda_registro", "ayuda_legal", "ayuda_acerca"]),
    ]

    def _llenar_menu(self, menu, entradas):
        """Añade a ``menu`` las entradas: acción, None para separador o (título, entradas) para submenú."""
        for entrada in entradas:
            if entrada is None:
                menu.AppendSeparator()
                continue
            if isinstance(entrada, tuple):
                titulo, dentro = entrada
                submenu = wx.Menu()
                self._llenar_menu(submenu, dentro)
                menu.AppendSubMenu(submenu, titulo)
                continue
            elemento = menu.Append(wx.ID_ANY, self.teclas.etiqueta_menu(entrada))
            self.Bind(wx.EVT_MENU, lambda e, a=entrada: self.ejecutar(a), elemento)

    def construir_menu(self):
        barra = wx.MenuBar()
        for titulo, entradas in self.MENUS:
            menu = wx.Menu()
            self._llenar_menu(menu, entradas)
            barra.Append(menu, titulo)
        anterior = self.GetMenuBar()
        self.SetMenuBar(barra)
        if anterior is not None:
            anterior.Destroy()

    def aplicar_teclas(self):
        """Tras cambiar una tecla: menús nuevos, mapa global y navegador actualizados."""
        self.construir_menu()
        self.teclas._mapa_global = None
        if self.navegador is not None:
            try:
                self.navegador.actualizar_script()
                self.navegador.inyectar()
            except Exception:
                registro.debug("No se pudo actualizar el script del navegador", exc_info=True)

    def editar_teclas(self):
        with DialogoTeclas(self) as dialogo:
            dialogo.ShowModal()

    def construir_interfaz(self):
        """Ventana principal: solo las listas.

        El reproductor se maneja con las teclas de función; la imagen, si la
        hay, se ve en una ventana aparte que solo se abre cuando se pide.
        """
        self.panel = wx.Panel(self)
        exterior = wx.BoxSizer(wx.VERTICAL)
        self.libro = configurar_notebook_accesible(wx.Notebook(self.panel), "Secciones: Televisión, Radio, Guía, Películas y series, e Información")
        self.paneles = {"tv": PanelCanales(self.libro, self, "tv"), "radio": PanelCanales(self.libro, self, "radio")}
        self.libro.AddPage(self.paneles["tv"], "Televisión")
        self.libro.AddPage(self.paneles["radio"], "Radio")
        self.panel_guia = PanelGuia(self.libro, self)
        self.libro.AddPage(self.panel_guia, "Guía")
        self.panel_vod = PanelVod(self.libro, self)
        self.libro.AddPage(self.panel_vod, "Películas y series")
        self.panel_info = PanelInformacion(self.libro, self)
        self.libro.AddPage(self.panel_info, "Información")
        exterior.Add(self.libro, 1, wx.EXPAND | wx.ALL, 6)
        self.panel.SetSizer(exterior)
        self.texto_estado = "Sin reproducción"
        self.pistas_audio: list[tuple[int, str]] = []
        self.pistas_sub: list[tuple[int, str]] = []

    # --- apariencia --------------------------------------------------------------
    def aplicar_accesibilidad(self):
        acc = self.datos.windows["accesibilidad"]
        voz.configurar(acc["voz"], acc["braille"], acc["retardoVoz"])
        accesible.preferencias.update({"decirFila": acc["decirFila"], "decirColumna": acc["decirColumna"], "decirCelda": acc["decirCelda"]})
        try:
            sonidos.preparar(self.datos)
        except OSError:
            registro.debug("No se pudieron preparar los sonidos", exc_info=True)
        sonidos.configurar(self.datos.windows.get("sonidos", True), self.datos.windows.get("avisosSonido") or {})

    def aplicar_teclas_globales(self, avisar: bool = True):
        """Activa o desactiva las teclas que funcionan con la aplicación en segundo plano."""
        if self.teclas_globales is None:
            return
        activar = bool(self.datos.windows.get("interfazInvisible"))
        fallidas = self.teclas_globales.aplicar(activar, self.datos.windows)
        if not avisar:
            return
        if activar and fallidas:
            self.estado("Interfaz invisible activada, pero otras aplicaciones ya usan: " + ", ".join(modulo_teclas.legible(f) for f in fallidas) + ".")
        elif activar:
            self.estado("Interfaz invisible activada: las teclas del reproductor funcionan aunque estés en otro programa.")
        else:
            self.estado("Interfaz invisible desactivada.")

    def aplicar_apariencia(self):
        windows, usuario = self.datos.windows, self.datos.usuario
        fuente = wx.Font(wx.FontInfo(windows["tamanoLetra"]))
        oscuro = usuario["darkMode"] == "1" or (usuario["darkMode"] == "2" and wx.SystemSettings.GetAppearance().IsDark())
        if windows["altoContraste"]:
            fondo, texto = wx.Colour(0, 0, 0), wx.Colour(255, 255, 0)
        elif oscuro:
            fondo, texto = wx.Colour(30, 30, 30), wx.Colour(240, 240, 240)
        else:
            fondo, texto = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW), wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        fondo_panel = fondo if (oscuro or windows["altoContraste"]) else wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE)

        def aplicar(ventana):
            ventana.SetFont(fuente)
            if isinstance(ventana, wx.Panel) and ventana.GetName() == "Vídeo de la emisión":
                return
            if isinstance(ventana, (wx.TextCtrl, wx.ListBox, wx.CheckListBox, wx.ListCtrl)):
                ventana.SetBackgroundColour(fondo)
                ventana.SetForegroundColour(texto)
            elif isinstance(ventana, (wx.Panel, wx.StaticText, wx.CheckBox, wx.Notebook)):
                ventana.SetBackgroundColour(fondo_panel)
                ventana.SetForegroundColour(texto)
            for hijo in ventana.GetChildren():
                aplicar(hijo)

        aplicar(self.panel)
        self.panel.Layout()
        self.Refresh()

    # --- avisos ------------------------------------------------------------------
    def estado(self, texto: str, decir: bool = True):
        self.SetStatusText(texto)
        if decir and self.datos.windows["accesibilidad"]["anunciarAvisos"]:
            voz.decir(texto, interrumpir=True)

    def estado_reproduccion(self, texto: str, decir: bool = True):
        self.texto_estado = texto
        self.SetStatusText(texto)
        if decir and self.datos.windows["accesibilidad"]["anunciarEstado"]:
            voz.decir(texto, interrumpir=True)

    def decir_estado(self):
        """Dice qué se está reproduciendo y, si las hay, qué se está grabando."""
        partes = [self.texto_estado]
        if self.grabador is not None and self.grabador.activa:
            partes.append(self.grabador.estado())
        partes += [g.estado() for g in (self.grabaciones_fondo.grabaciones.values() if self.grabaciones_fondo is not None else [])]
        texto = " ".join(p for p in partes if p)
        voz.decir(texto, interrumpir=True)
        self.SetStatusText(texto)

    def leer_info_canal(self):
        panel = self.panel_activo()
        if panel is not None:
            voz.decir(panel.info.GetValue(), interrumpir=True)

    # --- carga de listas -------------------------------------------------------
    def cargar(self, refrescar: bool = True):
        if self.carga_en_curso:
            return
        self.carga_en_curso = True
        self.generacion += 1
        generacion = self.generacion
        if refrescar:
            self.estado("Cargando contenido: contactando con el servidor de las listas…")
        else:
            ultima = self.datos.windows.get("ultimaComprobacion") or 0
            marca = time.strftime("%d/%m/%Y a las %H:%M", time.localtime(ultima)) if ultima else "todavía sin fecha"
            self.estado(f"Cargando las listas guardadas ({marca}). {modulo_teclas.legible(self.teclas.combo('archivo_actualizar'))} las actualiza.")
        listas = [{"nombre": NOMBRE_LISTA_OFICIAL[t], "url": URL_LISTAS[t][0], "respaldo": URL_LISTAS[t][1], "ruta": "", "formato": "json", "tipo": t, "oficial": True} for t in TIPOS]
        listas += [{"nombre": l["nombre"], "url": l.get("url", ""), "respaldo": None, "ruta": l.get("ruta", ""), "formato": l.get("formato", "auto"), "tipo": l["tipo"], "oficial": False} for l in self.datos.windows["listas"]]
        cuentas = self.cuentas()
        threading.Thread(target=self._cargar_en_hilo, args=(generacion, listas, cuentas, refrescar), daemon=True).start()

    def _cargar_lista_propia(self, lista, refrescar):
        """Lee una lista del usuario: M3U o JSON, de Internet o del equipo. (canales, aviso)."""
        aviso_lista = ""
        if lista["ruta"]:
            texto = Path(lista["ruta"]).read_text(encoding="utf-8-sig", errors="replace")
        elif lista["formato"] == "json":
            data, aviso_lista = self.datos.obtener_json(lista["url"], None, refrescar, catalogo.validar_lista)
            return catalogo.parsear_lista(data, lista["tipo"] if lista["tipo"] != "auto" else "tv", lista["nombre"]), aviso_lista, ""
        else:
            texto, aviso_lista = self.datos.obtener_texto(lista["url"], refrescar)
        if lista["formato"] == "m3u" or (lista["formato"] == "auto" and m3u.es_m3u(texto)):
            canales = m3u.parsear_m3u(texto, lista["tipo"], lista["nombre"])
            return canales, aviso_lista, m3u.guia_declarada(texto)
        data = json.loads(texto)
        return catalogo.parsear_lista(data, lista["tipo"] if lista["tipo"] != "auto" else "tv", lista["nombre"]), aviso_lista, ""

    def _canales_de_cuenta(self, cuenta, refrescar: bool):
        """Canales de una cuenta de proveedor, con copia en la caché para arrancar sin red."""
        clave = f"xtream|{cuenta.servidor}|{cuenta.usuario}"
        if not refrescar:
            guardados, fecha = self.datos.leer_cache(clave)
            if guardados:
                marca = time.strftime("%d/%m/%Y %H:%M", time.localtime(fecha))
                return [self._canal_guardado(cuenta, c) for c in guardados], f"se usan los canales guardados ({marca})."
        try:
            canales = xtream.canales(cuenta)
        except Exception:
            guardados, fecha = self.datos.leer_cache(clave)
            if guardados:
                marca = time.strftime("%d/%m/%Y %H:%M", time.localtime(fecha))
                return [self._canal_guardado(cuenta, c) for c in guardados], f"no responde; se usan los canales guardados ({marca})."
            raise
        modulo_datos.guardar_json_atomico(self.datos.ruta_cache(clave), [self._canal_a_json(c) for c in canales])
        return canales, ""

    @staticmethod
    def _canal_a_json(canal: Canal) -> dict:
        emision = canal.emision_principal
        return {"nombre": canal.nombre, "tipo": canal.tipo, "ambito": canal.ambito, "logo": canal.logo, "epg_id": canal.epg_id,
                "url": emision.url if emision else "", "numero": canal.numero, "catchup": canal.catchup,
                "catchup_dias": canal.catchup_dias, "identificador": canal.identificador}

    @staticmethod
    def _canal_guardado(cuenta, entrada: dict) -> Canal:
        return Canal(
            nombre=str(entrada.get("nombre") or ""), tipo=entrada.get("tipo") if entrada.get("tipo") in TIPOS else cuenta.tipo,
            pais="", ambito=str(entrada.get("ambito") or "Sin categoría"), web="", logo=str(entrada.get("logo") or ""),
            epg_id=str(entrada.get("epg_id") or ""), emisiones=(Emision("directo", str(entrada.get("url") or ""), "m3u8"),),
            origen=cuenta.nombre, numero=int(entrada.get("numero") or 0), catchup=str(entrada.get("catchup") or ""),
            catchup_dias=int(entrada.get("catchup_dias") or 0), identificador=str(entrada.get("identificador") or ""),
        )

    def _cargar_en_hilo(self, generacion, listas, cuentas, refrescar):
        canales, guias, avisos = [], {"tv": {}, "radio": {}}, []
        guias_extra: list[str] = []
        for lista in listas:
            try:
                if lista["oficial"]:
                    data, aviso_lista = self.datos.obtener_json(lista["url"], lista["respaldo"], refrescar, catalogo.validar_lista)
                    nuevos = catalogo.parsear_lista(data, lista["tipo"], lista["nombre"])
                    if lista["tipo"] == "tv":
                        nuevos = catalogo.insertar_atresmedia(nuevos)
                    guia_propia = ""
                else:
                    nuevos, aviso_lista, guia_propia = self._cargar_lista_propia(lista, refrescar)
                if guia_propia:
                    guias_extra.append(guia_propia)
                nombres = {(c.tipo, c.nombre) for c in canales}
                canales.extend(c for c in nuevos if (c.tipo, c.nombre) not in nombres)
                if aviso_lista:
                    avisos.append(f"{lista['nombre']}: {aviso_lista}")
            except Exception as error:
                registro.exception("Error cargando %s", lista.get("url") or lista.get("ruta"))
                avisos.append(f"{lista['nombre']}: no se pudo cargar ({error}).")
        for cuenta in cuentas:
            try:
                nuevos, aviso_cuenta = self._canales_de_cuenta(cuenta, refrescar)
                nombres = {(c.tipo, c.nombre) for c in canales}
                canales.extend(c for c in nuevos if (c.tipo, c.nombre) not in nombres)
                if aviso_cuenta:
                    avisos.append(f"Cuenta {cuenta.nombre}: {aviso_cuenta}")
            except Exception as error:
                registro.info("Cuenta %s: %s", cuenta.nombre, error)
                avisos.append(f"Cuenta {cuenta.nombre}: no se pudo cargar ({error}).")
        for tipo in TIPOS:
            try:
                data, aviso_guia = self.datos.obtener_json(URL_GUIAS[tipo][0], URL_GUIAS[tipo][1], refrescar, catalogo.validar_guia)
                guias[tipo] = catalogo.parsear_guia(data)
                if aviso_guia:
                    avisos.append(f"Guía de {NOMBRE_TIPO[tipo].lower()}: {aviso_guia}")
            except Exception as error:
                registro.exception("Error cargando la guía de %s", tipo)
                avisos.append(f"Guía de {NOMBRE_TIPO[tipo].lower()}: no disponible ({error}).")
        # Guía adicional (XMLTV) para los canales que la oficial no cubre, como los
        # de Atresmedia o muchas autonómicas. Se indexa por nombre de canal.
        variante = self.datos.windows.get("guiaExtraVariante") or catalogo.GUIA_EXTRA
        direcciones = ([variante] if self.datos.windows.get("guiaExtra", True) else []) + list(self.datos.windows.get("guiasPropias") or []) + guias_extra
        for direccion in dict.fromkeys(direcciones):
            try:
                sufijo = ".xml.gz" if direccion.endswith(".gz") else ".xml"
                archivo = self.datos.descargar_archivo(direccion, sufijo, refrescar)
                if archivo is not None:
                    extra = catalogo.parsear_xmltv(archivo)
                    guias["tv"].update(extra)
                    guias["radio"].update(extra)
                    registro.info("Guía adicional (%s): %s canales", direccion, len(extra))
            except Exception as error:
                registro.info("Guía adicional no disponible (%s): %s", direccion, error)
        # Programación que ofrece el propio proveedor para sus canales. Solo se
        # pide al actualizar: al arrancar con la copia guardada no se toca la red.
        for cuenta in cuentas if refrescar else []:
            try:
                propios = [c for c in canales if c.origen == cuenta.nombre and c.identificador]
                if propios:
                    guias[cuenta.tipo].update(xtream.guia(cuenta, propios))
            except Exception as error:
                registro.info("Guía de la cuenta %s: %s", cuenta.nombre, error)
        wx.CallAfter(self._carga_terminada, generacion, canales, guias, avisos, refrescar)

    def _carga_terminada(self, generacion, canales, guias, avisos, refrescar):
        self.carga_en_curso = False
        if generacion != self.generacion:
            return
        if canales:
            if self.datos.windows.get("quitarDuplicados", True):
                antes = len(canales)
                canales = organizar.quitar_duplicados(canales)
                if antes != len(canales):
                    avisos.append(f"Se han unificado {antes - len(canales)} canales repetidos entre listas.")
            self.canales = canales
            self.guia = guias
        self.avisos_carga = avisos
        self.panel_vod.actualizar_cuentas()
        if refrescar and canales:
            self.datos.windows["ultimaComprobacion"] = int(time.time())
            self.datos.guardar()
        for panel in self.paneles.values():
            panel.actualizar_ambitos(self.canales)
            panel.refrescar()
        self.panel_guia.rellenar_canales()
        self.panel_info.rellenar()
        if not canales:
            self.estado("Algo fue mal: la lista no ha podido ser descargada. Comprueba tu conexión a Internet.")
            aviso(self, "La lista no ha podido ser descargada. Comprueba que tengas Internet y que las direcciones de las listas sean correctas.\n\n" + "\n".join(avisos), "Algo fue mal", wx.ICON_ERROR)
            return
        resumen = f"Contenido de TV y radio {'actualizado' if refrescar else 'cargado'}: {sum(1 for c in canales if c.tipo == 'tv')} canales de televisión y {sum(1 for c in canales if c.tipo == 'radio')} de radio."
        if not refrescar:
            ultima = self.datos.windows.get("ultimaComprobacion") or 0
            marca = time.strftime("%d/%m/%Y a las %H:%M", time.localtime(ultima)) if ultima else "sin fecha"
            resumen += f" Son las listas guardadas del {marca}; {modulo_teclas.legible(self.teclas.combo('archivo_actualizar'))} las actualiza."
        if avisos:
            resumen += " Avisos: " + " ".join(avisos)
        self.estado(resumen)
        # Con la guía recién cargada es el momento de mirar las reglas de grabación
        # y de aplicar la limpieza automática, si las hay puestas.
        wx.CallLater(1500, self._tras_cargar)

    def _tras_cargar(self):
        if self.cerrando:
            return
        self.ultimas_reglas = time.time()
        try:
            self.aplicar_reglas()
            self.limpiar_grabaciones_si_toca()
            self.sincronizar_tareas()
        except Exception:
            registro.exception("Error aplicando las reglas de grabación")

    # --- selección y acciones sobre canales -----------------------------------------
    def panel_activo(self) -> PanelCanales | None:
        pagina = self.libro.GetCurrentPage()
        return pagina if isinstance(pagina, PanelCanales) else None

    def canal_seleccionado(self, panel: PanelCanales | None = None) -> Canal | None:
        panel = panel or self.panel_activo()
        if panel is None:
            return self.canal_actual
        return panel.canal

    def enfocar_busqueda(self):
        panel = self.panel_activo()
        if panel is None:
            self.libro.SetSelection(0)
            panel = self.paneles["tv"]
        panel.busqueda.SetFocus()
        panel.busqueda.SelectAll()

    def alternar_favorito(self, panel: PanelCanales | None = None):
        panel = panel or self.panel_activo()
        canal = self.canal_seleccionado(panel)
        if not canal:
            return
        estado = self.datos.estado_canal(canal.tipo, canal.nombre)
        nuevo = not estado["favorite"]
        self.datos.fijar_estado_canal(canal.tipo, canal.nombre, favorite=nuevo)
        self.datos.guardar()
        self.paneles[canal.tipo].refrescar()
        self.panel_guia.rellenar_canales(self.panel_guia.canal_actual())
        self.estado(f"{canal.nombre}: {'añadido a' if nuevo else 'quitado de'} favoritos.")

    def alternar_oculto(self, panel: PanelCanales | None = None):
        panel = panel or self.panel_activo()
        canal = self.canal_seleccionado(panel)
        if not canal:
            return
        estado = self.datos.estado_canal(canal.tipo, canal.nombre)
        nuevo = not estado["hide"]
        self.datos.fijar_estado_canal(canal.tipo, canal.nombre, hide=nuevo)
        self.datos.guardar()
        self.paneles[canal.tipo].refrescar()
        self.panel_guia.rellenar_canales(self.panel_guia.canal_actual())
        self.estado(f"{canal.nombre}: {'oculto' if nuevo else 'visible de nuevo'}.")

    def mover(self, direccion: int, panel: PanelCanales | None = None):
        panel = panel or self.panel_activo()
        if panel is None or not panel.canal:
            return
        canal = panel.canal
        visibles = panel.visibles
        if canal not in visibles:
            return
        indice = visibles.index(canal)
        if direccion == 0:
            self.datos.fijar_estado_canal(canal.tipo, canal.nombre, position=None)
        else:
            destino = indice + direccion
            if destino < 0 or destino >= len(visibles):
                self.estado("No se puede mover más.")
                return
            orden = list(visibles)
            orden[indice], orden[destino] = orden[destino], orden[indice]
            for posicion, c in enumerate(orden):
                self.datos.fijar_estado_canal(c.tipo, c.nombre, position=posicion)
        self.datos.guardar()
        panel.refrescar()
        panel.lista.SetFocus()
        self.estado(f"{canal.nombre} en la posición {panel.visibles.index(canal) + 1}." if direccion else f"{canal.nombre} quitado del orden personal.")

    def abrir_web(self, canal: Canal | None = None):
        canal = canal or self.canal_seleccionado()
        if not canal:
            return
        if not canal.web:
            aviso(self, "Este canal no tiene web oficial en la lista.")
            return
        integrado = self.datos.usuario["browserEmbedWeb"]
        self.estado(f"Abriendo el sitio web oficial de {canal.nombre}" + (" en el navegador integrado…" if integrado and navegador.motor_disponible() else "…"))
        navegador.abrir(self, canal.web, canal.nombre, integrado)

    def copiar_enlace(self, panel: PanelCanales | None = None):
        panel = panel or self.panel_activo()
        emision = panel.emision_seleccionada() if panel else self.emision_actual
        if emision and copiar_portapapeles(emision.url):
            self.estado("Enlace copiado en el portapapeles.")

    def ver_programacion(self, canal: Canal | None = None):
        canal = canal or self.canal_seleccionado()
        if not canal:
            return
        with DialogoProgramacion(self, canal) as dialogo:
            dialogo.ShowModal()

    def ir_a_guia(self, canal: Canal | None = None):
        canal = canal or self.canal_seleccionado()
        if not canal:
            return
        self.panel_guia.medio.SetSelection(TIPOS.index(canal.tipo))
        self.libro.SetSelection(2)
        self.panel_guia.rellenar_canales(canal)
        if canal not in self.panel_guia.canales:
            self.estado(f"{canal.nombre} no tiene programación disponible.")
        self.panel_guia.lista.SetFocus()

    def dialogo_favoritos(self):
        with DialogoFavoritos(self) as dialogo:
            dialogo.ShowModal()

    def crear_recordatorio(self, canal: Canal, programa: Programa, parent=None):
        parent = parent or self
        if programa.en_curso():
            aviso(parent, "Este programa ya ha empezado. Puedes verlo con Ver canal.")
            return
        if programa.fin <= time.time():
            aviso(parent, "Este programa ya ha terminado.")
            return
        with wx.SingleChoiceDialog(parent, f"{programa.titulo}\n{programa.fecha()} a las {time.strftime('%H:%M', time.localtime(programa.inicio))}\n\n¿Cuántos minutos antes quieres el aviso?", "Recordatorio", [f"{m} minuto{'s' if m != 1 else ''} antes" for m in MINUTOS_RECORDATORIO]) as dialogo:
            dialogo.SetSelection(1)
            if dialogo.ShowModal() != wx.ID_OK:
                return
            minutos = MINUTOS_RECORDATORIO[dialogo.GetSelection()]
        lista = self.datos.windows["recordatorios"]
        lista[:] = [r for r in lista if not (r["inicio"] == programa.inicio and r["canal"] == canal.nombre)]
        lista.append({"canal": canal.nombre, "epg_id": canal.epg_id, "titulo": programa.titulo, "inicio": programa.inicio, "minutos": minutos, "tipo": canal.tipo})
        self.datos.guardar()
        self.estado(f"Recordatorio establecido para {minutos} minutos antes del inicio.")

    def anadir_lista(self):
        if len(self.datos.windows["listas"]) >= 10:
            aviso(self, "Se ha llegado al límite de diez listas adicionales. Quita alguna en la pestaña Información.")
            return
        with dialogos.DialogoLista(self) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            valor = dialogo.valor()
        if valor["ruta"]:
            if not Path(valor["ruta"]).exists():
                aviso(self, "Ese archivo no existe.", icono=wx.ICON_ERROR)
                return
            valor["url"] = ""
        elif not modulo_datos.url_http(valor["url"]):
            aviso(self, "Indica una dirección que empiece por https:// o http://, o elige un archivo del equipo.", icono=wx.ICON_ERROR)
            return
        if not valor["nombre"]:
            valor["nombre"] = valor["url"] or Path(valor["ruta"]).stem
        self.guardar_lista(valor)

    def guardar_lista(self, valor: dict, mensaje: str = ""):
        """Guarda una lista nueva (propia o de un catálogo) y recarga el contenido."""
        listas = self.datos.windows.setdefault("listas", [])
        direccion = valor.get("url") or valor.get("ruta")
        if any((l.get("url") or l.get("ruta")) == direccion for l in listas):
            self.estado("Esa lista ya estaba añadida.")
            return
        if len(listas) >= 10:
            aviso(self, "Se ha llegado al límite de diez listas adicionales. Quita alguna en la pestaña Información.")
            return
        listas.append(valor)
        self.datos.guardar()
        if mensaje:
            self.estado(mensaje)
        self.cargar(True)

    def anadir_iptvorg(self):
        """Añade una lista del catálogo público de iptv-org."""
        with dialogos.DialogoIptvOrg(self) as dialogo:
            dialogo.ShowModal()

    def configurar_guias(self):
        with dialogos.DialogoGuias(self) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            dialogo.aplicar()
        self.estado("Guías guardadas. Actualiza las listas para descargarlas.")
        if pregunta(self, "¿Actualizar ahora las listas y la guía?"):
            self.cargar(True)

    def ver_cobertura(self):
        """Informe de qué canales tienen programación y cuáles no, y por qué."""
        partes = ["<h1>Cobertura de la guía</h1>"]
        texto = ["Cobertura de la guía", ""]
        import html as modulo_html

        soportados = self._canales_de_la_guia()
        for tipo in TIPOS:
            con, sin = catalogo.cobertura_guia(self.canales, self.guia.get(tipo, {}), tipo)
            total = len(con) + len(sin)
            porcentaje = (100 * len(con) / total) if total else 0
            partes.append(f"<h2>{NOMBRE_TIPO[tipo]}</h2><p>{len(con)} de {total} canales tienen programación ({porcentaje:.0f} por ciento).</p>")
            texto.append(f"{NOMBRE_TIPO[tipo]}: {len(con)} de {total} canales con programación ({porcentaje:.0f}%).")
            if not sin:
                continue
            partes.append("<h3>Canales sin programación</h3><table><tr><th>Canal</th><th>Nombres parecidos en la guía ampliada</th></tr>")
            for canal in sin[:120]:
                parecidos = catalogo.parecidos(canal.nombre, soportados) if soportados else []
                partes.append(f"<tr><td>{modulo_html.escape(canal.nombre)}</td><td>{modulo_html.escape(', '.join(parecidos) or '—')}</td></tr>")
                texto.append(f"  {canal.nombre}: {', '.join(parecidos) or 'sin equivalente'}")
            partes.append("</table>")
            if len(sin) > 120:
                partes.append(f"<p>Y {len(sin) - 120} canales más.</p>")
        partes.append("<p>La guía ampliada empareja por identificador y por nombre, sin tildes ni «HD». Si un canal aparece aquí con un nombre parecido, "
                      "basta con que la lista use ese nombre para que salga su programación.</p>")
        dialogo_html(self, "Cobertura de la guía", "".join(partes), "\n".join(texto))

    def _canales_de_la_guia(self) -> list[str]:
        """Nombres de los canales que cubre la guía ampliada, para comparar."""
        try:
            ruta = self.datos.descargar_archivo(catalogo.CANALES_DOBLEM, ".txt", refrescar=False, horas=168)
            if ruta is None:
                return []
            return [l.strip() for l in Path(ruta).read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        except OSError:
            return []

    def ambitos_visibles(self):
        panel = self.panel_activo() or self.paneles["tv"]
        tipo = panel.tipo
        with DialogoAmbitos(self, tipo, catalogo.ambitos(self.canales, tipo), self.datos.comunidades_ocultas(tipo)) as dialogo:
            if dialogo.ShowModal() == wx.ID_OK:
                self.datos.comunidades_ocultas(tipo)[:] = dialogo.ocultos()
                self.datos.guardar()
                panel.refrescar()
                self.panel_guia.rellenar_canales()

    # --- reproductor libmpv --------------------------------------------------------
    def asegurar_reproductor(self) -> bool:
        if self.reproductor is not None:
            return True
        if not modulo_datos.ruta_libmpv(self.datos):
            if not self.descargar_mpv():
                return False
        try:
            self.ventana_video = self.ventana_video or VentanaVideo(self)
            self.reproductor = Reproductor(self.ventana_video.video.GetHandle(), modulo_datos.carpeta_mpv(self.datos), lambda tipo, texto: wx.CallAfter(self.evento_reproductor, tipo, texto), self.datos.windows["volumen"], self.datos.windows["silencio"], self.datos.windows.get("bufferRecepcion", "normal"))
            self.reproductor.modo_imagen(self.datos.windows["modoImagen"])
            self.aplicar_preferencias_reproductor()
            self.grabador = grabacion.Grabador(self.reproductor)
            self.version_mpv = str(self.reproductor.mpv.mpv_version)
            self.panel_info.rellenar()
        except Exception as error:
            registro.exception("No se pudo iniciar libmpv")
            aviso(self, f"No se pudo iniciar el reproductor: {error}\n\nPrueba Herramientas > Mantenimiento > Buscar actualizaciones del reproductor libmpv.", icono=wx.ICON_ERROR)
            return False
        return True

    def aplicar_preferencias_reproductor(self):
        """Lleva al reproductor la calidad, el modo solo audio, la audiodescripción y la caché."""
        if self.reproductor is None:
            return
        windows = self.datos.windows
        self.recargar_por_buffer = self.reproductor.configurar_buffer(windows.get("bufferRecepcion", "normal"))
        self.reproductor.calidad(windows.get("calidad", "max"))
        self.reproductor.solo_audio(windows.get("soloAudio", False))
        self.reproductor.preferir_audiodescripcion(windows.get("audiodescripcion", False))
        self.reproductor.configurar_cache(windows.get("timeshiftMinutos", 0))
        self.reproductor.nivelar_volumen(windows.get("nivelarVolumen", False))

    def descargar_mpv(self) -> bool:
        if not pregunta(self, "Falta el reproductor libmpv en la carpeta data/mpv (unos 31 MB de descarga).\n\n¿Descargarlo ahora?"):
            return False
        with DialogoDescarga(self, self.datos, en_uso=False) as dialogo:
            resultado = dialogo.ShowModal()
        if resultado == wx.ID_OK:
            self.estado("Reproductor libmpv preparado en data/mpv.")
            self.panel_info.rellenar()
            return True
        return False

    def comprobar_mpv_al_iniciar(self):
        windows = self.datos.windows
        if not windows["comprobarMpv"] or time.time() - (windows.get("ultimaComprobacionMpv") or 0) < UNA_SEMANA:
            return
        self.comprobar_mpv(manual=False)

    def comprobar_mpv(self, manual: bool):
        if not modulo_datos.ruta_libmpv(self.datos):
            if manual:
                self.descargar_mpv()
            return
        if manual:
            self.estado("Buscando versiones nuevas de libmpv…")
        threading.Thread(target=self._comprobar_mpv_en_hilo, args=(manual,), daemon=True).start()

    def _comprobar_mpv_en_hilo(self, manual: bool):
        try:
            try:
                version = self.version_mpv or version_libmpv_cargada(modulo_datos.carpeta_mpv(self.datos))
            except Exception as err:
                registro.warning("No se pudo leer la versión de libmpv instalada: %s", err)
                version = ""
            nombre, _url, tamano = modulo_datos.localizar_paquete_mpv()
            disponible = modulo_datos.actualizacion_disponible(version, nombre) if version else True
            wx.CallAfter(self._resultado_mpv, manual, version, nombre, tamano, disponible, None)
        except Exception as error:
            registro.warning("Comprobación de libmpv: %s", error)
            wx.CallAfter(self._resultado_mpv, manual, "", "", 0, False, error)

    def _resultado_mpv(self, manual, version, nombre, tamano, disponible, error):
        if self.cerrando:
            return
        if error is None:
            self.datos.windows["ultimaComprobacionMpv"] = int(time.time())
            self.datos.guardar()
        self.version_mpv = version or self.version_mpv
        self.panel_info.rellenar()
        pendiente = (modulo_datos.carpeta_mpv(self.datos) / modulo_datos.DLL_NUEVA).exists()
        if error is not None:
            if manual:
                aviso(self, f"No se pudo comprobar si hay una versión nueva de libmpv: {error}", icono=wx.ICON_WARNING)
            return
        if pendiente:
            if manual:
                self.ofrecer_reinicio()
            else:
                self.estado("Ya hay una versión nueva de libmpv descargada; se instalará al reiniciar la aplicación.")
            return
        if not disponible:
            if manual:
                aviso(self, f"El reproductor está actualizado.\nVersión instalada: {version}\nÚltimo paquete publicado: {nombre}")
            return
        # En cuanto se ha consultado la versión la DLL ya está cargada en este
        # proceso, suene algo o no, y Windows no deja sustituirla hasta cerrar.
        en_uso = libmpv_en_memoria()
        texto = f"Hay una versión nueva del reproductor libmpv.\nInstalada: {version or 'no disponible (error al cargar)'}\nDisponible: {nombre} ({tamano / 1e6:.1f} MB)\n\n¿Descargarla ahora?"
        if en_uso:
            texto += "\nComo el reproductor está cargado, se instalará al reiniciar la aplicación."
        if not pregunta(self, texto, "Actualización de libmpv"):
            self.estado("Actualización de libmpv pendiente: la tienes en Herramientas, Mantenimiento.")
            return
        with DialogoDescarga(self, self.datos, en_uso=en_uso) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            ruta = dialogo.resultado[0] if dialogo.resultado else None
        if ruta is None or ruta.name != modulo_datos.DLL_NUEVA:
            self.estado("libmpv descargado. Ya se usa la versión nueva.")
            return
        self.estado("libmpv descargado. Se instalará al reiniciar la aplicación.")
        self.ofrecer_reinicio()

    def ofrecer_reinicio(self):
        """Tras descargar libmpv con la DLL cargada: reiniciar para empezar a usarla."""
        texto = "La versión nueva de libmpv ya está descargada. Para empezar a usarla hay que reiniciar la aplicación.\n\n¿Reiniciar ahora?"
        grabando = len(self.grabaciones_fondo) if self.grabaciones_fondo is not None else 0
        if grabando or (self.grabador is not None and self.grabador.activa):
            texto += "\n\nOjo: hay grabaciones en marcha y se cerrarán."
        if not pregunta(self, texto, "Actualización de libmpv"):
            self.estado("La versión nueva de libmpv se instalará la próxima vez que abras la aplicación.")
            return
        try:
            modulo_datos.lanzar_reinicio()
        except OSError as error:
            registro.exception("No se pudo reiniciar la aplicación")
            aviso(self, f"No se pudo reiniciar la aplicación: {error}\n\nCiérrala y vuelve a abrirla para usar la versión nueva.", icono=wx.ICON_WARNING)
            return
        self.salir()

    # --- reproducción -----------------------------------------------------------
    def reproducir_seleccion(self, panel: PanelCanales | None = None):
        panel = panel or self.panel_activo()
        if panel is None:
            if self.canal_actual:
                self.reproducir_canal(self.canal_actual)
            return
        canal = panel.canal
        if not canal:
            return
        emision = panel.emision_seleccionada()
        if emision is None:
            if canal.web:
                self.reproducir(canal, Emision("web", canal.web, "web"))
            else:
                aviso(self, f"{canal.nombre} no tiene emisiones disponibles.")
            return
        self.reproducir(canal, emision)

    def reproducir_canal(self, canal: Canal):
        """Reproduce la emisión principal del canal (zapping, favoritos, guía y recordatorios)."""
        emision = canal.emision_principal
        if emision is None:
            aviso(self, f"{canal.nombre} no tiene emisiones disponibles.")
            return
        self.reproducir(canal, emision)

    def reproducir(self, canal: Canal, emision: Emision):
        """Reproduce una emisión, siempre que se pueda con el reproductor de la aplicación.

        Para YouTube, Twitch y las webs de emisoras se busca antes la dirección
        real del directo; solo si no aparece se recurre al navegador.
        """
        if organizar.bloqueado(self.datos, canal) and not self.pedir_pin(f"«{canal.nombre}» está bloqueado."):
            self.estado(f"{canal.nombre} está bloqueado con PIN.")
            return
        if canal.drm:
            aviso(self, f"La emisión de {canal.nombre} está cifrada (DRM) y no se puede reproducir con este reproductor.", icono=wx.ICON_WARNING)
            self.estado_reproduccion(f"{canal.nombre}: emisión cifrada, no se puede reproducir.")
            return
        self.intentos = 0
        self.cancelar_reintento()
        if self.emision_actual is None or self.canal_actual is None or self.canal_actual.nombre != canal.nombre:
            self.emisiones_probadas = set()
        self.emisiones_probadas.add(emision.url)
        organizar.anotar(self.datos, canal)
        if emision.tipo == "directo":
            self._preparar_reproduccion(canal, emision)
            self._iniciar(proveedores.fuente_directa(canal, emision))
            return
        if emision.tipo in ("ext", "youtube", "twitch", "web"):
            self._preparar_reproduccion(canal, emision)
            self.estado_reproduccion(f"Buscando la emisión de {canal.nombre}…")
            threading.Thread(target=self._buscar_fuente_en_hilo, args=(self.generacion_reproduccion, canal, emision), daemon=True).start()
            return
        self._reproducir_en_navegador(canal, emision)

    def _preparar_reproduccion(self, canal: Canal, emision: Emision) -> None:
        self.soltar_grabacion()
        if self.canal_actual and self.canal_actual.nombre != canal.nombre:
            self.canal_anterior = self.canal_actual
        self.canal_actual, self.emision_actual = canal, emision
        self.datos.windows["ultimoCanal"][canal.tipo] = canal.nombre
        self.SetTitle(f"{canal.nombre} · {NOMBRE_APP}")
        if self.ventana_video is not None:
            self.ventana_video.SetTitle(f"{canal.nombre} · {NOMBRE_APP}")
        self.generacion_reproduccion += 1

    def _buscar_fuente_en_hilo(self, generacion, canal: Canal, emision: Emision):
        fuente, aviso_error = self._fuente_reproducible(canal, emision)
        wx.CallAfter(self._fuente_encontrada, generacion, canal, emision, fuente, aviso_error)

    def _fuente_reproducible(self, canal: Canal, emision: Emision):
        """Busca una fuente reproducible: primero el servicio oficial, luego el extractor.

        Hace peticiones de red, así que se llama siempre desde un hilo (la
        reproducción y también las grabaciones en segundo plano).
        """
        if emision.tipo == "directo":
            return proveedores.fuente_directa(canal, emision), None
        fuente, aviso_error = None, None
        if emision.tipo == "ext":
            try:
                fuente = proveedores.fuente_final(canal, emision, proveedores.resolver(emision.url))
            except proveedores.ProveedorNoSoportado:
                fuente = None
            except Exception as error:
                registro.info("Proveedor %s: %s", emision.url, error)
                aviso_error = error
        if fuente is None:
            fuente = extractor.extraer(emision.tipo, emision.url, canal.user_agent)
        return fuente, aviso_error

    def _fuente_encontrada(self, generacion, canal, emision, fuente, aviso_error):
        if generacion != self.generacion_reproduccion or self.cerrando:
            return
        if fuente is not None:
            self._iniciar(fuente)
            return
        if aviso_error is not None:
            self.estado_reproduccion(f"{canal.nombre}: {aviso_error}")
        self._reproducir_en_navegador(canal, emision)

    def _reproducir_en_navegador(self, canal: Canal, emision: Emision):
        """Último recurso: la web de la emisora, buscando allí su emisión."""
        if emision.navegador:
            integrado = self.datos.usuario["browserEmbedYoutube" if emision.tipo in ("youtube", "twitch") else "browserEmbedWeb"]
            usa_integrado = integrado and navegador.motor_disponible()
            self.canal_actual, self.emision_actual = canal, emision
            self.datos.windows["ultimoCanal"][canal.tipo] = canal.nombre
            self.generacion_reproduccion += 1
            # Un canal de YouTube no se puede incrustar tal cual: hay que averiguar qué
            # vídeo emite ahora (como hace el APK), o el reproductor muestra un error.
            video_youtube, canal_youtube = catalogo.identificador_youtube(emision.url) if emision.tipo == "youtube" else ("", "")
            if usa_integrado and canal_youtube:
                self.estado(f"Buscando el directo de {canal.nombre} en YouTube…")
                threading.Thread(target=self._resolver_youtube_en_hilo, args=(self.generacion_reproduccion, canal, emision), daemon=True).start()
                return
            # Con el navegador integrado se carga el reproductor como página principal
            # (página local de YouTube, canal de Twitch): así se maneja con el teclado.
            if usa_integrado and video_youtube:
                url = self.url_youtube(video_youtube, canal.nombre)
            else:
                url = emision.url_incrustada if usa_integrado else emision.url
            # En las webs de emisoras se busca en segundo plano la dirección real del
            # directo para reproducirla con el reproductor de la aplicación, que es
            # accesible. Si no aparece, se muestra la web como hasta ahora.
            detectar = emision.tipo not in ("youtube", "twitch")
            if usa_integrado and detectar:
                self.estado(f"Buscando la emisión de {canal.nombre} en su web para reproducirla en la aplicación…")
            else:
                self.estado(f"Abriendo {canal.nombre} en el navegador" + (" integrado…" if usa_integrado else "…"))
            navegador.abrir(self, url, canal.nombre, integrado, detectar, oculto=detectar)
            return
        # Emisiones «ext» sin servicio conocido: se abre su web y se busca allí.
        integrado = self.datos.usuario["browserEmbedWeb"]
        usa_integrado = integrado and navegador.motor_disponible()
        destino = emision.url if emision.tipo == "ext" else (canal.web or emision.url)
        self.estado_reproduccion(f"Buscando la emisión de {canal.nombre} en su web…" if usa_integrado else f"Abriendo la web de {canal.nombre}…")
        navegador.abrir(self, destino, canal.nombre, integrado, detectar=True, oculto=usa_integrado)

    def reproducir_flujo_detectado(self, url: str, pagina: str, origen: str, titulo: str):
        """Reproduce con libmpv la emisión que se ha detectado en la web de la emisora."""
        if self.cerrando:
            return
        canal = self.canal_actual
        agente = (canal.user_agent if canal else "") or proveedores.UA_UAGB
        fuente = proveedores.Fuente(url, origin=origen, referer=pagina, user_agent=agente, descripcion="Directo detectado en la web oficial")
        if not self.asegurar_reproductor():
            return
        self.emision_actual = catalogo.Emision("directo", url, "m3u8")
        self.SetTitle(f"{titulo} · {NOMBRE_APP}")
        self.generacion_reproduccion += 1
        self._iniciar(fuente)
        self.estado_reproduccion(f"Emisión de {titulo} detectada en su web; reproduciendo en la aplicación.")
        if self.navegador is not None:
            self.navegador.Close()
        self.Raise()

    def recargar(self):
        """Vuelve a cargar la emisión actual (si se corta el directo)."""
        if self.canal_actual and self.emision_actual:
            self.estado("Recargando la emisión…")
            self.reproducir(self.canal_actual, self.emision_actual)
        else:
            self.estado("No hay ninguna emisión que recargar.")

    def url_youtube(self, video: str, titulo: str) -> str:
        """Página local con la API de iframe de YouTube (como el APK); si falla, el incrustado directo."""
        try:
            return servidor.url_youtube(video=video, titulo=f"{titulo} en directo")
        except OSError as error:
            registro.warning("No se pudo abrir el servidor local del reproductor: %s", error)
            return f"https://www.youtube.com/embed/{video}?autoplay=1&playsinline=1&rel=0"

    def _resolver_youtube_en_hilo(self, generacion, canal, emision):
        video = proveedores.video_en_directo_youtube(emision.url)
        wx.CallAfter(self._youtube_resuelto, generacion, canal, emision, video)

    def _youtube_resuelto(self, generacion, canal, emision, video):
        if generacion != self.generacion_reproduccion or self.cerrando:
            return
        if video:
            self.estado(f"Abriendo {canal.nombre} en el reproductor de YouTube dentro de la aplicación…")
            navegador.abrir(self, self.url_youtube(video, canal.nombre), canal.nombre, True)
            return
        self.estado(f"{canal.nombre} no está emitiendo en directo ahora mismo en YouTube.")
        if pregunta(self, f"{canal.nombre} no tiene ninguna emisión en directo ahora mismo en YouTube.\n\n¿Quieres abrir su canal para ver el resto de vídeos?", "YouTube"):
            navegador.abrir(self, emision.url, canal.nombre, self.datos.usuario["browserEmbedYoutube"])

    def _iniciar(self, fuente: proveedores.Fuente):
        if not self.asegurar_reproductor():
            return
        try:
            self.reproductor.reproducir(fuente, self.datos.usuario["playerSubtitle"])
        except Exception as error:
            registro.exception("Error al reproducir")
            self.estado_reproduccion(f"Error mientras cargaba: {error}")
            return
        sonidos.reproducir("inicio")
        nombre = self.canal_actual.nombre if self.canal_actual else "la emisión"
        self.estado_reproduccion(f"Cargando {nombre}, debería empezar en breve…")
        if self.canal_actual is not None:
            wx.CallLater(1200, self.anunciar_programa, self.canal_actual)

    def anunciar_programa(self, canal: Canal):
        """Al sintonizar, decir qué están dando ahora y hasta qué hora."""
        if self.cerrando or not self.datos.windows.get("anunciarPrograma", True):
            return
        if self.canal_actual is None or self.canal_actual.nombre != canal.nombre:
            return
        programas = catalogo.programas_canal(self.guia.get(canal.tipo, {}), canal)
        actual, siguiente = catalogo.ahora_y_siguiente(programas)
        if actual is None:
            return
        fin = time.strftime("%H:%M", time.localtime(actual.fin))
        texto = f"{canal.nombre}, ahora {actual.titulo}, hasta las {fin}."
        if siguiente is not None:
            texto += f" Después, {siguiente.titulo}."
        voz.decir(texto, interrumpir=False)
        self.SetStatusText(texto)

    def evento_reproductor(self, tipo: str, texto: str):
        if self.cerrando or self.reproductor is None:
            return
        if tipo == "estado":
            nombre = self.canal_actual.nombre if self.canal_actual else ""
            self.estado_reproduccion(f"{texto}: {nombre}" if nombre else texto)
        elif tipo in ("cargado", "pistas"):
            self.actualizar_pistas()
        elif tipo == "titulo":
            if self.canal_actual and self.canal_actual.tipo == "radio":
                self.estado_reproduccion(f"Reproduciendo {self.canal_actual.nombre}: {texto}", decir=False)
        elif tipo == "error":
            sonidos.reproducir("error")
            if self.recuperar_emision(texto):
                return
            self.estado_reproduccion(f"Error mientras cargaba: {texto}")
            canal = self.canal_actual
            mensaje = "La fuente no está disponible, comprueba si están emitiendo. Además, revisa tu conexión a Internet."
            sugerencia = self.sugerencia_dns()
            if sugerencia:
                mensaje += "\n\n" + sugerencia
            if canal and canal.web and pregunta(self, f"{mensaje}\n\nDetalle: {texto}\n\n¿Quieres abrir la web oficial de {canal.nombre}?", "Error mientras cargaba"):
                self.abrir_web(canal)
        elif tipo == "fin":
            self.estado_reproduccion(texto)
        elif tipo == "grabacion_dañada":
            if self.grabador is not None and self.grabador.activa:
                self.estado(texto + " El resto se sigue grabando.", decir=False)
            else:
                registro.info("Fragmentos con tiempos incorrectos: %s", texto)
        elif tipo == "aviso":
            self.estado(texto, decir=False)

    # --- recuperación de la emisión ------------------------------------------
    def cancelar_reintento(self):
        if self.reintento_pendiente is not None:
            try:
                self.reintento_pendiente.Stop()
            except Exception:
                pass
            self.reintento_pendiente = None

    def recuperar_emision(self, detalle: str) -> bool:
        """Ante un corte: probar otra emisión del canal o reintentar la misma.

        Devuelve True si se ha puesto en marcha una recuperación, para no
        molestar todavía con el aviso de error.
        """
        canal, emision = self.canal_actual, self.emision_actual
        if canal is None or emision is None or self.cerrando:
            return False
        if self.datos.windows.get("emisionAlternativa", True):
            alternativa = next((e for e in canal.emisiones if e.url not in self.emisiones_probadas and not e.navegador), None)
            if alternativa is not None:
                self.estado_reproduccion(f"{canal.nombre}: esa emisión falla; probando otra.")
                wx.CallAfter(self.reproducir, canal, alternativa)
                return True
        if not self.datos.windows.get("reintentos", True) or self.intentos >= len(ESPERAS_REINTENTO):
            return False
        espera = ESPERAS_REINTENTO[self.intentos]
        self.intentos += 1
        self.estado_reproduccion(f"{canal.nombre}: se ha cortado la emisión. Reintento {self.intentos} de {len(ESPERAS_REINTENTO)} en {espera} segundos.")
        self.cancelar_reintento()
        self.reintento_pendiente = wx.CallLater(espera * 1000, self._reintentar, canal, emision)
        return True

    def _reintentar(self, canal: Canal, emision: Emision):
        self.reintento_pendiente = None
        if self.cerrando or self.canal_actual is None or self.canal_actual.nombre != canal.nombre:
            return
        intentos = self.intentos
        probadas = set(self.emisiones_probadas)
        self.reproducir(canal, emision)
        self.intentos = intentos  # reproducir() los reinicia; aquí se conserva la cuenta
        self.emisiones_probadas = probadas | {emision.url}

    def actualizar_pistas(self):
        if self.reproductor is None:
            return
        self.pistas_audio = self.reproductor.pistas("audio")
        self.pistas_sub = self.reproductor.pistas("sub")
        if self.datos.windows.get("audiodescripcion"):
            pista = self.reproductor.pista_audiodescripcion()
            activa = next((i for i, t in self.pistas_audio if "(activa)" in t), None)
            if pista is not None and activa != pista:
                self.reproductor.seleccionar_pista("audio", pista)
                self.estado("Audiodescripción activada en esta emisión.", decir=False)
                voz.decir("Esta emisión tiene audiodescripción y se ha seleccionado.")
        if self.datos.windows.get("soloAudio") or self.ventana_video is None or self.reproductor is None:
            return
        if not self.reproductor.tiene_video():
            return
        nombre = self.canal_actual.nombre if self.canal_actual else ""
        if self.datos.windows.get("mostrarVideo"):
            # Se abre sin robar el foco: quien esté en la lista sigue en ella.
            self.ventana_video.mostrar(nombre, activar=False)
        elif not self.ventana_video.IsShown() and not self.video_avisado:
            self.video_avisado = True
            wx.CallLater(2500, self._avisar_video)

    def _avisar_video(self):
        """Recuerda una vez por sesión que la imagen está a un toque de tecla."""
        if self.cerrando or self.ventana_video is None or self.ventana_video.IsShown():
            return
        if self.reproductor is None or not self.reproductor.activo:
            return
        self.estado(f"Esta emisión trae imagen: {modulo_teclas.legible(self.teclas.combo('repro_video'))} abre la ventana de vídeo cuando quieras.", decir=False)

    def cambiar_pista(self, tipo: str, indice: int):
        """``indice`` -1 es automático (audio) o desactivados (subtítulos)."""
        if self.reproductor is None:
            return
        pistas = self.pistas_audio if tipo == "audio" else self.pistas_sub
        if indice < 0:
            self.reproductor.seleccionar_pista(tipo, None if tipo == "sub" else (pistas[0][0] if pistas else None))
        elif indice < len(pistas):
            self.reproductor.seleccionar_pista(tipo, pistas[indice][0])
        etiqueta = "Automático" if tipo == "audio" else "Desactivados"
        if 0 <= indice < len(pistas):
            etiqueta = pistas[indice][1]
        self.estado(("Pista de audio" if tipo == "audio" else "Subtítulos") + ": " + etiqueta)

    def elegir_pista(self, tipo: str):
        """Elige pista de audio o de subtítulos en un diálogo (no hay controles en pantalla)."""
        if self.reproductor is None or not self.reproductor.activo:
            aviso(self, "No hay ninguna emisión en reproducción.")
            return
        self.pistas_audio = self.reproductor.pistas("audio")
        self.pistas_sub = self.reproductor.pistas("sub")
        pistas = self.pistas_audio if tipo == "audio" else self.pistas_sub
        opciones = ["Automático" if tipo == "audio" else "Desactivados"] + [t for _, t in pistas]
        if len(opciones) == 1:
            self.estado("Esta emisión no ofrece " + ("otras pistas de audio." if tipo == "audio" else "subtítulos."))
            return
        activa = next((i for i, (_, t) in enumerate(pistas) if "(activa)" in t), -1)
        with wx.SingleChoiceDialog(self, "Elige la pista:", "Pista de audio" if tipo == "audio" else "Subtítulos", opciones) as dialogo:
            dialogo.SetSelection(activa + 1)
            if dialogo.ShowModal() == wx.ID_OK:
                self.cambiar_pista(tipo, dialogo.GetSelection() - 1)

    def elegir_modo_imagen(self):
        opciones = [m[0] for m in MODOS_IMAGEN]
        with wx.SingleChoiceDialog(self, "Tamaño de la imagen:", "Tamaño de la imagen", opciones) as dialogo:
            dialogo.SetSelection([m[1] for m in MODOS_IMAGEN].index(self.datos.windows["modoImagen"]))
            if dialogo.ShowModal() == wx.ID_OK:
                self.datos.windows["modoImagen"] = MODOS_IMAGEN[dialogo.GetSelection()][1]
                self.datos.guardar()
                if self.reproductor:
                    self.reproductor.modo_imagen(self.datos.windows["modoImagen"])
                self.estado("Tamaño de la imagen: " + opciones[dialogo.GetSelection()])

    def pausar(self):
        if self.reproductor is None or not self.reproductor.activo:
            if self.canal_actual and self.emision_actual:
                self.reproducir(self.canal_actual, self.emision_actual)
            else:
                self.estado("No hay ninguna emisión en reproducción. Elige un canal y pulsa Intro.")
            return
        pausado = self.reproductor.pausar()
        self.estado_reproduccion(("En pausa: " if pausado else "Reproduciendo: ") + (self.canal_actual.nombre if self.canal_actual else ""))

    def detener(self):
        self.cancelar_reintento()
        self.soltar_grabacion()
        if self.grabador is not None and self.grabador.activa:
            ruta, _segundos, tamano = self.grabador.parar()
            sonidos.reproducir("grabacion")
            self.estado(f"Grabación guardada: {ruta.name if ruta else 'archivo'} ({tamano / 1e6:.1f} megabytes).")
        if self.reproductor is not None:
            self.reproductor.detener()
        sonidos.reproducir("parada")
        self.SetTitle(f"{NOMBRE_APP} · Televisión y radio")
        self.pistas_audio, self.pistas_sub = [], []
        if self.ventana_video is not None:
            self.ventana_video.ocultar(avisar=False)   # el aviso de la parada es este, no el de la ventana
        grabando = len(self.grabaciones_fondo) if self.grabaciones_fondo is not None else 0
        aviso_grabacion = "" if not grabando else f" Sigue{'n' if grabando != 1 else ''} {grabando} grabación{'es' if grabando != 1 else ''} en segundo plano."
        self.estado_reproduccion("Detenido." + aviso_grabacion)

    def alternar_silencio(self):
        nuevo = not self.datos.windows["silencio"]
        self.datos.windows["silencio"] = nuevo
        self.datos.guardar()
        if self.reproductor:
            self.reproductor.silencio(nuevo)
        self.estado("Sonido silenciado." if nuevo else "Sonido activado.")

    def cambiar_volumen(self, delta: int):
        anterior = int(self.datos.windows["volumen"])
        valor = max(0, min(100, anterior + delta))
        if valor == anterior:
            sonidos.reproducir("limite")
        self.datos.windows["volumen"] = valor
        if self.reproductor:
            self.reproductor.volumen(valor)
        self.datos.guardar()
        self.estado(f"Volumen: {valor} por ciento.")

    def zapping(self, direccion: int):
        canal = self.canal_actual or self.canal_seleccionado()
        if not canal:
            return
        panel = self.paneles[canal.tipo]
        visibles = [c for c in panel.visibles if c.reproducibles]
        if not visibles:
            return
        indice = next((i for i, c in enumerate(visibles) if c.nombre == canal.nombre), -1)
        nuevo = visibles[(indice + direccion) % len(visibles)]
        sonidos.reproducir("cambio")
        if nuevo in panel.visibles:
            panel.lista.seleccionar(panel.visibles.index(nuevo))
            panel.mostrar_canal(nuevo)
        self.reproducir_canal(nuevo)

    def volver_anterior(self):
        if self.canal_anterior:
            self.reproducir_canal(self.canal_anterior)
        else:
            self.estado("No hay canal anterior.")

    def alternar_pantalla_completa(self):
        """Pantalla completa de la ventana de vídeo, que es donde se ve la imagen."""
        if self.ventana_video is None or self.reproductor is None or not self.reproductor.activo:
            self.estado("No hay ninguna emisión con imagen en reproducción.")
            return
        self.ventana_video.alternar_completa()

    def mostrar_video(self):
        """Muestra u oculta la ventana de vídeo (menú Reproducción)."""
        if self.ventana_video is None or self.reproductor is None or not self.reproductor.activo:
            self.estado("No hay ninguna emisión en reproducción.")
            return
        if self.ventana_video.IsShown():
            self.ventana_video.ocultar()
        else:
            self.ventana_video.mostrar(self.canal_actual.nombre if self.canal_actual else "", activar=True)
            self.ventana_video.info.SetFocus()
            self.estado("Ventana de vídeo abierta. Escape la cierra y el sonido sigue.")

    def _al_pulsar_ventana(self, evento):
        evento.Skip()

    # --- cuentas de proveedor -------------------------------------------------
    def cuentas(self) -> list:
        """Cuentas Xtream Codes guardadas, ya descifradas."""
        return [c for c in (xtream.Cuenta.desde_json(e) for e in self.datos.windows.get("cuentas") or []) if c is not None]

    def anadir_cuenta(self):
        with dialogos.DialogoCuenta(self) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK or dialogo.resultado is None:
                return
        self.datos.windows.setdefault("cuentas", []).append(dialogo.resultado.a_json())
        self.datos.guardar()
        self.panel_vod.actualizar_cuentas()
        self.estado(f"Cuenta «{dialogo.resultado.nombre}» añadida; se cargan sus canales.")
        self.cargar(True)

    def gestionar_cuentas(self):
        with dialogos.DialogoCuentas(self) as dialogo:
            dialogo.ShowModal()
        self.panel_vod.actualizar_cuentas()
        self.panel_info.rellenar()

    # --- grabación ------------------------------------------------------------
    def modo_fondo(self) -> bool:
        """True si las grabaciones van por su cuenta, sin ocupar el reproductor (Ajustes > Grabación)."""
        return bool(self.datos.windows.get("grabacionSegundoPlano", True))

    def gestor_fondo(self) -> grabacion.GestorFondo | None:
        """Gestor de grabaciones en segundo plano; None si todavía no hay libmpv instalado."""
        if self.grabaciones_fondo is None:
            if not modulo_datos.ruta_libmpv(self.datos):
                return None
            self.grabaciones_fondo = grabacion.GestorFondo(
                modulo_datos.carpeta_mpv(self.datos),
                lambda clave, tipo, texto: wx.CallAfter(self.evento_grabacion_fondo, clave, tipo, texto))
        return self.grabaciones_fondo

    def grabaciones_en_curso(self, ahora: float | None = None) -> list[dict]:
        """Lo que se está grabando ahora mismo, para el diálogo y para decirlo en voz alta."""
        gestor = self.grabaciones_fondo
        return gestor.resumenes(ahora) if gestor is not None else []

    @staticmethod
    def clave_programada(entrada: dict) -> str:
        return f"prog:{entrada['tipo']}:{entrada['inicio']}:{entrada['canal']}"

    @staticmethod
    def clave_manual(canal: Canal) -> str:
        return f"manual:{canal.tipo}:{canal.nombre}"

    def titulo_ahora(self, canal: Canal) -> str:
        """Título del programa en emisión, para ponérselo al archivo."""
        try:
            programas = catalogo.programas_canal(self.guia.get(canal.tipo, {}), canal)
            actual, _siguiente = catalogo.ahora_y_siguiente(programas)
        except Exception:
            return ""
        return actual.titulo if actual is not None else ""

    def alternar_grabacion(self):
        """Empieza o detiene la grabación del canal que se está viendo."""
        if self.modo_fondo() and self.canal_actual is not None:
            clave = self.clave_manual(self.canal_actual)
            gestor = self.gestor_fondo()
            if gestor is not None and gestor.activa(clave):
                self.estado(self.parar_grabacion_fondo(clave))
                return
            self.grabar_en_fondo(self.canal_actual, self.emision_actual)
            return
        if self.reproductor is None or not self.reproductor.activo:
            self.estado("No hay ninguna emisión que grabar.")
            return
        if self.grabador is None:
            self.grabador = grabacion.Grabador(self.reproductor)
        if self.grabador.activa:
            ruta, segundos, tamano = self.grabador.parar()
            sonidos.reproducir("grabacion")
            self.grabacion_programada = None
            self.estado(f"Grabación terminada: {ruta.name if ruta else 'archivo'}, {int(segundos // 60)} minutos, {tamano / 1e6:.1f} megabytes.")
            self.grabacion_terminada(ruta)
            return
        nombre = self.canal_actual.nombre if self.canal_actual else "emisión"
        formato_tv = self.datos.windows.get("formatoGrabacionTV", "ts")
        destino = grabacion.carpeta(self.datos) / grabacion.nombre_archivo(nombre, extension=self.reproductor.extension_grabacion(formato_tv))
        try:
            ruta = self.grabador.iniciar(destino, nombre)
        except RuntimeError as error:
            aviso(self, str(error), icono=wx.ICON_WARNING)
            return
        sonidos.reproducir("grabacion")
        self.estado(f"Grabando {nombre} en {ruta.name}. Pulsa otra vez para detener.")

    def grabar_canal(self, canal: Canal):
        """Graba un canal desde la lista o su menú contextual, según el modo elegido."""
        if not self.modo_fondo():
            self.reproducir_canal(canal)
            wx.CallLater(4000, self.alternar_grabacion)
            self.estado(f"Sintonizando {canal.nombre} para grabarlo…")
            return
        clave = self.clave_manual(canal)
        gestor = self.gestor_fondo()
        if gestor is not None and gestor.activa(clave):
            self.estado(self.parar_grabacion_fondo(clave))
            return
        self.grabar_en_fondo(canal)

    def grabar_en_fondo(self, canal: Canal, emision: Emision | None = None, titulo: str = "",
                        fin: float | None = None, entrada: dict | None = None, momento: float | None = None) -> str:
        """Arranca una grabación con un reproductor aparte. Devuelve la clave, o "" si no se pudo.

        No toca el reproductor principal: la emisión se descarga otra vez, sin
        imagen ni sonido, así que se puede seguir escuchando o viendo otra cosa.
        """
        automatica = entrada is not None
        gestor = self.gestor_fondo()
        if gestor is None:
            self._grabacion_imposible(entrada, "falta el reproductor libmpv; instálalo desde Herramientas, Mantenimiento.", automatica)
            return ""
        emision = emision or canal.emision_principal
        if emision is None:
            self._grabacion_imposible(entrada, f"{canal.nombre} no tiene emisiones disponibles.", automatica)
            return ""
        if canal.drm:
            self._grabacion_imposible(entrada, f"la emisión de {canal.nombre} está cifrada (DRM) y no se puede grabar.", automatica)
            return ""
        if not automatica and organizar.bloqueado(self.datos, canal) and not self.pedir_pin(f"«{canal.nombre}» está bloqueado."):
            self.estado(f"{canal.nombre} está bloqueado con PIN.")
            return ""
        clave = self.clave_programada(entrada) if automatica else self.clave_manual(canal)
        if gestor.activa(clave):
            self.estado(f"{canal.nombre} ya se está grabando.")
            return clave
        maximo = int(self.datos.windows.get("maximoGrabacionesFondo", 3))
        if len(gestor) >= maximo:
            self._grabacion_imposible(entrada, f"ya hay {len(gestor)} grabaciones en marcha (el máximo está en {maximo}, se cambia en Ajustes > Grabación).", automatica)
            return ""
        titulo = titulo or (self.titulo_ahora(canal) if not automatica else "")
        base = grabacion.carpeta(self.datos) / grabacion.nombre_archivo(canal.nombre, titulo, momento, extension="")
        if entrada is not None:
            self.programadas_fondo[clave] = entrada
        self.estado(f"Preparando la grabación de {canal.nombre} en segundo plano…")
        threading.Thread(target=self._fuente_fondo_en_hilo, args=(clave, canal, emision, base, titulo, fin, entrada), daemon=True).start()
        return clave

    def _grabacion_imposible(self, entrada: dict | None, motivo: str, automatica: bool):
        if entrada is not None:
            entrada["estado"] = "error"
            self.datos.guardar()
        texto = (f"No se pudo grabar «{entrada['titulo']}»: {motivo}" if entrada is not None else f"No se puede grabar: {motivo}")
        sonidos.reproducir("error")
        self.estado(texto)
        if not automatica:
            aviso(self, texto, icono=wx.ICON_WARNING)

    def _fuente_fondo_en_hilo(self, clave, canal, emision, base, titulo, fin, entrada):
        """Busca la dirección real (servicio oficial, YouTube, Twitch, web) sin bloquear la interfaz."""
        fuente, error = self._fuente_reproducible(canal, emision)
        wx.CallAfter(self._arrancar_fondo, clave, canal, emision, base, titulo, fin, entrada, fuente, error)

    def _arrancar_fondo(self, clave, canal, emision, base, titulo, fin, entrada, fuente, error):
        if self.cerrando:
            return
        gestor = self.gestor_fondo()
        if gestor is None or gestor.activa(clave):
            return
        if fuente is None:
            motivo = str(error) if error else "no se ha encontrado la dirección de la emisión; este canal solo se puede grabar con el reproductor."
            self._grabacion_imposible(entrada, motivo, entrada is not None)
            self.programadas_fondo.pop(clave, None)
            return
        try:
            gestor.iniciar(clave, fuente, base, canal.nombre, titulo, self.datos.windows.get("calidad", "max"),
                           self.datos.windows.get("bufferRecepcion", "normal"), fin,
                           lambda: self._fuente_reproducible(canal, emision)[0],
                           bool(self.datos.windows.get("grabarSoloAudio", False)),
                           self.datos.windows.get("formatoGrabacionTV", "ts"))
        except RuntimeError as fallo:
            self._grabacion_imposible(entrada, str(fallo), entrada is not None)
            return
        sonidos.reproducir("programada" if entrada is not None else "grabacion")
        quedan = "" if fin is None else f" Termina a las {time.strftime('%H:%M', time.localtime(fin + grabacion.MARGEN_FIN))}."
        self.estado(f"Grabando {canal.nombre} en segundo plano{' · ' + titulo if titulo else ''}.{quedan} El reproductor sigue libre.")

    def evento_grabacion_fondo(self, clave: str, tipo: str, texto: str):
        """Avisos de una grabación en segundo plano (llegan desde sus propios hilos)."""
        if self.cerrando:
            return
        gestor = self.grabaciones_fondo
        grabador = gestor.obtener(clave) if gestor is not None else None
        nombre = grabador.canal if grabador is not None else "la emisión"
        entrada = self.programadas_fondo.get(clave)
        if tipo == "grabando":
            if entrada is not None:
                entrada["archivo"] = texto
                self.datos.guardar()
            self.estado(f"Grabando {nombre} en segundo plano en {texto}.", decir=False)
        elif tipo == "reintento":
            self.estado(f"La grabación de {nombre} se ha cortado: {texto}", decir=False)
        elif tipo == "error":
            sonidos.reproducir("error")
            if gestor is not None:
                gestor.parar(clave)
            if entrada is not None:
                entrada["estado"] = "error"
                self.datos.guardar()
                self.programadas_fondo.pop(clave, None)
            self.estado(f"La grabación de {nombre} ha fallado: {texto}")

    def parar_grabacion_fondo(self, clave: str, terminada: bool = False) -> str:
        """Detiene una grabación en segundo plano y devuelve el mensaje para la barra de estado."""
        gestor = self.grabaciones_fondo
        if gestor is None or not gestor.activa(clave):
            return "Esa grabación ya no estaba en marcha."
        grabador = gestor.obtener(clave)
        nombre, archivos = grabador.canal, grabador.nombres()
        ruta, segundos, tamano = gestor.parar(clave)
        entrada = self.programadas_fondo.pop(clave, None)
        if entrada is not None:
            entrada["estado"] = "hecha"
            entrada["archivo"] = ruta.name if ruta else entrada.get("archivo", "")
            self.datos.guardar()
        sonidos.reproducir("programada" if entrada is not None else "grabacion")
        self.panel_info.rellenar()
        self.grabacion_terminada(ruta)
        cabecera = "Grabación terminada" if terminada else "Grabación detenida"
        return (f"{cabecera}: {nombre}, {grabacion.duracion_hablada(segundos)}, "
                f"{grabacion.tamano_hablado(tamano)} en {archivos or 'ningún archivo'}.")

    def grabacion_terminada(self, ruta):
        """Lo que toca hacer cuando una grabación acaba de cerrarse."""
        if ruta is not None:
            grabacion.ejecutar_orden_posterior(self.datos.windows.get("ordenPosterior", ""), ruta)
        self.limpiar_grabaciones_si_toca()
        self.sincronizar_tareas()
        wx.CallLater(3000, self.al_terminar_grabaciones)

    # --- reglas de grabación automática ---------------------------------------
    def aplicar_reglas(self, avisar: bool = False) -> int:
        """Programa sola las grabaciones que encajen con las reglas. Devuelve cuántas.

        Se llama al cargar la guía, cada media hora y cuando se toca una regla.
        """
        reglas = self.datos.windows.get("reglasGrabacion") or []
        if not reglas or not self.canales:
            return 0
        entradas = self.datos.windows.setdefault("grabaciones", [])
        candidatos = []
        for canal in self.canales:
            programas = catalogo.programas_canal(self.guia.get(canal.tipo, {}), canal)
            if not programas:
                continue
            favorito = bool(self.datos.estado_canal(canal.tipo, canal.nombre)["favorite"])
            candidatos.append((canal, programas, favorito))
        nuevas = grabacion.programadas_de_reglas(reglas, candidatos, entradas)
        if not nuevas:
            if avisar:
                self.estado("Las reglas no han encontrado nada nuevo que grabar en la guía.")
            return 0
        entradas.extend(nuevas)
        grabacion.podar_programadas(entradas)
        self.datos.guardar()
        self.sincronizar_tareas()
        titulos = ", ".join(dict.fromkeys(n["titulo"] for n in nuevas[:4]))
        self.estado(f"Las reglas han programado {len(nuevas)} grabación" + ("es" if len(nuevas) != 1 else "") + f": {titulos}"
                    + ("…" if len(nuevas) > 4 else "."))
        self.avisar_conflictos()
        return len(nuevas)

    def gestionar_reglas(self):
        with dialogos.DialogoReglas(self) as dialogo:
            dialogo.ShowModal()
        self.panel_info.rellenar()

    def regla_desde_programa(self, canal: Canal, programa: Programa):
        """Crea una regla a partir de un programa concreto («graba siempre esto»)."""
        regla = grabacion.regla_nueva(programa.titulo, canal.nombre)
        with dialogos.DialogoRegla(self, self.canales, regla) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK or dialogo.resultado is None:
                return
            self.datos.windows.setdefault("reglasGrabacion", []).append(dialogo.resultado)
        self.datos.guardar()
        puestas = self.aplicar_reglas(avisar=True)
        self.estado(f"Regla creada para «{programa.titulo}»: {puestas} grabación" + ("es" if puestas != 1 else "") + " programada" + ("s" if puestas != 1 else "") + ".")

    def avisar_conflictos(self) -> int:
        """Dice si hay más grabaciones solapadas de las que se pueden hacer a la vez."""
        if not self.modo_fondo():
            return 0
        maximo = int(self.datos.windows.get("maximoGrabacionesFondo", 3))
        grupos = grabacion.conflictos(self.datos.windows.get("grabaciones") or [], maximo)
        if not grupos:
            return 0
        grupo = grupos[0]
        hora = time.strftime("%H:%M", time.localtime(grupo[0]["inicio"]))
        self.estado(f"Aviso: a las {hora} se solapan {len(grupo)} grabaciones y el máximo está en {maximo}. "
                    "Se pueden quitar algunas en Herramientas, Grabación, Grabaciones, o subir el máximo en Ajustes.")
        return len(grupos)

    # --- qué empieza ahora ------------------------------------------------------
    def programas_proximos(self, minutos: int = 60, solo_favoritos: bool = True) -> list[tuple]:
        """(canal, programa) de lo que empieza en los próximos minutos."""
        ahora = time.time()
        limite = ahora + minutos * 60
        salida = []
        for canal in self.canales:
            if solo_favoritos and not self.datos.estado_canal(canal.tipo, canal.nombre)["favorite"]:
                continue
            for programa in catalogo.programas_canal(self.guia.get(canal.tipo, {}), canal):
                if ahora < programa.inicio <= limite:
                    salida.append((canal, programa))
        salida.sort(key=lambda par: (par[1].inicio, par[0].nombre))
        return salida[:400]

    def ver_ahora(self):
        with dialogos.DialogoAhora(self) as dialogo:
            dialogo.ShowModal()

    # --- comprobar canales -------------------------------------------------------
    def comprobar_canales(self):
        """Comprueba en segundo plano qué canales responden."""
        panel = self.panel_activo()
        visibles = list(getattr(panel, "visibles", []) or []) if panel is not None else []
        favoritos = [c for c in self.canales if self.datos.estado_canal(c.tipo, c.nombre)["favorite"]]
        opciones = [
            (f"Mis favoritos ({len(favoritos)} canales)", favoritos),
            (f"Los canales de la lista que estoy viendo ({len(visibles)})", visibles),
            (f"Todos los canales de televisión ({sum(1 for c in self.canales if c.tipo == 'tv')})", [c for c in self.canales if c.tipo == "tv"]),
            (f"Todas las emisoras de radio ({sum(1 for c in self.canales if c.tipo == 'radio')})", [c for c in self.canales if c.tipo == "radio"]),
        ]
        opciones = [(texto, canales) for texto, canales in opciones if canales]
        if not opciones:
            aviso(self, "No hay canales cargados que comprobar.")
            return
        with wx.SingleChoiceDialog(self, "¿Qué canales quieres comprobar?", "Comprobar canales", [o[0] for o in opciones]) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            elegidos = opciones[dialogo.GetSelection()][1]
        with dialogos.DialogoComprobar(self, elegidos) as dialogo:
            dialogo.ShowModal()
        self.panel_info.rellenar()

    # --- sincronizar con una carpeta en la nube ----------------------------------
    def carpeta_sincronizacion(self) -> Path | None:
        ruta = (self.datos.windows.get("carpetaSincronizacion") or "").strip()
        return Path(ruta) if ruta else None

    def archivo_sincronizacion(self) -> Path | None:
        carpeta = self.carpeta_sincronizacion()
        return (carpeta / "Resintoniza-sincronizacion.zip") if carpeta else None

    def sincronizar_nube(self, manual: bool = True):
        """Guarda o trae la configuración de una carpeta de OneDrive, Dropbox…"""
        destino = self.archivo_sincronizacion()
        if destino is None:
            aviso(self, "Primero elige la carpeta en Ajustes, pestaña Organización: «Carpeta para sincronizar».")
            return
        opciones = ["Guardar mi configuración en esa carpeta", "Traer la configuración que hay en esa carpeta"]
        detalle = ""
        if destino.exists():
            marca = time.strftime("%d/%m/%Y a las %H:%M", time.localtime(destino.stat().st_mtime))
            detalle = f"\n\nLa copia que hay en la carpeta es del {marca}."
        with wx.SingleChoiceDialog(self, f"Carpeta: {destino.parent}{detalle}\n\nSe sincronizan ajustes, favoritos, orden, plantillas, recordatorios, grabaciones programadas, reglas y perfiles.", "Sincronizar", opciones) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            subir = dialogo.GetSelection() == 0
        try:
            if subir:
                destino.parent.mkdir(parents=True, exist_ok=True)
                respaldo.crear_copia(self.datos, destino)
                self.estado(f"Configuración guardada en {destino}. Al abrir en otro equipo, elige «Traer la configuración».")
                return
            if not destino.exists():
                aviso(self, "En esa carpeta todavía no hay ninguna copia. Guarda primero desde el equipo que tenga la configuración buena.")
                return
            if not pregunta(self, "Se va a sustituir tu configuración por la de la carpeta.\nAntes se guarda una copia de la actual.\n\n¿Seguir?"):
                return
            respaldo.restaurar(self.datos, destino)
        except Exception as error:
            aviso(self, f"No se pudo sincronizar: {error}", icono=wx.ICON_ERROR)
            return
        self.estado("Configuración traída de la carpeta compartida. Se recargan las listas.")
        self.aplicar_accesibilidad()
        self.cargar(False)

    # --- multiventana ------------------------------------------------------------
    def abrir_mosaico(self):
        """Elige hasta cuatro canales y los abre a la vez, con el sonido de uno."""
        if self.mosaico is not None:
            self.mosaico.Raise()
            self.estado("La multiventana ya está abierta.")
            return
        if not modulo_datos.ruta_libmpv(self.datos):
            aviso(self, "Falta el reproductor libmpv. Instálalo desde Herramientas, Mantenimiento.")
            return
        candidatos = [c for c in self.canales if self.datos.estado_canal(c.tipo, c.nombre)["favorite"] and c.emision_principal]
        if len(candidatos) < 2:
            candidatos = [c for c in self.canales if c.tipo == "tv" and c.emision_principal][:200]
        if len(candidatos) < 2:
            aviso(self, "Hacen falta al menos dos canales para la multiventana.")
            return
        etiquetas = [c.nombre for c in candidatos]
        with wx.MultiChoiceDialog(self, f"Elige de dos a {mosaico.MAXIMO} canales (se abren a la vez y suena el primero):", "Multiventana", etiquetas) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            elegidos = [candidatos[i] for i in dialogo.GetSelections()][:mosaico.MAXIMO]
        if len(elegidos) < 2:
            aviso(self, "Elige al menos dos canales.")
            return
        self.estado(f"Preparando la multiventana con {len(elegidos)} canales…")
        generacion = self.generacion_reproduccion
        threading.Thread(target=self._preparar_mosaico, args=(generacion, elegidos), daemon=True).start()

    def _preparar_mosaico(self, generacion, canales):
        seleccion = []
        for canal in canales:
            emision = canal.emision_principal
            fuente, _error = self._fuente_reproducible(canal, emision) if emision is not None else (None, None)
            if fuente is not None:
                seleccion.append((canal, fuente))
        wx.CallAfter(self._abrir_mosaico, generacion, seleccion)

    def _abrir_mosaico(self, generacion, seleccion):
        if self.cerrando or self.mosaico is not None:
            return
        if len(seleccion) < 2:
            aviso(self, "No se han podido preparar al menos dos de esos canales (puede que solo se vean en su web).")
            return
        self.mosaico = mosaico.VentanaMosaico(self, seleccion, modulo_datos.carpeta_mpv(self.datos),
                                              self.datos.windows["volumen"], self.datos.windows.get("bufferRecepcion", "normal"))
        self.estado(f"Multiventana abierta con {len(seleccion)} canales. Las cifras eligen cuál suena y Escape la cierra.")

    # --- nivelador, velocidad y desfase del audio --------------------------------
    def alternar_nivelador(self):
        nuevo = not self.datos.windows.get("nivelarVolumen", False)
        self.datos.windows["nivelarVolumen"] = nuevo
        self.datos.guardar()
        if self.reproductor is not None:
            self.reproductor.nivelar_volumen(nuevo)
        self.estado("Nivelador de volumen activado: los canales suenan más parecidos." if nuevo
                    else "Nivelador de volumen desactivado: cada canal suena como emite.")

    def elegir_velocidad(self):
        if self.reproductor is None or not self.reproductor.activo:
            self.estado("No hay ninguna emisión en reproducción.")
            return
        actual = self.reproductor.velocidad()
        opciones = [n for n, _v in VELOCIDADES]
        with wx.SingleChoiceDialog(self, "Velocidad de reproducción (el tono se corrige solo; en directo se vuelve al directo enseguida):", "Velocidad", opciones) as dialogo:
            dialogo.SetSelection(next((i for i, (_n, v) in enumerate(VELOCIDADES) if abs(v - actual) < 0.01), 0))
            if dialogo.ShowModal() != wx.ID_OK:
                return
            nombre, valor = VELOCIDADES[dialogo.GetSelection()]
        self.reproductor.velocidad(valor)
        self.estado(f"Velocidad: {nombre}.")

    def ajustar_desfase(self):
        if self.reproductor is None or not self.reproductor.activo:
            self.estado("No hay ninguna emisión en reproducción.")
            return
        actual = self.reproductor.desfase_audio()
        opciones = [("Sin desfase (0)", 0.0)] + [(f"Audio {abs(d):.1f} segundos {'antes' if d < 0 else 'después'}", d)
                                                 for d in (-1.0, -0.5, -0.25, 0.25, 0.5, 1.0)]
        with wx.SingleChoiceDialog(self, f"Retraso del audio respecto a la imagen (ahora: {actual:.2f} segundos):", "Retraso del audio", [o[0] for o in opciones]) as dialogo:
            dialogo.SetSelection(next((i for i, (_n, v) in enumerate(opciones) if abs(v - actual) < 0.01), 0))
            if dialogo.ShowModal() != wx.ID_OK:
                return
            nombre, valor = opciones[dialogo.GetSelection()]
        self.reproductor.desfase_audio(valor)
        self.estado(f"Retraso del audio: {nombre}.")

    # --- recortar, limpiar, tareas y apagado -------------------------------------
    def recortar_grabacion(self, archivo: dict, parent=None):
        """Corta el principio y el final de una grabación sin recodificar nada."""
        parent = parent or self
        ruta = archivo["ruta"]
        if not grabacion.recortable(ruta):
            aviso(parent, "Solo se pueden recortar las grabaciones en formato .ts (las de las emisiones HLS, que son casi todas).")
            return
        if not modulo_datos.ruta_libmpv(self.datos):
            aviso(parent, "Hace falta el reproductor libmpv para recortar.")
            return
        duracion = grabacion.duracion_de(ruta, modulo_datos.carpeta_mpv(self.datos))
        if duracion <= 0:
            aviso(parent, "No se ha podido leer la duración de esa grabación.")
            return
        with dialogos.DialogoRecorte(parent, archivo["nombre"], duracion) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            inicio, fin = dialogo.inicio, dialogo.fin
        self.estado("Recortando la grabación…")
        wx.BeginBusyCursor()
        try:
            destino = grabacion.recortar(ruta, inicio, fin, modulo_datos.carpeta_mpv(self.datos))
        except Exception as error:
            wx.EndBusyCursor()
            aviso(parent, f"No se pudo recortar: {error}", icono=wx.ICON_ERROR)
            return
        wx.EndBusyCursor()
        tamano = destino.stat().st_size if destino.exists() else 0
        self.estado(f"Recorte guardado en {destino.name}: {grabacion.duracion_hablada(fin - inicio)}, {grabacion.tamano_hablado(tamano)}. La grabación original no se ha tocado.")

    def limpiar_grabaciones_si_toca(self):
        """Aplica las reglas de limpieza (solo si la persona las ha configurado)."""
        windows = self.datos.windows
        if not any(int(windows.get(c, 0) or 0) for c in ("retencionDias", "retencionGigas", "retencionPorPrograma")):
            return 0
        borradas = grabacion.limpiar_carpeta(self.datos)
        if borradas:
            self.estado(f"Limpieza automática de grabaciones: {len(borradas)} borradas ({', '.join(borradas[:3])}"
                        + ("…" if len(borradas) > 3 else "") + ").")
        return len(borradas)

    def sincronizar_tareas(self, avisar: bool = False):
        """Deja en el Programador de Windows una tarea por grabación pendiente."""
        if not self.datos.windows.get("tareaWindows") or not tareas.disponible():
            return
        programadas = list(self.datos.windows.get("grabaciones") or [])
        threading.Thread(target=self._tareas_en_hilo, args=(programadas, avisar), daemon=True).start()

    def _tareas_en_hilo(self, programadas, avisar):
        creadas, quitadas, problema = tareas.sincronizar(programadas)
        if avisar or problema:
            wx.CallAfter(self._tareas_hechas, creadas, quitadas, problema)

    def _tareas_hechas(self, creadas, quitadas, problema):
        if self.cerrando:
            return
        if problema:
            self.estado(f"No se han podido crear las tareas de Windows: {problema}")
            return
        self.estado(f"Programador de tareas: {creadas} tareas nuevas y {quitadas} quitadas. "
                    "Windows abrirá la aplicación (y despertará el equipo) unos minutos antes de cada grabación.")

    def comprobar_espacio(self, ahora: float):
        """Cada medio minuto: si el disco se está llenando, se para de grabar."""
        if ahora - self.ultimo_espacio < 30:
            return
        self.ultimo_espacio = ahora
        if self.grabaciones_fondo is None or not len(self.grabaciones_fondo):
            return
        suficiente, libre = grabacion.hay_espacio(self.datos)
        if suficiente:
            return
        cuantas = len(self.grabaciones_fondo)
        for clave in list(self.grabaciones_fondo.grabaciones):
            self.parar_grabacion_fondo(clave)
        sonidos.reproducir("error")
        self.estado(f"Se han parado {cuantas} grabaciones: quedan {libre:.1f} gigabytes libres en el disco, "
                    f"por debajo del mínimo que tienes puesto. Lo guardado hasta ahora está a salvo.")

    def anunciar_grabaciones_si_toca(self, ahora: float):
        """Aviso hablado cada tantos minutos mientras se está grabando."""
        minutos = int(self.datos.windows.get("avisoGrabacionMinutos", 0) or 0)
        if not minutos or self.grabaciones_fondo is None or not len(self.grabaciones_fondo):
            return
        if ahora - self.ultimo_aviso_grabacion < minutos * 60:
            return
        self.ultimo_aviso_grabacion = ahora
        for grabador in list(self.grabaciones_fondo.grabaciones.values()):
            voz.decir(grabador.estado(), interrumpir=False)

    def al_terminar_grabaciones(self):
        """Cerrar, suspender o apagar cuando ya no queda nada grabando."""
        modo = self.datos.windows.get("alTerminarGrabacion", "nada")
        if modo == "nada" or self.cerrando:
            return
        if self.grabaciones_fondo is not None and len(self.grabaciones_fondo):
            return
        if self.grabador is not None and self.grabador.activa:
            return
        if any(e.get("estado") == "pendiente" and e["inicio"] - time.time() < 900
               for e in (self.datos.windows.get("grabaciones") or [])):
            self.estado("Queda otra grabación dentro de poco: no se apaga nada todavía.")
            return
        self.datos.windows["alTerminarGrabacion"] = "nada"   # solo una vez
        self.datos.guardar()
        if modo == "cerrar":
            self.estado("Grabaciones terminadas: se cierra la aplicación.")
            wx.CallLater(4000, self.Close)
            return
        ok, mensaje = tareas.apagar(modo)
        sonidos.reproducir("parada")
        self.estado(mensaje if ok else f"No se pudo {modo} el equipo: {mensaje}")
        if ok and modo == "apagar":
            if not pregunta(self, f"{mensaje}\n\n¿Cancelar el apagado?", "Apagado programado"):
                return
            tareas.cancelar_apagado()
            self.estado("Apagado cancelado.")

    # --- reanudar las grabaciones donde se dejaron --------------------------------
    def guardar_posicion(self, ruta_texto: str, segundos: float, duracion: float):
        posiciones = self.datos.windows.setdefault("posicionesGrabaciones", {})
        if segundos < 30 or (duracion and segundos > duracion - 30):
            posiciones.pop(ruta_texto, None)
        else:
            posiciones[ruta_texto] = float(segundos)

    def soltar_grabacion(self):
        """Al dejar de ver una grabación guardada, anota por dónde iba."""
        if self.archivo_reproduciendo is None:
            return
        if self.reproductor is not None and self.reproductor.activo:
            self.guardar_posicion(self.archivo_reproduciendo, self.reproductor.posicion(), self.reproductor.duracion())
            self.datos.guardar()
        self.archivo_reproduciendo = None

    def anotar_posicion_actual(self, ahora: float):
        """Cada 15 segundos guarda por dónde va la grabación que se está viendo."""
        if self.archivo_reproduciendo is None or self.reproductor is None or not self.reproductor.activo:
            return
        if ahora - self.ultima_posicion < 15:
            return
        self.ultima_posicion = ahora
        self.guardar_posicion(self.archivo_reproduciendo, self.reproductor.posicion(), self.reproductor.duracion())

    def programar_grabacion(self, canal: Canal, programa: Programa, parent=None):
        """Programa la grabación de un programa desde la guía."""
        parent = parent or self
        if programa.fin <= time.time():
            if catchup.disponible(canal, programa.inicio, programa.fin):
                if pregunta(parent, "Ese programa ya ha terminado, pero este canal permite verlo emitido.\n\n¿Quieres verlo ahora?"):
                    self.reproducir_catchup(canal, programa, parent)
                return
            aviso(parent, "Ese programa ya ha terminado.")
            return
        antes, despues = grabacion.margenes(self.datos, canal.nombre)
        duracion = programa.fin - programa.inicio + (antes + despues) * 60
        ocupa = grabacion.tamano_estimado(duracion, self.datos.windows.get("grabarSoloAudio", False))
        suficiente, libre = grabacion.hay_espacio(self.datos)
        detalle = (f"\n\nDura {int(duracion // 60)} minutos y ocupará unos {ocupa:.0f} megabytes; "
                   f"quedan {libre:.1f} gigabytes libres." + ("" if suficiente else " ¡Ojo, queda muy poco espacio!"))
        opciones = [f"{m} minuto{'s' if m != 1 else ''} antes" for m in dialogos.MINUTOS_MARGEN]
        with wx.SingleChoiceDialog(parent, f"{programa.titulo}\n{canal.nombre} · {programa.fecha()} {programa.horario()}{detalle}\n\n¿Cuántos minutos antes quieres empezar a grabar?", "Grabar programa", opciones) as dialogo:
            dialogo.SetSelection(next((i for i, m in enumerate(dialogos.MINUTOS_MARGEN) if m == antes), 2))
            if dialogo.ShowModal() != wx.ID_OK:
                return
            margen = dialogos.MINUTOS_MARGEN[dialogo.GetSelection()]
        lista = self.datos.windows.setdefault("grabaciones", [])
        entrada = grabacion.nueva_programada(canal, programa, margen, despues)
        lista[:] = [g for g in lista if not (g["canal"] == canal.nombre and g["inicio"] == entrada["inicio"])]
        lista.append(entrada)
        self.datos.guardar()
        hora = time.strftime("%H:%M", time.localtime(entrada["inicio"]))
        como = ("Se grabará en segundo plano, sin ocupar el reproductor." if self.modo_fondo()
                else "A esa hora se sintonizará el canal para grabarlo.")
        abierta = ("Windows abrirá la aplicación unos minutos antes." if self.datos.windows.get("tareaWindows") and tareas.disponible()
                   else "La aplicación debe estar abierta.")
        self.estado(f"Grabación programada: {programa.titulo} en {canal.nombre}, a partir de las {hora}. {como} {abierta}")
        self.sincronizar_tareas()
        self.avisar_conflictos()

    def ver_grabaciones(self):
        with dialogos.DialogoGrabaciones(self) as dialogo:
            dialogo.ShowModal()
        self.panel_info.rellenar()

    def reproducir_archivo(self, ruta, titulo: str):
        """Reproduce una grabación guardada, ofreciendo seguir donde se dejó."""
        if not self.asegurar_reproductor():
            return
        self.canal_actual, self.emision_actual = None, None
        self.generacion_reproduccion += 1
        self.archivo_reproduciendo = str(ruta)
        self.SetTitle(f"{titulo} · {NOMBRE_APP}")
        self._iniciar(proveedores.Fuente(str(ruta), descripcion="Grabación guardada"))
        guardada = (self.datos.windows.get("posicionesGrabaciones") or {}).get(str(ruta), 0)
        if guardada and guardada > 30:
            texto = grabacion.duracion_hablada(guardada)
            if pregunta(self, f"Dejaste «{titulo}» por el minuto {int(guardada // 60)}.\n\n¿Seguir donde lo dejaste ({texto})?", "Reanudar"):
                wx.CallLater(1500, self._reanudar, guardada)
                self.estado_reproduccion(f"Reanudando {titulo} en {texto}.")
                return
            self.datos.windows.setdefault("posicionesGrabaciones", {}).pop(str(ruta), None)
            self.datos.guardar()
        self.estado_reproduccion(f"Reproduciendo la grabación {titulo}.")

    def _reanudar(self, segundos: float):
        if self.reproductor is not None and self.reproductor.activo:
            self.reproductor.ir_a(segundos)

    def _revisar_grabaciones(self, ahora: float):
        """Arranca y detiene las grabaciones programadas. Se llama cada segundo.

        En segundo plano cada una tiene su propio reproductor, así que pueden
        solaparse varias; con el reproductor principal solo cabe una.
        """
        pendientes = self.datos.windows.get("grabaciones") or []
        cambios = False
        for entrada in list(pendientes):
            clave = self.clave_programada(entrada)
            if grabacion.caducada(entrada, ahora):
                entrada["estado"] = "error"
                cambios = True
                self.estado(f"La grabación de «{entrada['titulo']}» no se pudo hacer: la aplicación no estaba abierta a esa hora.")
            elif grabacion.toca_empezar(entrada, ahora):
                canal = next((c for c in self.canales if c.tipo == entrada["tipo"] and c.nombre == entrada["canal"]), None)
                if canal is None:
                    entrada["estado"] = "error"
                    cambios = True
                    self.estado(f"La grabación de «{entrada['titulo']}» no se pudo hacer: {entrada['canal']} ya no está en las listas.")
                    continue
                if self.modo_fondo():
                    gestor = self.gestor_fondo()
                    if gestor is not None and gestor.activa(clave):
                        continue
                    entrada["estado"] = "grabando"
                    cambios = True
                    self.grabar_en_fondo(canal, titulo=entrada["titulo"], fin=entrada["fin"], entrada=entrada, momento=entrada["inicio"])
                elif self.grabador is None or not self.grabador.activa:
                    entrada["estado"] = "grabando"
                    cambios = True
                    self.grabacion_programada = entrada
                    self.reproducir_canal(canal)
                    wx.CallLater(6000, self._empezar_programada, entrada)
            elif grabacion.toca_parar(entrada, ahora):
                entrada["estado"] = "hecha"
                cambios = True
                gestor = self.grabaciones_fondo
                if gestor is not None and gestor.activa(clave):
                    self.estado(self.parar_grabacion_fondo(clave, terminada=True))
                elif self.grabacion_programada is entrada and self.grabador is not None and self.grabador.activa:
                    ruta, _segundos, tamano = self.grabador.parar()
                    entrada["archivo"] = ruta.name if ruta else ""
                    sonidos.reproducir("programada")
                    self.estado(f"Grabación de «{entrada['titulo']}» terminada: {entrada['archivo']} ({tamano / 1e6:.1f} megabytes).")
                    self.grabacion_terminada(ruta)
                if self.grabacion_programada is entrada:
                    self.grabacion_programada = None
        if cambios:
            self.datos.guardar()
            if getattr(self, "icono_bandeja", None):
                self.icono_bandeja.actualizar_estado()

    def detener_programada(self, entrada: dict) -> str:
        """Para ya una grabación programada que está en marcha (desde el diálogo)."""
        clave = self.clave_programada(entrada)
        gestor = self.grabaciones_fondo
        if gestor is not None and gestor.activa(clave):
            mensaje = self.parar_grabacion_fondo(clave)
        elif self.grabacion_programada is entrada and self.grabador is not None and self.grabador.activa:
            ruta, segundos, tamano = self.grabador.parar()
            self.grabacion_programada = None
            entrada["archivo"] = ruta.name if ruta else entrada.get("archivo", "")
            sonidos.reproducir("grabacion")
            mensaje = (f"Grabación detenida: {entrada['canal']}, {grabacion.duracion_hablada(segundos)}, "
                       f"{grabacion.tamano_hablado(tamano)} en {entrada['archivo'] or 'ningún archivo'}.")
        else:
            mensaje = "Esa grabación ya no estaba en marcha."
        entrada["estado"] = "hecha"
        self.datos.guardar()
        self.estado(mensaje)
        return mensaje

    def _empezar_programada(self, entrada: dict):
        """Empieza a grabar cuando la emisión ya está en marcha."""
        if self.cerrando or entrada.get("estado") != "grabando":
            return
        if self.reproductor is None or not self.reproductor.activo:
            wx.CallLater(5000, self._empezar_programada, entrada)
            return
        if self.grabador is None:
            self.grabador = grabacion.Grabador(self.reproductor)
        if self.grabador.activa:
            return
        formato_tv = self.datos.windows.get("formatoGrabacionTV", "ts")
        destino = grabacion.carpeta(self.datos) / grabacion.nombre_archivo(entrada["canal"], entrada["titulo"], entrada["inicio"], self.reproductor.extension_grabacion(formato_tv))
        try:
            ruta = self.grabador.iniciar(destino, entrada["canal"])
        except RuntimeError as error:
            entrada["estado"] = "error"
            self.datos.guardar()
            self.estado(f"No se pudo grabar «{entrada['titulo']}»: {error}")
            return
        entrada["archivo"] = ruta.name
        self.datos.guardar()
        sonidos.reproducir("grabacion")
        self.estado(f"Grabando «{entrada['titulo']}» de {entrada['canal']} en {ruta.name}.")

    # --- catch-up y pausa del directo ----------------------------------------
    def reproducir_catchup(self, canal: Canal, programa: Programa, parent=None):
        """Reproduce un programa ya emitido, si el proveedor lo permite."""
        parent = parent or self
        emision = canal.emision_principal
        if emision is None or not catchup.disponible(canal, programa.inicio, programa.fin):
            aviso(parent, "Este canal no permite ver programas ya emitidos.")
            return
        url = catchup.url_programa(canal, emision.url, programa.inicio, programa.fin)
        if not url:
            aviso(parent, "No se ha podido construir la dirección de ese programa.")
            return
        if not self.asegurar_reproductor():
            return
        self.canal_actual, self.emision_actual = canal, catalogo.Emision("directo", url, "m3u8")
        self.generacion_reproduccion += 1
        self.SetTitle(f"{programa.titulo} · {canal.nombre} · {NOMBRE_APP}")
        self._iniciar(proveedores.fuente_directa(canal, self.emision_actual, url))
        self.estado_reproduccion(f"Reproduciendo «{programa.titulo}» de {canal.nombre}, emitido el {programa.fecha()}.")

    def retroceder_directo(self):
        if self.reproductor is None or not self.reproductor.activo:
            self.estado("No hay ninguna emisión en reproducción.")
            return
        if not self.datos.windows.get("timeshiftMinutos", 0):
            self.estado("La pausa del directo está desactivada. Actívala en Ajustes, Reproductor.")
            return
        if self.reproductor.retroceder(RETROCESO):
            self.estado_reproduccion(f"Retrocedidos {RETROCESO} segundos del directo.")
        else:
            sonidos.reproducir("limite")
            self.estado("No hay más directo guardado para retroceder.")

    def volver_al_directo(self):
        if self.reproductor is None or not self.reproductor.activo:
            self.estado("No hay ninguna emisión en reproducción.")
            return
        if self.reproductor.volver_al_directo():
            self.estado_reproduccion("De vuelta al directo.")
        else:
            self.estado("No se ha podido volver al directo.")

    # --- calidad, datos y solo audio -----------------------------------------
    def elegir_calidad(self):
        opciones = [c[0] for c in CALIDADES]
        actual = self.datos.windows.get("calidad", "max")
        with wx.SingleChoiceDialog(self, "Calidad máxima de las emisiones con varias resoluciones:", "Calidad", opciones) as dialogo:
            dialogo.SetSelection(next((i for i, c in enumerate(CALIDADES) if c[1] == actual), 0))
            if dialogo.ShowModal() != wx.ID_OK:
                return
            eleccion = CALIDADES[dialogo.GetSelection()]
        self.datos.windows["calidad"] = eleccion[1]
        self.datos.guardar()
        if self.reproductor is not None:
            self.reproductor.calidad(eleccion[1])
        self.estado(f"Calidad: {eleccion[0]}. Se aplica al volver a cargar la emisión.")
        if self.canal_actual and self.emision_actual and pregunta(self, "¿Recargar ahora la emisión para aplicar la calidad nueva?"):
            self.recargar()

    def ver_estadisticas(self):
        if self.reproductor is None or not self.reproductor.activo:
            aviso(self, "No hay ninguna emisión en reproducción.")
            return
        filas = self.reproductor.estadisticas()
        if self.grabador is not None and self.grabador.activa:
            filas.append(("Grabación", self.grabador.estado()))
        for grabador in (self.grabaciones_fondo.grabaciones.values() if self.grabaciones_fondo is not None else []):
            filas.append(("Grabación en segundo plano", grabador.estado()))
        titulo = f"Datos de {self.canal_actual.nombre}" if self.canal_actual else "Datos de la emisión"
        texto = "\n".join(f"{k}: {v}" for k, v in filas)
        dialogo_html(self, titulo, tabla_html(titulo, filas, "Información técnica de la emisión que se está reproduciendo."), texto)

    def alternar_solo_audio(self):
        nuevo = not self.datos.windows.get("soloAudio", False)
        self.datos.windows["soloAudio"] = nuevo
        self.datos.guardar()
        if self.reproductor is not None:
            self.reproductor.solo_audio(nuevo)
        if nuevo and self.ventana_video is not None and self.ventana_video.IsShown():
            self.ventana_video.ocultar(avisar=False)
        self.estado("Modo solo audio activado: no se descarga el vídeo." if nuevo else "Modo solo audio desactivado.")
        if self.canal_actual and self.emision_actual:
            self.recargar()

    # --- enviar a la tele -----------------------------------------------------
    def enviar_a_tele(self):
        fuente = self.reproductor.fuente if self.reproductor is not None else None
        if fuente is None:
            self.estado("No hay ninguna emisión que enviar. Reproduce un canal primero.")
            return
        titulo = self.canal_actual.nombre if self.canal_actual else "Emisión"
        with dialogos.DialogoEnviar(self, fuente.url, titulo) as dialogo:
            dialogo.ShowModal()

    # --- organización ---------------------------------------------------------
    def ver_historial(self):
        with dialogos.DialogoHistorial(self) as dialogo:
            dialogo.ShowModal()

    def ir_a_numero(self):
        panel = self.panel_activo()
        if panel is None or not panel.visibles:
            self.estado("Abre la pestaña de Televisión o Radio para ir a un número de canal.")
            return
        with dialogos.DialogoNumero(self, len(panel.visibles)) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            numero = dialogo.valor()
        indice = organizar.buscar_numero(panel.visibles, numero)
        if 0 <= indice < len(panel.visibles):
            panel.lista.seleccionar(indice, enfocar=True)
            panel.mostrar_canal(panel.visibles[indice])
            self.estado(f"Canal {numero}: {panel.visibles[indice].nombre}.")
        else:
            self.estado(f"No hay ningún canal con el número {numero}.")

    def ver_duplicados(self):
        with dialogos.DialogoDuplicados(self) as dialogo:
            dialogo.ShowModal()

    # --- bloqueo por PIN ------------------------------------------------------
    def pedir_pin(self, motivo: str = "") -> bool:
        """Pide el PIN si hay uno puesto. True si se puede continuar."""
        if not organizar.hay_pin(self.datos):
            return True
        with dialogos.DialogoPin(self, "Canal bloqueado" if motivo else "Bloqueo por PIN") as dialogo:
            if motivo:
                dialogo.SetTitle("Canal bloqueado")
            if dialogo.ShowModal() != wx.ID_OK:
                return False
            pin = dialogo.valor()
        if organizar.comprobar_pin(self.datos, pin):
            return True
        aviso(self, "El PIN no es correcto.", icono=wx.ICON_WARNING)
        return False

    def configurar_pin(self):
        if organizar.hay_pin(self.datos):
            if not self.pedir_pin():
                return
            opciones = ["Cambiar el PIN", "Quitar el bloqueo", "Ver los canales y categorías bloqueados"]
            with wx.SingleChoiceDialog(self, "¿Qué quieres hacer con el bloqueo por PIN?", "Bloqueo por PIN", opciones) as dialogo:
                if dialogo.ShowModal() != wx.ID_OK:
                    return
                eleccion = dialogo.GetSelection()
            if eleccion == 1:
                organizar.fijar_pin(self.datos, "")
                self.datos.guardar()
                for panel in self.paneles.values():
                    panel.refrescar()
                self.estado("Bloqueo por PIN quitado.")
                return
            if eleccion == 2:
                estado = organizar.bloqueo(self.datos)
                filas = [("Canales bloqueados", ", ".join(estado.get("canales") or []) or "ninguno"),
                         ("Categorías bloqueadas", ", ".join(estado.get("grupos") or []) or "ninguna")]
                dialogo_html(self, "Bloqueo por PIN", tabla_html("Bloqueo por PIN", filas), "\n".join(f"{k}: {v}" for k, v in filas))
                return
        with dialogos.DialogoPin(self, "Nuevo PIN", nuevo=True) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            pin = dialogo.valor()
        organizar.fijar_pin(self.datos, pin)
        self.datos.guardar()
        self.estado("PIN guardado. Ahora puedes bloquear canales desde su menú contextual.")

    def alternar_bloqueo(self, canal: Canal | None = None):
        canal = canal or self.canal_seleccionado()
        if canal is None:
            return
        if not organizar.hay_pin(self.datos):
            if not pregunta(self, "Todavía no hay ningún PIN. ¿Quieres crearlo ahora?"):
                return
            self.configurar_pin()
            if not organizar.hay_pin(self.datos):
                return
        if organizar.bloqueado(self.datos, canal) and not self.pedir_pin("desbloquear"):
            return
        nuevo = organizar.alternar_bloqueo_canal(self.datos, canal)
        self.datos.guardar()
        self.paneles[canal.tipo].refrescar()
        self.estado(f"{canal.nombre}: {'bloqueado' if nuevo else 'desbloqueado'}.")

    # --- DNS alternativo ------------------------------------------------------
    def configurar_dns(self):
        """Diálogo del DNS alternativo, para cuando el operador bloquea una emisión."""
        with dialogos.DialogoDns(self) as dialogo:
            dialogo.ShowModal()

    def sugerencia_dns(self) -> str:
        """Frase que se añade a los errores de red, según cómo esté el DNS ahora."""
        try:
            from . import dns_xdp

            nombre = self.datos.windows.get("dnsAdaptador") or ""
            adaptadores = dns_xdp.adaptadores()
            nombre = nombre if nombre in adaptadores else (adaptadores[0] if adaptadores else "")
            if not nombre:
                return ""
            if dns_xdp.estado(nombre, comprobar=False).get("activo"):
                return "Ya estás usando el DNS alternativo; si aun así falla, prueba a restaurarlo en Herramientas, Solucionar problemas, DNS alternativo."
            return ("Si crees que tu operador está bloqueando el acceso (los bloqueos de los partidos afectan también a emisiones que no tienen nada que ver), "
                    "puedes probar el DNS alternativo en Herramientas, Solucionar problemas, DNS alternativo.")
        except Exception:
            registro.debug("No se pudo consultar el estado del DNS", exc_info=True)
            return ""

    # --- perfiles, copias y actualizaciones ----------------------------------
    def gestionar_perfiles(self):
        with dialogos.DialogoPerfiles(self) as dialogo:
            dialogo.ShowModal()

    def aplicar_ajustes_nuevos(self, ajustes: dict, mensaje: str, perfil: str = ""):
        """Sustituye los ajustes en caliente (importar, perfil o copia de seguridad)."""
        self.datos.ajustes = ajustes
        if perfil:
            self.datos.windows["perfilActual"] = perfil
        self.datos.guardar()
        self.teclas = modulo_teclas.Teclas(self.datos.windows)
        self.aplicar_teclas()
        self.aplicar_accesibilidad()
        self.aplicar_apariencia()
        self.aplicar_teclas_globales(avisar=False)
        self.aplicar_preferencias_reproductor()
        if self.reproductor:
            self.reproductor.volumen(self.datos.windows["volumen"])
        for panel in self.paneles.values():
            panel.vista.SetSelection(1 if self.datos.solo_favoritos(panel.tipo) else 0)
        self.aplicar_plantillas()
        self.panel_vod.actualizar_cuentas()
        self.cargar(False)
        self.estado(mensaje)

    def copia_seguridad(self):
        opciones = ["Crear una copia de seguridad", "Restaurar desde una copia"]
        with wx.SingleChoiceDialog(self, "La copia guarda ajustes, favoritos, orden, plantillas, recordatorios, grabaciones programadas y perfiles.", "Copia de seguridad", opciones) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            crear = dialogo.GetSelection() == 0
        if crear:
            with wx.FileDialog(self, "Guardar copia de seguridad", wildcard="Copia de Resintoniza (*.zip)|*.zip", defaultFile=respaldo.nombre_copia(), style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialogo:
                if dialogo.ShowModal() != wx.ID_OK:
                    return
                destino = Path(dialogo.GetPath())
            try:
                respaldo.crear_copia(self.datos, destino)
            except OSError as error:
                aviso(self, f"No se pudo crear la copia: {error}", icono=wx.ICON_ERROR)
                return
            self.estado(f"Copia de seguridad guardada en {destino}.")
            return
        with wx.FileDialog(self, "Restaurar copia de seguridad", wildcard="Copia de Resintoniza (*.zip)|*.zip|Todos (*.*)|*.*", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            origen = Path(dialogo.GetPath())
        try:
            ajustes = respaldo.restaurar(self.datos, origen)
        except (ValueError, OSError) as error:
            aviso(self, f"No se pudo restaurar: {error}", icono=wx.ICON_ERROR)
            return
        self.aplicar_ajustes_nuevos(ajustes, "Copia de seguridad restaurada. La configuración anterior se guardó en ajustes-antes-de-restaurar.json.")

    def instalar_addon(self):
        """Genera el complemento de NVDA y lo abre para que NVDA lo instale."""
        destino = self.datos.raiz / "bin"
        ruta = destino / "resintonizaListViewFix.nvda-addon"
        if not ruta.exists():
            try:
                from tools.construir_addon import construir_addon

                ruta = construir_addon(destino, origen=modulo_datos.raiz_aplicacion() / "nvda_addon")
            except Exception as error:
                registro.info("No se pudo generar el complemento: %s", error)
                aviso(self, f"No se encuentra el complemento de NVDA y no se ha podido generar: {error}", icono=wx.ICON_WARNING)
                return
        if not pregunta(self, ("El complemento amplía el límite de NVDA al leer listas, para que se lean enteras las descripciones largas.\n\n"
                               f"Archivo: {ruta}\n\n¿Abrirlo ahora para que NVDA lo instale?"), "Complemento de NVDA"):
            self.estado(f"El complemento de NVDA está en {ruta}.")
            return
        try:
            import os

            os.startfile(str(ruta))
            self.estado("NVDA debería preguntar si quieres instalar el complemento.")
        except OSError as error:
            aviso(self, f"No se pudo abrir el complemento: {error}\nÁbrelo a mano desde {ruta}.", icono=wx.ICON_WARNING)

    def comprobar_app_al_iniciar(self):
        windows = self.datos.windows
        if not windows.get("comprobarActualizaciones") or not windows.get("urlActualizaciones"):
            return
        if time.time() - (windows.get("ultimaComprobacionApp") or 0) < UNA_SEMANA:
            return
        threading.Thread(target=self._comprobar_app_en_hilo, daemon=True).start()

    def _comprobar_app_en_hilo(self):
        resultado = actualizacion.comprobar(self.datos.windows.get("urlActualizaciones", ""))
        wx.CallAfter(self._resultado_app, resultado)

    def _resultado_app(self, resultado: dict):
        if self.cerrando:
            return
        self.datos.windows["ultimaComprobacionApp"] = int(time.time())
        self.datos.guardar()
        if resultado.get("hay"):
            self.estado(actualizacion.resumen(resultado))

    def comprobar_app(self):
        with dialogos.DialogoActualizacion(self) as dialogo:
            dialogo.ShowModal()

    def editar_teclas_globales(self):
        with dialogos.DialogoTeclasGlobales(self) as dialogo:
            dialogo.ShowModal()

    def buscar_en_guia(self):
        panel = self.panel_activo()
        texto = panel.busqueda.GetValue().strip() if panel is not None else ""
        with dialogos.DialogoBuscarGuia(self, texto) as dialogo:
            dialogo.ShowModal()

    def reproducir_vod(self, elemento: dict):
        """Reproduce una película o un episodio de una cuenta de proveedor."""
        if not self.asegurar_reproductor():
            return
        self.canal_actual, self.emision_actual = None, None
        self.generacion_reproduccion += 1
        titulo = elemento.get("titulo", "Contenido")
        self.SetTitle(f"{titulo} · {NOMBRE_APP}")
        self._iniciar(proveedores.Fuente(elemento["url"], descripcion="Catálogo del proveedor"))
        self.estado_reproduccion(f"Reproduciendo {titulo}.")

    def exportar_m3u(self):
        """Guarda los canales favoritos como lista M3U, para usarlos en otros programas."""
        favoritos = [c for c in self.canales if self.datos.estado_canal(c.tipo, c.nombre)["favorite"]]
        if not favoritos:
            aviso(self, "Todavía no tienes ningún favorito. Añade alguno con la tecla de favoritos en la lista de canales.")
            return
        with wx.FileDialog(self, "Exportar favoritos a M3U", wildcard="Lista M3U (*.m3u)|*.m3u", defaultFile="favoritos.m3u", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            ruta = Path(dialogo.GetPath())
        try:
            ruta.write_text(m3u.escribir_m3u(favoritos), encoding="utf-8")
        except OSError as error:
            aviso(self, f"No se pudo guardar la lista: {error}", icono=wx.ICON_ERROR)
            return
        self.estado(f"{len(favoritos)} favoritos exportados a {ruta}.")

    # --- temporizador y recordatorios ------------------------------------------------
    def temporizador(self):
        opciones = [o[0] for o in OPCIONES_TEMPORIZADOR]
        if self.temporizador_fin:
            restante = int((self.temporizador_fin - time.time()) / 60)
            opciones[0] = f"Desactivado (ahora quedan {max(0, restante)} minutos)"
        with wx.SingleChoiceDialog(self, "¿Cuándo debería detenerse la reproducción?", "Temporizador de apagado", opciones) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            minutos = OPCIONES_TEMPORIZADOR[dialogo.GetSelection()][1]
        if minutos:
            self.temporizador_fin = time.time() + minutos * 60
            self.estado(f"Temporizador configurado: la reproducción se detendrá a las {time.strftime('%H:%M', time.localtime(self.temporizador_fin))}.")
        else:
            self.temporizador_fin = None
            self.estado("El temporizador ha sido cancelado.")

    def tic(self, _evento):
        ahora = time.time()
        try:
            self._revisar_grabaciones(ahora)
            self.comprobar_espacio(ahora)
            self.anunciar_grabaciones_si_toca(ahora)
            self.anotar_posicion_actual(ahora)
            if ahora - self.ultimas_reglas > 1800:   # las reglas se repasan cada media hora
                self.ultimas_reglas = ahora
                self.aplicar_reglas()
        except Exception:
            registro.exception("Error revisando las grabaciones programadas")
        if self.temporizador_fin and ahora >= self.temporizador_fin:
            self.temporizador_fin = None
            self.detener()
            self.estado_reproduccion("Reproducción detenida por el temporizador.")
        minuto = int(ahora // 60)
        if minuto != self.ultimo_minuto:
            self.ultimo_minuto = minuto
            if self.icono_bandeja:
                self.icono_bandeja.actualizar_estado()
            for panel in self.paneles.values():
                panel.refrescar_ahora()
        pendientes = self.datos.windows["recordatorios"]
        for recordatorio in list(pendientes):
            momento = recordatorio["inicio"] - recordatorio["minutos"] * 60
            if ahora >= momento:
                pendientes.remove(recordatorio)
                self.datos.guardar()
                if ahora < recordatorio["inicio"] + 3600:
                    self.avisar_recordatorio(recordatorio)

    def avisar_recordatorio(self, recordatorio):
        hora = time.strftime("%H:%M", time.localtime(recordatorio["inicio"]))
        texto = f"{recordatorio['titulo']} empieza a las {hora} en {recordatorio['canal']}."
        try:
            wx.adv.NotificationMessage(f"Recordatorio de {NOMBRE_APP}", texto, self).Show(timeout=15)
        except Exception:
            pass
        self.estado("Recordatorio: " + texto)
        canal = next((c for c in self.canales if c.tipo == recordatorio["tipo"] and c.nombre == recordatorio["canal"]), None)
        if canal and pregunta(self, texto + "\n\n¿Quieres ver el canal ahora?", "Recordatorio"):
            self.reproducir_canal(canal)

    # --- ajustes, importación y exportación ------------------------------------------
    def ajustes(self):
        with DialogoAjustes(self, self.datos) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                if dialogo.plantillas_cambiadas:
                    self.aplicar_plantillas()
                return
            dialogo.aplicar()
        self.datos.guardar()
        self.aplicar_accesibilidad()
        self.aplicar_apariencia()
        self.aplicar_plantillas()
        self.aplicar_teclas_globales(avisar=False)
        self.recargar_por_buffer = False
        self.aplicar_preferencias_reproductor()
        if self.reproductor:
            self.reproductor.modo_imagen(self.datos.windows["modoImagen"])
        for panel in self.paneles.values():
            panel.refrescar()
        self.estado("Ajustes guardados.")
        # El margen respecto al directo solo cambia al volver a cargar la emisión.
        if self.recargar_por_buffer and self.canal_actual and self.emision_actual:
            if pregunta(self, "El búfer de recepción ha cambiado.\n\n¿Recargar ahora la emisión para aplicarlo?"):
                self.recargar()

    def editar_plantillas(self):
        with DialogoPlantillas(self, self.datos) as dialogo:
            if dialogo.ShowModal() == wx.ID_OK:
                self.aplicar_plantillas()
                self.estado("Plantillas de lectura guardadas.")

    def aplicar_plantillas(self):
        for panel in self.paneles.values():
            panel.aplicar_plantillas()
        self.panel_guia.lista.aplicar_plantilla()
        self.panel_guia.rellenar_programas()
        self.panel_info.listas.aplicar_plantilla()
        self.panel_info.rellenar()

    def exportar(self, _evento=None):
        with wx.FileDialog(self, "Exportar configuración", wildcard="Configuración (*.json)|*.json|Configuración de la aplicación Android (*.tdtchannels)|*.tdtchannels", defaultFile="configuracion.json", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            ruta = Path(dialogo.GetPath())
        try:
            modulo_datos.guardar_json_atomico(ruta, self.datos.ajustes)
        except OSError as error:
            aviso(self, f"No se pudo guardar la configuración: {error}", icono=wx.ICON_ERROR)
            return
        self.estado(f"Configuración guardada en {ruta}. También se puede importar en la aplicación Android.")

    def importar(self, _evento=None):
        with wx.FileDialog(self, "Importar configuración", wildcard="Configuración (*.json;*.tdtchannels)|*.json;*.tdtchannels|Todos (*.*)|*.*", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialogo:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            ruta = Path(dialogo.GetPath())
        try:
            nuevos = modulo_datos.validar_ajustes(json.loads(ruta.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError, TypeError) as error:
            aviso(self, f"El archivo no contiene una configuración válida.\n{error}", icono=wx.ICON_ERROR)
            return
        copia = self.datos.raiz / "ajustes-antes-de-importar.json"
        modulo_datos.guardar_json_atomico(copia, self.datos.ajustes)
        self.aplicar_ajustes_nuevos(nuevos, f"Configuración cargada. La anterior se guardó en {copia.name}.")

    def limpiar_cache(self):
        cuenta = self.datos.limpiar_cache()
        self.estado(f"Caché limpiada: {cuenta} archivo{'s' if cuenta != 1 else ''} eliminado{'s' if cuenta != 1 else ''}. Actualiza las listas para descargarlas de nuevo.")

    # --- ayuda ----------------------------------------------------------------------------
    def ayuda(self):
        t = self.teclas
        k = lambda accion: modulo_teclas.legible(t.combo(accion))  # noqa: E731
        texto = (
            f"{NOMBRE_APP} · uso y teclado\n\n"
            "Pestañas: Televisión, Radio, Guía e Información. Tabulador y Mayús+Tabulador recorren los controles; Alt abre los menús.\n\n"
            "La ventana principal solo tiene las listas: el reproductor se maneja con las teclas de función y desde los menús. El canal suena en segundo plano, el título de la ventana dice cuál es y la barra de estado su estado. Si la emisión trae imagen, esta se abre en su propia ventana de vídeo.\n\n"
            "Listas accesibles: flechas arriba y abajo cambian de fila; izquierda y derecha leen la fila por columnas; Ctrl+1 a Ctrl+9 leen una columna concreta; Ctrl+0 lee la fila entera con la plantilla de lectura.\n"
            "Intro reproduce (o abre las acciones del programa en la guía). La tecla Aplicaciones o Mayús+F10 abre el menú contextual de cada elemento, y cada opción muestra su tecla actual.\n"
            "Herramientas > Accesibilidad y teclas > Plantillas de lectura decide qué columnas tiene cada lista y en qué orden se leen. Ajustes > Accesibilidad decide qué se dice al moverte por columnas y qué avisos se locutan.\n\n"
            f"Reproductor (teclas globales, funcionan en toda la aplicación y se personalizan en Herramientas > Accesibilidad y teclas > Personalizar teclas, {k('herr_teclas')}):\n"
            f"  {k('repro_favoritos')} favoritos · {k('repro_pausa')} reproducir o pausar · {k('repro_recargar')} recargar · {k('repro_detener')} detener\n"
            f"  {k('repro_bajar_volumen')} / {k('repro_subir_volumen')} volumen · {k('repro_anterior')} / {k('repro_siguiente')} canal anterior o siguiente · {k('repro_silencio')} silenciar\n"
            f"  {k('repro_video')} mostrar u ocultar la ventana de vídeo · {k('repro_pantalla_completa')} pantalla completa (Escape sale) · {k('repro_estado')} decir el estado · {k('repro_volver')} volver al canal anterior\n"
            f"  {k('repro_audio')} pista de audio · {k('repro_subtitulos')} subtítulos · {k('repro_temporizador')} temporizador · {k('repro_solo_audio')} modo solo audio · {k('repro_calidad')} calidad · {k('repro_estadisticas')} datos de la emisión\n"
            f"  {k('repro_grabar')} grabar o parar la grabación · {k('repro_retroceder')} retroceder {RETROCESO} segundos del directo · {k('repro_directo')} volver al directo · {k('repro_enviar')} enviar a la tele · {k('repro_historial')} historial\n"
            f"  {k('repro_mosaico')} multiventana (varios canales a la vez) · {k('repro_nivelador')} nivelar el volumen entre canales · {k('repro_velocidad')} velocidad · {k('repro_desfase')} retraso del audio\n\n"
            f"Canales: {k('canal_reproducir')} reproducir · {k('canal_web')} web oficial · {k('canal_programacion')} programación · {k('canal_guia')} ver en la guía\n"
            f"  {k('canal_favorito')} favorito · {k('canal_ocultar')} ocultar o mostrar · {k('canal_subir')} / {k('canal_bajar')} orden personal · {k('canal_info')} leer la información · {k('canal_numero')} ir a un número de canal\n"
            "  En la lista de canales, teclear las cifras salta a ese número, como en un mando a distancia.\n\n"
            f"Generales: {k('buscar')} buscar · {k('herr_buscar_guia')} buscar en toda la guía · {k('archivo_actualizar')} actualizar listas y guía · {k('archivo_lista')} añadir lista · {k('herr_ajustes')} ajustes · {k('herr_recordatorios')} recordatorios · {k('herr_grabaciones')} grabaciones · {k('archivo_salir')} salir\n\n"
            "Listas de canales: además de las incluidas, se pueden añadir listas M3U o M3U8 (el formato habitual en IPTV), de Internet o del propio equipo, el catálogo público de iptv-org por país, idioma o categoría, y cuentas de proveedor con servidor, usuario y contraseña (Xtream Codes). "
            "Las cuentas traen también sus películas y series, que aparecen en su propia pestaña, y su programación. La contraseña se guarda cifrada con la protección de datos de Windows.\n\n"
            "Grabar: en Ajustes > Grabación se elige cómo. De fábrica se graba en segundo plano: cada grabación abre su propio reproductor, sin imagen ni sonido, así que puedes seguir escuchando o viendo otra cosa, "
            "grabar varios canales a la vez y pausar, cambiar de canal o detener sin que le pase nada a lo que se está grabando. La otra opción graba lo que suena con el reproductor principal, sin descargarlo dos veces, pero lo deja ocupado. "
            "En las emisiones de TV puedes elegir si guardar en .ts o en .mp4 (para mayor compatibilidad), y no se recodifica nada. Desde la programación se puede grabar un programa concreto, y la aplicación lo hace a su hora siempre que esté abierta. "
            f"En {k('herr_grabaciones')} se ve lo que se está grabando ahora, cuánto lleva, cuánto le queda y cuánto ocupa, y se puede detener cualquiera con Suprimir; ahí mismo se recortan las grabaciones sin recodificar, se protegen de la limpieza y se ven los gigabytes libres. "
            "Si el proveedor lo permite, la programación también ofrece «Ver este programa emitido» para lo que ya se emitió.\n\n"
            f"Grabar sin estar delante: en {k('herr_reglas')} se ponen reglas («graba siempre lo que lleve Telediario en La 1»), que miran la guía y programan solas, sin repetir el mismo episodio, el mismo título o más de una vez por semana, según elijas. "
            "En Ajustes > Grabación están los márgenes de antes y después (también por canal), la carpeta por programa, grabar solo el audio (ocupa una décima parte), el espacio libre mínimo, la limpieza automática por días, por número de grabaciones o por gigabytes, "
            "qué hacer al terminar (cerrar la aplicación, suspender o apagar) y la posibilidad de que Windows abra la aplicación, y despierte el equipo, unos minutos antes de cada grabación programada. "
            f"En {k('herr_ahora')} se ve lo que empieza en los próximos minutos en tus favoritos, listo para grabar, poner un recordatorio o crear una regla.\n\n"
            "Las grabaciones guardadas se reanudan donde las dejaste. Con la multiventana se pueden ver hasta cuatro canales a la vez, eligiendo con las cifras cuál suena.\n\n"
            f"{k('herr_comprobar')} comprueba en segundo plano qué canales responden y ofrece ocultar los caídos, sin tocar lo que estés escuchando. En Herramientas > Copias de seguridad se puede sincronizar la configuración con una carpeta de la nube para llevarla a otro equipo.\n\n"
            "Pausa del directo: activando en Ajustes los minutos que se guardan, se puede retroceder dentro de la emisión y volver luego al directo.\n\n"
            f"Si una emisión va a tirones, en Ajustes se puede subir el búfer de recepción y bajar la calidad, y {k('repro_estadisticas')} muestra los datos de la emisión, "
            "con el búfer que hay y cuántos cortes ha habido desde que empezó.\n\n"
            "Al iniciar, la aplicación usa las listas y la guía que ya tiene guardadas, así que abre rápido y funciona sin conexión. "
            f"Se actualizan cuando tú quieras con {k('archivo_actualizar')}, y en Ajustes puedes pedir que se actualicen solas cada día, cada semana o cada vez que se abre.\n\n"
            "Enviar a la tele: por DLNA o UPnP (casi cualquier televisor), a un Chromecast o Google TV, y los Fire TV y Android TV se detectan y se explica cómo verlos, con una aplicación receptora o duplicando la pantalla de Windows.\n\n"
            "Si tu operador bloquea el acceso a una emisión (los bloqueos de los partidos afectan también a emisiones que no tienen nada que ver), en Herramientas > Solucionar problemas hay un DNS alternativo con DNS sobre HTTPS: "
            "se activa y se desactiva cuando quieras, Windows pide permiso y la configuración que tenías se guarda para poder volver a ella.\n\n"
            "Guía: la ficha de cada programa trae los géneros, el año, la temporada y el episodio, la valoración y la edad recomendada cuando la guía los da. "
            "En Herramientas > Guía y recordatorios > Guías de programación se elige la variante de la guía ampliada y se añaden guías XMLTV propias; Cobertura de la guía, ahí mismo, dice qué canales tienen programación y con qué nombre la tendrían los que no.\n\n"
            "Con muchos canales: números de canal, historial, bloqueo por PIN de canales o categorías, aviso de duplicados al mezclar listas y búsqueda de un título en toda la guía.\n\n"
            "Accesibilidad: avisos sonoros que se pueden elegir uno a uno, anuncio del programa al sintonizar, modo solo audio, preferencia por la pista de audiodescripción, complemento de NVDA para que se lean enteras las descripciones largas "
            "e interfaz invisible, que deja manejar la reproducción con teclas del sistema aunque estés en otro programa.\n\n"
            f"En el navegador integrado: {k('nav_zonas')} cambia entre la página y la barra de botones, Escape cierra (y Alt+F4 lo cierra siempre, aunque la página se quede sin responder) y las teclas del reproductor manejan el vídeo de la web.\n\n"
            "Los canales sin emisión directa en la lista (marcados «se ve en su web oficial», como DMAX, Ten o Squirrel) se abren en el navegador integrado, con el reproductor de su propia web, igual que en Android. "
            "Las emisiones «Directo de la web oficial» (Telecinco, Cuatro, Antena 3, laSexta, GOL…) se obtienen consultando la API de la emisora.\n\n"
            "La configuración se puede exportar e importar; el formato es compatible con el de la aplicación Android.\n\n"
            f"Todo lo que genera la aplicación está en la carpeta de datos: {self.datos.raiz}"
        )
        import html as modulo_html

        bloques = texto.split("\n\n")
        cuerpo = f"<h1>{modulo_html.escape(bloques[0])}</h1>" + "".join(f"<p>{modulo_html.escape(b).replace(chr(10), '<br>')}</p>" for b in bloques[1:])
        dialogo_html(self, "Uso y teclado", cuerpo, texto)

    def manual(self):
        """Manual de usuario: se lee de MANUAL.md, que se copia junto al ejecutable."""
        ruta = modulo_datos.raiz_aplicacion() / "MANUAL.md"
        try:
            texto = ruta.read_text(encoding="utf-8")
        except OSError:
            registro.debug("No se pudo leer el manual", exc_info=True)
            aviso(self, f"No se encuentra el manual de usuario.\n\nDebería estar en:\n{ruta}\n\n"
                        "Mientras tanto, Ayuda > Uso y teclado tiene lo esencial.", icono=wx.ICON_WARNING)
            return
        dialogo_html(self, "Manual de usuario", markdown_a_html(texto), texto)

    def ayuda_teclas(self):
        import html as modulo_html

        t = self.teclas
        partes = ["<h1>Teclas actuales</h1>", "<p>Se cambian en Herramientas &gt; Accesibilidad y teclas &gt; Personalizar teclas. Cada tabla es una sección.</p>"]
        for seccion in modulo_teclas.SECCIONES:
            partes.append(f"<h2>{modulo_html.escape(seccion)}</h2><table><tr><th>Tecla</th><th>Acción</th><th>Estado</th></tr>")
            for accion in t.acciones_de(seccion):
                partes.append(f"<tr><td>{modulo_html.escape(modulo_teclas.legible(t.combo(accion)))}</td><td>{modulo_html.escape(t.etiqueta(accion, False))}</td><td>{'personalizada' if t.es_personalizada(accion) else 'predeterminada'}</td></tr>")
            partes.append("</table>")
        partes.append("<h2>En las listas</h2><ul><li>Flechas arriba y abajo: cambiar de fila.</li><li>Izquierda y derecha: leer la fila por columnas.</li><li>Ctrl+1 a Ctrl+9: leer una columna; Ctrl+0: la fila entera.</li><li>Cifras: ir al número de canal, como en un mando.</li><li>Intro: activar; Aplicaciones o Mayús+F10: menú contextual.</li></ul>")
        if self.datos.windows.get("interfazInvisible") and self.teclas_globales is not None:
            partes.append("<h2>Con la aplicación en segundo plano</h2><table><tr><th>Tecla</th><th>Acción</th></tr>")
            for etiqueta, tecla in self.teclas_globales.resumen(self.datos.windows):
                partes.append(f"<tr><td>{modulo_html.escape(tecla)}</td><td>{modulo_html.escape(etiqueta)}</td></tr>")
            partes.append("</table>")
        partes.append("<h2>En el navegador integrado</h2><ul><li>Escape: cerrar; F6: alternar entre la barra de botones y la página.</li><li>Las teclas del reproductor controlan el vídeo de la web (reproducir, pausar, volumen, silencio).</li></ul>")
        dialogo_html(self, "Teclas actuales", "".join(partes), t.texto_ayuda())

    def ver_registro(self):
        ruta = self.datos.raiz / "logs" / "aplicacion.log"
        try:
            contenido = ruta.read_text(encoding="utf-8", errors="replace")[-20000:] or "El registro está vacío."
        except OSError:
            contenido = "Todavía no hay registro."
        dialogo_texto(self, f"Registro: {ruta}", contenido)

    def acerca_de(self):
        """Acerca de, en un diálogo propio: el nativo de Windows no se lee bien."""
        import html as modulo_html

        cuenta_tv = sum(1 for c in self.canales if c.tipo == "tv")
        cuenta_radio = sum(1 for c in self.canales if c.tipo == "radio")
        datos = [
            ("Versión", VERSION),
            ("Desarrollado por", AUTOR),
            ("Reproductor", self.version_mpv or "libmpv (sin iniciar todavía)"),
            ("Interfaz", f"wxPython {wx.version().split(' ')[0]}"),
            ("Canales cargados", f"{cuenta_tv} de televisión y {cuenta_radio} de radio"),
            ("Carpeta de datos", str(self.datos.raiz)),
        ]
        filas = "".join(f"<tr><th scope=\"row\">{modulo_html.escape(k)}</th><td>{modulo_html.escape(str(v))}</td></tr>" for k, v in datos)
        cuerpo = (
            f"<h1>{modulo_html.escape(NOMBRE_APP)}</h1>"
            f"<p>{modulo_html.escape(LEMA)}.</p>"
            "<p>Televisión y radio en directo para Windows, pensada para manejarse con el teclado y con lector de pantalla.</p>"
            f"<h2>Datos</h2><table>{filas}</table>"
            "<h2>Aviso</h2>"
            "<p>Esta aplicación no emite ni distribuye ningún contenido. Al reproducir un canal se conecta al servidor de la emisora, "
            "que ofrece su señal bajo sus propios términos. Las restricciones por zona, los registros y la disponibilidad dependen de cada emisora.</p>"
            "<h2>Componentes</h2>"
            "<ul><li>Python, licencia PSF</li><li>wxPython y wxWidgets, wxWindows Library Licence</li>"
            "<li>libmpv y FFmpeg, GPL o LGPL</li><li>python-mpv</li><li>accessible_output2, para la voz</li>"
            "<li>wx-accessible-webview, para los diálogos y el navegador accesibles</li><li>Microsoft Edge WebView2</li></ul>"
            "<p>El detalle está en el archivo LICENCIAS.md, junto al programa.</p>"
        )
        texto = "\n".join([NOMBRE_APP, LEMA, ""] + [f"{k}: {v}" for k, v in datos] + [
            "", "Esta aplicación no emite ni distribuye ningún contenido: cada canal procede del servidor de su emisora.",
            "", "Componentes: Python, wxPython, libmpv y FFmpeg, python-mpv, accessible_output2, wx-accessible-webview y Microsoft Edge WebView2.",
            "El detalle está en LICENCIAS.md."])
        dialogo_html(self, f"Acerca de {NOMBRE_APP}", cuerpo, texto)

    def aviso_legal(self):
        """Origen de los datos y condiciones, en un diálogo accesible."""
        cuerpo = (
            "<h1>Aviso legal y fuentes</h1>"
            "<h2>Qué hace esta aplicación</h2>"
            "<p>Descarga listas públicas de canales y guías de programación publicadas en Internet, y reproduce cada emisión "
            "conectándose al servidor de su emisora. No aloja, no emite y no redistribuye ningún contenido, ni modifica las "
            "restricciones por zona, los registros ni la protección de las señales.</p>"
            "<h2>De dónde salen los datos</h2>"
            "<ul>"
            "<li>Listas de canales de televisión y radio: servicios públicos en formato JSON, con copia de respaldo y caché local.</li>"
            "<li>Guía de programación: la guía pública asociada a esas listas y una guía adicional en formato XMLTV.</li>"
            "<li>Puedes añadir tus propias listas en Información, con el mismo formato.</li>"
            "</ul>"
            "<p>Cada emisora es responsable de su señal y de sus condiciones de uso. Si una emisión no está disponible en tu zona "
            "o requiere registro, la aplicación te lo indica y abre su web oficial.</p>"
            "<h2>Componentes de terceros</h2>"
            "<p>Las licencias completas están en el archivo LICENCIAS.md, junto al programa.</p>"
        )
        texto = ("Aviso legal y fuentes\n\n"
                 "Esta aplicación descarga listas de canales y guías publicadas en Internet y reproduce cada emisión conectándose al servidor de su emisora. "
                 "No aloja, no emite y no redistribuye ningún contenido.\n\n"
                 "Cada emisora es responsable de su señal y de sus condiciones de uso.\n\n"
                 "Las licencias de los componentes están en LICENCIAS.md.")
        dialogo_html(self, "Aviso legal y fuentes", cuerpo, texto)

    # --- cierre ----------------------------------------------------------------------------
    def salir(self):
        self.cerrando = True
        self.Close(True)

    def al_minimizar(self, evento):
        if evento.IsIconized() and self.datos.windows.get("minimizarABandeja"):
            wx.CallAfter(self.a_bandeja)
        evento.Skip()

    def al_cerrar(self, evento):
        reproduciendo = self.reproductor is not None and self.reproductor.activo
        grabando = len(self.grabaciones_fondo) if self.grabaciones_fondo is not None else 0
        programadas = [e for e in (self.datos.windows.get("grabaciones") or []) if e.get("estado") == "pendiente" and e.get("inicio", 0) > time.time()]
        num_prog = len(programadas)
        if not self.cerrando and grabando and evento.CanVeto():
            cuantas = f"{grabando} grabaciones en segundo plano" if grabando != 1 else "una grabación en segundo plano"
            respuesta = wx.MessageBox(
                f"Hay {cuantas} en marcha.\n\nSí: se cierran las grabaciones y se sale.\nNo: la ventana se oculta en la bandeja del sistema y se sigue grabando.",
                NOMBRE_APP, wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION, self)
            if respuesta == wx.CANCEL:
                evento.Veto()
                return
            if respuesta == wx.NO:
                self.a_bandeja()
                evento.Veto()
                return
        elif not self.cerrando and reproduciendo and evento.CanVeto():
            modo = self.datos.usuario["closeOnExit"]
            if modo == "0":
                texto_prog = f" (hay {num_prog} grabación{'es' if num_prog != 1 else ''} programada{'s' if num_prog != 1 else ''} pendiente{'s' if num_prog != 1 else ''})" if num_prog else ""
                respuesta = wx.MessageBox(f"¿Quieres cerrar la aplicación?{texto_prog}\n\nSí: se detiene la reproducción y se cierra.\nNo: la ventana se oculta en la bandeja del sistema y sigue reproduciendo.", NOMBRE_APP, wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION, self)
                if respuesta == wx.CANCEL:
                    evento.Veto()
                    return
                if respuesta == wx.NO:
                    self.a_bandeja()
                    evento.Veto()
                    return
            elif modo == "2":
                self.a_bandeja()
                evento.Veto()
                return
        elif not self.cerrando and num_prog and evento.CanVeto():
            cuantas = f"{num_prog} grabaciones programadas pendientes" if num_prog != 1 else "una grabación programada pendiente"
            respuesta = wx.MessageBox(
                f"Hay {cuantas}.\n\nSí: salir de la aplicación.\nNo: la ventana se oculta en la bandeja del sistema para que sigan programadas.",
                NOMBRE_APP, wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION, self)
            if respuesta == wx.CANCEL:
                evento.Veto()
                return
            if respuesta == wx.NO:
                self.a_bandeja()
                evento.Veto()
                return
        self.cerrando = True
        self.reloj.Stop()
        self.cancelar_reintento()
        self.filtro_teclas.quitar()
        if self.teclas_globales is not None:
            self.teclas_globales.quitar()
        if self.grabador is not None and self.grabador.activa:
            ruta, _segundos, _tamano = self.grabador.parar()
            registro.info("Grabación cerrada al salir: %s", ruta)
        self.soltar_grabacion()
        if self.mosaico is not None:
            try:
                self.mosaico.Close()
            except Exception:
                registro.debug("Error cerrando la multiventana", exc_info=True)
            self.mosaico = None
        if self.grabaciones_fondo is not None:
            for clave, ruta in self.grabaciones_fondo.parar_todo():
                entrada = self.programadas_fondo.pop(clave, None)
                if entrada is not None:
                    entrada["estado"] = "hecha"
                    entrada["archivo"] = ruta.name if ruta else entrada.get("archivo", "")
                registro.info("Grabación en segundo plano cerrada al salir: %s", ruta)
        try:
            self.datos.guardar()
        except OSError:
            registro.exception("No se pudieron guardar los ajustes")
        if self.icono_bandeja:
            self.icono_bandeja.Destroy()
            self.icono_bandeja = None
        if self.navegador is not None:
            try:
                self.navegador.Destroy()
            except RuntimeError:
                pass
            self.navegador = None
        if self.reproductor:
            self.reproductor.cerrar()
            self.reproductor = None
        servidor.cerrar()
        self.Destroy()

    def a_bandeja(self):
        if self.icono_bandeja is None:
            self.icono_bandeja = IconoBandeja(self)
        self.Hide()
        grabando = len(self.grabaciones_fondo) if self.grabaciones_fondo is not None else 0
        reproduciendo = self.reproductor is not None and self.reproductor.activo
        programadas = [e for e in (self.datos.windows.get("grabaciones") or []) if e.get("estado") == "pendiente" and e.get("inicio", 0) > time.time()]
        num_prog = len(programadas)

        self.icono_bandeja.actualizar_estado()
        if grabando:
            self.estado(f"Ventana oculta en la bandeja del sistema; sigue la reproducción y {grabando} grabación" + ("es" if grabando != 1 else "") + " en segundo plano.")
        elif reproduciendo:
            self.estado("Ventana oculta en la bandeja del sistema; la reproducción continúa.")
        elif num_prog:
            plural = "grabaciones" if num_prog != 1 else "grabación"
            self.estado(f"Ventana oculta en la bandeja del sistema; {num_prog} {plural} programadas pendientes.")
        else:
            self.estado("Ventana oculta en la bandeja del sistema.")

    def desde_bandeja(self):
        if self.IsIconized():
            self.Restore()
        self.Show()
        self.Raise()
        if self.icono_bandeja:
            self.icono_bandeja.Destroy()
            self.icono_bandeja = None
        self.estado("Ventana restaurada.")


class IconoBandeja(wx.adv.TaskBarIcon):
    def __init__(self, ventana: VentanaPrincipal):
        super().__init__()
        self.ventana = ventana
        mapa = wx.Bitmap(32, 32)
        dc = wx.MemoryDC(mapa)
        dc.SetBackground(wx.Brush(wx.Colour(0, 90, 160)))
        dc.Clear()
        dc.SetTextForeground(wx.WHITE)
        dc.SetFont(wx.Font(wx.FontInfo(18).Bold()))
        dc.DrawText("R", 8, 2)
        dc.SelectObject(wx.NullBitmap)
        icono = wx.Icon()
        icono.CopyFromBitmap(mapa)
        self.icono = icono
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, lambda e: self.ventana.desde_bandeja())
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_UP, lambda e: self.ventana.desde_bandeja())
        self.actualizar_estado()

    def actualizar_estado(self) -> None:
        """Actualiza el texto descriptivo del icono en la bandeja según el estado actual."""
        grabando = len(self.ventana.grabaciones_fondo) if self.ventana.grabaciones_fondo is not None else 0
        reproduciendo = self.ventana.reproductor is not None and self.ventana.reproductor.activo
        programadas = [e for e in (self.ventana.datos.windows.get("grabaciones") or []) if e.get("estado") == "pendiente" and e.get("inicio", 0) > time.time()]
        num_prog = len(programadas)

        if grabando:
            plural = "grabaciones" if grabando != 1 else "grabación"
            texto = f"{NOMBRE_APP}: {grabando} {plural} en segundo plano."
        elif reproduciendo:
            canal = self.ventana.canal_actual.nombre if self.ventana.canal_actual else "emisión"
            texto = f"{NOMBRE_APP}: reproduciendo {canal}."
        elif num_prog:
            plural = "grabaciones" if num_prog != 1 else "grabación"
            texto = f"{NOMBRE_APP}: {num_prog} {plural} programadas pendientes."
        else:
            texto = f"{NOMBRE_APP}: en segundo plano."
        self.SetIcon(self.icono, f"{texto} Clic para mostrar la ventana.")

    def anotar_grabaciones(self, cuantas: int) -> None:
        self.actualizar_estado()

    def CreatePopupMenu(self):
        menu = wx.Menu()
        mostrar = menu.Append(wx.ID_ANY, "&Mostrar ventana")
        menu.SetDefaultItem(mostrar.GetId())

        reproduciendo = self.ventana.reproductor is not None and self.ventana.reproductor.activo
        if reproduciendo:
            detener = menu.Append(wx.ID_ANY, "&Detener reproducción")
            self.Bind(wx.EVT_MENU, lambda e: (self.ventana.detener(), self.ventana.desde_bandeja()), detener)

        grabando = len(self.ventana.grabaciones_fondo) if self.ventana.grabaciones_fondo is not None else 0
        programadas = [e for e in (self.ventana.datos.windows.get("grabaciones") or []) if e.get("estado") == "pendiente" and e.get("inicio", 0) > time.time()]
        if grabando or programadas:
            menu.AppendSeparator()
            ver_grab = menu.Append(wx.ID_ANY, "&Grabaciones…")
            self.Bind(wx.EVT_MENU, lambda e: (self.ventana.desde_bandeja(), self.ventana.ver_grabaciones()), ver_grab)

        menu.AppendSeparator()
        salir = menu.Append(wx.ID_ANY, "&Salir")
        self.Bind(wx.EVT_MENU, lambda e: self.ventana.desde_bandeja(), mostrar)
        self.Bind(wx.EVT_MENU, lambda e: self.ventana.salir(), salir)
        return menu
