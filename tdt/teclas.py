"""Catálogo de teclas de la aplicación (personalizables, como en SocialRSS).

Única fuente de verdad de los atajos: cada acción tiene su tecla por
defecto y su sección. Las etiquetas de los menús, los menús contextuales,
la ayuda de teclas y el filtro global del reproductor se construyen a
partir de aquí, así que personalizar una tecla se refleja en todos ellos.

Las acciones de la sección del reproductor (F1 a F12 por defecto) funcionan
desde cualquier parte de la aplicación, también con diálogos abiertos, por
lo que solo admiten teclas de función o combinaciones con Ctrl o Alt.
"""
from __future__ import annotations

import wx

SEC_GENERAL = "Generales"
SEC_CANAL = "Canales y listas"
SEC_REPRODUCTOR = "Reproductor (F1 a F12, en toda la aplicación)"
SEC_NAVEGADOR = "Navegador integrado"
SEC_HERRAMIENTAS = "Herramientas y ayuda"

# (acción, etiqueta con & para el menú, sección, tecla por defecto)
CATALOGO = [
    ("archivo_actualizar", "&Actualizar listas y guía", SEC_GENERAL, "Ctrl+Shift+R"),
    ("archivo_lista", "Añadir &lista de reproducción…", SEC_GENERAL, "Ctrl+L"),
    ("archivo_cuenta", "Añadir cuenta de &proveedor (Xtream Codes)…", SEC_GENERAL, ""),
    ("archivo_iptvorg", "Añadir canales del catálogo de &iptv-org…", SEC_GENERAL, ""),
    ("archivo_exportar", "&Exportar configuración…", SEC_GENERAL, ""),
    ("archivo_importar", "&Importar configuración…", SEC_GENERAL, ""),
    ("archivo_exportar_m3u", "Exportar los &favoritos a una lista M3U…", SEC_GENERAL, ""),
    ("archivo_bandeja", "Ocultar en la &bandeja del sistema", SEC_GENERAL, "Ctrl+M"),
    ("archivo_salir", "&Salir", SEC_GENERAL, "Ctrl+Q"),
    ("buscar", "&Buscar canal", SEC_GENERAL, "Ctrl+F"),
    ("canal_reproducir", "&Reproducir", SEC_CANAL, "Ctrl+P"),
    ("canal_web", "&Web oficial", SEC_CANAL, "Ctrl+W"),
    ("canal_programacion", "&Programación del canal…", SEC_CANAL, "Ctrl+G"),
    ("canal_guia", "Ver en la &guía", SEC_CANAL, "Ctrl+Shift+G"),
    ("canal_favorito", "Añadir o quitar de &favoritos", SEC_CANAL, "Ctrl+D"),
    ("canal_ocultar", "&Ocultar o mostrar", SEC_CANAL, "Ctrl+H"),
    ("canal_copiar", "Copiar &enlace de la emisión", SEC_CANAL, "Ctrl+Shift+C"),
    ("canal_info", "Leer la &información del canal", SEC_CANAL, "Ctrl+Shift+I"),
    ("canal_subir", "&Subir en el orden personal", SEC_CANAL, "Alt+Up"),
    ("canal_bajar", "&Bajar en el orden personal", SEC_CANAL, "Alt+Down"),
    ("canal_quitar_orden", "Quitar del orden &personal", SEC_CANAL, ""),
    ("canal_bloquear", "Bloquear o desbloquear con &PIN", SEC_CANAL, ""),
    ("canal_numero", "Ir al &número de canal…", SEC_CANAL, "Ctrl+N"),
    ("repro_favoritos", "Canales &favoritos (elegir y reproducir)…", SEC_REPRODUCTOR, "F1"),
    ("repro_pausa", "Reproducir o &pausar", SEC_REPRODUCTOR, "F2"),
    ("repro_recargar", "&Recargar la emisión", SEC_REPRODUCTOR, "F3"),
    ("repro_detener", "&Detener", SEC_REPRODUCTOR, "F4"),
    ("repro_bajar_volumen", "Bajar el &volumen", SEC_REPRODUCTOR, "F5"),
    ("repro_subir_volumen", "Subir el vol&umen", SEC_REPRODUCTOR, "F6"),
    ("repro_anterior", "Canal &anterior", SEC_REPRODUCTOR, "F7"),
    ("repro_siguiente", "Canal &siguiente", SEC_REPRODUCTOR, "F8"),
    ("repro_silencio", "Silenciar o activar el s&onido", SEC_REPRODUCTOR, "F9"),
    ("repro_video", "Mostrar u ocultar la ventana de &vídeo", SEC_REPRODUCTOR, "F10"),
    ("repro_pantalla_completa", "Pantalla &completa", SEC_REPRODUCTOR, "F11"),
    ("repro_estado", "Decir el &estado de la reproducción", SEC_REPRODUCTOR, "F12"),
    ("repro_volver", "&Volver al canal anterior", SEC_REPRODUCTOR, "Ctrl+Shift+B"),
    ("nav_zonas", "Cambiar entre la página y la barra de botones", SEC_NAVEGADOR, "Ctrl+B"),
    ("repro_audio", "Pista de audi&o…", SEC_REPRODUCTOR, "Ctrl+Shift+A"),
    ("repro_subtitulos", "Su&btítulos…", SEC_REPRODUCTOR, "Ctrl+Shift+T"),
    ("repro_tamano", "&Tamaño de la imagen…", SEC_REPRODUCTOR, ""),
    ("repro_temporizador", "Te&mporizador de apagado…", SEC_REPRODUCTOR, "Ctrl+E"),
    ("repro_grabar", "&Grabar o detener la grabación", SEC_REPRODUCTOR, "Ctrl+Alt+R"),
    ("repro_retroceder", "&Retroceder 30 segundos del directo", SEC_REPRODUCTOR, "Ctrl+Alt+Z"),
    ("repro_directo", "Volver al &directo", SEC_REPRODUCTOR, "Ctrl+Alt+X"),
    ("repro_calidad", "&Calidad de la emisión…", SEC_REPRODUCTOR, "Ctrl+Alt+C"),
    ("repro_estadisticas", "&Datos de la emisión…", SEC_REPRODUCTOR, "Ctrl+Alt+D"),
    ("repro_solo_audio", "Modo solo a&udio", SEC_REPRODUCTOR, "Ctrl+Alt+U"),
    ("repro_enviar", "&Enviar a la tele (DLNA o Chromecast)…", SEC_REPRODUCTOR, "Ctrl+Alt+T"),
    ("repro_historial", "&Historial de canales…", SEC_REPRODUCTOR, "Ctrl+Shift+H"),
    ("repro_mosaico", "&Multiventana: varios canales a la vez…", SEC_REPRODUCTOR, "Ctrl+Alt+M"),
    ("repro_nivelador", "&Nivelar el volumen entre canales", SEC_REPRODUCTOR, "Ctrl+Alt+N"),
    ("repro_velocidad", "&Velocidad de reproducción…", SEC_REPRODUCTOR, ""),
    ("repro_desfase", "Retraso del a&udio respecto a la imagen…", SEC_REPRODUCTOR, ""),
    ("herr_ajustes", "&Ajustes…", SEC_HERRAMIENTAS, "Ctrl+,"),
    ("herr_teclas", "Personalizar &teclas…", SEC_HERRAMIENTAS, "Ctrl+K"),
    ("herr_teclas_globales", "Teclas con la aplicación en segundo pla&no…", SEC_HERRAMIENTAS, ""),
    ("herr_plantillas", "&Plantillas de lectura…", SEC_HERRAMIENTAS, ""),
    ("herr_categorias", "Ca&tegorías y comunidades visibles…", SEC_HERRAMIENTAS, ""),
    ("herr_recordatorios", "&Recordatorios…", SEC_HERRAMIENTAS, "Ctrl+R"),
    ("herr_buscar_guia", "&Buscar en toda la guía…", SEC_HERRAMIENTAS, "Ctrl+Shift+F"),
    ("herr_guias", "Guías de programa&ción…", SEC_HERRAMIENTAS, ""),
    ("herr_cobertura", "C&obertura de la guía…", SEC_HERRAMIENTAS, ""),
    ("herr_grabaciones", "&Grabaciones…", SEC_HERRAMIENTAS, "Ctrl+Shift+Z"),
    ("herr_reglas", "Reglas de grabación a&utomática…", SEC_HERRAMIENTAS, "Ctrl+Alt+G"),
    ("herr_ahora", "Qué empieza a&hora en tus favoritos…", SEC_HERRAMIENTAS, "Ctrl+Alt+A"),
    ("herr_comprobar", "Comprobar qué canales &responden…", SEC_HERRAMIENTAS, ""),
    ("herr_sincronizar", "Sincronizar con una carpeta en la &nube…", SEC_HERRAMIENTAS, ""),
    ("herr_cuentas", "&Cuentas de proveedor (Xtream Codes)…", SEC_HERRAMIENTAS, ""),
    ("herr_duplicados", "Canales &duplicados…", SEC_HERRAMIENTAS, ""),
    ("herr_pin", "Bloqueo por &PIN…", SEC_HERRAMIENTAS, ""),
    ("herr_dns", "DNS alternativo para bloqueos del &operador…", SEC_HERRAMIENTAS, ""),
    ("herr_perfiles", "Perfiles de &uso…", SEC_HERRAMIENTAS, ""),
    ("herr_respaldo", "Copia de &seguridad…", SEC_HERRAMIENTAS, ""),
    ("herr_addon", "Instalar el complemento de &NVDA…", SEC_HERRAMIENTAS, ""),
    ("herr_actualizar_app", "Buscar &versiones nuevas de la aplicación…", SEC_HERRAMIENTAS, ""),
    ("herr_mpv", "Buscar actualizaciones del &reproductor libmpv…", SEC_HERRAMIENTAS, ""),
    ("herr_cache", "&Limpiar caché de listas", SEC_HERRAMIENTAS, ""),
    ("ayuda_uso", "&Uso y teclado", SEC_HERRAMIENTAS, "Ctrl+F1"),
    ("ayuda_manual", "&Manual de usuario", SEC_HERRAMIENTAS, ""),
    ("ayuda_teclas", "&Teclas actuales", SEC_HERRAMIENTAS, ""),
    ("ayuda_registro", "Ver el &registro de errores", SEC_HERRAMIENTAS, ""),
    ("ayuda_legal", "&Aviso legal y fuentes", SEC_HERRAMIENTAS, ""),
    ("ayuda_acerca", "Acerca &de…", SEC_HERRAMIENTAS, ""),
]
ACCIONES = [a for a, _e, _s, _t in CATALOGO]
ETIQUETAS = {a: e for a, e, _s, _t in CATALOGO}
SECCION = {a: s for a, _e, s, _t in CATALOGO}
DEFECTO = {a: t for a, _e, _s, t in CATALOGO}
SECCIONES = [SEC_GENERAL, SEC_CANAL, SEC_REPRODUCTOR, SEC_NAVEGADOR, SEC_HERRAMIENTAS]
ACCIONES_GLOBALES = [a for a in ACCIONES if SECCION[a] == SEC_REPRODUCTOR]

# Teclas que no se pueden asignar: las usan las listas y los campos de texto.
RESERVADAS = {"space", "left", "right", "up", "down", "enter", "return", "esc", "escape", "tab", "back", "delete", "ctrl+0", "ctrl+1", "ctrl+2", "ctrl+3", "ctrl+4", "ctrl+5", "ctrl+6", "ctrl+7", "ctrl+8", "ctrl+9", "ctrl+a", "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "shift+f10"}

_ESPECIALES = {
    "SPACE": wx.WXK_SPACE, "LEFT": wx.WXK_LEFT, "RIGHT": wx.WXK_RIGHT, "UP": wx.WXK_UP, "DOWN": wx.WXK_DOWN, "ENTER": wx.WXK_RETURN, "RETURN": wx.WXK_RETURN,
    "ESC": wx.WXK_ESCAPE, "ESCAPE": wx.WXK_ESCAPE, "TAB": wx.WXK_TAB, "PGUP": wx.WXK_PAGEUP, "PGDN": wx.WXK_PAGEDOWN, "PAGEUP": wx.WXK_PAGEUP, "PAGEDOWN": wx.WXK_PAGEDOWN,
    "HOME": wx.WXK_HOME, "END": wx.WXK_END, "INS": wx.WXK_INSERT, "INSERT": wx.WXK_INSERT, "DEL": wx.WXK_DELETE, "DELETE": wx.WXK_DELETE, "BACK": wx.WXK_BACK,
    "F1": wx.WXK_F1, "F2": wx.WXK_F2, "F3": wx.WXK_F3, "F4": wx.WXK_F4, "F5": wx.WXK_F5, "F6": wx.WXK_F6, "F7": wx.WXK_F7, "F8": wx.WXK_F8, "F9": wx.WXK_F9, "F10": wx.WXK_F10, "F11": wx.WXK_F11, "F12": wx.WXK_F12,
}
_NOMBRE_TECLA = {v: k for k, v in _ESPECIALES.items() if k not in ("RETURN", "ESCAPE", "PAGEUP", "PAGEDOWN", "INSERT", "DELETE")}
_LEGIBLE = {"SPACE": "Espacio", "LEFT": "Flecha izquierda", "RIGHT": "Flecha derecha", "UP": "Flecha arriba", "DOWN": "Flecha abajo", "ENTER": "Intro", "ESC": "Escape", "TAB": "Tabulador", "PGUP": "Retroceder página", "PGDN": "Avanzar página", "HOME": "Inicio", "END": "Fin", "INS": "Insertar", "DEL": "Suprimir", "BACK": "Retroceso", ",": "Coma", ".": "Punto"}


def normalizar(combo: str) -> str:
    """Forma canónica: modificadores en orden Ctrl, Alt, Shift y tecla en mayúsculas."""
    partes = [p.strip() for p in (combo or "").split("+") if p.strip()]
    if not partes:
        return ""
    if combo.strip().endswith("+") and partes:
        partes.append("+")
    tecla = partes[-1]
    modificadores = {p.lower() for p in partes[:-1]}
    tecla = tecla.upper() if len(tecla) == 1 or tecla.upper() in _ESPECIALES else tecla
    orden = [n for n, m in (("Ctrl", "ctrl"), ("Alt", "alt"), ("Shift", "shift")) if m in modificadores]
    return "+".join(orden + [tecla])


def a_wx(combo: str):
    """(modificadores wx.MOD_*, código de tecla) o None si la combinación no vale."""
    combo = normalizar(combo)
    if not combo:
        return None
    partes = combo.split("+")
    tecla = partes[-1]
    modificadores = 0
    for parte in partes[:-1]:
        modificadores |= {"Ctrl": wx.MOD_CONTROL, "Alt": wx.MOD_ALT, "Shift": wx.MOD_SHIFT}[parte]
    if tecla.upper() in _ESPECIALES:
        return modificadores, _ESPECIALES[tecla.upper()]
    if len(tecla) == 1:
        return modificadores, ord(tecla.upper())
    return None


def legible(combo: str) -> str:
    combo = normalizar(combo)
    if not combo:
        return "sin tecla"
    partes = combo.split("+")
    salida = [{"Ctrl": "Ctrl", "Alt": "Alt", "Shift": "Mayús"}[p] for p in partes[:-1]]
    tecla = partes[-1]
    salida.append(_LEGIBLE.get(tecla.upper(), tecla))
    return "+".join(salida)


def evento_a_combo(evento) -> str:
    """Combinación pulsada en un evento de teclado, o "" si solo son modificadores."""
    codigo = evento.GetKeyCode()
    if codigo in (wx.WXK_CONTROL, wx.WXK_SHIFT, wx.WXK_ALT, wx.WXK_RAW_CONTROL, wx.WXK_WINDOWS_LEFT, wx.WXK_WINDOWS_RIGHT, wx.WXK_MENU, wx.WXK_NONE):
        return ""
    modificadores = evento.GetModifiers()
    partes = []
    if modificadores & wx.MOD_CONTROL:
        partes.append("Ctrl")
    if modificadores & wx.MOD_ALT:
        partes.append("Alt")
    if modificadores & wx.MOD_SHIFT:
        partes.append("Shift")
    if codigo in _NOMBRE_TECLA:
        partes.append(_NOMBRE_TECLA[codigo])
    elif codigo == wx.WXK_NUMPAD_ENTER:
        partes.append("ENTER")
    elif 33 <= codigo <= 126:
        partes.append(chr(codigo).upper())
    else:
        return ""
    return "+".join(partes)


def valida_global(combo: str) -> bool:
    """Las teclas del reproductor actúan en toda la aplicación: tecla de función o con Ctrl/Alt."""
    combo = normalizar(combo)
    if not combo:
        return True
    partes = combo.split("+")
    return partes[-1].upper().startswith("F") and partes[-1].upper() in _ESPECIALES or "Ctrl" in partes or "Alt" in partes


class Teclas:
    """Teclas actuales: catálogo más las personalizadas guardadas en ``ajustes.windows["teclas"]``."""

    def __init__(self, ajustes_windows: dict | None = None):
        self.ajustes_windows = ajustes_windows if ajustes_windows is not None else {}
        self.personalizadas: dict[str, str] = {}
        for accion, combo in (self.ajustes_windows.get("teclas") or {}).items():
            if accion in DEFECTO and isinstance(combo, str):
                self.personalizadas[accion] = normalizar(combo)
        self._mapa_global: dict[tuple[int, int], str] | None = None

    def combo(self, accion: str) -> str:
        return self.personalizadas.get(accion, DEFECTO.get(accion, ""))

    def es_personalizada(self, accion: str) -> bool:
        return accion in self.personalizadas and self.personalizadas[accion] != DEFECTO.get(accion, "")

    def etiqueta(self, accion: str, con_ampersand: bool = True) -> str:
        texto = ETIQUETAS.get(accion, accion)
        return texto if con_ampersand else texto.replace("&", "")

    def etiqueta_menu(self, accion: str, texto: str | None = None) -> str:
        """Texto para un elemento de menú con su tecla actual (wx la convierte en acelerador)."""
        texto = texto if texto is not None else self.etiqueta(accion)
        combo = self.combo(accion)
        return f"{texto}\t{combo}" if combo else texto

    def acciones_de(self, seccion: str) -> list[str]:
        return [a for a in ACCIONES if SECCION[a] == seccion]

    def conflicto(self, accion: str, combo: str) -> str | None:
        combo = normalizar(combo)
        if not combo:
            return None
        for otra in ACCIONES:
            if otra != accion and self.combo(otra) == combo:
                return otra
        return None

    def es_reservada(self, combo: str) -> bool:
        return normalizar(combo).lower() in RESERVADAS

    def establecer(self, accion: str, combo: str) -> None:
        combo = normalizar(combo)
        if combo == DEFECTO.get(accion, ""):
            self.personalizadas.pop(accion, None)
        else:
            self.personalizadas[accion] = combo
        self._mapa_global = None
        self.guardar()

    def restaurar(self, accion: str | None = None, seccion: str | None = None) -> None:
        for a in list(self.personalizadas):
            if accion is None and seccion is None or a == accion or (seccion and SECCION[a] == seccion):
                self.personalizadas.pop(a, None)
        self._mapa_global = None
        self.guardar()

    def guardar(self) -> None:
        self.ajustes_windows["teclas"] = dict(self.personalizadas)

    # --- coincidencia con eventos de teclado ---------------------------------------------
    def mapa_global(self) -> dict[tuple[int, int], str]:
        if self._mapa_global is None:
            mapa = {}
            for accion in ACCIONES_GLOBALES:
                clave = a_wx(self.combo(accion))
                if clave:
                    mapa[clave] = accion
            self._mapa_global = mapa
        return self._mapa_global

    def accion_global(self, evento) -> str | None:
        return self.mapa_global().get((evento.GetModifiers(), evento.GetKeyCode()))

    def coincide(self, accion: str, evento) -> bool:
        clave = a_wx(self.combo(accion))
        return bool(clave) and clave == (evento.GetModifiers(), evento.GetKeyCode())

    def texto_ayuda(self) -> str:
        lineas = ["Teclas actuales (Herramientas > Accesibilidad y teclas > Personalizar teclas para cambiarlas):", ""]
        for seccion in SECCIONES:
            lineas.append(seccion)
            for accion in self.acciones_de(seccion):
                marca = " (personalizada)" if self.es_personalizada(accion) else ""
                lineas.append(f"  {legible(self.combo(accion)):28} {self.etiqueta(accion, False)}{marca}")
            lineas.append("")
        lineas += ["En las listas: flechas arriba y abajo cambian de fila; izquierda y derecha leen por columnas; Ctrl+1 a 9 leen una columna; Ctrl+0 lee la fila entera; Intro activa; Aplicaciones o Mayús+F10 abren el menú contextual.", "En pantalla completa: Escape sale y espacio pausa, además de las teclas del reproductor."]
        return "\n".join(lineas)
