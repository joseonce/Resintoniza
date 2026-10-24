"""Piezas comunes de la interfaz: utilidades accesibles y filas de las listas.

Aquí viven las funciones que usan tanto la ventana principal como los diálogos:
crear controles con nombre accesible, mostrar avisos, abrir diálogos HTML
legibles con lector de pantalla, construir menús contextuales y convertir cada
objeto (canal, emisión, programa, grabación…) en la fila de una lista
accesible según su plantilla de lectura.
"""
from __future__ import annotations

import logging
import time
import webbrowser

import wx

from . import NOMBRE_APP, catalogo
from .accesible import ListaAccesible
from .catalogo import NOMBRE_TIPO, Canal, Emision, Programa

registro = logging.getLogger(__name__)
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
BUSCADORES = [
    ("Buscar en &FilmAffinity", "https://www.filmaffinity.com/es/search.php?stext="),
    ("Buscar en &IMDb", "https://www.imdb.com/find/?q="),
    ("Buscar en Rotten &Tomatoes", "https://www.rottentomatoes.com/search?search="),
    ("Buscar en &Google", "https://www.google.com/search?q="),
]


# --- utilidades de accesibilidad ------------------------------------------
def nombrar(control, nombre: str):
    """Nombre accesible del control (lo leen NVDA y Narrador)."""
    control.SetName(nombre)
    if hasattr(control, "SetToolTip") and not isinstance(control, (wx.TextCtrl, wx.ListBox, wx.ListCtrl, wx.Notebook)):
        control.SetToolTip(nombre)
    return control


def configurar_notebook_accesible(notebook: wx.Notebook, nombre: str = "") -> wx.Notebook:
    """Configura un wx.Notebook para que los lectores de pantalla anuncien sus pestañas.

    - Asigna el nombre accesible sin ToolTip (para no interferir con las pestañas).
    - Anuncia por voz directa (voz.decir) y mediante eventos de Windows (NotifyWinEvent)
      el nombre y la posición de la pestaña actual al cambiar de página y al recibir el foco.
    - Soporta la navegación por teclado con Ctrl+Tab, Ctrl+Shift+Tab, Ctrl+AvPág y Ctrl+RePág.
    """
    if nombre:
        nombrar(notebook, nombre)

    ultimo_anuncio = [-1, 0.0]

    def anunciar(indice: int, forzar: bool = False):
        if not (0 <= indice < notebook.GetPageCount()):
            return
        top = notebook.GetTopLevelParent()
        if top and not top.IsShown():
            return
        ahora = time.time()
        # Evitar anuncios duplicados si coinciden cambio de página y foco (< 0.25 s)
        if not forzar and ultimo_anuncio[0] == indice and (ahora - ultimo_anuncio[1]) < 0.25:
            return
        ultimo_anuncio[0] = indice
        ultimo_anuncio[1] = ahora
        titulo = notebook.GetPageText(indice)
        total = notebook.GetPageCount()
        mensaje = f"{titulo}, pestaña {indice + 1} de {total}"
        from . import voz
        voz.decir(mensaje, interrumpir=True)
        try:
            import ctypes
            hwnd = notebook.GetHandle()
            if hwnd:
                user32 = ctypes.windll.user32
                EVENT_OBJECT_SELECTION = 0x8006
                EVENT_OBJECT_FOCUS = 0x8005
                OBJID_CLIENT = -4
                user32.NotifyWinEvent(EVENT_OBJECT_SELECTION, hwnd, OBJID_CLIENT, indice + 1)
                user32.NotifyWinEvent(EVENT_OBJECT_FOCUS, hwnd, OBJID_CLIENT, indice + 1)
        except Exception:
            pass

    def al_cambiar_pagina(evento):
        anunciar(evento.GetSelection())
        evento.Skip()

    def al_enfocar(evento):
        anunciar(notebook.GetSelection())
        evento.Skip()

    def al_pulsar_teclas(evento):
        tecla = evento.GetKeyCode()
        mod = evento.GetModifiers()
        if (mod == wx.MOD_CONTROL and tecla in (wx.WXK_TAB, wx.WXK_PAGEDOWN)) or \
           (mod == (wx.MOD_CONTROL | wx.MOD_SHIFT) and tecla == wx.WXK_TAB) or \
           (mod == wx.MOD_CONTROL and tecla == wx.WXK_PAGEUP):
            direccion = -1 if (mod & wx.MOD_SHIFT or tecla == wx.WXK_PAGEUP) else 1
            total = notebook.GetPageCount()
            if total > 1:
                nueva = (notebook.GetSelection() + direccion) % total
                notebook.SetSelection(nueva)
            return
        evento.Skip()

    notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, al_cambiar_pagina)
    notebook.Bind(wx.EVT_SET_FOCUS, al_enfocar)
    notebook.Bind(wx.EVT_KEY_DOWN, al_pulsar_teclas)
    return notebook



def campo(parent, sizer, etiqueta: str, crear, proporcion: int = 1, expandir: bool = True):
    """Crea una etiqueta y su control. La etiqueta se crea antes para que Windows los asocie."""
    texto = wx.StaticText(parent, label=etiqueta)
    control = crear()
    nombrar(control, etiqueta.replace("&", "").rstrip(":"))
    sizer.Add(texto, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
    sizer.Add(control, proporcion, (wx.EXPAND if expandir else wx.ALIGN_CENTER_VERTICAL) | wx.RIGHT, 10)
    return control


def boton(parent, etiqueta: str, manejador, nombre: str | None = None):
    control = wx.Button(parent, label=etiqueta)
    nombrar(control, nombre or etiqueta.replace("&", ""))
    control.Bind(wx.EVT_BUTTON, manejador)
    return control


def aviso(parent, texto: str, titulo: str = NOMBRE_APP, icono=wx.ICON_INFORMATION):
    wx.MessageBox(texto, titulo, wx.OK | icono, parent)


def dialogo_pregunta(parent, texto: str, titulo: str = NOMBRE_APP, icono=wx.ICON_QUESTION):
    """Arma el cuadro de Sí o No de la aplicación. Separado de ``pregunta`` para poder comprobarlo."""
    dialogo = wx.GenericMessageDialog(parent, texto, titulo, wx.YES_NO | icono)
    dialogo.SetYesNoLabels("&Sí", "&No")
    dialogo.SetEscapeId(wx.ID_NO)
    return dialogo


def pregunta(parent, texto: str, titulo: str = NOMBRE_APP, icono=wx.ICON_QUESTION) -> bool:
    """Pregunta de Sí o No en la que Escape responde «No», como en el resto de la aplicación.

    El cuadro de mensaje nativo de Windows con solo Sí y No **no se cierra con
    Escape**: Win32 solo lo permite cuando hay un botón Cancelar, y añadir un
    tercer botón confunde. Se usa la versión propia de wxWidgets, que sí deja
    decir qué botón responde a Escape (comprobado enviando la tecla: el nativo
    la ignoraba y este cierra al momento).
    """
    dialogo = dialogo_pregunta(parent, texto, titulo, icono)
    try:
        return dialogo.ShowModal() == wx.ID_YES
    finally:
        dialogo.Destroy()


def copiar_portapapeles(texto: str) -> bool:
    if wx.TheClipboard.Open():
        wx.TheClipboard.SetData(wx.TextDataObject(texto))
        wx.TheClipboard.Close()
        return True
    return False


def abrir_navegador(parent, url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        aviso(parent, "Ha habido un error. No se ha podido abrir el navegador.", icono=wx.ICON_ERROR)


def dialogo_html(parent, titulo: str, cuerpo_html: str, texto_alternativo: str) -> None:
    """Diálogo HTML accesible (wx-accessible-webview): encabezados y tablas navegables con el lector.

    Si no hay motor WebView, muestra el texto plano en un cuadro de edición.
    """
    try:
        from wx_accessible_webview import AccessibleHtmlDialog

        dialogo = AccessibleHtmlDialog(parent, titulo, cuerpo_html, buttons=[("&Cerrar", wx.ID_CANCEL)], size=(760, 620), open_links_externally=True, lang="es")
        dialogo.show_modal()
    except Exception:
        registro.exception("Diálogo HTML accesible no disponible; se usa texto")
        dialogo_texto(parent, titulo, texto_alternativo)


def dialogo_texto(parent, titulo: str, texto: str) -> None:
    with wx.Dialog(parent, title=titulo, size=(720, 520), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER) as dialogo:
        caja = wx.BoxSizer(wx.VERTICAL)
        contenido = nombrar(wx.TextCtrl(dialogo, value=texto, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP), titulo)
        caja.Add(contenido, 1, wx.EXPAND | wx.ALL, 10)
        caja.Add(wx.Button(dialogo, wx.ID_CANCEL, "&Cerrar"), 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        dialogo.SetSizer(caja)
        contenido.SetFocus()
        dialogo.ShowModal()


def _ancla(titulo: str) -> str:
    """Identificador de un encabezado, con la misma forma que los enlaces del índice del manual."""
    limpio = "".join(c for c in titulo.lower() if c.isalnum() or c in " -")
    return "-".join(limpio.split())


def _linea_html(texto: str) -> str:
    """Negrita, código y enlaces de una línea de Markdown."""
    import html as modulo_html
    import re

    salida = modulo_html.escape(texto)
    salida = re.sub(r"`([^`]+)`", r"<code>\1</code>", salida)
    salida = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", salida)
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', salida)


def markdown_a_html(texto: str) -> str:
    """Convierte el manual a HTML para el diálogo accesible.

    No es un procesador de Markdown completo: entiende solo lo que usa
    ``MANUAL.md`` (encabezados, tablas, listas, separadores, negrita, código y
    enlaces), que es contenido nuestro y no de fuera.
    """
    salida: list[str] = []
    parrafo: list[str] = []
    lineas = texto.replace("\r\n", "\n").split("\n")

    def cerrar_parrafo():
        if parrafo:
            salida.append("<p>" + " ".join(parrafo) + "</p>")
            parrafo.clear()

    numero = 0
    while numero < len(lineas):
        linea = lineas[numero].rstrip()
        pelada = linea.strip()
        if not pelada:
            cerrar_parrafo()
            numero += 1
            continue
        if set(pelada) == {"-"} and len(pelada) >= 3:
            cerrar_parrafo()
            salida.append("<hr>")
            numero += 1
            continue
        if pelada.startswith("#"):
            cerrar_parrafo()
            nivel = min(len(pelada) - len(pelada.lstrip("#")), 6)
            titulo = pelada.lstrip("#").strip()
            salida.append(f'<h{nivel} id="{_ancla(titulo)}">{_linea_html(titulo)}</h{nivel}>')
            numero += 1
            continue
        if pelada.startswith("|"):
            cerrar_parrafo()
            filas = []
            while numero < len(lineas) and lineas[numero].strip().startswith("|"):
                filas.append([c.strip() for c in lineas[numero].strip().strip("|").split("|")])
                numero += 1
            # La segunda fila de una tabla de Markdown es la de guiones: marca cuál es la cabecera.
            cabecera = len(filas) > 1 and all(set(c) <= set("-: ") and c for c in filas[1])
            salida.append("<table>")
            for indice, celdas in enumerate(filas):
                if cabecera and indice == 1:
                    continue
                etiqueta = "th" if cabecera and indice == 0 else "td"
                salida.append("<tr>" + "".join(f"<{etiqueta}>{_linea_html(c)}</{etiqueta}>" for c in celdas) + "</tr>")
            salida.append("</table>")
            continue
        marca = pelada[:2] == "- "
        ordenada = not marca and pelada[:1].isdigit() and ". " in pelada[:5]
        if marca or ordenada:
            cerrar_parrafo()
            etiqueta = "ul" if marca else "ol"
            salida.append(f"<{etiqueta}>")
            while numero < len(lineas):
                actual = lineas[numero].strip()
                if marca and actual.startswith("- "):
                    salida.append(f"<li>{_linea_html(actual[2:])}</li>")
                elif not marca and actual[:1].isdigit() and ". " in actual[:5]:
                    salida.append(f"<li>{_linea_html(actual.split('. ', 1)[1])}</li>")
                else:
                    break
                numero += 1
            salida.append(f"</{etiqueta}>")
            continue
        parrafo.append(_linea_html(pelada))
        numero += 1
    cerrar_parrafo()
    return "".join(salida)


def tabla_html(titulo: str, filas, introduccion: str = "") -> str:
    """Cuerpo HTML con un encabezado y una tabla de dos columnas."""
    import html as modulo_html

    cuerpo = [f"<h1>{modulo_html.escape(titulo)}</h1>"]
    if introduccion:
        cuerpo.append(f"<p>{modulo_html.escape(introduccion)}</p>")
    cuerpo.append("<table>")
    for clave, valor in filas:
        cuerpo.append(f'<tr><th scope="row">{modulo_html.escape(str(clave))}</th><td>{modulo_html.escape(str(valor))}</td></tr>')
    cuerpo.append("</table>")
    return "".join(cuerpo)


def menu_desde(ventana, opciones, lista: ListaAccesible | None = None, fila: int | None = None) -> None:
    """Construye y muestra un menú contextual. ``opciones``: (etiqueta, acción) o None como separador.

    Con teclado (tecla Aplicaciones o Mayús+F10) el menú se abre junto a la fila enfocada.
    """
    menu = wx.Menu()
    for opcion in opciones:
        if opcion is None:
            menu.AppendSeparator()
            continue
        etiqueta, accion = opcion[0], opcion[1]
        if isinstance(accion, wx.Menu):
            menu.AppendSubMenu(accion, etiqueta)
            continue
        elemento = menu.Append(wx.ID_ANY, etiqueta)
        if accion is None:
            elemento.Enable(False)
            continue
        ventana.Bind(wx.EVT_MENU, lambda e, a=accion: a(), elemento)
    posicion = wx.DefaultPosition
    if lista is not None and fila is not None and fila != wx.NOT_FOUND and wx.GetMouseState().LeftIsDown() is False:
        try:
            rect = lista.GetItemRect(fila)
            posicion = wx.Point(rect.x + 20, rect.y + rect.height)
        except Exception:
            posicion = wx.DefaultPosition
    if posicion != wx.DefaultPosition and lista is not None:
        lista.PopupMenu(menu, posicion)
    else:
        ventana.PopupMenu(menu)
    menu.Destroy()


# --- filas para las listas accesibles -------------------------------------------
def fila_canal(canal: Canal, datos, guia: dict, posicion: int = 0, bloqueado: bool = False) -> dict:
    estado = datos.estado_canal(canal.tipo, canal.nombre)
    marcas = [m for m, activa in (("favorito", estado["favorite"]), ("oculto", estado["hide"]), ("bloqueado", bloqueado)) if activa]
    programas = catalogo.programas_canal(guia, canal)
    actual, siguiente = catalogo.ahora_y_siguiente(programas)
    notas = []
    if canal.drm:
        notas.append("emisión cifrada, no se puede reproducir")
    if canal.intermitente:
        notas.append("no emite las veinticuatro horas")
    if canal.catchup:
        notas.append("permite ver programas ya emitidos")
    if canal.sin_emision:
        notas.append("sin directo propio: se abre su web")
    if canal.geo:
        notas.append("solo España")
    if canal.registro:
        notas.append("requiere registro")
    reproducibles = len(canal.reproducibles)
    primera = canal.emision_principal
    if not reproducibles and primera is not None and primera.tipo in ("youtube", "twitch"):
        notas.append(f"se ve en {'YouTube' if primera.tipo == 'youtube' else 'Twitch'} dentro de la aplicación")
    return {
        "numero": str(canal.numero or (posicion + 1)),
        "nombre": canal.nombre,
        "ahora": f"Ahora {actual.horario()}: {actual.titulo}" if actual else ("Sin programación" if canal.epg_id and not programas else ""),
        "siguiente": f"Después {siguiente.horario()}: {siguiente.titulo}" if siguiente else "",
        "categoria": canal.ambito, "pais": canal.pais, "estado": ", ".join(marcas), "notas": ", ".join(notas),
        "emisiones": f"{reproducibles} emisi{'ón' if reproducibles == 1 else 'ones'}" if reproducibles else ({"youtube": "YouTube", "twitch": "Twitch"}.get(primera.tipo if primera else "", "web oficial") if canal.web or primera else "sin emisiones"),
        "fuente": canal.origen, "web": canal.web, "_canal": canal,
    }


def fila_emision(emision: Emision, numero: int) -> dict:
    tipos = {"directo": "Directo", "ext": "Directo de la web oficial", "youtube": "YouTube (navegador)", "twitch": "Twitch (navegador)", "web": "Web oficial (navegador)"}
    zona = {"SP": "solo España", "CAT": "solo Cataluña", "ZONA": "restringido por zona geográfica"}.get(emision.geo or "", f"zona {emision.geo}" if emision.geo else "")
    return {"numero": f"Emisión {numero}", "tipo": tipos.get(emision.tipo, emision.tipo), "formato": emision.formato if emision.tipo == "directo" else "", "calidad": (emision.resolucion or "").upper(), "idioma": emision.idioma or "", "zona": zona, "url": emision.url, "_emision": emision}


def fila_programa(programa: Programa, canal: Canal | None, ahora: float | None = None) -> dict:
    ahora = ahora or time.time()
    if programa.en_curso(ahora):
        estado = "Ahora"
    elif programa.fin <= ahora:
        estado = "Terminado"
    else:
        estado = "Próximo"
    inicio = time.localtime(programa.inicio)
    return {
        "hora": programa.horario(), "dia": f"{DIAS[inicio.tm_wday]} {inicio.tm_mday}", "titulo": programa.titulo, "categoria": programa.categoria_es(), "estado": estado,
        "duracion": f"{(programa.fin - programa.inicio) // 60} minutos", "descripcion": programa.descripcion, "canal": canal.nombre if canal else "",
        "episodio": programa.episodio, "valoracion": programa.valoracion, "edad": programa.edad, "subtitulo": programa.subtitulo,
        "_programa": programa, "_canal": canal,
    }


def texto_detalle_programa(canal, programa: Programa) -> str:
    """Ficha del programa con todo lo que trae la guía, para el cuadro de detalles."""
    if programa is None:
        return ""
    cabecera = " · ".join(p for p in ((canal.nombre if canal else ""), programa.fecha(), programa.horario()) if p)
    lineas = [cabecera, programa.titulo]
    for clave, valor in programa.detalles():
        lineas.append(f"{clave}: {valor}")
    if programa.descripcion:
        lineas.append(programa.descripcion)
    return "\n".join(l for l in lineas if l)


def fila_lista(nombre: str, url: str, tipo: str, propia: bool, clase: str = "lista") -> dict:
    return {"nombre": nombre, "tipo": NOMBRE_TIPO.get(tipo, tipo), "url": url, "fuente": "propia" if propia else "oficial", "_url": url, "_propia": propia, "_clase": clase}


def fila_recordatorio(recordatorio: dict) -> dict:
    return {"fecha": time.strftime("%d/%m %H:%M", time.localtime(recordatorio["inicio"])), "canal": recordatorio["canal"], "titulo": recordatorio["titulo"], "minutos": f"aviso {recordatorio['minutos']} minutos antes", "_recordatorio": recordatorio}


def fila_grabacion(entrada: dict) -> dict:
    from .grabacion import ESTADOS

    minutos = max(1, int((entrada["fin"] - entrada["inicio"]) / 60))
    return {
        "fecha": time.strftime("%d/%m %H:%M", time.localtime(entrada["inicio"])), "canal": entrada["canal"], "titulo": entrada["titulo"],
        "duracion": f"{minutos} minutos", "estado": ESTADOS.get(entrada.get("estado", ""), "Pendiente"), "_grabacion": entrada,
    }


def fila_en_curso(resumen: dict) -> dict:
    """Una grabación que está ocurriendo ahora: cuánto lleva, cuánto le queda y cuánto ocupa."""
    from .grabacion import duracion_hablada, tamano_hablado

    situaciones = {"preparando": "Preparando", "grabando": "Grabando", "reintentando": "Reanudando tras un corte", "hecha": "Terminando", "error": "Con error"}
    estado = situaciones.get(resumen.get("situacion", ""), "Grabando")
    if resumen.get("partes", 1) > 1:
        estado += f" (en {resumen['partes']} archivos)"
    restante = resumen.get("restante")
    return {
        "canal": resumen.get("canal", ""), "titulo": resumen.get("titulo", "") or "Grabación manual", "estado": estado,
        "transcurrido": f"lleva {duracion_hablada(resumen.get('transcurrido', 0))}",
        "restante": (f"quedan {duracion_hablada(restante)}" if restante is not None else "hasta que la detengas"),
        "tamano": tamano_hablado(resumen.get("tamano", 0)), "archivo": resumen.get("archivo", ""),
        "fecha": time.strftime("%H:%M", time.localtime(resumen.get("inicio") or time.time())),
        "duracion": f"lleva {duracion_hablada(resumen.get('transcurrido', 0))}",
        "_curso": resumen,
    }


def fila_regla(regla: dict, programadas: int = 0) -> dict:
    """Una regla de grabación automática, contando lo que tiene programado."""
    from .grabacion import DIAS_SEMANA, REPETICIONES

    donde = f"en {regla['canal']}" if regla["canal"] else ("solo en favoritos" if regla["soloFavoritos"] else "en todos los canales")
    cuando = []
    if regla["dias"]:
        cuando.append("los " + ", ".join(DIAS_SEMANA[d] for d in regla["dias"]))
    if regla["desde"] or regla["hasta"]:
        cuando.append(f"entre las {regla['desde'] or '00:00'} y las {regla['hasta'] or '23:59'}")
    return {
        "texto": regla["texto"], "donde": donde, "cuando": " ".join(cuando) or "siempre",
        "repeticiones": REPETICIONES[regla["repeticiones"]],
        "programadas": f"{programadas} programada" + ("s" if programadas != 1 else ""),
        "estado": "activa" if regla["activa"] else "parada", "_regla": regla,
    }


def fila_comprobacion(resultado: dict) -> dict:
    from .comprobador import ESTADOS

    return {
        "nombre": resultado["canal"], "estado": ESTADOS.get(resultado["estado"], resultado["estado"]),
        "detalle": resultado["detalle"], "respuesta": f"{resultado['ms']} milisegundos" if resultado.get("ms") else "",
        "tipo": NOMBRE_TIPO.get(resultado.get("tipo", ""), ""), "_resultado": resultado,
    }


def fila_archivo(archivo: dict) -> dict:
    estado = "Protegida" if archivo.get("protegida") else "Grabada"
    return {
        "fecha": time.strftime("%d/%m/%Y %H:%M", time.localtime(archivo["fecha"])), "titulo": archivo["nombre"],
        "duracion": f"{archivo['tamano'] / 1e6:.1f} megabytes", "canal": "", "estado": estado, "_archivo": archivo,
    }


def fila_historial(entrada: dict) -> dict:
    return {
        "fecha": time.strftime("%d/%m %H:%M", time.localtime(entrada.get("hora") or 0)) if entrada.get("hora") else "",
        "nombre": entrada.get("nombre", ""), "tipo": NOMBRE_TIPO.get(entrada.get("tipo", ""), ""), "_entrada": entrada,
    }


def fila_vod(elemento: dict) -> dict:
    clases = {"pelicula": "Película", "serie": "Serie", "episodio": "Episodio"}
    return {
        "titulo": elemento.get("titulo", ""), "categoria": elemento.get("categoria", ""), "tipo": clases.get(elemento.get("clase", ""), ""),
        "valoracion": elemento.get("valoracion", ""), "descripcion": elemento.get("descripcion", ""), "_elemento": elemento,
    }


def fila_cuenta(cuenta, estado: str = "") -> dict:
    return {"nombre": cuenta.nombre, "servidor": cuenta.servidor, "usuario": cuenta.usuario, "tipo": NOMBRE_TIPO.get(cuenta.tipo, cuenta.tipo), "estado": estado, "_cuenta": cuenta}
