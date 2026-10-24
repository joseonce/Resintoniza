"""Reproductor de audio y vídeo basado en libmpv (python-mpv).

Sustituye a ExoPlayer/Media3 del APK. libmpv es una única DLL que se guarda
en ``data/mpv`` y se dibuja dentro de un panel de wxPython mediante su HWND.
Los avisos del reproductor se entregan por ``on_evento(tipo, texto)`` desde
hilos de mpv: la interfaz debe pasarlos por ``wx.CallAfter``.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from .proveedores import Fuente

registro = logging.getLogger(__name__)
IDIOMAS_SUBTITULOS = {"es": "es,spa,Spanish,Español", "en": "en,eng,English", "ca": "ca,cat,Catalan,Català", "gl": "gl,glg,Galician,Galego", "eu": "eu,eus,Basque,Euskera"}
# Pistas de audiodescripción: así se etiquetan en las emisiones españolas y europeas.
IDIOMAS_AUDIODESCRIPCION = "ads,esad,ad,spa-ad,es-ad,audesc,vi,visual,descripcion"
CALIDADES = [("La mejor disponible", "max"), ("La más ligera (conexión lenta)", "min"), ("Hasta 1 megabit", "1000000"), ("Hasta 2,5 megabits", "2500000"), ("Hasta 5 megabits", "5000000")]
# Nivelador de volumen entre canales (ffmpeg): sube lo flojo y baja lo fuerte
# con una ventana corta, para que el salto al cambiar de emisora no asuste.
FILTRO_NIVELADOR = "dynaudnorm=g=7:f=250:r=0.9:p=0.5"
VELOCIDADES = [("Normal", 1.0), ("Un poco más despacio (0,9)", 0.9), ("Un poco más rápido (1,25)", 1.25), ("Rápido (1,5)", 1.5), ("Muy rápido (2)", 2.0)]

# Búfer de recepción. En un directo no se puede guardar por delante más de lo
# que el servidor haya publicado, así que el margen sale de tres cosas: cuánto
# se guarda (``demuxer-max-bytes`` y ``cache-secs``), cuánto se espera a tener
# datos antes de seguir tras un corte (``cache-pause-wait``, con
# ``cache-pause-initial``) y dónde se empieza respecto al directo
# (``live_start_index``).
# Medido con una emisión real, tres vueltas por nivel: retrasarse más de la
# cuenta no ayuda y encima estorba (ocho fragmentos atrás dejaban 11,9 segundos
# de búfer al cargar, frente a 19,4 quedándose donde el propio servidor manda),
# así que el margen de verdad lo dan la espera y el tamaño, no el retraso.
BUFERES = [
    ("Normal: unos 15 segundos de margen", "normal"),
    ("Amplio: más margen, con algo más de retraso", "amplio"),
    ("Mínimo: lo más pegado al directo posible", "minimo"),
]
# El manual de mpv describe exactamente el problema de «va a tirones»: la
# reproducción empieza y el búfer se queda sin datos enseguida. Su receta es
# entrar en modo búfer antes de empezar (``cache-pause-initial``) y darle a
# ``cache-secs`` y ``cache-pause-wait`` valores parecidos, de modo que tras un
# corte se rellene de verdad en vez de reanudar con lo justo y volver a cortar.
OPCIONES_BUFER = {
    "minimo": {"live_start_index": -3, "readahead": 5.0, "cache_secs": 5.0, "espera": 1.0, "inicial": False, "bytes": "96MiB", "flujo": "1MiB"},
    "normal": {"live_start_index": -3, "readahead": 30.0, "cache_secs": 30.0, "espera": 5.0, "inicial": True, "bytes": "192MiB", "flujo": "4MiB"},
    "amplio": {"live_start_index": -6, "readahead": 60.0, "cache_secs": 60.0, "espera": 10.0, "inicial": True, "bytes": "256MiB", "flujo": "8MiB"},
}


def opciones_buffer(nivel: str) -> dict:
    """Ajustes de mpv para el nivel de búfer pedido."""
    return OPCIONES_BUFER.get(nivel, OPCIONES_BUFER["normal"])


def cargar_mpv(carpeta: Path):
    """Importa python-mpv con la DLL de ``carpeta``. Lanza RuntimeError si falta."""
    carpeta = Path(carpeta)
    if not (carpeta / "libmpv-2.dll").exists():
        raise RuntimeError(f"No se encuentra libmpv-2.dll en {carpeta}.")
    os.environ["PATH"] = str(carpeta) + os.pathsep + os.environ.get("PATH", "")
    try:
        os.add_dll_directory(str(carpeta))
    except (AttributeError, OSError):
        pass
    try:
        os.add_dll_directory(str(Path(sys.executable).parent))
    except (AttributeError, OSError):
        pass
    try:
        import mpv  # noqa: WPS433 (importación tardía a propósito)
    except OSError as error:
        raise RuntimeError(f"No se pudo cargar libmpv-2.dll: {error}") from error
    locale_c()
    return mpv


def locale_c() -> None:
    """libmpv exige LC_NUMERIC en "C": wx.Locale(es) lo cambia y mpv_create devuelve NULL."""
    import locale

    try:
        locale.setlocale(locale.LC_NUMERIC, "C")
    except locale.Error:
        pass


def libmpv_en_memoria() -> bool:
    """True si este proceso ya ha cargado libmpv-2.dll.

    Una DLL cargada no se puede sustituir ni descargar de la memoria hasta cerrar
    el programa, y basta con haber consultado la versión para cargarla: que no
    suene nada no quiere decir que esté libre.
    """
    if "mpv" in sys.modules:
        return True
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        return bool(kernel32.GetModuleHandleW("libmpv-2.dll"))
    except (AttributeError, OSError):
        return False


def version_libmpv_cargada(carpeta: Path) -> str:
    """Versión de la DLL de ``carpeta`` (p. ej. "mpv v0.41.0-1023-g69e63f425")."""
    modulo = cargar_mpv(carpeta)
    instancia = modulo.MPV(vo="null", ao="null", terminal=False, log_handler=lambda *a: None)
    try:
        return str(instancia.mpv_version)
    finally:
        instancia.terminate()


class Reproductor:
    ESTADOS = {"cargando": "Cargando, debería empezar en breve", "reproduciendo": "Reproduciendo", "pausado": "En pausa", "detenido": "Detenido", "error": "Error mientras cargaba"}

    def __init__(self, hwnd: int, carpeta_mpv: Path, on_evento, volumen: int = 80, silencio: bool = False, buffer: str = "normal"):
        self.modulo = cargar_mpv(carpeta_mpv)
        self.on_evento = on_evento
        self.cerrado = False
        self.fuente: Fuente | None = None
        self.nivel_buffer = buffer if buffer in OPCIONES_BUFER else "normal"
        ajuste = opciones_buffer(self.nivel_buffer)
        locale_c()
        self.mpv = self.modulo.MPV(
            wid=str(int(hwnd)), vo="gpu", hwdec="auto-safe", osc=False, osd_level=0, input_default_bindings=False, input_vo_keyboard=False,
            input_cursor=False, cursor_autohide="no", keep_open="no", ytdl=False, idle="yes", force_window="no", cache="yes",
            demuxer_max_bytes=ajuste["bytes"], demuxer_max_back_bytes="64MiB", network_timeout=60,
            demuxer_readahead_secs=ajuste["readahead"], cache_secs=ajuste["cache_secs"],
            cache_pause_wait=ajuste["espera"], cache_pause_initial=ajuste["inicial"],
            stream_buffer_size=ajuste["flujo"], stream_lavf_o="reconnect=1,reconnect_streamed=1,reconnect_delay_max=5",
            audio_client_name="Resintoniza", title="Resintoniza", terminal=False, log_handler=self._registro, loglevel="warn", volume=int(volumen), mute=bool(silencio),
            hls_bitrate="max", sub_auto="no", audio_display="no",
            # Dos ajustes del lector de flujos, los dos comprobados con emisiones reales:
            # · igndts: varias emisoras (Mediaset entre ellas) mandan el audio con
            #   marcas de tiempo imposibles (pts anterior al dts). Al reproducir no se
            #   nota, pero al grabar se rechazaban todos esos paquetes y la grabación
            #   salía sin sonido: de 96 paquetes perdidos en ocho segundos a ninguno.
            # · live_start_index: empezar unos fragmentos por detrás del directo, que
            #   es lo único que da margen de verdad en una emisión en vivo.
            demuxer_lavf_o=f"fflags=+igndts,live_start_index={ajuste['live_start_index']}",
        )
        self._estado = "detenido"
        self.paquetes_perdidos = 0
        self.parones = 0
        self._ultimo_aviso = 0.0
        self._texto_ultimo_aviso = ""
        self._ultimo_aviso_grabacion = 0.0
        self.mpv.observe_property("pause", self._on_pausa)
        self.mpv.observe_property("core-idle", self._on_idle)
        self.mpv.observe_property("track-list", self._on_pistas)
        self.mpv.observe_property("media-title", self._on_titulo)

        @self.mpv.event_callback("end-file")
        def _fin(evento):
            self._on_fin(evento)

        @self.mpv.event_callback("file-loaded")
        def _cargado(_evento):
            self._emitir("cargado", "Emisión cargada")

    # --- utilidades internas ------------------------------------------------
    def _registro(self, nivel, componente, mensaje):
        """Anota los errores de mpv y avisa a la interfaz, sin inundarla.

        En un directo, ffmpeg repite el mismo error decenas de veces por segundo
        (marcas de tiempo, fragmentos que llegan tarde…). Se guardan todos en el
        registro, pero a la barra de estado solo llega un aviso cada pocos
        segundos y traducido, que si no es imposible leer nada.
        """
        if nivel not in ("error", "fatal"):
            return
        texto = mensaje.strip()
        registro.error("[%s] %s", componente, texto)
        ahora = time.monotonic()
        if componente in ("ffmpeg", "recorder") and "packet" in texto.lower():
            self.paquetes_perdidos += 1
            if ahora - self._ultimo_aviso_grabacion < 10:
                return
            self._ultimo_aviso_grabacion = ahora
            self._emitir("grabacion_dañada", f"La emisión manda fragmentos con marcas de tiempo incorrectas: {self.paquetes_perdidos} no se han podido guardar.")
            return
        if ahora - self._ultimo_aviso < 5 and texto == self._texto_ultimo_aviso:
            return
        self._ultimo_aviso, self._texto_ultimo_aviso = ahora, texto
        self._emitir("aviso", texto)

    def _emitir(self, tipo: str, texto: str = "") -> None:
        if not self.cerrado and self.on_evento:
            try:
                self.on_evento(tipo, texto)
            except Exception:  # nunca romper el hilo de mpv
                registro.exception("Error en el aviso %s", tipo)

    def _on_pausa(self, _nombre, valor):
        if self.fuente is None:
            return
        self._estado = "pausado" if valor else "reproduciendo"
        self._emitir("estado", self.ESTADOS[self._estado])

    def _on_idle(self, _nombre, valor):
        if self.fuente is None:
            return
        if valor:
            if self._estado == "reproduciendo":
                self._estado = "cargando"
                self.parones += 1
                self._emitir("estado", "Almacenando en búfer…")
        else:
            try:
                pausado = bool(self.mpv.pause)
            except Exception:
                pausado = False
            self._estado = "pausado" if pausado else "reproduciendo"
            self._emitir("estado", self.ESTADOS[self._estado])

    def _on_pistas(self, _nombre, _valor):
        if self.fuente is not None:
            self._emitir("pistas", "")

    def _on_titulo(self, _nombre, valor):
        """Título ICY de las radios (canción en emisión); se ignoran nombres de archivo."""
        if self.fuente is None or not isinstance(valor, str) or not valor:
            return
        bajo = valor.lower()
        if bajo.startswith("http") or bajo.endswith((".m3u8", ".mpd", ".mp3", ".aac", ".ts")) or bajo in self.fuente.url.lower():
            return
        self._emitir("titulo", valor)

    def _on_fin(self, evento):
        if self.fuente is None:
            return
        try:
            datos = evento.as_dict() if hasattr(evento, "as_dict") else {}
        except Exception:
            datos = {}
        razon = datos.get("reason")
        error = datos.get("error", 0)
        if hasattr(razon, "value"):
            razon = razon.value
        if hasattr(error, "value"):
            error = error.value
        if razon == 4 or (isinstance(error, int) and error < 0):
            texto = ""
            if isinstance(error, int) and error < 0:
                try:
                    texto = self.modulo._mpv_error_string(error).decode("utf-8", "replace")
                except Exception:
                    texto = f"código {error}"
            self._estado = "error"
            self._emitir("error", texto or "La fuente no está disponible. Comprueba si están emitiendo y tu conexión a Internet.")
        elif razon == 0:
            self._estado = "detenido"
            self._emitir("fin", "La emisión ha terminado.")

    # --- control -------------------------------------------------------------
    def reproducir(self, fuente: Fuente, subtitulos: str = "off") -> None:
        self.fuente = fuente
        self._estado = "cargando"
        self.paquetes_perdidos = 0
        self.parones = 0
        self.mpv["user-agent"] = fuente.user_agent or "Mozilla/5.0"
        self.mpv["referrer"] = fuente.referer or ""
        self.mpv["http-header-fields"] = fuente.cabeceras()
        if subtitulos == "off":
            self.mpv["sid"] = "no"
            self.mpv["slang"] = ""
        else:
            self.mpv["sid"] = "auto"
            self.mpv["slang"] = IDIOMAS_SUBTITULOS.get(subtitulos, subtitulos)
        self._emitir("estado", self.ESTADOS["cargando"])
        self.mpv.play(fuente.url)

    def detener(self) -> None:
        self.fuente = None
        self._estado = "detenido"
        try:
            self.mpv.command("stop")
        except Exception:
            pass

    def pausar(self) -> bool:
        """Alterna la pausa. Devuelve True si queda en pausa."""
        if self.fuente is None:
            return False
        self.mpv.pause = not self.mpv.pause
        return bool(self.mpv.pause)

    @property
    def activo(self) -> bool:
        return self.fuente is not None

    @property
    def estado(self) -> str:
        return self._estado

    def volumen(self, valor: int) -> None:
        self.mpv.volume = max(0, min(100, int(valor)))

    def silencio(self, valor: bool) -> None:
        self.mpv.mute = bool(valor)

    def modo_imagen(self, modo: str) -> None:
        if modo == "llenar":
            self.mpv["keepaspect"] = False
            self.mpv["panscan"] = 0.0
        elif modo == "zoom":
            self.mpv["keepaspect"] = True
            self.mpv["panscan"] = 1.0
        else:
            self.mpv["keepaspect"] = True
            self.mpv["panscan"] = 0.0

    def pistas(self, tipo: str) -> list[tuple[int, str]]:
        """Pistas ``audio`` o ``sub`` como (identificador, descripción)."""
        resultado = []
        try:
            lista = self.mpv.track_list or []
        except Exception:
            return resultado
        for pista in lista:
            if pista.get("type") != tipo:
                continue
            partes = [p for p in (pista.get("title"), pista.get("lang"), pista.get("codec")) if p]
            texto = " · ".join(str(p) for p in partes) or f"Pista {pista.get('id')}"
            if pista.get("selected"):
                texto += " (activa)"
            resultado.append((int(pista.get("id")), texto))
        return resultado

    def seleccionar_pista(self, tipo: str, identificador: int | None) -> None:
        propiedad = "aid" if tipo == "audio" else "sid"
        self.mpv[propiedad] = "no" if identificador is None else int(identificador)

    def tiene_video(self) -> bool:
        try:
            return bool(self.mpv.vid) and self.mpv.vid != "no"
        except Exception:
            return False

    # --- calidad, solo audio y audiodescripción -------------------------------
    def calidad(self, valor: str) -> None:
        """Límite de calidad en las emisiones HLS con varias resoluciones (``hls-bitrate``)."""
        try:
            self.mpv["hls-bitrate"] = valor if valor in ("max", "min") else int(valor)
        except Exception:
            registro.debug("No se pudo fijar la calidad %s", valor, exc_info=True)

    def solo_audio(self, valor: bool) -> None:
        """Descarta el vídeo: ahorra datos y proceso cuando solo interesa escuchar."""
        try:
            self.mpv["vid"] = "no" if valor else "auto"
        except Exception:
            registro.debug("No se pudo cambiar el modo solo audio", exc_info=True)

    def nivelar_volumen(self, valor: bool) -> None:
        """Iguala el volumen entre canales con el filtro ``dynaudnorm`` de ffmpeg.

        Cambiar de emisora es hoy pegar un salto de volumen: unas emiten muy
        bajo y otras muy alto. Este filtro sube lo flojo y baja lo fuerte sobre
        la marcha, que es lo que hacen los «modos noche» de otros reproductores.
        """
        try:
            self.mpv["af"] = FILTRO_NIVELADOR if valor else ""
        except Exception:
            registro.debug("No se pudo cambiar el nivelador de volumen", exc_info=True)

    def velocidad(self, valor: float | None = None) -> float:
        """Lee o cambia la velocidad de reproducción (el tono se corrige solo)."""
        try:
            if valor is not None:
                self.mpv["audio-pitch-correction"] = True
                self.mpv["speed"] = max(0.25, min(4.0, float(valor)))
            return float(self.mpv.speed or 1.0)
        except Exception:
            registro.debug("No se pudo cambiar la velocidad", exc_info=True)
            return 1.0

    def desfase_audio(self, segundos: float | None = None) -> float:
        """Lee o cambia el retraso del audio respecto a la imagen (emisiones descuadradas)."""
        try:
            if segundos is not None:
                self.mpv["audio-delay"] = max(-5.0, min(5.0, float(segundos)))
            return float(self.mpv.audio_delay or 0.0)
        except Exception:
            registro.debug("No se pudo cambiar el desfase del audio", exc_info=True)
            return 0.0

    def posicion(self) -> float:
        """Segundos por los que va la reproducción (para reanudar una grabación)."""
        try:
            return float(self.mpv.time_pos or 0.0)
        except Exception:
            return 0.0

    def duracion(self) -> float:
        try:
            return float(self.mpv.duration or 0.0)
        except Exception:
            return 0.0

    def ir_a(self, segundos: float) -> bool:
        try:
            self.mpv.command("seek", str(max(0.0, float(segundos))), "absolute")
            return True
        except Exception:
            registro.debug("No se pudo saltar a la posición", exc_info=True)
            return False

    def preferir_audiodescripcion(self, valor: bool) -> None:
        """Elige la pista de audiodescripción cuando la emisión la traiga."""
        try:
            self.mpv["alang"] = IDIOMAS_AUDIODESCRIPCION if valor else ""
        except Exception:
            registro.debug("No se pudo fijar el idioma de audio preferido", exc_info=True)

    def pista_audiodescripcion(self) -> int | None:
        """Identificador de la pista que parece audiodescripción, si existe."""
        try:
            lista = self.mpv.track_list or []
        except Exception:
            return None
        marcas = ("audiodescrip", "audesc", "descripcion", "described", "visual", "-ad", "ad ")
        for pista in lista:
            if pista.get("type") != "audio":
                continue
            texto = " ".join(str(pista.get(c) or "") for c in ("title", "lang")).lower()
            if any(marca in texto for marca in marcas):
                return int(pista.get("id"))
        return None

    # --- pausa del directo (timeshift) ---------------------------------------
    def configurar_buffer(self, nivel: str) -> bool:
        """Cambia el búfer de recepción. Devuelve True si hace falta recargar la emisión.

        El tamaño del búfer y los segundos de espera se aplican al momento; dónde
        se empieza respecto al directo solo puede cambiar al volver a cargar.
        """
        nivel = nivel if nivel in OPCIONES_BUFER else "normal"
        anterior, self.nivel_buffer = self.nivel_buffer, nivel
        ajuste = opciones_buffer(nivel)
        try:
            self.mpv["demuxer-max-bytes"] = ajuste["bytes"]
            self.mpv["demuxer-readahead-secs"] = ajuste["readahead"]
            self.mpv["cache-secs"] = ajuste["cache_secs"]
            self.mpv["cache-pause-wait"] = ajuste["espera"]
            self.mpv["cache-pause-initial"] = ajuste["inicial"]
            self.mpv["stream-buffer-size"] = ajuste["flujo"]
            self.mpv["demuxer-lavf-o"] = f"fflags=+igndts,live_start_index={ajuste['live_start_index']}"
        except Exception:
            registro.debug("No se pudo cambiar el búfer", exc_info=True)
        return anterior != nivel

    def configurar_cache(self, minutos: int) -> None:
        """Guarda en memoria los últimos minutos del directo para poder retroceder."""
        segundos = max(0, min(60, int(minutos))) * 60
        try:
            self.mpv["cache"] = "yes"
            self.mpv["demuxer-max-back-bytes"] = f"{max(16, segundos * 2)}MiB"
            self.mpv["cache-secs"] = float(segundos or 10)
        except Exception:
            registro.debug("No se pudo configurar la caché del directo", exc_info=True)

    def margen_atras(self) -> float:
        """Segundos del directo que quedan guardados y a los que se puede volver."""
        try:
            return float(self.mpv.demuxer_cache_time or 0) - float(self.mpv.time_pos or 0)
        except Exception:
            return 0.0

    def retroceder(self, segundos: int) -> bool:
        """Va hacia atrás dentro de lo que hay en la caché. False si no se pudo."""
        if not self.activo:
            return False
        try:
            self.mpv.command("seek", str(-abs(int(segundos))), "relative")
            return True
        except Exception:
            registro.debug("No se pudo retroceder en el directo", exc_info=True)
            return False

    def volver_al_directo(self) -> bool:
        if not self.activo:
            return False
        try:
            self.mpv.pause = False
            self.mpv.command("seek", "100", "absolute-percent")
            return True
        except Exception:
            registro.debug("No se pudo volver al directo", exc_info=True)
            return False

    def desfase_directo(self) -> float:
        """Segundos de retraso respecto al directo (0 si se está viendo en vivo)."""
        try:
            cache = self.mpv.demuxer_cache_duration
            return float(cache) if cache else 0.0
        except Exception:
            return 0.0

    # --- estadísticas ---------------------------------------------------------
    def estadisticas(self) -> list[tuple[str, str]]:
        """Datos de la emisión en curso, para mostrarlos en un diálogo accesible.

        Las propiedades de mpv se leen como atributos (``mpv.video_codec``);
        el acceso por corchetes es solo para las opciones.
        """
        def leer(nombre, formato=str, defecto=""):
            try:
                valor = getattr(self.mpv, nombre)
            except Exception:
                return defecto
            if valor is None or valor == "":
                return defecto
            try:
                return formato(valor)
            except (TypeError, ValueError):
                return defecto

        ancho, alto = leer("width", int, 0), leer("height", int, 0)
        imagenes = leer("container_fps", float, 0.0) or leer("estimated_vf_fps", float, 0.0)
        velocidad = leer("video_bitrate", float, 0.0) + leer("audio_bitrate", float, 0.0)
        parametros = leer("audio_params", dict, {}) or {}
        canales = parametros.get("channels") or parametros.get("channel-count") or ""
        filas = [
            ("Resolución", f"{ancho} por {alto} puntos" if ancho and alto else "sin imagen"),
            ("Imágenes por segundo", f"{imagenes:.2f}" if imagenes else "no disponible"),
            ("Códec de vídeo", leer("video_codec", str, "sin vídeo")),
            ("Códec de audio", leer("audio_codec_name", str, "no disponible")),
            ("Canales de audio", str(canales) or "no disponible"),
            ("Frecuencia de audio", f"{parametros.get('samplerate')} hercios" if parametros.get("samplerate") else "no disponible"),
            ("Velocidad de la emisión", f"{velocidad / 1000:.0f} kilobits por segundo" if velocidad else "no disponible"),
            ("Búfer disponible", f"{leer('demuxer_cache_duration', float, 0.0):.1f} segundos"),
            ("Imágenes perdidas", str(leer("frame_drop_count", int, 0))),
            ("Formato del contenedor", leer("file_format", str, "no disponible")),
            ("Búfer de recepción", dict((v, n) for n, v in BUFERES).get(self.nivel_buffer, self.nivel_buffer)),
            ("Cortes desde que empezó", f"{self.parones} " + ("veces" if self.parones != 1 else "vez")),
            ("Velocidad de descarga", f"{leer('cache_speed', float, 0.0) / 1e6:.2f} megabytes por segundo" if leer("cache_speed", float, 0.0) else "no disponible"),
        ]
        if self.fuente is not None:
            filas.append(("Dirección", self.fuente.url))
        return filas

    def grabando(self) -> bool:
        try:
            return bool(self.mpv["stream-record"])
        except Exception:
            return False

    def extension_grabacion(self) -> str:
        """Contenedor que mejor admite lo que se está emitiendo, sin recodificar.

        Con emisiones HLS o MPEG-TS (la mayoría) se guarda en ``.ts``, que es una
        copia tal cual. Para lo demás, Matroska. En ``.mp4`` no se graba: falla
        al escribir la cabecera con emisiones en directo.
        """
        try:
            formato = str(self.mpv.file_format or "").lower()
        except Exception:
            formato = ""
        if "mpegts" in formato or "hls" in formato:
            return ".ts"
        return ".mkv"

    def cerrar(self) -> None:
        if self.cerrado:
            return
        self.cerrado = True
        self.fuente = None
        try:
            self.mpv.terminate()
        except Exception:
            registro.exception("Error al cerrar mpv")
