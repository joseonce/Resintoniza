"""Arranque de Resintoniza.

Uso:
    python main.py                 abre la aplicación
    python main.py --preparar      descarga libmpv a la carpeta data y termina
    python main.py --comprobar     comprueba que wxPython y libmpv funcionan
"""
from __future__ import annotations

import logging
import sys
import traceback


def preparar_extras(datos) -> None:
    """Genera lo que la aplicación necesita en data y no hay que descargar: sonidos y complemento."""
    from tdt import sonidos

    try:
        sonidos.preparar(datos)
        print(f"Avisos sonoros generados en {datos.raiz / 'sonidos'}.")
    except OSError as error:
        print(f"No se pudieron generar los sonidos: {error}")
    try:
        from tools.construir_addon import construir_addon

        print(f"Complemento de NVDA generado en {construir_addon(datos.raiz / 'bin')}.")
    except Exception as error:
        print(f"No se pudo generar el complemento de NVDA: {error}")


def preparar_datos() -> int:
    from tdt.datos import Datos, aplicar_actualizacion_pendiente, descargar_libmpv, limpiar_carpeta_mpv, ruta_libmpv

    datos = Datos()
    aplicar_actualizacion_pendiente(datos)
    limpiar_carpeta_mpv(datos)
    preparar_extras(datos)
    if ruta_libmpv(datos) and "--forzar" not in sys.argv:
        print(f"libmpv ya está en {datos.raiz / 'mpv'}. Usa --forzar para descargar la última versión.")
        return 0
    try:
        ruta, nombre = descargar_libmpv(datos, progreso=lambda mensaje, fraccion: print(mensaje))
    except Exception as error:  # se informa y se devuelve código de error
        print(f"ERROR: {error}")
        return 1
    print(f"Listo: {ruta} ({nombre})")
    return 0


def comprobar() -> int:
    """Comprueba wxPython y libmpv; escribe el resultado en data/logs/comprobacion.json."""
    import json
    from pathlib import Path

    from tdt import VERSION
    from tdt.datos import Datos, congelada, ruta_libmpv

    datos = Datos()
    informe = {"version": VERSION, "congelada": congelada(), "datos": str(datos.raiz), "correcto": False}
    try:
        import wx

        informe["wxPython"] = wx.version()
        app = wx.App(False)
        app.locale = wx.Locale(wx.LANGUAGE_SPANISH)  # misma situación que la aplicación real
        dll = ruta_libmpv(datos)
        if not dll:
            raise RuntimeError("Falta libmpv-2.dll en data/mpv. Ejecuta: python main.py --preparar")
        from tdt.reproductor import version_libmpv_cargada

        informe["libmpv"] = version_libmpv_cargada(Path(dll).parent)
        try:
            from tdt import voz

            voz.iniciar()
            informe["voz"] = "accessible_output2 disponible"
        except Exception as error:
            informe["voz"] = f"sin voz directa: {error}"
        try:
            from tdt import navegador

            informe["navegador"] = "Edge WebView2 disponible" if navegador.motor_disponible() else "sin Edge WebView2"
        except Exception as error:
            informe["navegador"] = f"error: {error}"
        try:
            import time
            import urllib.request

            from tdt.servidor import servidor

            direccion = servidor.url_youtube(video="prueba123456", titulo="Comprobación")
            pagina = ""
            for intento in range(3):
                try:
                    with urllib.request.urlopen(direccion, timeout=6) as respuesta:
                        pagina = respuesta.read().decode("utf-8")
                    break
                except OSError:
                    if intento == 2:
                        raise
                    time.sleep(0.5)
            servidor.cerrar()
            informe["reproductor_youtube"] = "correcto" if "iframe_api" in pagina else "la página no se generó bien"
        except Exception as error:
            informe["reproductor_youtube"] = f"error: {error}"
        try:
            from tdt import sonidos

            rutas = sonidos.generar(datos.raiz / "sonidos")
            informe["sonidos"] = f"{sum(1 for r in rutas if r.exists())} de {len(rutas)} avisos listos"
        except Exception as error:
            informe["sonidos"] = f"error: {error}"
        try:
            from tdt import casting

            informe["envio_tele"] = "DLNA y Fire TV siempre; Chromecast " + ("disponible" if casting.chromecast_disponible() else "no disponible")
        except Exception as error:
            informe["envio_tele"] = f"error: {error}"
        addon = datos.raiz / "bin" / "resintonizaListViewFix.nvda-addon"
        informe["complemento_nvda"] = "listo" if addon.exists() else "no generado (usa --preparar)"
        informe["grabaciones"] = str(datos.raiz / "grabaciones")
        informe["correcto"] = True
    except Exception as error:
        informe["error"] = str(error)
    (datos.raiz / "logs").mkdir(parents=True, exist_ok=True)
    (datos.raiz / "logs" / "comprobacion.json").write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    for clave, valor in informe.items():
        print(f"{clave}: {valor}")
    return 0 if informe["correcto"] else 1


def main() -> int:
    if "--preparar" in sys.argv:
        return preparar_datos()
    if "--comprobar" in sys.argv:
        return comprobar()
    from tdt.datos import Datos, aplicar_actualizacion_pendiente, configurar_registro, esperar_proceso, limpiar_carpeta_mpv, pid_a_esperar

    # Reinicio pedido por la propia aplicación (p. ej. tras descargar libmpv):
    # hay que esperar a que la instancia anterior suelte la DLL.
    anterior = pid_a_esperar(sys.argv[1:])
    if anterior is not None:
        esperar_proceso(anterior)
    datos = Datos()
    ruta_registro = configurar_registro(datos)
    if aplicar_actualizacion_pendiente(datos):
        logging.getLogger(__name__).info("Instalada la versión nueva de libmpv descargada previamente.")
    limpiar_carpeta_mpv(datos)
    from tdt import NOMBRE_APP, navegador

    # Antes de crear cualquier WebView2: perfil dentro de data y autoreproducción permitida.
    navegador.preparar_entorno(datos.raiz)
    import wx

    app = wx.App(False)
    app.SetAppName(NOMBRE_APP)
    try:
        app.locale = wx.Locale(wx.LANGUAGE_SPANISH)
    except Exception:
        pass

    def gancho_errores(tipo, error, tb):
        logging.error("Error inesperado", exc_info=(tipo, error, tb))
        detalle = "".join(traceback.format_exception_only(tipo, error)).strip()
        try:
            wx.MessageBox(f"Ha ocurrido un error inesperado:\n{detalle}\n\nLos detalles se guardan en {ruta_registro}", NOMBRE_APP, wx.OK | wx.ICON_ERROR)
        except Exception:
            pass

    sys.excepthook = gancho_errores
    from tdt import tareas
    from tdt.interfaz import VentanaPrincipal

    ventana = VentanaPrincipal(datos)
    app.SetTopWindow(ventana)
    if datos.windows.get("iniciarConWindows") and tareas.disponible():
        tareas.configurar_arranque_windows(True)

    if datos.windows.get("iniciarMinimizado"):
        if datos.windows.get("minimizarABandeja"):
            ventana.Show()
            ventana.a_bandeja()
        else:
            ventana.Iconize(True)
            ventana.Show()
    else:
        ventana.Show()

    def _confirmar_actualizacion():
        import os
        from pathlib import Path

        ready = os.environ.pop("RESINTONIZA_UPDATE_READY", None)
        if ready:
            try:
                Path(ready).write_text("ready", encoding="utf-8")
            except OSError:
                pass

    wx.CallAfter(_confirmar_actualizacion)
    app.MainLoop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
