"""Servidor local mínimo para el reproductor de YouTube.

El reproductor incrustado de YouTube exige un origen ``http(s)`` válido: si se
navega directamente a ``youtube.com/embed/…`` responde «Error de configuración
del reproductor de vídeo». El APK lo resuelve sirviendo su propia página desde
un origen virtual (``https://appassets.androidplatform.net``) y usando la API
de iframe de YouTube.

Aquí se hace igual con un servidor que solo escucha en ``127.0.0.1``, en un
puerto que asigna el sistema, y que sirve una única página en español con el
reproductor y los controles de teclado de la aplicación.
"""
from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

registro = logging.getLogger(__name__)
RUTA = "/reproductor"

PAGINA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>__TITULO__</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%; background: #000; color: #fff;
               font-family: system-ui, Segoe UI, Arial, sans-serif; }
  h1 { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  #caja, #reproductor { width: 100vw; height: 100vh; border: 0; }
  #caja iframe, #reproductor { display: block; }
  #aviso { padding: 16px; font-size: 1.1rem; }
  :focus { outline: 3px solid Highlight; outline-offset: 2px; }
</style>
</head>
<body>
<h1>__TITULO__</h1>
<!-- La API de YouTube sustituye #reproductor por su marco, así que el foco vive en
     #caja: dentro del marco las teclas de la aplicación no llegarían. -->
<div id="caja" tabindex="0" role="application" aria-label="__TITULO__"><div id="reproductor"></div></div>
<p id="aviso" hidden></p>
<script>
(function () {
  var listo = false, pendiente = true, reproductor = null;
  function base() { return window.__tdt || {}; }
  function decir(texto) {
    var b = base();
    if (b.anunciar) { b.anunciar(texto); }
    var aviso = document.getElementById('aviso');
    if (aviso) { aviso.hidden = false; aviso.textContent = texto; }
  }
  function estado() {
    try { return reproductor && reproductor.getPlayerState ? reproductor.getPlayerState() : -1; } catch (e) { return -1; }
  }
  function sonando() { var e = estado(); return e === 1 || e === 3; }  // reproduciendo o cargando
  function sonido() {
    // Quita el silencio con el que hay que arrancar. Devuelve true si ya suena.
    try {
      if (!reproductor.isMuted()) { return true; }
      reproductor.unMute();
      reproductor.setVolume(100);
      return !reproductor.isMuted();
    } catch (e) { return false; }
  }
  function volumen() {
    try { return Math.round(reproductor.getVolume()); } catch (e) { return 100; }
  }
  function conectar() {
    var anterior = base();
    window.__tdt = {
      anunciar: anterior.anunciar || function () {},
      diagnostico: function () {
        return JSON.stringify({video: !!reproductor, pausado: !sonando(), videos: reproductor ? 1 : 0, marcos: [], youtube: true, estado: estado()});
      },
      iniciar: function () { try { reproductor.playVideo(); } catch (e) {} return 'ok'; },
      iniciarSiParado: function () { if (!sonando()) { try { reproductor.playVideo(); } catch (e) {} } },
      cookies: anterior.cookies || function () { return ''; },
      pulsarPlay: anterior.pulsarPlay || function () { return ''; },
      accion: function (nombre) {
        if (!reproductor) { return 'sin-video'; }
        try {
          if (nombre === 'pausa') {
            if (sonando()) { reproductor.pauseVideo(); decir('En pausa'); }
            else { reproductor.playVideo(); decir('Reproduciendo'); }
          } else if (nombre === 'detener') { reproductor.stopVideo(); decir('Detenido'); }
          else if (nombre === 'subir') { var s = Math.min(100, volumen() + 5); reproductor.unMute(); reproductor.setVolume(s); decir('Volumen ' + s + ' por ciento'); }
          else if (nombre === 'bajar') { var b = Math.max(0, volumen() - 5); reproductor.setVolume(b); decir('Volumen ' + b + ' por ciento'); }
          else if (nombre === 'silencio') {
            if (reproductor.isMuted()) { reproductor.unMute(); decir('Sonido activado'); }
            else { reproductor.mute(); decir('Sonido silenciado'); }
          } else if (nombre === 'estado') {
            decir((sonando() ? 'Reproduciendo' : 'En pausa') + ', volumen ' + volumen() + ' por ciento' + (reproductor.isMuted() ? ', silenciado' : ''));
          } else if (nombre === 'enfocar') {
            // El foco se queda en NUESTRA página, nunca dentro del marco de YouTube:
            // dentro del marco las teclas no llegan a la aplicación (F6, Escape…).
            var caja = document.getElementById('caja');
            if (caja) { caja.focus(); }
          }
        } catch (e) { return 'sin-video'; }
        return 'ok';
      }
    };
  }
  function crear() {
    var opciones = {
      // YouTube solo arranca solo si empieza en silencio; en cuanto suena se le quita
      // el silencio (el navegador lo permite: la aplicación desactiva el bloqueo de
      // reproducción automática, igual que el APK con setMediaPlaybackRequiresUserGesture).
      playerVars: {autoplay: 1, mute: 1, controls: 1, fs: 1, rel: 0, modestbranding: 1, playsinline: 1,
                   iv_load_policy: 3, hl: 'es', cc_lang_pref: 'es', origin: window.location.origin},
      events: {
        onReady: function (evento) {
          conectar();
          try { evento.target.playVideo(); } catch (e) {}
          decir('Reproductor de YouTube listo. F2 pausa o reanuda; F5 y F6 cambian el volumen; Escape cierra.');
          setTimeout(function () {
            if (!sonando()) { decir('Pulsa F2 para empezar a ver ' + document.title + '.'); }
            else if (!sonido()) { decir('Reproduciendo sin sonido: pulsa F9 para activarlo.'); }
            else { decir('Reproduciendo ' + document.title + '.'); }
          }, 4000);
          try {
            var marco = evento.target.getIframe();
            if (marco) {
              marco.setAttribute('title', '__TITULO__');
              marco.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
              // Fuera del recorrido del tabulador: si el foco entra en el marco, las
              // teclas de la aplicación (F6, F2, Escape) dejan de funcionar.
              marco.setAttribute('tabindex', '-1');
            }
            var caja = document.getElementById('caja');
            if (caja) { caja.focus(); }
          } catch (e) {}
        },
        onStateChange: function (evento) {
          if (evento.data === 1) {
            if (sonido()) { decir('Reproduciendo'); }
          } else if (evento.data === 2) { decir('En pausa'); }
          else if (evento.data === 0) { decir('La emisión ha terminado'); }
        },
        onError: function (evento) {
          decir('YouTube no puede reproducir esta emisión (código ' + evento.data + '). Prueba el navegador externo.');
        }
      }
    };
    __ORIGEN__
    reproductor = new YT.Player('reproductor', opciones);
  }
  window.onYouTubeIframeAPIReady = function () { listo = true; if (pendiente) { crear(); } };
  conectar();
  var etiqueta = document.createElement('script');
  etiqueta.src = 'https://www.youtube.com/iframe_api';
  document.head.appendChild(etiqueta);
})();
</script>
</body>
</html>
"""


def _pagina(video: str, canal: str, titulo: str) -> str:
    if canal:
        origen = "opciones.videoId = 'live_stream'; opciones.playerVars.channel = " + repr(canal).replace("'", '"') + ";"
    else:
        origen = "opciones.videoId = " + repr(video).replace("'", '"') + ";"
    return PAGINA.replace("__ORIGEN__", origen).replace("__TITULO__", titulo.replace("<", "").replace(">", "").replace('"', ""))


class _Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 (nombre impuesto por http.server)
        partes = urlparse(self.path)
        if partes.path.rstrip("/") != RUTA:
            self.send_error(404)
            return
        consulta = parse_qs(partes.query)
        video = (consulta.get("video") or [""])[0]
        canal = (consulta.get("canal") or [""])[0]
        titulo = (consulta.get("titulo") or ["Reproductor de YouTube"])[0]
        if not _identificador_valido(video) or not _identificador_valido(canal) or (not video and not canal):
            self.send_error(400)
            return
        cuerpo = _pagina(video, canal, titulo[:120]).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(cuerpo)
            self.wfile.flush()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            registro.debug("El navegador cerró la conexión antes de recibir la página")
        self.close_connection = True

    def log_message(self, formato, *args):  # silencia la salida por consola
        registro.debug("servidor local: " + formato, *args)

    def handle_one_request(self):
        # El navegador cierra las conexiones en espera; no es un error que deba salir por consola.
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    def log_error(self, formato, *args):
        registro.debug("servidor local: " + formato, *args)


def _identificador_valido(valor: str) -> bool:
    return all(c.isalnum() or c in "-_" for c in valor)


class _Servidor(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def handle_error(self, request, direccion):  # no sacar trazas por consola
        registro.debug("Error atendiendo a %s", direccion, exc_info=True)


class ServidorLocal:
    """Servidor en 127.0.0.1 que sirve la página del reproductor de YouTube."""

    def __init__(self):
        self.servidor: _Servidor | None = None
        self.puerto = 0

    def iniciar(self) -> int:
        if self.servidor is not None:
            return self.puerto
        self.servidor = _Servidor(("127.0.0.1", 0), _Manejador)
        self.puerto = self.servidor.server_address[1]
        threading.Thread(target=self.servidor.serve_forever, name="ServidorTDT", daemon=True).start()
        registro.info("Servidor local del reproductor en 127.0.0.1:%s", self.puerto)
        return self.puerto

    def url_youtube(self, video: str = "", canal: str = "", titulo: str = "Reproductor de YouTube") -> str:
        from urllib.parse import urlencode

        puerto = self.iniciar()
        datos = {"titulo": titulo}
        if video:
            datos["video"] = video
        if canal:
            datos["canal"] = canal
        return f"http://127.0.0.1:{puerto}{RUTA}?{urlencode(datos)}"

    def cerrar(self) -> None:
        if self.servidor is not None:
            try:
                self.servidor.shutdown()
                self.servidor.server_close()
            except Exception:
                registro.debug("Error al cerrar el servidor local", exc_info=True)
            self.servidor = None


servidor = ServidorLocal()
