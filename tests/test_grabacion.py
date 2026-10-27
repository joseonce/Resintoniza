"""Pruebas de la grabación: nombres de archivo, tiempos hablados y grabación en segundo plano.

No se abre libmpv: se comprueba la maquinaria que lo rodea (estado, resúmenes,
parada, gestor de varias a la vez), que es donde está la lógica.
"""
import logging
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tdt import grabacion  # noqa: E402
from tdt.widgets import fila_en_curso  # noqa: E402


class PruebaNombres(unittest.TestCase):
    def test_nombre_con_extension(self):
        nombre = grabacion.nombre_archivo("La 1", "Telediario", 1757275200.0, ".ts")
        self.assertTrue(nombre.startswith("La 1 - Telediario - "))
        self.assertTrue(nombre.endswith(".ts"))

    def test_nombre_sin_extension(self):
        """La grabación en segundo plano no sabe el contenedor hasta que carga."""
        nombre = grabacion.nombre_archivo("La 1", "", 1757275200.0, "")
        self.assertFalse(nombre.endswith("."))
        self.assertNotIn(".", nombre.split(" - ")[-1])

    def test_caracteres_prohibidos(self):
        self.assertNotIn("/", grabacion.nombre_archivo("Canal 24/7", "¿Qué? *", None, ".mkv"))


class PruebaTiempos(unittest.TestCase):
    def test_duracion(self):
        self.assertEqual(grabacion.duracion_hablada(0), "0 segundos")
        self.assertEqual(grabacion.duracion_hablada(1), "1 segundo")
        self.assertEqual(grabacion.duracion_hablada(95), "1 minuto y 35 segundos")
        self.assertEqual(grabacion.duracion_hablada(3600), "1 hora")
        self.assertEqual(grabacion.duracion_hablada(3725), "1 hora, 2 minutos y 5 segundos")

    def test_tamano(self):
        self.assertEqual(grabacion.tamano_hablado(1_500_000), "1.5 megabytes")
        self.assertIn("gigabytes", grabacion.tamano_hablado(2_000_000_000))


class PruebaGrabadorFondo(unittest.TestCase):
    """El grabador sin libmpv: nunca llega a grabar, pero se comporta."""

    def nuevo(self, **extra):
        return grabacion.GrabadorFondo("prog:tv:100:La 1", None, Path("La 1 - prueba"), Path("no-existe"),
                                       canal="La 1", titulo="Telediario", **extra)

    def test_resumen_inicial(self):
        grabador = self.nuevo(fin=time.time() + 600)
        datos = grabador.resumen()
        self.assertEqual(datos["situacion"], "preparando")
        self.assertEqual(datos["canal"], "La 1")
        self.assertEqual(datos["tamano"], 0)
        self.assertGreater(datos["restante"], 600)  # se suma el margen del final

    def test_sin_fin_no_hay_restante(self):
        self.assertIsNone(self.nuevo().resumen()["restante"])

    def test_parar_sin_mpv(self):
        grabador = self.nuevo()
        ruta, segundos, tamano = grabador.parar()
        self.assertIsNone(ruta)
        self.assertEqual(tamano, 0)
        self.assertGreaterEqual(segundos, 0)
        self.assertFalse(grabador.activa)
        self.assertEqual(grabador.situacion, "hecha")

    def test_fallo_avisa_una_vez(self):
        avisos = []
        grabador = self.nuevo()
        grabador.on_evento = lambda clave, tipo, texto: avisos.append((clave, tipo, texto))
        grabador._fallo("no hay red")
        grabador.parar()
        grabador._fallo("ya no debería avisar")
        self.assertEqual([a[1] for a in avisos], ["error"])
        self.assertEqual(grabador.situacion, "error")

    def test_arranque_sin_libmpv_da_error(self):
        avisos = []
        grabador = self.nuevo()
        grabador.on_evento = lambda clave, tipo, texto: avisos.append(tipo)
        logging.disable(logging.CRITICAL)   # el fallo se anota en el registro a propósito
        try:
            grabador._arrancar()            # la carpeta de libmpv no existe
        finally:
            logging.disable(logging.NOTSET)
        self.assertEqual(avisos, ["error"])
        self.assertEqual(grabador.situacion, "error")

    def test_formato_tv_por_defecto_y_mp4(self):
        grabador_defecto = self.nuevo()
        self.assertEqual(grabador_defecto.formato_tv, "ts")
        self.assertEqual(grabador_defecto.resumen()["formato_tv"], "ts")

        grabador_mp4 = self.nuevo(formato_tv="mp4")
        self.assertEqual(grabador_mp4.formato_tv, "mp4")
        self.assertEqual(grabador_mp4.resumen()["formato_tv"], "mp4")

    def test_extension_grabacion_formato(self):
        from unittest.mock import MagicMock
        from tdt.reproductor import Reproductor

        repro = object.__new__(Reproductor)
        repro.mpv = MagicMock()

        # Con emisión HLS
        repro.mpv.file_format = "hls"
        self.assertEqual(repro.extension_grabacion("ts"), ".ts")
        self.assertEqual(repro.extension_grabacion("mp4"), ".mp4")

        # Con emisión MPEG-TS
        repro.mpv.file_format = "mpegts"
        self.assertEqual(repro.extension_grabacion("ts"), ".ts")
        self.assertEqual(repro.extension_grabacion("mp4"), ".mp4")

        # Con emisión matroska u otro formato
        repro.mpv.file_format = "matroska,webm"
        self.assertEqual(repro.extension_grabacion("ts"), ".mkv")
        self.assertEqual(repro.extension_grabacion("mp4"), ".mkv")


class PruebaGestor(unittest.TestCase):
    def test_varias_a_la_vez_y_parada(self):
        gestor = grabacion.GestorFondo(Path("no-existe"))
        for clave in ("uno", "dos"):
            gestor.grabaciones[clave] = grabacion.GrabadorFondo(clave, None, Path(clave), Path("no-existe"), canal=clave)
        self.assertEqual(len(gestor), 2)
        self.assertTrue(gestor.activa("uno"))
        self.assertIsNotNone(gestor.parar("uno"))
        self.assertFalse(gestor.activa("uno"))
        self.assertEqual(len(gestor.resumenes()), 1)
        gestor.parar_todo()
        self.assertEqual(len(gestor), 0)

    def test_parar_lo_que_no_existe(self):
        self.assertIsNone(grabacion.GestorFondo(Path("no-existe")).parar("nada"))


class VentanaFalsa:
    """Lo justo para probar el revisor de grabaciones programadas sin abrir la interfaz."""

    from tdt.interfaz import VentanaPrincipal as _real

    _revisar_grabaciones = _real._revisar_grabaciones
    clave_programada = staticmethod(_real.clave_programada)
    modo_fondo = _real.modo_fondo

    def __init__(self, entradas, canales=("La 1",)):
        self.datos = type("Datos", (), {})()
        self.datos.windows = {"grabaciones": entradas, "grabacionSegundoPlano": True}
        self.datos.guardar = lambda: None
        self.canales = [type("Canal", (), {"tipo": "tv", "nombre": n})() for n in canales]
        self.grabador = None
        self.grabacion_programada = None
        self.grabaciones_fondo = None
        self.arrancadas, self.paradas, self.mensajes = [], [], []

    def gestor_fondo(self):
        return self.grabaciones_fondo

    def grabar_en_fondo(self, canal, **extra):
        self.arrancadas.append((canal.nombre, extra))
        return "clave"

    def parar_grabacion_fondo(self, clave, terminada=False):
        self.paradas.append((clave, terminada))
        return "parada"

    def estado(self, texto, decir=True):
        self.mensajes.append(texto)


def programada(inicio, fin, estado="pendiente", canal="La 1"):
    return {"canal": canal, "tipo": "tv", "epg_id": "", "titulo": "Programa", "inicio": int(inicio),
            "fin": int(fin), "estado": estado, "archivo": ""}


class PruebaRevisor(unittest.TestCase):
    def test_empieza_a_su_hora(self):
        ahora = time.time()
        entrada = programada(ahora, ahora + 600)
        ventana = VentanaFalsa([entrada])
        ventana._revisar_grabaciones(ahora)
        self.assertEqual(entrada["estado"], "grabando")
        self.assertEqual(ventana.arrancadas[0][0], "La 1")
        self.assertEqual(ventana.arrancadas[0][1]["fin"], entrada["fin"])

    def test_no_arranca_dos_veces(self):
        ahora = time.time()
        entrada = programada(ahora, ahora + 600)
        ventana = VentanaFalsa([entrada])
        ventana._revisar_grabaciones(ahora)
        ventana._revisar_grabaciones(ahora + 1)
        self.assertEqual(len(ventana.arrancadas), 1)

    def test_varias_solapadas_arrancan_todas(self):
        """En segundo plano sí caben a la vez; con el reproductor solo cabía una."""
        ahora = time.time()
        entradas = [programada(ahora, ahora + 600), programada(ahora, ahora + 900, canal="La 2")]
        ventana = VentanaFalsa(entradas, canales=("La 1", "La 2"))
        ventana._revisar_grabaciones(ahora)
        self.assertEqual([a[0] for a in ventana.arrancadas], ["La 1", "La 2"])

    def test_para_al_terminar(self):
        ahora = time.time()
        entrada = programada(ahora - 1000, ahora - grabacion.MARGEN_FIN - 1, estado="grabando")
        ventana = VentanaFalsa([entrada])
        ventana.grabaciones_fondo = grabacion.GestorFondo(Path("no-existe"))
        clave = ventana.clave_programada(entrada)
        ventana.grabaciones_fondo.grabaciones[clave] = grabacion.GrabadorFondo(clave, None, Path("x"), Path("no-existe"))
        ventana._revisar_grabaciones(ahora)
        self.assertEqual(entrada["estado"], "hecha")
        self.assertEqual(ventana.paradas, [(clave, True)])

    def test_caducada_sin_grabar(self):
        ahora = time.time()
        entrada = programada(ahora - 7200, ahora - 3600)
        ventana = VentanaFalsa([entrada])
        ventana._revisar_grabaciones(ahora)
        self.assertEqual(entrada["estado"], "error")
        self.assertFalse(ventana.arrancadas)

    def test_canal_que_ya_no_esta(self):
        ahora = time.time()
        entrada = programada(ahora, ahora + 600, canal="Canal fantasma")
        ventana = VentanaFalsa([entrada])
        ventana._revisar_grabaciones(ahora)
        self.assertEqual(entrada["estado"], "error")
        self.assertIn("ya no está en las listas", ventana.mensajes[0])


class PruebaFilaEnCurso(unittest.TestCase):
    def test_texto_de_la_fila(self):
        resumen = {"clave": "uno", "canal": "La 1", "titulo": "Telediario", "situacion": "grabando",
                   "transcurrido": 125, "restante": 300, "tamano": 5_000_000, "archivo": "La 1.ts",
                   "partes": 1, "inicio": time.time(), "fin": None}
        fila = fila_en_curso(resumen)
        self.assertEqual(fila["canal"], "La 1")
        self.assertEqual(fila["estado"], "Grabando")
        self.assertIn("2 minutos", fila["transcurrido"])
        self.assertIn("5 minutos", fila["restante"])
        self.assertEqual(fila["_curso"], resumen)

    def test_sin_final_y_con_varios_archivos(self):
        fila = fila_en_curso({"canal": "La 2", "titulo": "", "situacion": "reintentando", "transcurrido": 10,
                              "restante": None, "tamano": 0, "partes": 2})
        self.assertEqual(fila["restante"], "hasta que la detengas")
        self.assertIn("2 archivos", fila["estado"])
        self.assertEqual(fila["titulo"], "Grabación manual")


class PruebaGrabacionAudioMP3(unittest.TestCase):
    def test_extensiones_incluye_mp3(self):
        self.assertIn(".mp3", grabacion.EXTENSIONES)

    def test_ajustes_formato_audio(self):
        from tdt.datos import AJUSTES_WINDOWS_DEFECTO, validar_ajustes
        self.assertEqual(AJUSTES_WINDOWS_DEFECTO.get("formatoGrabacionAudio"), "defecto")
        validado = validar_ajustes({"windows": {"formatoGrabacionAudio": "192k"}})
        self.assertEqual(validado["windows"]["formatoGrabacionAudio"], "192k")
        invalido = validar_ajustes({"windows": {"formatoGrabacionAudio": "invalido"}})
        self.assertEqual(invalido["windows"]["formatoGrabacionAudio"], "defecto")

    def test_grabador_convierte_a_mp3_cuando_solo_audio(self):
        import tempfile
        from unittest.mock import MagicMock, patch

        reproductor = MagicMock()
        reproductor.activo = True
        reproductor.mpv = {}
        reproductor.carpeta_mpv = Path("mpv")
        grabador = grabacion.Grabador(reproductor)

        with tempfile.TemporaryDirectory() as tempdir:
            archivo_ts = Path(tempdir) / "prueba.ts"
            ruta_iniciada = grabador.iniciar(archivo_ts, canal="Radio 1", solo_audio=True, formato_audio="192k")
            ruta_iniciada.write_bytes(b"DATOS_DE_AUDIO_FALSOS")
            self.assertTrue(grabador.solo_audio)
            self.assertEqual(grabador.formato_audio, "192k")

            def mock_convertir(origen, destino, bitrate, carpeta_mpv):
                destino.write_bytes(b"MP3_DATOS")
                return destino

            with patch("tdt.grabacion.convertir_a_mp3", side_effect=mock_convertir) as mock_conv:
                ruta, seg, tam = grabador.parar()
                self.assertTrue(mock_conv.called)
                self.assertEqual(ruta.suffix, ".mp3")
                self.assertTrue(ruta.exists())
                self.assertFalse(ruta_iniciada.exists())


if __name__ == "__main__":
    unittest.main()

