"""Carpeta de datos, ajustes, caché y descarga de libmpv.

Todo lo que la aplicación genera vive en la carpeta ``data`` situada junto al
programa (o en la carpeta indicada por la variable de entorno ``TDT_DATA``):

- ``data/mpv/libmpv-2.dll``  motor de audio y vídeo (descargado una vez).
- ``data/ajustes.json``       ajustes del usuario, en un formato compatible con
                              el de la aplicación Android.
- ``data/cache/``             listas y guías descargadas (copia de respaldo).
- ``data/logs/``              registro de errores.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from . import NOMBRE_APP, VERSION

USER_AGENT_APP = f"Resintoniza/{VERSION} (Windows NT 10.0; Win64; x64)"
# Cada cuánto se actualizan las listas al iniciar, y su equivalencia en segundos.
FRECUENCIAS = {"nunca": None, "siempre": 0, "diaria": 24 * 3600, "semanal": 7 * 24 * 3600}
LIMITE_JSON = 64 * 1024 * 1024
LIBMPV = "libmpv-2.dll"
VULKAN_DLL = "vulkan-1.dll"
API_MPV = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"

# Ajustes con los mismos nombres que UserSettings del APK (Gson).
AJUSTES_USUARIO_DEFECTO = {
    "schemaVersion": 1,
    "darkMode": "2",                 # "1" sí, "2" según sistema, "0" no
    "hiddenChannelsVisibility": 0,   # 0 mostrar ocultos, 1 no mostrar, 2 solo ocultos
    "closeOnExit": "0",              # "1" cerrar y detener, "2" seguir reproduciendo, "0" preguntar
    "closeFavoritesOpen": True,
    "marquee": True,
    "playerSubtitle": "off",         # off, es, en, ca, gl, eu
    "playerGestures": True,
    "playerForceHorizontal": True,
    "playerStartOnlyWifi": "2",
    "browserEmbedWeb": True,
    "browserEmbedYoutube": True,
    "browserForceHorizontal": False,
    "adsShow": True,
}

# Ajustes propios de la versión Windows (el APK ignora claves desconocidas).
AJUSTES_WINDOWS_DEFECTO = {
    "tamanoLetra": 11,
    "volumen": 80,
    "silencio": False,
    "altoContraste": False,
    "actualizarAlIniciar": True,     # compatibilidad: lo que manda es frecuenciaActualizacion
    # Cada cuánto se vuelven a descargar las listas y la guía al abrir la aplicación:
    # nunca (se usa siempre la copia guardada), siempre, diaria o semanal.
    "frecuenciaActualizacion": "nunca",
    "guiaExtra": True,               # guía XMLTV adicional para los canales sin programación
    "guiaExtraVariante": "",         # variante de esa guía (vacío: la recomendada)
    "guiasPropias": [],              # otras guías XMLTV que añada el usuario
    "modoImagen": "ajustar",         # ajustar, llenar, zoom
    "listas": [],                    # [{"nombre", "url" o "ruta", "tipo": tv|radio|auto, "formato": auto|json|m3u}]
    "cuentas": [],                   # cuentas Xtream Codes (la contraseña va cifrada)
    "recordatorios": [],             # [{"canal", "epg_id", "titulo", "inicio", "minutos", "tipo"}]
    "grabaciones": [],               # grabaciones programadas desde la guía
    "carpetaGrabaciones": "",        # vacío: data/grabaciones
    "grabacionSegundoPlano": True,   # grabar con un libmpv aparte, sin ocupar el reproductor
    "maximoGrabacionesFondo": 3,     # cuántas grabaciones en segundo plano a la vez
    "reglasGrabacion": [],           # reglas automáticas por título o palabra clave
    "margenAntes": 0,                # minutos de más al empezar una grabación programada
    "margenDespues": 2,              # minutos de más al terminarla
    "margenesCanal": {},             # canal → [antes, después], para los que siempre van tarde
    "carpetaPorPrograma": False,     # cada programa en su subcarpeta
    "ordenPosterior": "",            # orden a ejecutar al terminar una grabación (%f = archivo)
    "grabarSoloAudio": False,        # grabar sin vídeo: ocupa una décima parte
    "formatoGrabacionTV": "ts",      # formato de grabación en emisiones de TV: "ts" o "mp4"
    "minimoLibreGB": 2,              # espacio libre mínimo para empezar o seguir grabando
    "retencionDias": 0,              # borrar grabaciones de más de N días (0 desactivado)
    "retencionGigas": 0,             # tope de la carpeta en gigabytes (0 desactivado)
    "retencionPorPrograma": 0,       # dejar solo las N últimas de cada programa (0 desactivado)
    "grabacionesProtegidas": [],     # archivos que la limpieza automática no toca
    "alTerminarGrabacion": "nada",   # nada, cerrar, suspender o apagar
    "tareaWindows": False,           # abrir la aplicación con el Programador de tareas antes de grabar
    "minimizarABandeja": False,      # ocultar en la bandeja del sistema al minimizar la ventana
    "iniciarMinimizado": False,      # arrancar la aplicación minimizada
    "iniciarConWindows": False,      # arrancar automáticamente con Windows
    "posicionesGrabaciones": {},     # archivo → segundos vistos, para reanudar
    "nivelarVolumen": False,         # igualar el volumen entre canales
    "carpetaSincronizacion": "",     # carpeta (en la nube) donde se guarda y se lee la copia
    "avisoGrabacionMinutos": 0,      # decir cada N minutos qué se está grabando (0 desactivado)
    "historial": [],                 # últimos canales vistos
    "bloqueo": {},                   # PIN y canales o categorías bloqueados
    "calidad": "max",                # límite de calidad en emisiones HLS
    "bufferRecepcion": "normal",     # margen de recepción: minimo, normal o amplio
    "soloAudio": False,              # no abrir la ventana de vídeo (ahorra datos)
    "mostrarVideo": False,           # abrir sola la ventana de vídeo al reproducir
    "audiodescripcion": False,       # preferir la pista de audiodescripción
    "timeshiftMinutos": 0,           # minutos de directo guardados para poder retroceder
    "reintentos": True,              # volver a intentarlo si se corta la emisión
    "emisionAlternativa": True,      # probar la siguiente emisión del canal si la primera falla
    "quitarDuplicados": True,        # al mezclar listas, no repetir canales
    "numeroCanal": True,             # teclear cifras salta al número de canal
    "anunciarPrograma": True,        # al sintonizar, decir qué están dando
    "sonidos": True,                 # avisos sonoros
    "avisosSonido": {},              # nombre del sonido → activado
    "interfazInvisible": False,      # teclas del sistema con la aplicación en segundo plano
    "teclasGlobales": {},            # acción → combinación para la interfaz invisible
    "comprobarActualizaciones": True,
    "urlActualizaciones": "https://api.github.com/repos/joseonce/Resintoniza/releases/latest",        # manifiesto JSON con la última versión publicada
    "ultimaComprobacionApp": 0,
    "perfilActual": "",
    "dnsAdaptador": "",              # conexión de red elegida en el diálogo del DNS alternativo
    "dnsConfiguracionExterna": "",   # xdp_configuracion_original.json importado de la herramienta original
    "ultimaComprobacion": 0,
    "ultimoCanal": {"tv": "", "radio": ""},
    "comprobarMpv": True,            # buscar versiones nuevas de libmpv al iniciar (una vez por semana)
    "ultimaComprobacionMpv": 0,
    "teclas": {},                    # acción → combinación personalizada (ver tdt/teclas.py)
    "accesibilidad": {
        "voz": True,                 # locutar avisos con el lector de pantalla (accessible_output2)
        "braille": True,
        "retardoVoz": 120,
        "anunciarEstado": True,      # decir "Reproduciendo: La 1", errores, etc.
        "anunciarAvisos": True,      # decir los mensajes de la barra de estado
        "decirFila": True,           # navegación por columnas: "Fila 3"
        "decirColumna": True,        # "Canal", "Ahora"…
        "decirCelda": True,          # contenido de la celda
        "plantillas": {},            # clave de plantilla → texto (ver tdt/plantillas.py)
    },
}

AJUSTES_DEFECTO = {
    "tvChannels": [],
    "radioChannels": [],
    "tvCommunitiesRemoved": [],
    "radioCommunitiesRemoved": [],
    "showOnlyFavoritesTv": False,
    "showOnlyFavoritesRadio": False,
    "userSettings": AJUSTES_USUARIO_DEFECTO,
    "windows": AJUSTES_WINDOWS_DEFECTO,
}


def congelada() -> bool:
    return bool(getattr(sys, "frozen", False))


def raiz_aplicacion() -> Path:
    if congelada():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def carpeta_datos() -> Path:
    personalizada = os.environ.get("TDT_DATA", "").strip()
    if personalizada:
        return Path(personalizada).resolve()
    return raiz_aplicacion() / "data"


def url_http(valor) -> bool:
    if not isinstance(valor, str):
        return False
    partes = urlparse(valor)
    return partes.scheme in ("http", "https") and bool(partes.hostname) and not partes.username and not partes.password


def descargar_json(url: str, timeout: int = 25, cabeceras: dict | None = None):
    if not url_http(url):
        raise ValueError("La dirección debe empezar por https:// o http://.")
    encabezados = {"User-Agent": USER_AGENT_APP, "Accept": "application/json"}
    encabezados.update(cabeceras or {})
    peticion = urllib.request.Request(url, headers=encabezados)
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        crudo = respuesta.read(LIMITE_JSON + 1)
    if len(crudo) > LIMITE_JSON:
        raise ValueError("La respuesta supera el tamaño máximo permitido.")
    return json.loads(crudo.decode("utf-8-sig"))


def descargar_texto(url: str, timeout: int = 40, limite: int = LIMITE_JSON) -> str:
    """Descarga un archivo de texto (por ejemplo una lista M3U) y lo devuelve decodificado."""
    if not url_http(url):
        raise ValueError("La dirección debe empezar por https:// o http://.")
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT_APP, "Accept": "*/*"})
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        crudo = respuesta.read(limite + 1)
    if len(crudo) > limite:
        raise ValueError("La lista supera el tamaño máximo permitido.")
    return crudo.decode("utf-8-sig", "replace")


def guardar_json_atomico(ruta: Path, data) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(ruta)


def _lista_de_cadenas(valor):
    return [x for x in valor if isinstance(x, str)] if isinstance(valor, list) else []


def validar_ajustes(data) -> dict:
    """Devuelve ajustes limpios a partir de un JSON de Windows o del APK.

    Acepta cualquier objeto con la forma de UserSettingsContainer. Los valores
    desconocidos o con tipo incorrecto se sustituyen por los predeterminados.
    """
    if not isinstance(data, dict):
        raise ValueError("El archivo no contiene un objeto JSON de ajustes.")
    limpio = copy.deepcopy(AJUSTES_DEFECTO)
    for clave in ("tvChannels", "radioChannels"):
        canales = []
        vistos = set()
        for entrada in data.get(clave) or []:
            if not isinstance(entrada, dict) or not isinstance(entrada.get("channelName"), str):
                continue
            nombre = entrada["channelName"].strip()
            if not nombre or nombre in vistos:
                continue
            vistos.add(nombre)
            posicion = entrada.get("position")
            canales.append({
                "channelName": nombre,
                "favorite": bool(entrada.get("favorite", False)),
                "hide": bool(entrada.get("hide", False)),
                "position": posicion if isinstance(posicion, int) and not isinstance(posicion, bool) else None,
            })
        limpio[clave] = canales
    for clave in ("tvCommunitiesRemoved", "radioCommunitiesRemoved"):
        limpio[clave] = list(dict.fromkeys(_lista_de_cadenas(data.get(clave))))
    for clave in ("showOnlyFavoritesTv", "showOnlyFavoritesRadio"):
        limpio[clave] = bool(data.get(clave, False))
    usuario = data.get("userSettings") if isinstance(data.get("userSettings"), dict) else {}
    for clave, defecto in AJUSTES_USUARIO_DEFECTO.items():
        valor = usuario.get(clave, defecto)
        if isinstance(defecto, bool):
            limpio["userSettings"][clave] = bool(valor) if isinstance(valor, bool) else defecto
        elif isinstance(defecto, int):
            limpio["userSettings"][clave] = valor if isinstance(valor, int) and not isinstance(valor, bool) else defecto
        else:
            limpio["userSettings"][clave] = valor if isinstance(valor, str) else defecto
    us = limpio["userSettings"]
    if us["darkMode"] not in ("0", "1", "2"):
        us["darkMode"] = "2"
    if us["closeOnExit"] not in ("0", "1", "2"):
        us["closeOnExit"] = "0"
    if us["hiddenChannelsVisibility"] not in (0, 1, 2):
        us["hiddenChannelsVisibility"] = 0
    if us["playerSubtitle"] not in ("off", "es", "en", "ca", "gl", "eu"):
        us["playerSubtitle"] = "off"
    windows = data.get("windows") if isinstance(data.get("windows"), dict) else {}
    w = limpio["windows"]
    for clave, bajo, alto in (("tamanoLetra", 8, 28), ("volumen", 0, 100), ("maximoGrabacionesFondo", 1, 8),
                              ("margenAntes", 0, 60), ("margenDespues", 0, 60), ("minimoLibreGB", 0, 500),
                              ("retencionDias", 0, 3650), ("retencionGigas", 0, 100000), ("retencionPorPrograma", 0, 100),
                              ("avisoGrabacionMinutos", 0, 120)):
        valor = windows.get(clave, w[clave])
        if isinstance(valor, int) and not isinstance(valor, bool) and bajo <= valor <= alto:
            w[clave] = valor
    for clave in ("silencio", "altoContraste", "actualizarAlIniciar", "guiaExtra", "soloAudio", "mostrarVideo", "audiodescripcion", "reintentos",
                  "emisionAlternativa", "quitarDuplicados", "numeroCanal", "anunciarPrograma", "sonidos", "interfazInvisible",
                  "comprobarActualizaciones", "grabacionSegundoPlano", "carpetaPorPrograma", "grabarSoloAudio",
                  "tareaWindows", "nivelarVolumen", "minimizarABandeja", "iniciarMinimizado", "iniciarConWindows"):
        valor = windows.get(clave, w[clave])
        if isinstance(valor, bool):
            w[clave] = valor
    if windows.get("modoImagen") in ("ajustar", "llenar", "zoom"):
        w["modoImagen"] = windows["modoImagen"]
    calidad = windows.get("calidad")
    if isinstance(calidad, str) and (calidad in ("max", "min") or calidad.isdigit()):
        w["calidad"] = calidad
    if windows.get("bufferRecepcion") in ("minimo", "normal", "amplio"):
        w["bufferRecepcion"] = windows["bufferRecepcion"]
    if windows.get("formatoGrabacionTV") in ("ts", "mp4"):
        w["formatoGrabacionTV"] = windows["formatoGrabacionTV"]
    minutos = windows.get("timeshiftMinutos")
    if isinstance(minutos, int) and not isinstance(minutos, bool) and 0 <= minutos <= 60:
        w["timeshiftMinutos"] = minutos
    for clave in ("carpetaGrabaciones", "urlActualizaciones", "perfilActual", "dnsAdaptador", "dnsConfiguracionExterna",
                  "ordenPosterior", "carpetaSincronizacion"):
        valor = windows.get(clave)
        if isinstance(valor, str):
            w[clave] = valor.strip()
    frecuencia = windows.get("frecuenciaActualizacion")
    if frecuencia in FRECUENCIAS:
        w["frecuenciaActualizacion"] = frecuencia
    elif isinstance(windows.get("actualizarAlIniciar"), bool):
        # Ajustes de una versión anterior: se conserva lo que tenía elegido.
        w["frecuenciaActualizacion"] = "siempre" if windows["actualizarAlIniciar"] else "nunca"
    variante = windows.get("guiaExtraVariante")
    w["guiaExtraVariante"] = variante.strip() if isinstance(variante, str) and url_http(variante) else ""
    w["guiasPropias"] = [g for g in (windows.get("guiasPropias") or []) if url_http(g)][:5]
    listas = []
    for entrada in windows.get("listas") or []:
        if not isinstance(entrada, dict) or not isinstance(entrada.get("nombre"), str):
            continue
        if entrada.get("tipo") not in ("tv", "radio", "auto"):
            continue
        url, ruta = entrada.get("url"), entrada.get("ruta")
        if not url_http(url) and not (isinstance(ruta, str) and ruta.strip()):
            continue
        formato = entrada.get("formato") if entrada.get("formato") in ("auto", "json", "m3u") else "auto"
        listas.append({
            "nombre": entrada["nombre"].strip() or (url if url_http(url) else str(ruta)),
            "url": url if url_http(url) else "", "ruta": (ruta or "").strip() if isinstance(ruta, str) else "",
            "tipo": entrada["tipo"], "formato": formato,
        })
    w["listas"] = listas
    cuentas = []
    for entrada in windows.get("cuentas") or []:
        if not isinstance(entrada, dict):
            continue
        servidor, usuario = entrada.get("servidor"), entrada.get("usuario")
        if not url_http(servidor) or not isinstance(usuario, str) or not usuario.strip():
            continue
        cuentas.append({
            "nombre": str(entrada.get("nombre") or servidor).strip(), "servidor": servidor.rstrip("/"),
            "usuario": usuario.strip(), "secreto": str(entrada.get("secreto") or ""),
            "tipo": entrada["tipo"] if entrada.get("tipo") in ("tv", "radio") else "tv",
        })
    w["cuentas"] = cuentas
    recordatorios = []
    for entrada in windows.get("recordatorios") or []:
        if not isinstance(entrada, dict):
            continue
        if all(isinstance(entrada.get(k), str) for k in ("canal", "titulo", "tipo")) and isinstance(entrada.get("inicio"), int) and isinstance(entrada.get("minutos"), int):
            recordatorios.append({"canal": entrada["canal"], "epg_id": str(entrada.get("epg_id") or ""), "titulo": entrada["titulo"], "inicio": entrada["inicio"], "minutos": entrada["minutos"], "tipo": entrada["tipo"]})
    w["recordatorios"] = recordatorios
    from . import grabacion as _grabacion, organizar as _organizar  # importación tardía: evita ciclos

    w["grabaciones"] = _grabacion.validar_programadas(windows.get("grabaciones"))
    w["reglasGrabacion"] = _grabacion.validar_reglas(windows.get("reglasGrabacion"))
    w["margenesCanal"] = _grabacion.validar_margenes_canal(windows.get("margenesCanal"))
    w["grabacionesProtegidas"] = [n for n in (windows.get("grabacionesProtegidas") or []) if isinstance(n, str)][:5000]
    posiciones = windows.get("posicionesGrabaciones")
    w["posicionesGrabaciones"] = ({k: float(v) for k, v in posiciones.items()
                                   if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)}
                                  if isinstance(posiciones, dict) else {})
    if windows.get("alTerminarGrabacion") in ("nada", "cerrar", "suspender", "apagar"):
        w["alTerminarGrabacion"] = windows["alTerminarGrabacion"]
    w["historial"] = _organizar.validar_historial(windows.get("historial"))
    w["bloqueo"] = _organizar.validar_bloqueo(windows.get("bloqueo"))
    avisos = windows.get("avisosSonido")
    w["avisosSonido"] = {k: bool(v) for k, v in avisos.items() if isinstance(k, str)} if isinstance(avisos, dict) else {}
    atajos = windows.get("teclasGlobales")
    w["teclasGlobales"] = {k: v for k, v in atajos.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(atajos, dict) else {}
    ultima_app = windows.get("ultimaComprobacionApp", 0)
    w["ultimaComprobacionApp"] = ultima_app if isinstance(ultima_app, (int, float)) and not isinstance(ultima_app, bool) else 0
    ultima = windows.get("ultimaComprobacion", 0)
    w["ultimaComprobacion"] = ultima if isinstance(ultima, (int, float)) and not isinstance(ultima, bool) else 0
    ultimo = windows.get("ultimoCanal") if isinstance(windows.get("ultimoCanal"), dict) else {}
    w["ultimoCanal"] = {"tv": str(ultimo.get("tv") or ""), "radio": str(ultimo.get("radio") or "")}
    if isinstance(windows.get("comprobarMpv"), bool):
        w["comprobarMpv"] = windows["comprobarMpv"]
    ultima_mpv = windows.get("ultimaComprobacionMpv", 0)
    w["ultimaComprobacionMpv"] = ultima_mpv if isinstance(ultima_mpv, (int, float)) and not isinstance(ultima_mpv, bool) else 0
    teclas = windows.get("teclas") if isinstance(windows.get("teclas"), dict) else {}
    w["teclas"] = {k: v for k, v in teclas.items() if isinstance(k, str) and isinstance(v, str)}
    acc = windows.get("accesibilidad") if isinstance(windows.get("accesibilidad"), dict) else {}
    for clave, defecto in AJUSTES_WINDOWS_DEFECTO["accesibilidad"].items():
        valor = acc.get(clave, defecto)
        if isinstance(defecto, bool):
            w["accesibilidad"][clave] = valor if isinstance(valor, bool) else defecto
        elif isinstance(defecto, int):
            w["accesibilidad"][clave] = valor if isinstance(valor, int) and not isinstance(valor, bool) and 0 <= valor <= 600 else defecto
        elif isinstance(defecto, dict):
            w["accesibilidad"][clave] = {k: v for k, v in valor.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(valor, dict) else {}
    return limpio


class Datos:
    """Acceso a la carpeta ``data``: ajustes, caché y registro."""

    def __init__(self, raiz: Path | None = None):
        self.raiz = (raiz or carpeta_datos()).resolve()
        for sub in ("mpv", "cache", "logs"):
            (self.raiz / sub).mkdir(parents=True, exist_ok=True)
        self.ruta_ajustes = self.raiz / "ajustes.json"
        self.aviso = ""
        self.ajustes = copy.deepcopy(AJUSTES_DEFECTO)
        if self.ruta_ajustes.exists():
            try:
                self.ajustes = validar_ajustes(json.loads(self.ruta_ajustes.read_text(encoding="utf-8")))
            except (ValueError, OSError, TypeError) as error:
                copia = self.raiz / f"ajustes-danados-{time.strftime('%Y%m%d-%H%M%S')}.json"
                try:
                    self.ruta_ajustes.replace(copia)
                except OSError:
                    pass
                self.aviso = f"No se pudieron leer los ajustes; se ha guardado una copia en {copia.name} y se usan los valores predeterminados. Detalle: {error}"

    # --- ajustes -----------------------------------------------------------
    def guardar(self) -> None:
        guardar_json_atomico(self.ruta_ajustes, self.ajustes)

    @property
    def usuario(self) -> dict:
        return self.ajustes["userSettings"]

    @property
    def windows(self) -> dict:
        return self.ajustes["windows"]

    def _clave_canales(self, tipo: str) -> str:
        return "tvChannels" if tipo == "tv" else "radioChannels"

    def estado_canal(self, tipo: str, nombre: str) -> dict:
        for entrada in self.ajustes[self._clave_canales(tipo)]:
            if entrada["channelName"] == nombre:
                return entrada
        return {"channelName": nombre, "favorite": False, "hide": False, "position": None}

    def fijar_estado_canal(self, tipo: str, nombre: str, **cambios) -> dict:
        lista = self.ajustes[self._clave_canales(tipo)]
        for entrada in lista:
            if entrada["channelName"] == nombre:
                entrada.update(cambios)
                if not entrada["favorite"] and not entrada["hide"] and entrada["position"] is None:
                    lista.remove(entrada)
                return entrada
        entrada = {"channelName": nombre, "favorite": False, "hide": False, "position": None}
        entrada.update(cambios)
        lista.append(entrada)
        return entrada

    def comunidades_ocultas(self, tipo: str) -> list[str]:
        return self.ajustes["tvCommunitiesRemoved" if tipo == "tv" else "radioCommunitiesRemoved"]

    def solo_favoritos(self, tipo: str) -> bool:
        return self.ajustes["showOnlyFavoritesTv" if tipo == "tv" else "showOnlyFavoritesRadio"]

    def fijar_solo_favoritos(self, tipo: str, valor: bool) -> None:
        self.ajustes["showOnlyFavoritesTv" if tipo == "tv" else "showOnlyFavoritesRadio"] = bool(valor)

    # --- caché -------------------------------------------------------------
    def ruta_cache(self, url: str) -> Path:
        return self.raiz / "cache" / (hashlib.sha256(url.encode("utf-8")).hexdigest()[:32] + ".json")

    def leer_cache(self, url: str):
        ruta = self.ruta_cache(url)
        if not ruta.exists():
            return None, 0
        return json.loads(ruta.read_text(encoding="utf-8")), ruta.stat().st_mtime

    def obtener_json(self, url: str, respaldo: str | None = None, refrescar: bool = True, validar=None):
        """Descarga ``url`` (o ``respaldo``) y guarda copia. Sin red usa la caché.

        Devuelve (datos, aviso). ``validar`` es una función que lanza ValueError
        si los datos no sirven; así nunca se guarda en caché basura.
        """
        validar = validar or (lambda d: None)
        if not refrescar:
            try:
                datos, _ = self.leer_cache(url)
                if datos is not None:
                    validar(datos)
                    return datos, ""
            except (ValueError, OSError, TypeError, KeyError):
                pass
        errores = []
        for direccion in [u for u in (url, respaldo) if u]:
            try:
                datos = descargar_json(direccion)
                validar(datos)
                guardar_json_atomico(self.ruta_cache(url), datos)
                aviso = "" if direccion == url else "Se ha usado el servidor de respaldo."
                return datos, aviso
            except Exception as error:  # red, JSON o validación
                errores.append(f"{direccion}: {error}")
        try:
            datos, fecha = self.leer_cache(url)
            if datos is not None:
                validar(datos)
                marca = time.strftime("%d/%m/%Y %H:%M", time.localtime(fecha))
                return datos, f"No se ha podido conectar con el servidor de las listas; se usa la última lista descargada ({marca})."
        except (ValueError, OSError, TypeError, KeyError):
            pass
        raise RuntimeError("No se pudo descargar la lista. " + " | ".join(errores))

    def descargar_archivo(self, url: str, sufijo: str = ".bin", refrescar: bool = True, horas: float = 12.0):
        """Descarga un archivo grande (por ejemplo la guía XMLTV) y lo deja en la caché.

        Si ya hay una copia reciente no se vuelve a bajar. Devuelve su ruta o None.
        """
        if not url_http(url):
            return None
        destino = self.raiz / "cache" / (hashlib.sha256(url.encode("utf-8")).hexdigest()[:32] + sufijo)
        if destino.exists() and (not refrescar or time.time() - destino.stat().st_mtime < horas * 3600):
            return destino
        temporal = destino.with_suffix(destino.suffix + ".tmp")
        try:
            peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT_APP, "Accept": "*/*"})
            with urllib.request.urlopen(peticion, timeout=90) as respuesta, open(temporal, "wb") as salida:
                total = 0
                while True:
                    trozo = respuesta.read(256 * 1024)
                    if not trozo:
                        break
                    total += len(trozo)
                    if total > 128 * 1024 * 1024:
                        raise ValueError("El archivo supera el tamaño máximo permitido.")
                    salida.write(trozo)
            temporal.replace(destino)
            return destino
        except Exception as error:
            logging.getLogger(__name__).info("No se pudo descargar %s: %s", url, error)
            temporal.unlink(missing_ok=True)
            return destino if destino.exists() else None

    def obtener_texto(self, url: str, refrescar: bool = True):
        """Descarga una lista de texto (M3U) con copia en la caché. Devuelve (texto, aviso)."""
        destino = self.raiz / "cache" / (hashlib.sha256(url.encode("utf-8")).hexdigest()[:32] + ".m3u")
        if not refrescar and destino.exists():
            return destino.read_text(encoding="utf-8", errors="replace"), ""
        try:
            texto = descargar_texto(url)
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(texto, encoding="utf-8")
            return texto, ""
        except Exception as error:
            if destino.exists():
                marca = time.strftime("%d/%m/%Y %H:%M", time.localtime(destino.stat().st_mtime))
                return destino.read_text(encoding="utf-8", errors="replace"), f"no se pudo descargar; se usa la copia del {marca}."
            raise RuntimeError(f"No se pudo descargar la lista: {error}") from error

    def limpiar_cache(self) -> int:
        cuenta = 0
        for patron in ("*.json", "*.xml.gz", "*.m3u", "*.bin", "*.tmp"):
            for archivo in (self.raiz / "cache").glob(patron):
                archivo.unlink(missing_ok=True)
                cuenta += 1
        return cuenta


def toca_actualizar(ajustes_windows: dict, ahora: float | None = None) -> bool:
    """True si al iniciar hay que volver a descargar las listas y la guía."""
    intervalo = FRECUENCIAS.get(ajustes_windows.get("frecuenciaActualizacion", "nunca"))
    if intervalo is None:
        return False
    if intervalo == 0:
        return True
    ultima = ajustes_windows.get("ultimaComprobacion") or 0
    return (ahora if ahora is not None else time.time()) - ultima >= intervalo


def configurar_registro(datos: Datos) -> Path:
    ruta = datos.raiz / "logs" / "aplicacion.log"
    logging.basicConfig(filename=str(ruta), level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", encoding="utf-8")
    logging.getLogger(__name__).info("%s %s iniciado. Datos en %s", NOMBRE_APP, VERSION, datos.raiz)
    return ruta


# --- libmpv -----------------------------------------------------------------
# En data/mpv solo vive libmpv-2.dll. La versión se lee de la propia DLL
# (reproductor.version_libmpv_cargada) y se compara con el último paquete
# publicado; las descargas se extraen en una carpeta temporal del sistema.
URL_7ZR = "https://www.7-zip.org/a/7zr.exe"
DLL_NUEVA = LIBMPV + ".nuevo"


def carpeta_mpv(datos: Datos) -> Path:
    return datos.raiz / "mpv"


def ruta_libmpv(datos: Datos) -> Path | None:
    ruta = carpeta_mpv(datos) / LIBMPV
    return ruta if ruta.exists() and ruta.stat().st_size > 1_000_000 else None


DLL_DESCARGA = LIBMPV + ".descarga"


def aplicar_actualizacion_pendiente(datos: Datos, intentos: int = 10, espera: float = 0.5) -> bool:
    """Si hay una libmpv-2.dll.nuevo descargada con la aplicación abierta, la instala ahora.

    Se reintenta unos segundos: al reiniciar desde la propia aplicación, la
    instancia anterior puede tardar un poco en soltar la DLL.
    """
    nueva = carpeta_mpv(datos) / DLL_NUEVA
    if not nueva.exists():
        return False
    if nueva.stat().st_size <= 1_000_000:  # descarga a medias: no sirve
        try:
            nueva.unlink()
        except OSError:
            pass
        return False
    for intento in range(max(1, intentos)):
        try:
            nueva.replace(carpeta_mpv(datos) / LIBMPV)
            return True
        except OSError:
            if intento + 1 < intentos:
                time.sleep(espera)
    logging.getLogger(__name__).warning("No se pudo instalar %s: la DLL anterior sigue en uso.", nueva)
    return False


OPCION_ESPERAR = "--esperar-pid="


def orden_reinicio(pid: int | None = None) -> list[str]:
    """Orden para volver a abrir la aplicación cuando se cierre el proceso ``pid``."""
    pid = os.getpid() if pid is None else int(pid)
    base = [sys.executable] if congelada() else [sys.executable, str(raiz_aplicacion() / "main.py")]
    return base + [f"{OPCION_ESPERAR}{pid}"]


def lanzar_reinicio() -> None:
    """Abre otra instancia que espera a que esta se cierre (y suelte libmpv) antes de arrancar."""
    import subprocess

    marcas = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(orden_reinicio(), cwd=str(raiz_aplicacion()), close_fds=True, creationflags=marcas,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def pid_a_esperar(argumentos: list[str]) -> int | None:
    for argumento in argumentos:
        if argumento.startswith(OPCION_ESPERAR):
            try:
                return int(argumento[len(OPCION_ESPERAR):])
            except ValueError:
                return None
    return None


def esperar_proceso(pid: int, segundos: float = 30.0) -> bool:
    """Espera a que termine el proceso ``pid``. True si ya no está (o no existía)."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        sincronizar = 0x00100000  # SYNCHRONIZE
        proceso = kernel32.OpenProcess(sincronizar, False, int(pid))
        if not proceso:
            return True
        try:
            return kernel32.WaitForSingleObject(proceso, int(segundos * 1000)) == 0  # WAIT_OBJECT_0
        finally:
            kernel32.CloseHandle(proceso)
    except (AttributeError, OSError, ValueError):
        return True


def colocar_libmpv(origen: Path, carpeta: Path, en_uso: bool = False) -> Path:
    """Copia la DLL extraída a ``carpeta`` y la deja en su sitio. Devuelve dónde ha quedado.

    Primero se copia con un nombre provisional dentro de la misma carpeta: la
    extracción está en la carpeta temporal del sistema, que suele estar en otro
    disco, y ahí no se puede mover de una vez. Después se sustituye la DLL con un
    cambio de nombre. Si Windows no deja porque la DLL está cargada (lo está en
    cuanto la aplicación ha consultado la versión, aunque no suene nada), se deja
    como ``libmpv-2.dll.nuevo`` y se instala al arrancar la próxima vez.
    """
    provisional = carpeta / DLL_DESCARGA
    shutil.copyfile(origen, provisional)
    try:
        if not en_uso:
            try:
                os.replace(provisional, carpeta / LIBMPV)
                return carpeta / LIBMPV
            except PermissionError:
                pass
        os.replace(provisional, carpeta / DLL_NUEVA)
        return carpeta / DLL_NUEVA
    finally:
        try:
            provisional.unlink(missing_ok=True)
        except OSError:
            pass


def limpiar_carpeta_mpv(datos: Datos) -> None:
    """Elimina restos de descargas antiguas: solo deben quedar las DLL del reproductor."""
    for ruta in carpeta_mpv(datos).iterdir():
        if ruta.name in (LIBMPV, DLL_NUEVA, VULKAN_DLL):
            continue
        try:
            shutil.rmtree(ruta) if ruta.is_dir() else ruta.unlink()
        except OSError:
            pass


def _informar(progreso, mensaje: str, fraccion: float | None = None) -> None:
    if progreso:
        progreso(mensaje, fraccion)


def localizar_paquete_mpv() -> tuple[str, str, int]:
    """Devuelve (nombre, url, tamaño) del paquete libmpv de 64 bits más reciente."""
    peticion = urllib.request.Request(API_MPV, headers={"User-Agent": USER_AGENT_APP, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:
        publicacion = json.loads(respuesta.read(4 * 1024 * 1024).decode("utf-8"))
    for activo in publicacion.get("assets", []):
        nombre = activo.get("name", "")
        if nombre.startswith("mpv-dev-x86_64-") and "-v3-" not in nombre and nombre.endswith(".7z"):
            return nombre, activo["browser_download_url"], int(activo.get("size") or 0)
    raise RuntimeError("No se encontró el paquete libmpv de 64 bits en la última publicación.")


def hash_paquete(nombre: str) -> str:
    """Hash git del paquete: mpv-dev-x86_64-20260903-git-69e63f425a.7z → 69e63f425a."""
    marca = "-git-"
    if marca not in nombre:
        return ""
    return nombre.split(marca, 1)[1].split(".")[0].strip().lower()


def hash_version(version: str) -> str:
    """Hash git de la versión que informa la DLL: "mpv v0.41.0-1023-g69e63f425" → 69e63f425."""
    for trozo in reversed((version or "").replace("/", "-").split("-")):
        trozo = trozo.strip()
        if len(trozo) >= 8 and trozo.startswith("g") and all(c in "0123456789abcdef" for c in trozo[1:]):
            return trozo[1:].lower()
    return ""


def actualizacion_disponible(version_cargada: str, nombre_paquete: str) -> bool:
    actual, nuevo = hash_version(version_cargada), hash_paquete(nombre_paquete)
    if not actual or not nuevo:
        return False
    return not (nuevo.startswith(actual) or actual.startswith(nuevo))


def _descargar_archivo(url: str, destino: Path, progreso=None, etiqueta: str = "", tamano: int = 0) -> None:
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT_APP})
    with urllib.request.urlopen(peticion, timeout=60) as respuesta, open(destino, "wb") as salida:
        leidos = 0
        while True:
            trozo = respuesta.read(256 * 1024)
            if not trozo:
                break
            salida.write(trozo)
            leidos += len(trozo)
            if tamano:
                _informar(progreso, f"Descargando {etiqueta}: {leidos / 1e6:.1f} de {tamano / 1e6:.1f} MB", min(0.9, 0.9 * leidos / tamano))


def _extractor_7z(temporal: Path, progreso=None) -> Path:
    """Ejecutable capaz de extraer .7z: 7-Zip instalado o 7zr.exe oficial, descargado a la carpeta temporal.

    py7zr no admite el filtro BCJ2 que usan los paquetes de libmpv.
    """
    for candidato in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "7-Zip" / "7z.exe", Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "7-Zip" / "7z.exe"):
        if candidato.exists():
            return candidato
    herramienta = temporal / "7zr.exe"
    _informar(progreso, "Descargando la herramienta de extracción 7zr.exe (7-zip.org)…", 0.02)
    _descargar_archivo(URL_7ZR, herramienta)
    return herramienta


def descargar_libmpv(datos: Datos, progreso=None, archivo_local: Path | None = None, en_uso: bool = False) -> tuple[Path, str]:
    """Descarga libmpv-2.dll a ``data/mpv``. Devuelve (ruta, nombre del paquete).

    Con ``en_uso`` (la DLL está cargada por la aplicación), o si Windows no deja
    sustituirla, se deja como ``libmpv-2.dll.nuevo`` y se instala en el
    siguiente arranque: la ruta devuelta lo dice.
    """
    import subprocess
    import tempfile

    destino = carpeta_mpv(datos)
    destino.mkdir(parents=True, exist_ok=True)
    temporal = Path(tempfile.mkdtemp(prefix="tdt-mpv-"))
    try:
        if archivo_local:
            paquete = Path(archivo_local)
            nombre = paquete.name
        else:
            _informar(progreso, "Buscando la última versión de libmpv…", 0.0)
            nombre, url, tamano = localizar_paquete_mpv()
            paquete = temporal / nombre
            _informar(progreso, f"Descargando {nombre} ({tamano / 1e6:.1f} MB)…", 0.0)
            _descargar_archivo(url, paquete, progreso, "libmpv", tamano)
        extractor = _extractor_7z(temporal, progreso)
        _informar(progreso, "Extrayendo libmpv-2.dll…", 0.92)
        salida = temporal / "extraccion"
        salida.mkdir()
        orden = [str(extractor), "e", str(paquete), f"-o{salida}", LIBMPV, "-y", "-r"]
        resultado = subprocess.run(orden, capture_output=True, text=True, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        extraida = next(salida.rglob(LIBMPV), None)
        if resultado.returncode != 0 or extraida is None:
            raise RuntimeError("No se pudo extraer libmpv-2.dll: " + (resultado.stderr or resultado.stdout or "sin detalles").strip()[-400:])
        final = colocar_libmpv(extraida, destino, en_uso)
        limpiar_carpeta_mpv(datos)
        pendiente = final.name == DLL_NUEVA
        _informar(progreso, "libmpv descargado en la carpeta data/mpv." + (" Se instalará al reiniciar la aplicación." if pendiente else ""), 1.0)
        return final, nombre
    finally:
        shutil.rmtree(temporal, ignore_errors=True)
