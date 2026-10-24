"""Navegador integrado accesible (Edge WebView2) para las webs de las emisoras.

Equivale al WebView del APK. Se usa para tres cosas:

- **YouTube y Twitch**: se carga su reproductor como página principal
  (``youtube.com/embed/…``, ``twitch.tv/canal``), de modo que el elemento
  ``<video>`` está en el documento y se puede manejar con el teclado.
- **Canales que solo emiten desde su web** (marca NOEM del APK).
- Cualquier otra emisión de tipo web.

Sigue la técnica de wx-accessible-webview: el control nativo no se puede
subclasear, así que la accesibilidad se resuelve desde dentro de la página.
Un script inyectado en cada documento añade una región ``role="status"`` en
español, un puente de teclas (Escape cierra, F6 alterna barra y página, las
teclas del reproductor llegan a la aplicación) y el control del ``<video>``.

Para arrancar la emisión se imita ``ui/a.java`` del APK: si no hay ``<video>``
se pulsa el botón de reproducir de la web por clase, identificador o
``aria-label``, se aceptan los avisos de cookies y, si el reproductor está en
un marco, se abre ese marco como página principal.
"""
from __future__ import annotations

import json
import logging
import os
import webbrowser

import wx

from . import teclas as modulo_teclas, voz
from .widgets import pregunta

registro = logging.getLogger(__name__)
try:
    import wx.html2 as html2
except ImportError:  # wxPython sin WebView
    html2 = None

PUENTE = "tdt"
ESPERA_CARGA = 20000       # ms antes de avisar de que la página no responde
ESPERA_DETECCION = 22000   # ms buscando la emisión en segundo plano antes de mostrar la web
ESPERA_PUENTE = 4000       # ms entre comprobaciones de que el puente de teclas sigue vivo

# Botones de reproducción y avisos de cookies conocidos (tabla de ui/a.java del APK,
# ampliada con los reproductores web más habituales).
SELECTORES_PLAY = [
    '[aria-label="Continuar directo"]',            # Atresplayer (código 1)
    '[class*="prePlayer__playIcon"]',              # Mitele (código 10)
    ".hit-overlay",                                # Livestream (código 20)
    ".jw-icon-display", ".jwplayer .jw-display-icon-container",  # JW Player (100, 102)
    ".play-wrapper",                               # Almatelecom (código 105)
    ".vjs-big-play-button",                        # Video.js (código 111)
    ".ytp-large-play-button",                      # YouTube
    ".plyr__control--overlaid",                    # Plyr
    '[aria-label="Play"]', '[aria-label="Reproducir"]', '[title="Play"]', '[title="Reproducir"]',
    "button.play", ".btn-play", ".player-play", "#play",
]
SELECTORES_COOKIES = [
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",  # GOL (código 15)
    "#onetrust-accept-btn-handler", "#didomi-notice-agree-button",
    'button[aria-label="Aceptar"]', 'button[aria-label="Aceptar todo"]',
    "#ccc-recommended-settings", ".fc-cta-consent",
]

# Script inyectado en cada página y en cada marco: región de estado, puente de
# teclas y control del vídeo. El mapa de teclas va dentro para que llegue también
# a los marcos (el reproductor de YouTube es uno), donde no alcanza RunScript.
SCRIPT_PAGINA = r"""
window.__tdtTeclas = __TECLAS__;
window.__tdtOculto = __OCULTO__;
(function(){
  if (window.__tdt) { return 'ya'; }
  var estado = null;
  function region(){
    if (estado && document.body && document.body.contains(estado)) { return estado; }
    if (!document.body) { return null; }
    estado = document.createElement('div');
    estado.id = '__tdt_estado';
    estado.setAttribute('role', 'status');
    estado.setAttribute('aria-live', 'assertive');
    estado.setAttribute('aria-atomic', 'true');
    estado.lang = 'es';
    estado.style.cssText = 'position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;';
    document.body.appendChild(estado);
    return estado;
  }
  function puente(){
    try { return (window.__PUENTE__ && window.__PUENTE__.postMessage) ? window.__PUENTE__ : null; } catch (e) { return null; }
  }
  function enviar(datos){
    var p = puente();
    if (p) { try { p.postMessage(JSON.stringify(datos)); } catch (e) {} return; }
    // Dentro de un marco NO existe el puente con la aplicación: WebView2 solo lo
    // pone en el documento principal. Sin esto, el Escape pulsado dentro del
    // reproductor de la web se perdía y la ventana no se cerraba.
    try { if (window.top !== window) { window.top.postMessage({__tdt_puente: JSON.stringify(datos)}, '*'); } } catch (e) {}
  }
  if (window.top === window) {
    // Recogida de lo que mandan los marcos. Un marco no puede hacer aquí nada que
    // no pudiera hacer ya la propia página, así que basta con comprobar la forma.
    window.addEventListener('message', function(e){
      try {
        var texto = e && e.data ? e.data.__tdt_puente : null;
        if (typeof texto !== 'string' || texto.length > 4000) { return; }
        var datos = JSON.parse(texto);
        if (!datos || typeof datos.type !== 'string') { return; }
        var p = puente();
        if (p) { p.postMessage(texto); }
      } catch (err) {}
    }, false);
  }
  function anunciar(texto){
    var r = region();
    if (r) { r.textContent = ''; setTimeout(function(){ r.textContent = texto; }, 30); }
    enviar({type: 'estado', texto: texto});
  }
  function videos(){
    var lista = Array.prototype.slice.call(document.querySelectorAll('video'));
    var marcos = document.querySelectorAll('iframe');
    for (var i = 0; i < marcos.length; i++) {
      try { var d = marcos[i].contentDocument; if (d) { lista = lista.concat(Array.prototype.slice.call(d.querySelectorAll('video'))); } } catch (e) {}
    }
    lista.sort(function(a, b){ return (b.clientWidth * b.clientHeight) - (a.clientWidth * a.clientHeight); });
    return lista;
  }
  function video(){
    var lista = videos();
    for (var i = 0; i < lista.length; i++) { if (!lista[i].paused) { return lista[i]; } }
    return lista[0] || null;
  }
  function visible(el){
    if (!el) { return false; }
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  function pulsar(selectores){
    for (var i = 0; i < selectores.length; i++) {
      var els = document.querySelectorAll(selectores[i]);
      for (var j = 0; j < els.length; j++) {
        if (visible(els[j])) { try { els[j].click(); return selectores[i]; } catch (e) {} }
      }
    }
    return '';
  }
  function editando(e){
    var t = e.target;
    if (!t) { return false; }
    var tag = (t.tagName || '').toLowerCase();
    return t.isContentEditable || tag === 'input' || tag === 'textarea' || tag === 'select';
  }
  window.__tdt = {
    diagnostico: function(){
      var v = video();
      var marcos = [];
      var els = document.querySelectorAll('iframe');
      for (var i = 0; i < els.length; i++) { if (visible(els[i]) && els[i].src) { marcos.push(els[i].src); } }
      return JSON.stringify({video: !!v, pausado: v ? v.paused : null, videos: videos().length, marcos: marcos});
    },
    accion: function(nombre){
      var v = video();
      if (!v) { return 'sin-video'; }
      if (nombre === 'pausa') {
        if (v.paused) { var p = v.play(); if (p && p.catch) { p.catch(function(){ anunciar('El reproductor de la web no ha dejado iniciar el vídeo. Pulsa su botón de reproducir.'); }); } anunciar('Reproduciendo'); }
        else { v.pause(); anunciar('En pausa'); }
      } else if (nombre === 'detener') { v.pause(); try { v.currentTime = 0; } catch (e) {} anunciar('Detenido'); }
      else if (nombre === 'subir') { v.volume = Math.min(1, Math.round((v.volume + 0.05) * 100) / 100); v.muted = false; anunciar('Volumen ' + Math.round(v.volume * 100) + ' por ciento'); }
      else if (nombre === 'bajar') { v.volume = Math.max(0, Math.round((v.volume - 0.05) * 100) / 100); anunciar('Volumen ' + Math.round(v.volume * 100) + ' por ciento'); }
      else if (nombre === 'silencio') { v.muted = !v.muted; anunciar(v.muted ? 'Sonido silenciado' : 'Sonido activado'); }
      else if (nombre === 'estado') { anunciar((v.paused ? 'En pausa' : 'Reproduciendo') + ', volumen ' + Math.round(v.volume * 100) + ' por ciento' + (v.muted ? ', silenciado' : '')); }
      else if (nombre === 'enfocar') { try { v.setAttribute('tabindex', '0'); v.focus(); } catch (e) {} }
      return 'ok';
    },
    cookies: function(lista){ return pulsar(lista); },
    pulsarPlay: function(lista){ return pulsar(lista); },
    iniciar: function(){
      var v = video();
      if (!v) { return 'sin-video'; }
      if (v.paused) {
        var p = v.play();
        if (p && p.catch) { p.catch(function(){ enviar({type: 'sin-gesto'}); }); }
      }
      try { v.setAttribute('tabindex', '0'); v.focus(); } catch (e) {}
      return 'ok';
    },
    iniciarSiParado: function(){ var v = video(); if (v && v.paused) { try { v.play(); } catch (e) {} } },
    anunciar: anunciar
  };
  // Detección de la dirección real de la emisión: se vigilan las peticiones de la
  // página (y de sus marcos) buscando listas HLS o DASH, para poder reproducirlas
  // con el reproductor de la aplicación en lugar de dentro de la web.
  var vistos = {};
  function esFlujo(u){ return typeof u === 'string' && /\.(m3u8|mpd)([?#]|$)/i.test(u.split('#')[0]); }
  function esAnuncio(u){
    return /doubleclick|googlesyndication|googletagmanager|google-analytics|imasdk|adservice|amazon-adsystem|adnxs|adsrvr|pagead|\/ads?\/|smartadserver|sascdn|teads|criteo|conviva|permutive|omtrdc|springserve|freewheel|fwmrm|spotx|ottera/i.test(u);
  }
  function reportar(u){
    try {
      if (!esFlujo(u) || esAnuncio(u) || vistos[u]) { return; }
      var abs = new URL(u, location.href).href;
      if (vistos[abs] || esAnuncio(abs) || abs.indexOf('http') !== 0) { return; }
      vistos[u] = 1; vistos[abs] = 1;
      enviar({type: 'flujo', url: abs, pagina: location.href, origen: location.origin});
    } catch (e) {}
  }
  try {
    var fetchOriginal = window.fetch;
    if (fetchOriginal) {
      window.fetch = function (recurso) {
        try { reportar(typeof recurso === 'string' ? recurso : (recurso && recurso.url)); } catch (e) {}
        return fetchOriginal.apply(this, arguments);
      };
    }
    var abrirOriginal = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (metodo, direccion) {
      try { reportar(direccion); } catch (e) {}
      return abrirOriginal.apply(this, arguments);
    };
  } catch (e) {}
  setInterval(function () {
    try {
      var recursos = performance.getEntriesByType('resource');
      for (var i = Math.max(0, recursos.length - 80); i < recursos.length; i++) { reportar(recursos[i].name); }
      var v = document.querySelector('video');
      if (v) { reportar(v.currentSrc || v.src); }
      var fuentes = document.querySelectorAll('video source');
      for (var j = 0; j < fuentes.length; j++) { reportar(fuentes[j].src); }
      // Mientras se busca la emisión en segundo plano, la web no debe sonar.
      if (window.__tdtOculto) {
        var medios = document.querySelectorAll('video, audio');
        for (var k = 0; k < medios.length; k++) { medios[k].muted = true; medios[k].volume = 0; }
      }
      // El foco no puede quedarse dentro de un marco de otra web: allí las teclas de
      // la aplicación (F6 a la barra, Escape, las del reproductor) no llegarían.
      if (window.top === window && document.hasFocus()) {
        var activo = document.activeElement;
        if (activo && activo.tagName === 'IFRAME') {
          try { activo.blur(); } catch (e) {}
          var destino = document.getElementById('caja') || document.querySelector('video') || document.body;
          if (destino && destino.tagName !== 'IFRAME') {
            if (!destino.hasAttribute('tabindex')) { destino.setAttribute('tabindex', '-1'); }
            try { destino.focus({preventScroll: true}); } catch (e) { try { destino.focus(); } catch (e2) {} }
          }
        }
      }
    } catch (e) {}
  }, 1500);

  var NOMBRES = {'ArrowUp':'UP','ArrowDown':'DOWN','ArrowLeft':'LEFT','ArrowRight':'RIGHT','Enter':'ENTER','Escape':'ESC','Tab':'TAB','PageUp':'PGUP','PageDown':'PGDN',' ':'SPACE','Home':'HOME','End':'END','Delete':'DEL','Backspace':'BACK','Insert':'INS'};
  function combo(e){
    var t = e.key || '';
    t = NOMBRES[t] || (t.length === 1 ? t.toUpperCase() : t);
    var partes = [];
    if (e.ctrlKey) { partes.push('Ctrl'); }
    if (e.altKey) { partes.push('Alt'); }
    if (e.shiftKey) { partes.push('Shift'); }
    partes.push(t);
    return partes.join('+');
  }
  function alPulsar(e){
    if (e.__tdtVisto) { return; }
    e.__tdtVisto = 1;
    if (e.key === 'Control' || e.key === 'Alt' || e.key === 'Shift' || e.key === 'Meta') { return; }
    if (e.key === 'Escape') {
      // En pantalla completa Escape lo gasta el propio navegador en salir de ella:
      // la ventana se cierra a la segunda, que es lo que espera cualquiera.
      if (document.fullscreenElement || document.webkitFullscreenElement) { return; }
      e.preventDefault();
      enviar({type: 'cerrar'});
      return;
    }
    var mapa = window.__tdtTeclas || {};
    var accion = mapa[combo(e)];
    // Cambiar de zona (página o barra de botones) lo resuelve la aplicación.
    if (accion === '__zonas') { e.preventDefault(); enviar({type: 'barra'}); return; }
    if (editando(e) && !/^F\d{1,2}$/.test(e.key || '')) { return; }
    // Las acciones del reproductor se ejecutan AQUÍ: así cuentan como pulsación real
    // del usuario y el navegador deja iniciar el sonido (no lo permite desde fuera).
    if (accion && window.__tdt && window.__tdt.accion) {
      var r = window.__tdt.accion(accion);
      if (r === 'ok') { e.preventDefault(); return; }
    }
    var funcion = /^F\d{1,2}$/.test(e.key || '');
    if (funcion || e.ctrlKey || e.altKey) {
      var tecla = e.key.length === 1 ? e.key.toUpperCase() : e.key;
      enviar({type: 'tecla', key: tecla, ctrl: e.ctrlKey, alt: e.altKey, shift: e.shiftKey});
      if (funcion) { e.preventDefault(); }
    }
  }
  // Se escucha en la ventana ADEMÁS de en el documento: la captura de la ventana
  // va antes que la de cualquier documento, así que una web que se quede con las
  // teclas (algunos reproductores lo hacen) ya no deja la ventana sin salida.
  // La marca ``__tdtVisto`` evita atender dos veces la misma pulsación.
  window.addEventListener('keydown', alPulsar, true);
  document.addEventListener('keydown', alPulsar, true);
  document.addEventListener('click', function(){
    // Un clic del usuario también sirve para iniciar la emisión si estaba bloqueada.
    if (window.__tdt && window.__tdt.iniciarSiParado) { window.__tdt.iniciarSiParado(); }
  }, true);
  document.addEventListener('play', function(e){ if (e.target && e.target.tagName === 'VIDEO') { anunciar('Reproduciendo'); } }, true);
  document.addEventListener('pause', function(e){ if (e.target && e.target.tagName === 'VIDEO' && !e.target.ended) { anunciar('En pausa'); } }, true);
  region();
  return 'nuevo';
})();
""".replace("__PUENTE__", PUENTE)

ACCIONES_PAGINA = {"repro_pausa": "pausa", "repro_detener": "detener", "repro_subir_volumen": "subir", "repro_bajar_volumen": "bajar", "repro_silencio": "silencio", "repro_estado": "estado"}
NOMBRES_JS = {"ArrowUp": "UP", "ArrowDown": "DOWN", "ArrowLeft": "LEFT", "ArrowRight": "RIGHT", "Enter": "ENTER", "Escape": "ESC", "Tab": "TAB", "PageUp": "PGUP", "PageDown": "PGDN", " ": "SPACE", "Home": "HOME", "End": "END", "Delete": "DEL", "Backspace": "BACK", "Insert": "INS"}


def preparar_entorno(carpeta_datos=None) -> None:
    """Ajustes de WebView2. Debe hacerse antes de crear el primer navegador.

    ``--autoplay-policy`` permite que el vídeo arranque sin que el usuario haya
    hecho clic dentro de la página, que es justo lo que hace falta al abrir un
    canal desde la lista.
    """
    argumentos = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    if "autoplay-policy" not in argumentos:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (argumentos + " --autoplay-policy=no-user-gesture-required").strip()
    if carpeta_datos is not None and not os.environ.get("WEBVIEW2_USER_DATA_FOLDER"):
        carpeta = carpeta_datos / "navegador"
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
            os.environ["WEBVIEW2_USER_DATA_FOLDER"] = str(carpeta)
        except OSError as error:
            registro.warning("No se pudo preparar la carpeta del navegador: %s", error)


def script_con_teclas(mapa: dict | None = None, oculto: bool = False) -> str:
    """Script de la página con el mapa ``combinación → acción`` y si está en segundo plano."""
    return SCRIPT_PAGINA.replace("__TECLAS__", json.dumps(mapa or {})).replace("__OCULTO__", "true" if oculto else "false")


def motor_disponible() -> bool:
    return html2 is not None and html2.WebView.IsBackendAvailable(html2.WebViewBackendEdge)


def combo_desde_js(datos: dict) -> str:
    tecla = str(datos.get("key") or "")
    tecla = NOMBRES_JS.get(tecla, tecla)
    partes = []
    if datos.get("ctrl"):
        partes.append("Ctrl")
    if datos.get("alt"):
        partes.append("Alt")
    if datos.get("shift"):
        partes.append("Shift")
    partes.append(tecla)
    return modulo_teclas.normalizar("+".join(partes))


class VentanaNavegador(wx.Frame):
    """Ventana con la web de la emisora, barra de botones accesible y puente de teclas."""

    def __init__(self, parent, url: str, titulo: str, ventana_principal=None, detectar: bool = False, oculto: bool = False):
        super().__init__(parent, title=f"{titulo} · navegador integrado", size=(1100, 780))
        self.ventana_principal = ventana_principal
        self.vista = None
        self.titulo_canal = titulo
        self.cargada = False
        self.cerrandose = False
        self.intentos_play = 0
        self.url_inicial = url
        self.detectar = detectar          # buscar la dirección real de la emisión
        self.oculto = oculto and detectar  # buscarla en segundo plano, sin molestar
        self.temporizador_deteccion = None
        self.temporizador_play = None
        self.vigilante = None
        self.vigilante_teclas = None
        self.fallos_de_puente = 0
        self.reintento = False
        self.flujos: list[tuple[str, str, str]] = []
        self.flujo_usado = False
        panel = wx.Panel(self)
        caja = wx.BoxSizer(wx.VERTICAL)
        barra = wx.BoxSizer(wx.HORIZONTAL)

        def boton(etiqueta, manejador, nombre=None):
            control = wx.Button(panel, label=etiqueta)
            control.SetName(nombre or etiqueta.replace("&", ""))
            control.Bind(wx.EVT_BUTTON, manejador)
            barra.Add(control, 0, wx.RIGHT, 4)
            return control

        zonas = self.tecla_zonas()
        self.boton_pagina = boton("Ir a la &página", lambda e: self.enfocar_pagina(), f"Ir a la página. {zonas} alterna entre la barra de botones y la página")
        boton("&Reproducir el vídeo", lambda e: self.intentar_reproducir(manual=True))
        boton("Reproducir en la a&plicación", lambda e: self.usar_flujo(), "Reproducir la emisión detectada con el reproductor de la aplicación")
        boton("&Atrás", lambda e: self.vista.GoBack() if self.vista.CanGoBack() else self.anunciar("No hay página anterior"))
        boton("A&delante", lambda e: self.vista.GoForward() if self.vista.CanGoForward() else self.anunciar("No hay página siguiente"))
        boton("Re&cargar", lambda e: self.vista.Reload())
        boton("Navegador e&xterno", lambda e: self.abrir_fuera(), "Abrir esta página en el navegador externo")
        boton("&Cerrar (Escape)", lambda e: self.Close(), "Cerrar el navegador integrado. También con Escape, o con Alt más F4 si la página no responde")
        caja.Add(barra, 0, wx.ALL, 6)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        fila.Add(wx.StaticText(panel, label="Dirección:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.direccion = wx.TextCtrl(panel, value=url, style=wx.TE_READONLY)
        self.direccion.SetName("Dirección de la página")
        fila.Add(self.direccion, 1, wx.EXPAND)
        caja.Add(fila, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        self.vista = html2.WebView.New(panel, backend=html2.WebViewBackendEdge)
        if not self.vista:
            raise RuntimeError("Edge WebView2 no ha podido crear el navegador integrado.")
        self.vista.SetName(f"Página de {titulo}")
        try:
            self.vista.AddScriptMessageHandler(PUENTE)
            self.vista.Bind(html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED, self._mensaje_pagina)
            self.actualizar_script()
        except Exception as error:
            registro.warning("Sin puente de teclas en el navegador integrado: %s", error)
        self.vista.Bind(html2.EVT_WEBVIEW_NEWWINDOW, lambda e: self.vista.LoadURL(e.GetURL()))
        self.vista.Bind(html2.EVT_WEBVIEW_NAVIGATED, self._navegado)
        self.vista.Bind(html2.EVT_WEBVIEW_LOADED, self._cargado)
        self.vista.Bind(html2.EVT_WEBVIEW_ERROR, self._error)
        self.vista.Bind(html2.EVT_WEBVIEW_TITLE_CHANGED, lambda e: self.SetTitle(f"{e.GetString() or self.titulo_canal} · navegador integrado"))
        caja.Add(self.vista, 1, wx.EXPAND | wx.ALL, 6)
        caja.Add(wx.StaticText(panel, label="Estado del navegador:"), 0, wx.LEFT, 6)
        self.estado = wx.TextCtrl(panel, value="Abriendo la página…", style=wx.TE_READONLY)
        self.estado.SetName("Estado del navegador")
        caja.Add(self.estado, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        panel.SetSizer(caja)
        self.Bind(wx.EVT_CHAR_HOOK, self._teclas)
        self.Bind(wx.EVT_CLOSE, self._al_cerrar)
        self.Bind(wx.EVT_ACTIVATE, self._al_activar)
        wx.CallAfter(self.vista.LoadURL, url)
        self.vigilante = wx.CallLater(ESPERA_CARGA, self._sin_respuesta)
        if self.oculto:
            self.temporizador_deteccion = wx.CallLater(ESPERA_DETECCION, self.mostrar_ventana)

    # --- anuncios ------------------------------------------------------------------
    def anunciar(self, texto: str, decir: bool = True) -> None:
        self.estado.SetValue(texto)
        if decir:
            voz.decir(texto, interrumpir=True)

    def abrir_fuera(self):
        webbrowser.open(self.vista.GetCurrentURL() or self.url_inicial)
        self.anunciar("Página abierta en el navegador externo.")

    def _al_activar(self, evento):
        evento.Skip()
        if self.ventana_principal is not None:
            self.ventana_principal.navegador_activo = self if evento.GetActive() else None

    def _sin_respuesta(self):
        if self.cargada or self.IsBeingDeleted() or self.oculto:
            return
        self.anunciar("La página está tardando en cargar. Puedes esperar, recargar o abrirla en el navegador externo.")

    def _navegado(self, evento):
        self.direccion.SetValue(evento.GetURL())
        evento.Skip()

    def _cargado(self, evento):
        evento.Skip()
        # El script se inyecta con AddUserScript, pero no siempre llega a la primera
        # página (WebView2 se crea de forma asíncrona): se asegura en cada carga.
        puesto = self.inyectar()
        primera = not self.cargada
        self.cargada = True
        if self.vigilante is not None:
            self.vigilante.Stop()
        if primera and not self.oculto:
            principal = self.ventana_principal
            pausa = modulo_teclas.legible(principal.teclas.combo("repro_pausa")) if principal is not None else "F2"
            self.anunciar(f"Página de {self.titulo_canal} cargada. {self.tecla_zonas()} alterna entre la barra de botones y la página; Escape cierra, y Alt más F4 si la página no responde; {pausa} reproduce o pausa el vídeo.")
        if not puesto and not self.oculto:
            # Sin el script, las teclas de la aplicación no llegan: con el foco dentro
            # de Edge, wxPython no ve ni una pulsación (comprobado). Antes que dejar el
            # foco atrapado en la página, se lleva a la barra, donde Escape sí cierra.
            registro.info("El script no llegó a %s; el foco va a la barra de botones.", self.vista.GetCurrentURL())
            self.enfocar_barra()
            self.anunciar("Esta página no admite las teclas de la aplicación. Estás en la barra de botones: aquí Escape cierra el navegador, y Alt más F4 lo cierra desde cualquier sitio.")
        self.intentos_play = 0
        self._programar_play(1500, False)
        self.fallos_de_puente = 0
        self._vigilar_teclas()

    def _vigilar_teclas(self):
        """Comprueba de tanto en tanto que el puente de teclas sigue vivo, y lo repone.

        Las webs de hoy cambian de página sin recargar (y algunas reconstruyen el
        documento entero), y ahí el script se pierde sin que salte ningún aviso de
        carga. Como con el foco dentro de Edge wxPython no ve ninguna tecla, quedarse
        sin script significa quedarse sin Escape: si no se puede reponer, el foco se
        lleva a la barra de botones, que es donde las teclas sí llegan.
        """
        self.vigilante_teclas = None
        if self.cerrandose or self.IsBeingDeleted() or self.oculto or not self.IsShown():
            return
        # Hacen falta las dos mitades: el script que escucha las teclas y el puente
        # por el que se mandan. Sin puente, el script se come Escape y Ctrl+B y no
        # avisa a nadie, que es exactamente lo que pasaba tras mostrar la ventana.
        if self.inyectar() and self.puente_vivo():
            self.fallos_de_puente = 0
        else:
            self.fallos_de_puente += 1
            self._reponer_puente()   # vuelve a valer en cuanto la página navegue
            if self.fallos_de_puente == 2 and self.foco_en_pagina():
                registro.info("El puente de teclas no responde en %s; el foco va a la barra.", self.vista.GetCurrentURL())
                self.enfocar_barra()
                self.anunciar("Esta página ha dejado de admitir las teclas de la aplicación. Estás en la barra de botones: aquí Escape cierra el navegador.")
        self.vigilante_teclas = wx.CallLater(ESPERA_PUENTE, self._vigilar_teclas)

    def puente_vivo(self) -> bool:
        """True si la página tiene por dónde mandarle las teclas a la aplicación."""
        return self.ejecutar_js(f"(window.{PUENTE} && window.{PUENTE}.postMessage) ? 'si' : 'no'") == "si"

    def _error(self, evento):
        if self.vigilante is not None:
            self.vigilante.Stop()
        detalle = evento.GetString()
        if self.oculto:
            self.mostrar_ventana(f"No se pudo cargar la web de {self.titulo_canal}: {detalle}")
            return
        # La página local del reproductor puede fallar si el navegador cortó la
        # conexión: se reintenta una vez antes de dar el error por bueno.
        if "127.0.0.1" in (self.vista.GetCurrentURL() or self.url_inicial) and not self.reintento:
            self.reintento = True
            self.anunciar("Reintentando abrir el reproductor…", decir=False)
            wx.CallLater(600, lambda: self.ejecutar_js("location.reload()") if not self.cerrandose else None)
            wx.CallLater(1200, lambda: self.vista.LoadURL(self.url_inicial) if not self.cerrandose else None)
            return
        self.anunciar(f"Error al cargar la página: {detalle}. Prueba Recargar o el navegador externo.")
        evento.Skip()

    # --- teclas y puente con la página --------------------------------------------------
    def _teclas(self, evento):
        """Teclas de la ventana del navegador.

        Cuando el foco está dentro de la página, quien actúa es su propio script
        (así la pulsación cuenta como gesto del usuario): aquí solo se consume la
        tecla para que Windows no la use para otra cosa, por ejemplo F6, que de
        serie cambiaría de panel en lugar de subir el volumen.
        """
        if evento.GetKeyCode() == wx.WXK_ESCAPE and evento.GetModifiers() == wx.MOD_NONE:
            self.Close()
            return
        combo = modulo_teclas.evento_a_combo(evento)
        principal = self.ventana_principal
        if combo and principal is not None:
            en_pagina = self.foco_en_pagina()
            if combo == principal.teclas.combo("nav_zonas"):
                if not en_pagina:
                    self.alternar_foco()
                return
            # El resto de teclas del reproductor actúan sobre el vídeo de la web.
            if any(principal.teclas.combo(a) == combo for a in modulo_teclas.ACCIONES_GLOBALES):
                if not en_pagina:
                    self._tecla_desde_pagina(combo)
                return
        evento.Skip()

    def foco_en_pagina(self) -> bool:
        foco = wx.Window.FindFocus()
        if foco is None or not self.vista:
            return False
        return foco is self.vista or self.vista.IsDescendant(foco)

    def alternar_foco(self):
        """F6: ir de la página a la barra de botones y al revés."""
        if self.foco_en_pagina():
            self.enfocar_barra()
        else:
            self.enfocar_pagina()

    def enfocar_pagina(self):
        self.vista.SetFocus()
        self.anunciar(f"Página de {self.titulo_canal}. {self.tecla_zonas()} vuelve a la barra de botones; Escape cierra, y Alt más F4 si la página no responde.", decir=True)
        self.ejecutar_js("window.__tdt ? window.__tdt.accion('enfocar') : ''")

    def enfocar_barra(self):
        self.boton_pagina.SetFocus()
        self.anunciar(f"Barra de botones del navegador. Tabulador recorre los botones; {self.tecla_zonas()} vuelve a la página.")

    def ejecutar_js(self, script: str):
        # Nunca tocar el control después de cerrar: hacerlo tumba el proceso.
        if self.cerrandose or self.IsBeingDeleted() or not self.vista:
            return None
        try:
            correcto, resultado = self.vista.RunScript(script)
        except Exception:
            return None
        if not correcto:
            return None
        if isinstance(resultado, str) and resultado[:1] in ('"', "{", "["):
            try:
                return json.loads(resultado)
            except ValueError:
                return resultado
        return resultado

    def mapa_teclas(self) -> dict:
        """``combinación → acción`` de las teclas que maneja la propia página."""
        principal = self.ventana_principal
        if principal is None:
            return {}
        mapa = {}
        for accion, nombre in ACCIONES_PAGINA.items():
            combo = principal.teclas.combo(accion)
            if combo:
                mapa[combo] = nombre
        zonas = principal.teclas.combo("nav_zonas")
        if zonas:
            mapa[zonas] = "__zonas"
        return mapa

    def tecla_zonas(self) -> str:
        """Combinación legible para cambiar de zona (por defecto Ctrl+B)."""
        principal = self.ventana_principal
        combo = principal.teclas.combo("nav_zonas") if principal is not None else "Ctrl+B"
        return modulo_teclas.legible(combo or "Ctrl+B")

    def actualizar_script(self) -> None:
        """Reinstala el script (con las teclas actuales) para todas las páginas y marcos."""
        try:
            self.vista.RemoveAllUserScripts()
        except Exception:
            pass
        self._reponer_puente()
        self.vista.AddUserScript(script_con_teclas(self.mapa_teclas(), self.oculto), html2.WEBVIEW_INJECT_AT_DOCUMENT_START)

    def _reponer_puente(self) -> None:
        """Vuelve a instalar el puente con la aplicación después de borrar los scripts.

        ``RemoveAllUserScripts`` borra **todos** los scripts que se ejecutan al
        crear cada documento, y wxWidgets instala ahí el suyo: el que crea
        ``window.tdt``, por donde la página manda las teclas. Al reinstalar solo
        el script propio, la página se quedaba escuchando Escape y Ctrl+B y
        comiéndoselas (``preventDefault``) sin poder avisar a nadie. Le pasaba a
        todo canal que se abre primero en segundo plano buscando su emisión
        (los NOEM, como VEO7), porque son los que pasan por ``mostrar_ventana``.
        """
        try:
            self.vista.RemoveScriptMessageHandler(PUENTE)
        except Exception:
            pass
        try:
            if not self.vista.AddScriptMessageHandler(PUENTE):
                registro.warning("No se pudo reponer el puente de teclas del navegador.")
        except Exception:
            registro.debug("Error al reponer el puente de teclas", exc_info=True)

    def inyectar(self) -> bool:
        """Asegura que el script de accesibilidad y el mapa de teclas están en la página."""
        if self.ejecutar_js("window.__tdt ? 'si' : 'no'") != "si":
            self.ejecutar_js(script_con_teclas(self.mapa_teclas(), self.oculto))
        else:
            self.ejecutar_js("window.__tdtTeclas = " + json.dumps(self.mapa_teclas()) + "; window.__tdtOculto = " + ("true" if self.oculto else "false") + ";")
        return self.ejecutar_js("window.__tdt ? 'si' : 'no'") == "si"

    def mostrar_ventana(self, motivo: str = "") -> None:
        """Saca de segundo plano la ventana (no se encontró la emisión o hubo un error)."""
        if self.cerrandose or not self.oculto:
            return
        self.oculto = False
        if self.temporizador_deteccion is not None:
            self.temporizador_deteccion.Stop()
            self.temporizador_deteccion = None
        self.actualizar_script()
        self.Show()
        self.Raise()
        self.anunciar(motivo or f"No se ha encontrado la dirección de la emisión de {self.titulo_canal}; se abre su web.")
        # La página se recarga para que suene: mientras buscaba estaba en silencio.
        try:
            self.vista.Reload()
        except Exception:
            registro.debug("No se pudo recargar al mostrar el navegador", exc_info=True)
        self.vista.SetFocus()

    def diagnostico(self) -> dict:
        self.inyectar()
        datos = self.ejecutar_js("window.__tdt ? window.__tdt.diagnostico() : '{}'")
        if isinstance(datos, str):
            try:
                datos = json.loads(datos)
            except ValueError:
                datos = {}
        return datos if isinstance(datos, dict) else {}

    def intentar_reproducir(self, manual: bool = False) -> None:
        """Arranca la emisión como hace el APK: vídeo, botón de reproducir, cookies o marco."""
        if self.cerrandose or self.IsBeingDeleted():
            return
        self.inyectar()
        info = self.diagnostico()
        if info.get("video"):
            self.ejecutar_js("window.__tdt.iniciar()")
            if info.get("pausado"):
                self.anunciar("Reproduciendo el vídeo de la web.", decir=manual)
            elif manual:
                self.anunciar("El vídeo ya se está reproduciendo. F2 lo pausa.")
            return
        cookies = self.ejecutar_js(f"window.__tdt ? window.__tdt.cookies({json.dumps(SELECTORES_COOKIES)}) : ''")
        pulsado = self.ejecutar_js(f"window.__tdt ? window.__tdt.pulsarPlay({json.dumps(SELECTORES_PLAY)}) : ''")
        if cookies or pulsado:
            if not self.oculto:
                self.anunciar("Aceptando el aviso de la web…" if cookies and not pulsado else "Pulsando el botón de reproducir de la web…", decir=manual)
            self.intentos_play += 1
            if self.intentos_play <= 3:
                self._programar_play(2000, manual)
            return
        marcos = [m for m in info.get("marcos") or [] if m.startswith("http")]
        if marcos and manual:
            if pregunta(self, "El reproductor de esta web está dentro de un marco. ¿Quieres abrirlo directamente para poder manejarlo con el teclado?", "Reproducir el vídeo"):
                self.anunciar("Abriendo el reproductor de la web…")
                self.cargada = False
                self.vista.LoadURL(marcos[0])
            return
        if manual:
            self.anunciar("Esta página no tiene ahora mismo un vídeo que se pueda manejar con el teclado. Puede que el canal no esté emitiendo; navega por la página con el tabulador o pruébala en el navegador externo.")

    def _programar_play(self, milisegundos: int, manual: bool) -> None:
        """Reintento de arranque, guardado para poder cancelarlo al cerrar."""
        if self.temporizador_play is not None:
            self.temporizador_play.Stop()
        self.temporizador_play = wx.CallLater(milisegundos, lambda: self.intentar_reproducir(manual=manual))

    def accion_pagina(self, nombre: str) -> bool:
        """Ejecuta una acción del reproductor sobre el vídeo de la web. False si no hay vídeo."""
        self.inyectar()
        resultado = self.ejecutar_js(f"window.__tdt ? window.__tdt.accion({json.dumps(nombre)}) : 'sin-puente'")
        if resultado != "ok":
            if nombre == "pausa":
                self.intentar_reproducir(manual=True)
            else:
                self.anunciar("La página no tiene un vídeo que se pueda controlar desde el teclado.")
            return False
        return True

    def _mensaje_pagina(self, evento):
        try:
            datos = json.loads(evento.GetString())
        except (ValueError, TypeError):
            return
        tipo = datos.get("type")
        if tipo == "cerrar":
            self.Close()
        elif tipo == "barra":
            self.enfocar_barra()
        elif tipo == "estado":
            self.anunciar(str(datos.get("texto") or ""), decir=False)
        elif tipo == "sin-gesto":
            self.ejecutar_js(f"window.__tdt ? window.__tdt.pulsarPlay({json.dumps(SELECTORES_PLAY)}) : ''")
        elif tipo == "flujo":
            self._flujo_detectado(str(datos.get("url") or ""), str(datos.get("pagina") or ""), str(datos.get("origen") or ""))
        elif tipo == "tecla":
            self._tecla_desde_pagina(combo_desde_js(datos))

    def _flujo_detectado(self, url: str, pagina: str, origen: str):
        """La página ha pedido una lista HLS o DASH: es la emisión real del canal."""
        if not url or url in [f[0] for f in self.flujos]:
            return
        self.flujos.append((url, pagina, origen))
        registro.info("Emisión detectada en %s: %s", pagina, url)
        principal = self.ventana_principal
        if principal is None:
            return
        if self.detectar and not self.flujo_usado:
            self.flujo_usado = True
            if self.temporizador_deteccion is not None:
                self.temporizador_deteccion.Stop()
                self.temporizador_deteccion = None
            if not self.oculto:
                self.anunciar(f"Emisión de {self.titulo_canal} detectada; pasando al reproductor de la aplicación…")
            wx.CallAfter(principal.reproducir_flujo_detectado, url, pagina, origen, self.titulo_canal)
        else:
            self.anunciar("Emisión detectada. Pulsa el botón Reproducir en la aplicación para verla con el reproductor.", decir=False)

    def usar_flujo(self):
        """Botón: reproducir con el reproductor de la aplicación la emisión detectada."""
        principal = self.ventana_principal
        if not self.flujos:
            self.anunciar("Todavía no se ha detectado la dirección de la emisión. Inicia el vídeo en la web y espera unos segundos.")
            return
        if principal is None:
            return
        url, pagina, origen = self.flujos[-1]
        self.flujo_usado = True
        principal.reproducir_flujo_detectado(url, pagina, origen, self.titulo_canal)

    def _tecla_desde_pagina(self, combo: str):
        principal = self.ventana_principal
        if principal is None or not combo:
            return
        accion = next((a for a in modulo_teclas.ACCIONES_GLOBALES if principal.teclas.combo(a) == combo), None)
        if accion is None:
            return
        if accion in ACCIONES_PAGINA:
            if self.accion_pagina(ACCIONES_PAGINA[accion]):
                return
            if accion in ("repro_pausa", "repro_estado"):
                return
        if accion == "repro_pantalla_completa":
            self.ShowFullScreen(not self.IsFullScreen())
            self.anunciar("Pantalla completa del navegador" if self.IsFullScreen() else "Pantalla normal")
            return
        wx.CallAfter(principal.ejecutar, accion)

    # --- ciclo de vida ------------------------------------------------------------------
    def _al_cerrar(self, evento):
        """Cierre seguro.

        El control WebView2 NO se puede destruir dentro del propio mensaje de
        cierre de Windows: hacerlo cierra el proceso entero. Se oculta la
        ventana, se sueltan los enlaces del control y la destrucción se deja
        para el siguiente ciclo de eventos.
        """
        principal = self.ventana_principal
        if self.cerrandose:
            return
        self.cerrandose = True
        for temporizador in ("vigilante", "temporizador_deteccion", "temporizador_play", "vigilante_teclas"):
            actual = getattr(self, temporizador, None)
            if actual is not None:
                actual.Stop()
                setattr(self, temporizador, None)
        if principal is not None:
            if getattr(principal, "navegador", None) is self:
                principal.navegador = None
            principal.navegador_activo = None
        try:
            self.Hide()
        except Exception:
            pass
        try:
            self.vista.Unbind(html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED)
            self.vista.Unbind(html2.EVT_WEBVIEW_LOADED)
            self.vista.Unbind(html2.EVT_WEBVIEW_ERROR)
            self.vista.Unbind(html2.EVT_WEBVIEW_NAVIGATED)
            self.vista.Unbind(html2.EVT_WEBVIEW_NEWWINDOW)
            self.vista.Unbind(html2.EVT_WEBVIEW_TITLE_CHANGED)
            self.vista.RemoveAllUserScripts()
            self.vista.Stop()
        except Exception:
            registro.debug("Error al soltar el navegador", exc_info=True)
        wx.CallAfter(self._destruir, principal)

    def _destruir(self, principal):
        try:
            self.Destroy()
        except Exception:
            registro.debug("Error al destruir el navegador", exc_info=True)
        if principal is not None:
            wx.CallAfter(self._devolver_foco, principal)

    @staticmethod
    def _devolver_foco(principal):
        try:
            if not principal or principal.cerrando or not principal.IsShown():
                return
            principal.Raise()
            panel = principal.panel_activo()
            destino = panel.lista if panel is not None else principal
            if destino:
                destino.SetFocus()
            voz.decir("Navegador cerrado", interrumpir=True)
        except Exception:
            registro.debug("No se pudo devolver el foco tras cerrar el navegador", exc_info=True)

    def cargar(self, url: str, titulo: str, detectar: bool | None = None) -> None:
        self.titulo_canal = titulo
        self.cargada = False
        self.intentos_play = 0
        self.flujos = []
        self.flujo_usado = False
        if detectar is not None:
            self.detectar = detectar
        self.SetTitle(f"{titulo} · navegador integrado")
        self.vista.SetName(f"Página de {titulo}")
        self.direccion.SetValue(url)
        self.url_inicial = url
        self.anunciar(f"Abriendo {titulo}…", decir=False)
        self.vista.LoadURL(url)
        if self.vigilante is not None:
            self.vigilante.Stop()
        self.vigilante = wx.CallLater(ESPERA_CARGA, self._sin_respuesta)
        self.Raise()
        self.vista.SetFocus()


def abrir(ventana_principal, url: str, titulo: str, integrado: bool = True, detectar: bool = False, oculto: bool = False):
    """Abre ``url`` en el navegador integrado (si está disponible y se pide) o en el externo.

    Con ``detectar`` se vigila la página para encontrar la dirección real de la
    emisión y pasarla al reproductor de la aplicación.
    """
    if not integrado or not motor_disponible():
        if integrado:
            registro.warning("Edge WebView2 no disponible; se usa el navegador externo")
        webbrowser.open(url)
        return None
    preparar_entorno(getattr(getattr(ventana_principal, "datos", None), "raiz", None))
    actual = getattr(ventana_principal, "navegador", None)
    if actual is not None:
        try:
            if actual.IsBeingDeleted() or actual.cerrandose:
                raise RuntimeError("ventana cerrada")
            actual.cargar(url, titulo, detectar)
            actual.Show()
            return actual
        except (RuntimeError, AttributeError):
            registro.info("El navegador anterior ya no existe; se crea uno nuevo.")
            ventana_principal.navegador = None
    try:
        ventana = VentanaNavegador(ventana_principal, url, titulo, ventana_principal, detectar, oculto)
    except Exception as error:
        registro.exception("No se pudo abrir el navegador integrado")
        ventana_principal.navegador = None
        if pregunta(ventana_principal, f"No se pudo abrir el navegador integrado: {error}\n\n¿Quieres abrir la página en el navegador de Windows?", "Navegador integrado", wx.ICON_WARNING):
            webbrowser.open(url)
        return None
    ventana_principal.navegador = ventana
    if not ventana.oculto:
        ventana.Show()
        ventana.vista.SetFocus()
    return ventana
