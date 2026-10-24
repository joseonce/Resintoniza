import gzip
import tempfile
import time
import unittest
from pathlib import Path

from tdt import catalogo, extractor


class Extractor(unittest.TestCase):
    def test_identificadores(self):
        self.assertEqual(extractor.canal_twitch("https://player.twitch.tv/?channel=ibai&parent=x"), "ibai")
        self.assertEqual(extractor.canal_twitch("https://www.twitch.tv/auronplay"), "auronplay")
        self.assertEqual(extractor.canal_twitch("https://ejemplo.es"), "")
        self.assertEqual(catalogo.identificador_youtube("https://www.youtube.com/watch?v=abc12345678"), ("abc12345678", ""))
        self.assertEqual(catalogo.identificador_youtube("https://www.youtube.com/channel/UC123/live"), ("", "UC123"))

    def test_busqueda_de_flujos_en_html(self):
        html = """<html><body>
        <script>var ads = "https://pagead2.doubleclick.net/x/anuncio.m3u8";</script>
        <script>var fuente = "https:\\/\\/cdn.emisora.es\\/directo\\/master.m3u8?tk=1";</script>
        <video src="/relativo/otro.m3u8"></video></body></html>"""
        encontrados = extractor._candidatos(html, "https://www.emisora.es/directo")
        self.assertIn("https://cdn.emisora.es/directo/master.m3u8?tk=1", encontrados)
        self.assertIn("https://www.emisora.es/relativo/otro.m3u8", encontrados)
        self.assertFalse([u for u in encontrados if "doubleclick" in u])

    def test_youtube_hls_rechaza_identificadores_invalidos(self):
        self.assertEqual(extractor.youtube_hls(""), "")
        self.assertEqual(extractor.youtube_hls("no valido!"), "")

    def test_extraer_desconocido(self):
        self.assertIsNone(extractor.extraer("directo", "https://ejemplo.es/x.m3u8"))


class GuiaAmpliada(unittest.TestCase):
    def test_clave_de_nombre(self):
        self.assertEqual(catalogo.clave_nombre("Antena 3 HD"), catalogo.clave_nombre("antena 3"))
        self.assertEqual(catalogo.clave_nombre("À Punt"), catalogo.clave_nombre("A Punt"))
        self.assertNotEqual(catalogo.clave_nombre("La 1"), catalogo.clave_nombre("La 2"))

    def test_xmltv_y_emparejamiento(self):
        ahora = int(time.time())
        def marca(desplazamiento):
            return time.strftime("%Y%m%d%H%M%S", time.localtime(ahora + desplazamiento)) + " " + time.strftime("%z", time.localtime())
        xml = f"""<?xml version="1.0"?><tv>
        <channel id="Antena 3 HD"><display-name>Antena 3</display-name></channel>
        <channel id="Otra"><display-name>Otro canal</display-name></channel>
        <programme start="{marca(-600)}" stop="{marca(600)}" channel="Antena 3 HD">
          <title>Ahora en Antena 3</title><desc>Descripción</desc><category>Noticias</category></programme>
        <programme start="{marca(-100 * 24 * 3600)}" stop="{marca(-99 * 24 * 3600)}" channel="Antena 3 HD">
          <title>Antiguo</title></programme>
        </tv>"""
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "guia.xml"
            ruta.write_text(xml, encoding="utf-8")
            guia = catalogo.parsear_xmltv(ruta)
            comprimida = Path(carpeta) / "guia.xml.gz"
            comprimida.write_bytes(gzip.compress(xml.encode("utf-8")))
            self.assertEqual(len(catalogo.parsear_xmltv(comprimida)), len(guia))
        canal = catalogo.Canal("Antena 3", "tv", "España", "Generalistas", "https://x.es", "", "Antena3.TV", (), origen="p")
        programas = catalogo.programas_canal(guia, canal)
        self.assertEqual([p.titulo for p in programas], ["Ahora en Antena 3"])
        actual, _siguiente = catalogo.ahora_y_siguiente(programas)
        self.assertEqual(actual.categoria, "Noticias")
        sin_guia = catalogo.Canal("Canal raro", "tv", "España", "x", "", "", "", (), origen="p")
        self.assertEqual(catalogo.programas_canal(guia, sin_guia), [])

    def test_la_guia_oficial_tiene_prioridad(self):
        canal = catalogo.Canal("La 1", "tv", "España", "Generalistas", "", "", "La1.TV", (), origen="p")
        propio = catalogo.Programa(0, 10, "De la guía oficial")
        ajeno = catalogo.Programa(0, 10, "De la guía ampliada")
        guia = {"La1.TV": [propio], catalogo.PREFIJO_NOMBRE + catalogo.clave_nombre("La 1"): [ajeno]}
        self.assertEqual(catalogo.programas_canal(guia, canal)[0].titulo, "De la guía oficial")


if __name__ == "__main__":
    unittest.main()
