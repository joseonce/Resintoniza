"""Pruebas del lector de listas M3U."""
import unittest

from tdt import m3u

LISTA = """#EXTM3U url-tvg="https://ejemplo.es/guia.xml.gz"
#EXTINF:-1 tvg-id="La1.es" tvg-name="La 1 HD" tvg-logo="https://ejemplo.es/la1.png" tvg-chno="1" group-title="Generalistas" tvg-language="Castellano" tvg-shift="1" catchup="flussonic" catchup-days="7",La 1
#EXTVLCOPT:http-user-agent=Mozilla/5.0 (Windows NT 10.0)
#EXTVLCOPT:http-referrer=https://www.rtve.es/
https://ejemplo.es/la1/index.m3u8
#EXTINF:-1 tvg-id="RNE" radio="true" group-title="Radios",Radio Nacional
https://ejemplo.es/rne/audio.mp3
#EXTGRP:Cifrados
#EXTINF:-1,Canal con DRM
#KODIPROP:inputstream.adaptive.license_type=com.widevine.alpha
https://ejemplo.es/drm/manifest.mpd
#EXTINF:-1 group-title="Vídeos",Canal de YouTube
https://www.youtube.com/watch?v=abcdefghijk
#EXTINF:-1,La 1
https://ejemplo.es/repetido.m3u8
"""


class PruebaM3U(unittest.TestCase):
    def test_detecta_formato(self):
        self.assertTrue(m3u.es_m3u(LISTA))
        self.assertTrue(m3u.es_m3u("#EXTINF:-1,Canal\nhttp://x"))
        self.assertFalse(m3u.es_m3u('{"countries": []}'))

    def test_guia_declarada(self):
        self.assertEqual(m3u.guia_declarada(LISTA), "https://ejemplo.es/guia.xml.gz")
        self.assertEqual(m3u.guia_declarada("#EXTM3U\n#EXTINF:-1,X\nhttp://x"), "")

    def test_atributos_del_canal(self):
        canales = m3u.parsear_m3u(LISTA, "tv", "Mi lista")
        primero = canales[0]
        self.assertEqual(primero.nombre, "La 1")
        self.assertEqual(primero.epg_id, "La1.es")
        self.assertEqual(primero.ambito, "Generalistas")
        self.assertEqual(primero.numero, 1)
        self.assertEqual(primero.idioma, "Castellano")
        self.assertEqual(primero.desfase, 1.0)
        self.assertEqual(primero.catchup, "flussonic")
        self.assertEqual(primero.catchup_dias, 7)
        self.assertEqual(primero.origen, "Mi lista")
        self.assertEqual(primero.logo, "https://ejemplo.es/la1.png")

    def test_cabeceras_de_vlc(self):
        primero = m3u.parsear_m3u(LISTA, "tv")[0]
        self.assertTrue(primero.user_agent.startswith("Mozilla/5.0"))
        self.assertEqual(primero.referer, "https://www.rtve.es/")

    def test_tipos_de_emision(self):
        canales = {c.nombre: c for c in m3u.parsear_m3u(LISTA, "tv")}
        self.assertEqual(canales["La 1"].emisiones[0].tipo, "directo")
        self.assertEqual(canales["La 1"].emisiones[0].formato, "m3u8")
        self.assertEqual(canales["Canal de YouTube"].emisiones[0].tipo, "youtube")

    def test_marca_drm(self):
        canales = {c.nombre: c for c in m3u.parsear_m3u(LISTA, "tv")}
        self.assertTrue(canales["Canal con DRM"].drm)
        self.assertFalse(canales["La 1"].drm)
        self.assertIn("cifrada", " ".join(canales["Canal con DRM"].notas()))

    def test_tipo_automatico(self):
        canales = {c.nombre: c for c in m3u.parsear_m3u(LISTA, "auto")}
        self.assertEqual(canales["Radio Nacional"].tipo, "radio")
        self.assertEqual(canales["La 1"].tipo, "tv")

    def test_no_repite_canales(self):
        nombres = [c.nombre for c in m3u.parsear_m3u(LISTA, "tv")]
        self.assertEqual(nombres.count("La 1"), 1)

    def test_lista_invalida(self):
        with self.assertRaises(ValueError):
            m3u.parsear_m3u("no soy una lista", "tv")
        with self.assertRaises(ValueError):
            m3u.parsear_m3u("#EXTM3U\n", "tv")

    def test_exportar(self):
        canales = m3u.parsear_m3u(LISTA, "tv")
        salida = m3u.escribir_m3u(canales[:1])
        self.assertTrue(salida.startswith("#EXTM3U"))
        self.assertIn('tvg-chno="1"', salida)
        self.assertIn("https://ejemplo.es/la1/index.m3u8", salida)
        # Lo exportado se vuelve a leer sin perder lo esencial.
        vuelta = m3u.parsear_m3u(salida, "tv")[0]
        self.assertEqual(vuelta.nombre, "La 1")
        self.assertEqual(vuelta.numero, 1)


if __name__ == "__main__":
    unittest.main()
