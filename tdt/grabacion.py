"""Grabar la emisión que se está viendo y programar grabaciones desde la guía.

libmpv tiene una propiedad, ``stream-record``, que escribe en un archivo los
mismos datos que ya está descargando para reproducir: no hay que volver a
bajar nada ni recodificar, y el archivo resultante (Matroska) se abre con
cualquier reproductor. Aquí se envuelve esa propiedad y se lleva la cuenta de
las grabaciones programadas, que se guardan en los ajustes junto a los
recordatorios.

Hay dos maneras de grabar:

* ``Grabador`` graba **lo que está sonando**, con el reproductor de la
  aplicación. Es lo más barato (no se descarga nada dos veces), pero ocupa el
  reproductor: cambiar de canal o detener corta la grabación.
* ``GrabadorFondo`` abre **su propia instancia de libmpv**, sin imagen ni
  sonido (``vo=null``, ``ao=null`` y silencio), en hilos aparte. No toca el
  reproductor principal, así que se puede escuchar un canal mientras se graban
  otros, y pausar o parar lo que se escucha no afecta a la grabación.
  ``GestorFondo`` lleva varias a la vez.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

registro = logging.getLogger(__name__)
EXTENSION = ".mkv"
EXTENSIONES = (".ts", ".mkv", ".mp4")  # lo que se reconoce como grabación en la carpeta
PROHIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MARGEN_INICIO = 30       # segundos que se empieza antes de la hora
MARGEN_FIN = 120         # segundos que se sigue grabando después
ESTADOS = {"pendiente": "Pendiente", "grabando": "Grabando", "hecha": "Terminada", "error": "Con error"}
# Grabación en segundo plano: si el directo se corta, se vuelve a intentar y se
# sigue en un archivo nuevo, en vez de perder lo que quedaba por grabar.
REINTENTOS_FONDO = 20
ESPERA_REINTENTO = 8.0
DIAS_HISTORIAL = 90      # cuánto se conservan las programadas ya hechas (para no repetirlas)
DIAS_REGLAS = 8          # hasta dónde miran las reglas en la guía
MEGAS_POR_MINUTO = 22    # medido con emisiones reales en alta definición
MEGAS_POR_MINUTO_AUDIO = 2.1  # midiendo lo mismo sin vídeo


def carpeta(datos) -> Path:
    """Carpeta donde se guardan las grabaciones (se crea si hace falta)."""
    personalizada = (datos.windows.get("carpetaGrabaciones") or "").strip()
    ruta = Path(personalizada) if personalizada else datos.raiz / "grabaciones"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def limpiar(texto: str, maximo: int = 60) -> str:
    """Convierte un nombre en algo que Windows admita como archivo."""
    limpio = PROHIBIDOS.sub(" ", (texto or "").strip())
    limpio = re.sub(r"\s+", " ", limpio).strip(" .")
    return (limpio or "grabacion")[:maximo].strip()


def nombre_archivo(canal: str, titulo: str = "", momento: float | None = None, extension: str = EXTENSION) -> str:
    """``La 1 - Telediario - 20260907-2100.ts``.

    La extensión decide el contenedor: con emisiones HLS o MPEG-TS conviene
    ``.ts``, que guarda lo que llega tal cual (ver ``Reproductor.extension_grabacion``).
    """
    marca = time.strftime("%Y%m%d-%H%M", time.localtime(momento or time.time()))
    partes = [limpiar(canal, 40)]
    if titulo:
        partes.append(limpiar(titulo, 60))
    partes.append(marca)
    # Con ``extension`` vacía se devuelve el nombre a secas: así lo pide la
    # grabación en segundo plano, que no sabe el contenedor hasta que carga.
    sufijo = "" if not extension else (extension if extension.startswith(".") else "." + extension)
    return " - ".join(partes) + sufijo


def ruta_libre(destino: Path) -> Path:
    """Evita pisar una grabación anterior con el mismo nombre."""
    if not destino.exists():
        return destino
    for numero in range(2, 100):
        candidata = destino.with_name(f"{destino.stem} ({numero}){destino.suffix}")
        if not candidata.exists():
            return candidata
    return destino.with_name(f"{destino.stem} {int(time.time())}{destino.suffix}")


class Grabador:
    """Graba lo que suena ahora mismo usando ``stream-record`` de libmpv."""

    def __init__(self, reproductor):
        self.reproductor = reproductor
        self.ruta: Path | None = None
        self.inicio: float = 0.0
        self.canal: str = ""

    @property
    def activa(self) -> bool:
        return self.ruta is not None

    def iniciar(self, destino: Path, canal: str = "") -> Path:
        """Empieza a grabar en ``destino``. Lanza RuntimeError si no se puede."""
        if self.activa:
            raise RuntimeError("Ya hay una grabación en marcha.")
        if self.reproductor is None or not self.reproductor.activo:
            raise RuntimeError("No hay ninguna emisión en reproducción.")
        destino = ruta_libre(Path(destino))
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.reproductor.mpv["stream-record"] = str(destino)
        except Exception as error:
            raise RuntimeError(f"El reproductor no pudo empezar a grabar: {error}") from error
        self.ruta, self.inicio, self.canal = destino, time.time(), canal
        registro.info("Grabación iniciada en %s", destino)
        return destino

    def parar(self) -> tuple[Path | None, float, int]:
        """Detiene la grabación. Devuelve (archivo, segundos, bytes)."""
        if not self.activa:
            return None, 0.0, 0
        ruta, inicio = self.ruta, self.inicio
        self.ruta, self.inicio, self.canal = None, 0.0, ""
        try:
            self.reproductor.mpv["stream-record"] = ""
        except Exception:
            registro.debug("No se pudo cerrar stream-record", exc_info=True)
        tamano = 0
        try:
            tamano = ruta.stat().st_size if ruta and ruta.exists() else 0
        except OSError:
            tamano = 0
        registro.info("Grabación detenida: %s (%s bytes)", ruta, tamano)
        return ruta, time.time() - inicio, tamano

    def estado(self) -> str:
        if not self.activa:
            return "No se está grabando."
        segundos = int(time.time() - self.inicio)
        try:
            mega = (self.ruta.stat().st_size / 1e6) if self.ruta.exists() else 0.0
        except OSError:
            mega = 0.0
        return f"Grabando {self.canal or 'la emisión'} desde hace {segundos // 60} minutos y {segundos % 60} segundos, {mega:.1f} megabytes."


# --- grabación en segundo plano ---------------------------------------------
def duracion_hablada(segundos: float) -> str:
    """``95`` → «1 minuto y 35 segundos»; pensado para leerlo en voz alta."""
    segundos = max(0, int(segundos))
    horas, resto = divmod(segundos, 3600)
    minutos, restantes = divmod(resto, 60)
    partes = []
    if horas:
        partes.append(f"{horas} hora" + ("s" if horas != 1 else ""))
    if minutos:
        partes.append(f"{minutos} minuto" + ("s" if minutos != 1 else ""))
    if restantes or not partes:
        partes.append(f"{restantes} segundo" + ("s" if restantes != 1 else ""))
    return " y ".join(partes) if len(partes) < 3 else f"{partes[0]}, {partes[1]} y {partes[2]}"


def tamano_hablado(bytes_: int) -> str:
    if bytes_ >= 1e9:
        return f"{bytes_ / 1e9:.2f} gigabytes"
    return f"{bytes_ / 1e6:.1f} megabytes"


class GrabadorFondo:
    """Graba un canal con una instancia propia de libmpv, sin verlo ni oírlo.

    Se abre un libmpv aparte con ``vo=null`` y ``ao=null``: descarga la emisión
    y la escribe con ``stream-record``, pero no dibuja nada ni suena. Todo pasa
    en los hilos de esa instancia, así que el reproductor principal queda libre
    y lo que se haga con él (pausar, cambiar de canal, detener) no le afecta.

    Los avisos llegan por ``on_evento(clave, tipo, texto)`` desde hilos de mpv:
    quien lo use debe pasarlos por ``wx.CallAfter``.
    """

    def __init__(self, clave: str, fuente, base: Path, carpeta_mpv: Path, on_evento=None, canal: str = "",
                 titulo: str = "", calidad: str = "max", nivel_buffer: str = "normal", fin: float | None = None,
                 resolver=None, solo_audio: bool = False):
        self.clave = clave
        self.fuente = fuente                 # proveedores.Fuente con la dirección y las cabeceras
        self.base = Path(base)               # ruta sin extensión: el contenedor se decide al cargar
        self.carpeta_mpv = Path(carpeta_mpv)
        self.on_evento = on_evento
        self.canal, self.titulo = canal, titulo
        self.calidad, self.nivel_buffer = calidad, nivel_buffer
        self.fin = fin                       # hora prevista de final (grabaciones programadas)
        self.solo_audio = bool(solo_audio)   # sin vídeo: ocupa una décima parte (medido: 2,1 MB/min frente a 22)
        self.resolver = resolver             # devuelve una Fuente nueva al reintentar (direcciones que caducan)
        self.inicio = time.time()
        self.archivos: list[Path] = []       # una grabación puede continuar en otro archivo tras un corte
        self.situacion = "preparando"        # preparando, grabando, reintentando, hecha, error
        self.error = ""
        self.reintentos = 0
        self.mpv = None
        self._modulo = None
        self._parada = False
        self._cerrojo = threading.RLock()
        self._espera: threading.Timer | None = None

    # --- ciclo de vida --------------------------------------------------------
    def iniciar(self) -> None:
        """Arranca en un hilo aparte: crear libmpv tarda y no debe colgar la interfaz."""
        threading.Thread(target=self._arrancar, name=f"grabacion-{self.clave}", daemon=True).start()

    def _arrancar(self) -> None:
        from .reproductor import cargar_mpv, locale_c, opciones_buffer

        try:
            modulo = cargar_mpv(self.carpeta_mpv)
            locale_c()
            ajuste = opciones_buffer(self.nivel_buffer)
            instancia = modulo.MPV(
                vo="null", ao="null", mute=True, volume=0, osc=False, osd_level=0, terminal=False,
                input_default_bindings=False, input_vo_keyboard=False, input_cursor=False,
                keep_open="no", ytdl=False, idle="yes", force_window="no", cache="yes", hwdec="no",
                demuxer_max_bytes=ajuste["bytes"], demuxer_max_back_bytes="32MiB", network_timeout=60,
                demuxer_readahead_secs=ajuste["readahead"], cache_secs=ajuste["cache_secs"],
                cache_pause_wait=ajuste["espera"], cache_pause_initial=ajuste["inicial"],
                stream_buffer_size=ajuste["flujo"], stream_lavf_o="reconnect=1,reconnect_streamed=1,reconnect_delay_max=5",
                audio_client_name="Resintoniza", title="Resintoniza (grabando)", log_handler=self._registro, loglevel="warn",
                hls_bitrate=self.calidad or "max", sub_auto="no", audio_display="no",
                # Con ``vid=no`` el archivo sale con la pista de audio y nada más:
                # comprobado, 0,68 MB en 20 segundos frente a 10 MB con imagen.
                vid="no" if self.solo_audio else "auto",
                # Mismo arreglo que en el reproductor: sin ``igndts`` las emisiones
                # que mandan el audio con marcas imposibles se graban sin sonido.
                demuxer_lavf_o=f"fflags=+igndts,live_start_index={ajuste['live_start_index']}",
            )
        except Exception as error:  # noqa: BLE001 (cualquier fallo al abrir libmpv)
            registro.exception("No se pudo abrir el grabador en segundo plano")
            self._fallo(f"no se pudo abrir un reproductor para grabar: {error}")
            return
        with self._cerrojo:
            if self._parada:
                _terminar(instancia)
                return
            self.mpv, self._modulo = instancia, modulo

        @instancia.event_callback("file-loaded")
        def _cargado(_evento):  # hilo de mpv
            self._cargado()

        @instancia.event_callback("end-file")
        def _fin(evento):       # hilo de mpv
            self._fin_de_archivo(evento)

        self._cargar_fuente()

    def _cargar_fuente(self) -> None:
        """Manda a libmpv la dirección actual con sus cabeceras."""
        with self._cerrojo:
            instancia, fuente = self.mpv, self.fuente
            if instancia is None or self._parada or fuente is None:
                return
        try:
            instancia["user-agent"] = fuente.user_agent or "Mozilla/5.0"
            instancia["referrer"] = fuente.referer or ""
            instancia["http-header-fields"] = fuente.cabeceras()
            instancia["sid"] = "no"
            instancia.play(fuente.url)
        except Exception as error:  # noqa: BLE001
            self._fallo(f"no se pudo abrir la emisión: {error}")

    def _cargado(self) -> None:
        """La emisión ya está abierta: se elige el contenedor y empieza a escribir."""
        with self._cerrojo:
            instancia = self.mpv
            if instancia is None or self._parada:
                return
            try:
                formato = str(instancia.file_format or "").lower()
            except Exception:
                formato = ""
            extension = ".ts" if ("mpegts" in formato or "hls" in formato) else EXTENSION
            destino = ruta_libre(self.base.with_name(self.base.name + extension))
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
                instancia["stream-record"] = str(destino)
            except Exception as error:  # noqa: BLE001
                self._fallo(f"no se pudo escribir en {destino.name}: {error}")
                return
            self.archivos.append(destino)
            self.situacion = "grabando"
            self.error = ""
        registro.info("Grabación en segundo plano de %s en %s", self.canal, destino)
        self._avisar("grabando", destino.name)

    def _fin_de_archivo(self, evento) -> None:
        """La emisión se ha cortado: se reintenta y se sigue en otro archivo."""
        with self._cerrojo:
            if self._parada:
                return
        try:
            datos = evento.as_dict() if hasattr(evento, "as_dict") else {}
        except Exception:
            datos = {}
        razon, error = datos.get("reason"), datos.get("error", 0)
        razon = getattr(razon, "value", razon)
        error = getattr(error, "value", error)
        # Valores de libmpv: 0 fin de la emisión, 2 parada, 3 salida, 4 error, 5 redirección.
        if razon in (2, 3, 5):  # se cerró desde aquí, o mpv sigue solo con otra dirección
            return
        texto = ""
        if isinstance(error, int) and error < 0 and self._modulo is not None:
            try:
                texto = self._modulo._mpv_error_string(error).decode("utf-8", "replace")
            except Exception:
                texto = f"código {error}"
        self._reintentar_luego(texto or "la emisión se ha cortado")

    def _reintentar_luego(self, motivo: str) -> None:
        with self._cerrojo:
            if self._parada:
                return
            if self.reintentos >= REINTENTOS_FONDO:
                self._fallo(f"la emisión se cortó demasiadas veces ({motivo})")
                return
            self.reintentos += 1
            self.situacion = "reintentando"
            self.error = motivo
            intento = self.reintentos
            try:
                self.mpv["stream-record"] = ""   # cierra bien lo grabado hasta ahora
            except Exception:
                registro.debug("No se pudo cerrar stream-record al reintentar", exc_info=True)
            self._espera = threading.Timer(ESPERA_REINTENTO, self._reintentar)
            self._espera.daemon = True
            self._espera.start()
        self._avisar("reintento", f"{motivo}; se reintenta en {int(ESPERA_REINTENTO)} segundos (intento {intento}).")

    def _reintentar(self) -> None:
        with self._cerrojo:
            if self._parada or self.mpv is None:
                return
        if self.resolver is not None:
            try:
                fuente = self.resolver()
            except Exception:  # noqa: BLE001
                registro.debug("No se pudo volver a resolver la emisión", exc_info=True)
                fuente = None
            if fuente is not None:
                self.fuente = fuente
        self._cargar_fuente()

    def _fallo(self, texto: str) -> None:
        with self._cerrojo:
            if self._parada:
                return
            self.situacion, self.error = "error", texto
        self._avisar("error", texto)

    def parar(self) -> tuple[Path | None, float, int]:
        """Cierra el archivo y apaga su libmpv. Devuelve (archivo, segundos, bytes)."""
        with self._cerrojo:
            ya_parada = self._parada
            self._parada = True
            instancia, self.mpv = self.mpv, None
            espera, self._espera = self._espera, None
            if self.situacion not in ("error",):
                self.situacion = "hecha"
        if espera is not None:
            espera.cancel()
        if instancia is not None:
            try:
                instancia["stream-record"] = ""   # cierra el archivo antes de medirlo
            except Exception:
                registro.debug("No se pudo cerrar stream-record", exc_info=True)
            # ``terminate`` espera a los hilos de mpv: se hace aparte para no colgar la interfaz.
            threading.Thread(target=_terminar, args=(instancia,), daemon=True).start()
        segundos = time.time() - self.inicio if not ya_parada else 0.0
        return (self.archivos[-1] if self.archivos else None), segundos, self.tamano()

    # --- consulta -------------------------------------------------------------
    @property
    def activa(self) -> bool:
        return not self._parada

    def tamano(self) -> int:
        total = 0
        for ruta in self.archivos:
            try:
                total += ruta.stat().st_size
            except OSError:
                continue
        return total

    def nombres(self) -> str:
        return ", ".join(r.name for r in self.archivos)

    def resumen(self, ahora: float | None = None) -> dict:
        """Lo que enseña el diálogo de grabaciones: cuánto lleva, cuánto le queda y cuánto ocupa."""
        ahora = ahora or time.time()
        restante = None if self.fin is None else max(0, (self.fin + MARGEN_FIN) - ahora)
        return {
            "clave": self.clave, "canal": self.canal, "titulo": self.titulo, "situacion": self.situacion,
            "transcurrido": max(0.0, ahora - self.inicio), "restante": restante, "tamano": self.tamano(),
            "archivo": self.archivos[-1].name if self.archivos else "", "error": self.error,
            "partes": len(self.archivos), "inicio": self.inicio, "fin": self.fin, "solo_audio": self.solo_audio,
        }

    def estado(self) -> str:
        datos = self.resumen()
        if datos["situacion"] == "error":
            return f"La grabación de {self.canal or 'la emisión'} falló: {self.error}."
        if datos["situacion"] == "preparando":
            return f"Preparando la grabación de {self.canal or 'la emisión'}."
        if datos["situacion"] == "reintentando":
            return f"La grabación de {self.canal or 'la emisión'} se ha cortado y se está reanudando."
        texto = f"Grabando {self.canal or 'la emisión'} en segundo plano desde hace {duracion_hablada(datos['transcurrido'])}, {tamano_hablado(datos['tamano'])}"
        if datos["restante"] is not None:
            texto += f"; quedan {duracion_hablada(datos['restante'])}"
        return texto + "."

    def _avisar(self, tipo: str, texto: str) -> None:
        if self.on_evento is None:
            return
        try:
            self.on_evento(self.clave, tipo, texto)
        except Exception:  # nunca romper el hilo de mpv
            registro.exception("Error en el aviso %s de la grabación en segundo plano", tipo)

    def _registro(self, nivel, componente, mensaje):
        if nivel in ("error", "fatal"):
            registro.error("[grabación %s] [%s] %s", self.clave, componente, mensaje.strip())


def _terminar(instancia) -> None:
    try:
        instancia.terminate()
    except Exception:
        registro.debug("Error al cerrar el libmpv de la grabación", exc_info=True)


class GestorFondo:
    """Todas las grabaciones en segundo plano que hay en marcha, por clave."""

    def __init__(self, carpeta_mpv: Path, on_evento=None):
        self.carpeta_mpv = Path(carpeta_mpv)
        self.on_evento = on_evento
        self.grabaciones: dict[str, GrabadorFondo] = {}

    def iniciar(self, clave: str, fuente, base: Path, canal: str = "", titulo: str = "", calidad: str = "max",
                nivel_buffer: str = "normal", fin: float | None = None, resolver=None,
                solo_audio: bool = False) -> GrabadorFondo:
        if clave in self.grabaciones:
            raise RuntimeError("Esa grabación ya está en marcha.")
        grabador = GrabadorFondo(clave, fuente, base, self.carpeta_mpv, self.on_evento, canal, titulo,
                                 calidad, nivel_buffer, fin, resolver, solo_audio)
        self.grabaciones[clave] = grabador
        grabador.iniciar()
        return grabador

    def activa(self, clave: str) -> bool:
        return clave in self.grabaciones

    def obtener(self, clave: str) -> GrabadorFondo | None:
        return self.grabaciones.get(clave)

    def parar(self, clave: str) -> tuple[Path | None, float, int] | None:
        grabador = self.grabaciones.pop(clave, None)
        if grabador is None:
            return None
        return grabador.parar()

    def parar_todo(self) -> list[tuple[str, Path | None]]:
        paradas = []
        for clave in list(self.grabaciones):
            grabador = self.grabaciones.pop(clave)
            ruta, _segundos, _tamano = grabador.parar()
            paradas.append((clave, ruta))
        return paradas

    def resumenes(self, ahora: float | None = None) -> list[dict]:
        ahora = ahora or time.time()
        return [g.resumen(ahora) for g in self.grabaciones.values()]

    def __len__(self) -> int:
        return len(self.grabaciones)


# --- grabaciones programadas ------------------------------------------------
def nueva_programada(canal, programa, minutos_antes: int = 0, minutos_despues: int = 0, regla: str = "") -> dict:
    return {
        "canal": canal.nombre, "tipo": canal.tipo, "epg_id": canal.epg_id, "titulo": programa.titulo,
        "inicio": int(programa.inicio) - minutos_antes * 60, "fin": int(programa.fin) + minutos_despues * 60,
        "estado": "pendiente", "archivo": "", "episodio": getattr(programa, "episodio", "") or "", "regla": regla,
    }


def validar_programadas(valor) -> list[dict]:
    """Filtra la lista guardada en los ajustes dejando solo entradas con sentido."""
    limpias = []
    for entrada in valor if isinstance(valor, list) else []:
        if not isinstance(entrada, dict):
            continue
        if not all(isinstance(entrada.get(c), str) for c in ("canal", "titulo", "tipo")):
            continue
        inicio, fin = entrada.get("inicio"), entrada.get("fin")
        if not isinstance(inicio, int) or not isinstance(fin, int) or fin <= inicio:
            continue
        limpias.append({
            "canal": entrada["canal"], "tipo": entrada["tipo"], "epg_id": str(entrada.get("epg_id") or ""),
            "titulo": entrada["titulo"], "inicio": inicio, "fin": fin,
            "estado": entrada.get("estado") if entrada.get("estado") in ESTADOS else "pendiente",
            "archivo": str(entrada.get("archivo") or ""), "episodio": str(entrada.get("episodio") or ""),
            "regla": str(entrada.get("regla") or ""),
        })
    return limpias


def podar_programadas(entradas: list[dict], ahora: float | None = None, dias: int = DIAS_HISTORIAL) -> int:
    """Quita del historial lo que ya pasó hace mucho. Devuelve cuántas se han quitado.

    Las terminadas se conservan un tiempo a propósito: son las que permiten
    saber si un programa ya se grabó cuando una regla vuelve a encontrarlo.
    """
    ahora = ahora or time.time()
    limite = ahora - dias * 86400
    sobran = [e for e in entradas if e.get("estado") in ("hecha", "error") and e["fin"] < limite]
    for entrada in sobran:
        entradas.remove(entrada)
    return len(sobran)


def toca_empezar(entrada: dict, ahora: float) -> bool:
    return entrada.get("estado") == "pendiente" and entrada["inicio"] - MARGEN_INICIO <= ahora < entrada["fin"]


def toca_parar(entrada: dict, ahora: float) -> bool:
    return entrada.get("estado") == "grabando" and ahora >= entrada["fin"] + MARGEN_FIN


def caducada(entrada: dict, ahora: float) -> bool:
    """Programada que ya pasó sin llegar a grabarse (la aplicación estaba cerrada)."""
    return entrada.get("estado") == "pendiente" and ahora >= entrada["fin"]


def listar(datos) -> list[dict]:
    return sorted(datos.windows.get("grabaciones") or [], key=lambda g: g["inicio"])


def archivos(datos) -> list[dict]:
    """Grabaciones que hay en la carpeta, de la más reciente a la más antigua."""
    salida = []
    protegidas = set(datos.windows.get("grabacionesProtegidas") or [])
    for ruta in sorted(carpeta(datos).rglob("*")):
        if not ruta.is_file() or ruta.suffix.lower() not in EXTENSIONES:
            continue
        try:
            info = ruta.stat()
        except OSError:
            continue
        salida.append({"nombre": ruta.stem, "ruta": ruta, "tamano": info.st_size, "fecha": info.st_mtime,
                       "protegida": ruta.name in protegidas})
    salida.sort(key=lambda g: g["fecha"], reverse=True)
    return salida


# --- márgenes, espacio en disco y carpetas ----------------------------------
def margenes(datos, canal: str = "") -> tuple[int, int]:
    """Minutos de más al empezar y al terminar: los generales o los de ese canal."""
    windows = datos.windows
    antes, despues = int(windows.get("margenAntes", 0) or 0), int(windows.get("margenDespues", 2) or 0)
    propios = (windows.get("margenesCanal") or {}).get(canal)
    if isinstance(propios, list) and len(propios) == 2:
        try:
            antes, despues = int(propios[0]), int(propios[1])
        except (TypeError, ValueError):
            pass
    return max(0, min(60, antes)), max(0, min(60, despues))


def validar_margenes_canal(valor) -> dict:
    limpio = {}
    for nombre, margen in (valor or {}).items() if isinstance(valor, dict) else []:
        if not isinstance(nombre, str) or not isinstance(margen, list) or len(margen) != 2:
            continue
        try:
            antes, despues = int(margen[0]), int(margen[1])
        except (TypeError, ValueError):
            continue
        limpio[nombre] = [max(0, min(60, antes)), max(0, min(60, despues))]
    return limpio


def espacio_libre(datos) -> float:
    """Gigabytes libres en la unidad donde se graba."""
    try:
        return shutil.disk_usage(carpeta(datos)).free / 1e9
    except OSError:
        return 0.0


def hay_espacio(datos) -> tuple[bool, float]:
    """(¿se puede grabar?, gigabytes libres). El mínimo se elige en Ajustes."""
    libre = espacio_libre(datos)
    minimo = float(datos.windows.get("minimoLibreGB", 2) or 0)
    return (libre >= minimo or minimo <= 0), libre


def tamano_estimado(segundos: float, solo_audio: bool = False) -> float:
    """Megabytes que ocupará más o menos una grabación de esa duración."""
    return (segundos / 60.0) * (MEGAS_POR_MINUTO_AUDIO if solo_audio else MEGAS_POR_MINUTO)


def destino_de(datos, canal: str, titulo: str = "", momento: float | None = None) -> Path:
    """Ruta (sin extensión) donde va una grabación, creando la subcarpeta si toca."""
    base = carpeta(datos)
    if datos.windows.get("carpetaPorPrograma") and (titulo or canal):
        base = base / limpiar(titulo or canal, 60)
        base.mkdir(parents=True, exist_ok=True)
    return base / nombre_archivo(canal, titulo, momento, extension="")


def ejecutar_orden_posterior(orden: str, ruta: Path) -> bool:
    """Lanza la orden que haya puesto la persona al terminar una grabación.

    ``%f`` se sustituye por la ruta del archivo. No se espera a que termine y
    todo lo que diga va al registro: es cosa suya, aquí solo se lanza.
    """
    orden = (orden or "").strip()
    if not orden:
        return False
    linea = orden.replace("%f", str(ruta))
    try:
        subprocess.Popen(linea, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        registro.info("Orden posterior lanzada: %s", linea)
        return True
    except Exception:
        registro.exception("No se pudo lanzar la orden posterior")
        return False


# --- retención: qué se borra solo -------------------------------------------
def sobrantes(datos, ahora: float | None = None) -> list[dict]:
    """Grabaciones que las reglas de limpieza dejarían fuera (las protegidas nunca).

    Tres reglas, que se pueden combinar: más antiguas que X días, dejar solo las
    N últimas de cada programa y no pasar de Y gigabytes en la carpeta.
    """
    ahora = ahora or time.time()
    windows = datos.windows
    dias = int(windows.get("retencionDias", 0) or 0)
    por_programa = int(windows.get("retencionPorPrograma", 0) or 0)
    gigas = float(windows.get("retencionGigas", 0) or 0)
    todos = [a for a in archivos(datos) if not a["protegida"]]
    fuera: list[dict] = []

    def marcar(archivo):
        if archivo not in fuera:
            fuera.append(archivo)

    if dias > 0:
        for archivo in todos:
            if ahora - archivo["fecha"] > dias * 86400:
                marcar(archivo)
    if por_programa > 0:
        por_nombre: dict[str, list[dict]] = {}
        for archivo in todos:
            por_nombre.setdefault(nombre_programa(archivo["nombre"]), []).append(archivo)
        for lista in por_nombre.values():
            for archivo in sorted(lista, key=lambda a: a["fecha"], reverse=True)[por_programa:]:
                marcar(archivo)
    if gigas > 0:
        total = sum(a["tamano"] for a in archivos(datos)) / 1e9
        for archivo in sorted(todos, key=lambda a: a["fecha"]):
            if total <= gigas:
                break
            if archivo not in fuera:
                marcar(archivo)
            total -= archivo["tamano"] / 1e9
    return fuera


def nombre_programa(nombre: str) -> str:
    """De «La 1 - Telediario - 20260908-2100» saca «La 1 - Telediario»."""
    partes = nombre.split(" - ")
    if len(partes) >= 2 and re.fullmatch(r"\d{8}-\d{4}(\s\(\d+\))?", partes[-1].strip()):
        partes = partes[:-1]
    return " - ".join(partes).strip() or nombre


def limpiar_carpeta(datos, ahora: float | None = None) -> list[str]:
    """Borra lo que sobra según las reglas de limpieza. Devuelve los nombres borrados."""
    borradas = []
    for archivo in sobrantes(datos, ahora):
        try:
            archivo["ruta"].unlink()
            borradas.append(archivo["ruta"].name)
        except OSError:
            registro.warning("No se pudo borrar %s", archivo["ruta"])
    if borradas:
        registro.info("Limpieza de grabaciones: %s", ", ".join(borradas))
    return borradas


# --- reglas de grabación automática -----------------------------------------
# Las repeticiones se controlan como en Tvheadend: o se graba todo, o se salta
# lo que ya se grabó (por episodio, por título, o una vez por semana).
REPETICIONES = {
    "todas": "Grabar todas las emisiones",
    "episodio": "No repetir el mismo episodio",
    "titulo": "Grabarlo solo la primera vez",
    "semana": "Como mucho una vez por semana",
}
CAMPOS_REGLA = {"titulo": "Solo en el título", "todo": "En el título y en la descripción"}


def regla_nueva(texto: str = "", canal: str = "", tipo: str = "tv") -> dict:
    return {
        "texto": texto, "campo": "titulo", "canal": canal, "tipo": tipo, "soloFavoritos": False,
        "repeticiones": "episodio", "antes": 2, "despues": 5, "activa": True, "dias": [],
        "desde": "", "hasta": "", "maximo": 0,
    }


def validar_reglas(valor) -> list[dict]:
    limpias = []
    for regla in valor if isinstance(valor, list) else []:
        if not isinstance(regla, dict) or not isinstance(regla.get("texto"), str) or not regla["texto"].strip():
            continue
        dias = [d for d in (regla.get("dias") or []) if isinstance(d, int) and 0 <= d <= 6]
        limpias.append({
            "texto": regla["texto"].strip(),
            "campo": regla.get("campo") if regla.get("campo") in CAMPOS_REGLA else "titulo",
            "canal": str(regla.get("canal") or ""), "tipo": regla.get("tipo") if regla.get("tipo") in ("tv", "radio") else "tv",
            "soloFavoritos": bool(regla.get("soloFavoritos")),
            "repeticiones": regla.get("repeticiones") if regla.get("repeticiones") in REPETICIONES else "episodio",
            "antes": max(0, min(60, int(regla.get("antes", 2) or 0))),
            "despues": max(0, min(60, int(regla.get("despues", 5) or 0))),
            "activa": bool(regla.get("activa", True)), "dias": sorted(set(dias)),
            "desde": _hora_valida(regla.get("desde")), "hasta": _hora_valida(regla.get("hasta")),
            "maximo": max(0, min(50, int(regla.get("maximo", 0) or 0))),
        })
    return limpias


def _hora_valida(texto) -> str:
    if not isinstance(texto, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", texto.strip()):
        return ""
    return texto.strip()


def texto_regla(regla: dict) -> str:
    """Descripción de la regla en una línea, para la lista y para leerla en voz alta."""
    partes = [f"«{regla['texto']}»"]
    partes.append("en el título y la descripción" if regla["campo"] == "todo" else "en el título")
    partes.append(f"en {regla['canal']}" if regla["canal"] else ("solo en favoritos" if regla["soloFavoritos"] else "en todos los canales"))
    if regla["dias"]:
        partes.append("los " + ", ".join(DIAS_SEMANA[d] for d in regla["dias"]))
    if regla["desde"] or regla["hasta"]:
        partes.append(f"entre las {regla['desde'] or '00:00'} y las {regla['hasta'] or '23:59'}")
    partes.append(REPETICIONES[regla["repeticiones"]].lower())
    return ". ".join(partes) + "."


DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _plegar(texto: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", (texto or "").casefold()) if not unicodedata.combining(c))


def coincide_regla(regla: dict, canal, programa, favorito: bool = False) -> bool:
    """¿Este programa de este canal cumple la regla?"""
    if not regla.get("activa", True):
        return False
    if regla.get("tipo") and canal.tipo != regla["tipo"]:
        return False
    if regla["canal"] and canal.nombre != regla["canal"]:
        return False
    if regla["soloFavoritos"] and not favorito:
        return False
    buscado = _plegar(regla["texto"])
    donde = _plegar(programa.titulo)
    if regla["campo"] == "todo":
        donde += " " + _plegar(getattr(programa, "descripcion", "")) + " " + _plegar(getattr(programa, "subtitulo", ""))
    if buscado not in donde:
        return False
    momento = time.localtime(programa.inicio)
    if regla["dias"] and momento.tm_wday not in regla["dias"]:
        return False
    if regla["desde"] or regla["hasta"]:
        minutos = momento.tm_hour * 60 + momento.tm_min
        desde = _minutos(regla["desde"], 0)
        hasta = _minutos(regla["hasta"], 24 * 60 - 1)
        dentro = desde <= minutos <= hasta if desde <= hasta else (minutos >= desde or minutos <= hasta)
        if not dentro:
            return False
    return True


def _minutos(hora: str, defecto: int) -> int:
    if not hora:
        return defecto
    h, m = hora.split(":")
    return int(h) * 60 + int(m)


def es_repeticion(regla: dict, entradas: list[dict], canal, programa) -> bool:
    """¿Ya se grabó (o está programado) algo que esta regla considera lo mismo?"""
    modo = regla.get("repeticiones", "episodio")
    if modo == "todas":
        return False
    titulo = _plegar(programa.titulo)
    episodio = _plegar(getattr(programa, "episodio", ""))
    for entrada in entradas:
        if _plegar(entrada.get("titulo", "")) != titulo:
            continue
        if modo == "titulo":
            return True
        if modo == "semana" and abs(entrada["inicio"] - programa.inicio) < 7 * 86400:
            return True
        if modo == "episodio":
            if not episodio and not entrada.get("episodio"):
                # Sin datos de episodio, dos emisiones del mismo título el mismo
                # día son la misma cosa (la reposición de la tarde, por ejemplo).
                if abs(entrada["inicio"] - programa.inicio) < 86400:
                    return True
            elif _plegar(entrada.get("episodio", "")) == episodio:
                return True
    return False


def ya_programado(entradas: list[dict], canal, programa) -> bool:
    return any(e["canal"] == canal.nombre and abs(e["inicio"] - programa.inicio) < 300 and
               _plegar(e.get("titulo", "")) == _plegar(programa.titulo) for e in entradas)


def programadas_de_reglas(reglas: list[dict], candidatos, entradas: list[dict], ahora: float | None = None,
                          dias: int = DIAS_REGLAS) -> list[dict]:
    """Programadas nuevas que salen de las reglas.

    ``candidatos`` es una lista de ``(canal, programas, favorito)``. No se toca
    lo que ya está programado ni lo que la regla considere una repetición.
    """
    ahora = ahora or time.time()
    limite = ahora + dias * 86400
    nuevas: list[dict] = []
    for regla in reglas:
        if not regla.get("activa", True):
            continue
        puestas = sum(1 for e in entradas if e.get("regla") == regla["texto"] and e.get("estado") == "pendiente")
        for canal, programas, favorito in candidatos:
            for programa in programas:
                if programa.inicio <= ahora or programa.inicio > limite:
                    continue
                if not coincide_regla(regla, canal, programa, favorito):
                    continue
                if ya_programado(entradas + nuevas, canal, programa) or es_repeticion(regla, entradas + nuevas, canal, programa):
                    continue
                if regla["maximo"] and puestas >= regla["maximo"]:
                    break
                nuevas.append(nueva_programada(canal, programa, regla["antes"], regla["despues"], regla["texto"]))
                puestas += 1
    return nuevas


# --- conflictos --------------------------------------------------------------
def conflictos(entradas: list[dict], maximo: int, ahora: float | None = None) -> list[list[dict]]:
    """Grupos de programadas que se solapan por encima de lo que se puede grabar a la vez."""
    ahora = ahora or time.time()
    pendientes = [e for e in entradas if e.get("estado") in ("pendiente", "grabando") and e["fin"] > ahora]
    grupos = []
    for entrada in pendientes:
        solapan = [otra for otra in pendientes if otra["inicio"] < entrada["fin"] and entrada["inicio"] < otra["fin"]]
        if len(solapan) > maximo:
            clave = sorted(id(s) for s in solapan)
            if clave not in [sorted(id(s) for s in g) for g in grupos]:
                grupos.append(sorted(solapan, key=lambda e: e["inicio"]))
    return grupos


# --- recortar una grabación --------------------------------------------------
def recortable(ruta: Path) -> bool:
    """Solo los ``.ts`` se pueden recortar sin recodificar (son paquetes sueltos)."""
    return Path(ruta).suffix.lower() == ".ts"


def recortar(ruta: Path, inicio: float, fin: float, carpeta_mpv: Path, destino: Path | None = None) -> Path:
    """Copia el trozo entre ``inicio`` y ``fin`` (segundos) a un archivo nuevo.

    Este libmpv no admite ``--ovc=copy``, así que no se recodifica: se aprovecha
    que un MPEG-TS son paquetes de 188 bytes. Se busca cada tiempo con mpv, se
    lee ``stream-pos`` (el byte por el que iba) y se copia ese trozo tal cual.
    Comprobado: de un archivo de 21 segundos, el corte 5–12 da 7 segundos que se
    reproducen con imagen y sonido.
    """
    from .reproductor import cargar_mpv, locale_c

    ruta = Path(ruta)
    if not recortable(ruta):
        raise RuntimeError("Solo se pueden recortar las grabaciones en formato .ts.")
    if fin <= inicio:
        raise RuntimeError("El final tiene que ir después del principio.")
    modulo = cargar_mpv(carpeta_mpv)
    locale_c()
    instancia = modulo.MPV(vo="null", ao="null", terminal=False, log_handler=lambda *a: None, pause=True, hr_seek="yes")
    try:
        instancia.play(str(ruta))
        _esperar_carga(instancia)
        bytes_inicio = _byte_en(instancia, inicio)
        bytes_fin = _byte_en(instancia, fin)
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(f"No se pudo leer la grabación: {error}") from error
    finally:
        try:
            instancia.terminate()
        except Exception:
            pass
    bytes_inicio -= bytes_inicio % 188
    bytes_fin -= bytes_fin % 188
    if bytes_fin <= bytes_inicio:
        raise RuntimeError("El trozo elegido no tiene datos.")
    destino = ruta_libre(Path(destino) if destino else ruta.with_name(f"{ruta.stem} (recorte){ruta.suffix}"))
    with open(ruta, "rb") as entrada, open(destino, "wb") as salida:
        entrada.seek(bytes_inicio)
        quedan = bytes_fin - bytes_inicio
        while quedan > 0:
            trozo = entrada.read(min(1 << 20, quedan))
            if not trozo:
                break
            salida.write(trozo)
            quedan -= len(trozo)
    registro.info("Recorte de %s: %s (%s a %s segundos)", ruta.name, destino.name, inicio, fin)
    return destino


def _esperar_carga(instancia, segundos: float = 30.0) -> None:
    """Espera a que el archivo esté abierto (en pausa no vale ``wait_until_playing``)."""
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        try:
            if instancia.duration:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("la grabación no se ha podido abrir")


def _byte_en(instancia, segundos: float) -> int:
    instancia.command("seek", str(max(0.0, float(segundos))), "absolute", "exact")
    time.sleep(1.2)
    return int(instancia.stream_pos or 0)


def duracion_de(ruta: Path, carpeta_mpv: Path) -> float:
    """Duración en segundos de una grabación guardada (para recortarla o reanudarla)."""
    from .reproductor import cargar_mpv, locale_c

    modulo = cargar_mpv(carpeta_mpv)
    locale_c()
    instancia = modulo.MPV(vo="null", ao="null", terminal=False, log_handler=lambda *a: None, pause=True)
    try:
        instancia.play(str(ruta))
        _esperar_carga(instancia)
        return float(instancia.duration or 0)
    except Exception:
        return 0.0
    finally:
        try:
            instancia.terminate()
        except Exception:
            pass
