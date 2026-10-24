"""Pruebas del envío a la tele: DLNA, Chromecast y Fire TV."""
import unittest

from tdt import casting


def aparato(clase, nombre="Salón", anfitrion="192.168.1.50", control="http://192.168.1.50/ctl", modelo=""):
    return casting.Dispositivo(nombre, clase, control=control if clase == "dlna" else "", anfitrion=anfitrion, modelo=modelo)


class PruebaTipoContenido(unittest.TestCase):
    def test_segun_la_direccion(self):
        self.assertEqual(casting.tipo_contenido("https://x/live/master.m3u8?a=1"), "application/x-mpegURL")
        self.assertEqual(casting.tipo_contenido("https://x/grabacion.ts"), "video/mp2t")
        self.assertEqual(casting.tipo_contenido("https://x/radio.mp3"), "audio/mpeg")
        self.assertEqual(casting.tipo_contenido("https://x/manifest.mpd"), "application/dash+xml")
        self.assertEqual(casting.tipo_contenido("https://x/algo"), "video/mp4")


class PruebaDispositivos(unittest.TestCase):
    def test_tipos_legibles(self):
        self.assertEqual(aparato("dlna").tipo_legible, "DLNA")
        self.assertEqual(aparato("chromecast").tipo_legible, "Chromecast")
        self.assertEqual(aparato("dial").tipo_legible, "Fire TV o Android TV")

    def test_quien_admite_envio(self):
        self.assertTrue(aparato("dlna").admite_envio)
        self.assertTrue(aparato("chromecast").admite_envio)
        self.assertFalse(aparato("dial").admite_envio)

    def test_texto_de_la_lista(self):
        texto = str(aparato("dial", nombre="Fire TV de casa", modelo="AFTT"))
        self.assertIn("Fire TV de casa", texto)
        self.assertIn("no acepta enlaces directos", texto)
        self.assertNotIn("no acepta", str(aparato("dlna")))

    def test_instrucciones_para_fire_tv(self):
        texto = casting.instrucciones(aparato("dial", nombre="Fire TV de casa", modelo="AFTT"))
        self.assertIn("Fire TV", texto)
        self.assertIn("DLNA", texto)
        self.assertIn("Duplicar la pantalla", texto)

    def test_instrucciones_para_otro_televisor(self):
        texto = casting.instrucciones(aparato("dial", nombre="Televisor del salón"))
        self.assertIn("televisor", texto)


class PruebaBusqueda(unittest.TestCase):
    def setUp(self):
        self.originales = (casting.buscar_dlna, casting.buscar_chromecast, casting.buscar_dial)

    def tearDown(self):
        casting.buscar_dlna, casting.buscar_chromecast, casting.buscar_dial = self.originales

    def test_junta_los_tres_tipos_y_ordena(self):
        casting.buscar_dlna = lambda espera=0: [aparato("dlna", "Televisor Sony", "192.168.1.10")]
        casting.buscar_chromecast = lambda espera=0: [casting.Dispositivo("Chromecast cocina", "chromecast", anfitrion="192.168.1.20", identificador="uno")]
        casting.buscar_dial = lambda espera=0: [aparato("dial", "Fire TV", "192.168.1.30")]
        encontrados = casting.buscar(0.1)
        self.assertEqual(len(encontrados), 3)
        # Los que aceptan la emisión van primero.
        self.assertTrue(encontrados[0].admite_envio and encontrados[1].admite_envio)
        self.assertFalse(encontrados[-1].admite_envio)

    def test_un_aparato_que_responde_dos_veces_no_se_repite(self):
        # El mismo televisor por DLNA y por DIAL: manda el que acepta la emisión.
        casting.buscar_dlna = lambda espera=0: [aparato("dlna", "Televisor", "192.168.1.10")]
        casting.buscar_chromecast = lambda espera=0: []
        casting.buscar_dial = lambda espera=0: [aparato("dial", "Televisor", "192.168.1.10")]
        encontrados = casting.buscar(0.1)
        self.assertEqual([d.clase for d in encontrados], ["dlna"])

    def test_sin_aparatos(self):
        casting.buscar_dlna = casting.buscar_chromecast = casting.buscar_dial = lambda espera=0: []
        self.assertEqual(casting.buscar(0.1), [])


class PruebaEnvio(unittest.TestCase):
    def test_no_se_envia_a_lo_que_no_lo_admite(self):
        self.assertFalse(casting.enviar(aparato("dial"), "http://x/y.m3u8", "Canal"))
        self.assertFalse(casting.parar(aparato("dial")))

    def test_dlna_manda_las_dos_ordenes(self):
        llamadas = []
        original = casting._soap
        casting._soap = lambda control, accion, cuerpo: llamadas.append((accion, cuerpo)) or True
        try:
            self.assertTrue(casting.enviar(aparato("dlna"), "http://x/y.m3u8", "La 1"))
        finally:
            casting._soap = original
        self.assertEqual([a for a, _c in llamadas], ["SetAVTransportURI", "Play"])
        self.assertIn("http://x/y.m3u8", llamadas[0][1])
        self.assertIn("La 1", llamadas[0][1])

    def test_dlna_avisa_si_falla(self):
        original = casting._soap
        casting._soap = lambda *a, **k: False
        try:
            self.assertFalse(casting.enviar(aparato("dlna"), "http://x/y.m3u8", "La 1"))
        finally:
            casting._soap = original

    def test_chromecast_usa_su_biblioteca(self):
        enviados = []

        class ControlFalso:
            def play_media(self, url, tipo, title="", stream_type=""):
                enviados.append((url, tipo, title, stream_type))

            def block_until_active(self, timeout=0):
                pass

        class AparatoFalso:
            media_controller = ControlFalso()

            def wait(self, timeout=0):
                pass

        original = casting._aparato_chromecast
        casting._aparato_chromecast = lambda dispositivo: AparatoFalso()
        try:
            self.assertTrue(casting.enviar(casting.Dispositivo("Salón", "chromecast", anfitrion="1.2.3.4"), "http://x/y.m3u8", "La 1"))
        finally:
            casting._aparato_chromecast = original
        self.assertEqual(enviados[0][0], "http://x/y.m3u8")
        self.assertEqual(enviados[0][1], "application/x-mpegURL")
        self.assertEqual(enviados[0][3], "LIVE")

    def test_chromecast_disponible(self):
        # La biblioteca es una dependencia de la aplicación: debe estar.
        self.assertTrue(casting.chromecast_disponible())


if __name__ == "__main__":
    unittest.main()
