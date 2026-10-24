"""Pruebas de la lectura enriquecida de guías XMLTV y del catálogo de iptv-org."""
import tempfile
import time
import unittest
from pathlib import Path

from tdt import catalogo, iptvorg, m3u
from tdt.catalogo import Canal, Emision

XMLTV = """<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="La 1 HD">
    <display-name>La 1</display-name>
    <display-name>La 1.TV</display-name>
    <icon src="https://ejemplo/la1.png" />
  </channel>
  <programme start="{inicio} +0200" stop="{fin} +0200" channel="La 1 HD">
    <title lang="en">Telediario 1</title>
    <title lang="es">Telediario 1 [COLOR tomato]T10 E176[/COLOR]</title>
    <sub-title lang="es">[COLOR SlateBlue]Informacion,Informativo[/COLOR] | [COLOR cadetblue]2026[/COLOR] | [COLOR orange]&#9312;[/COLOR] | [COLOR gold]&#9733;6.2/10[/COLOR]</sub-title>
    <desc lang="es">· Informativo de mediodia.
[COLOR teal]· Pais:[/COLOR] Espana</desc>
    <category>News magazine</category>
    <icon src="https://ejemplo/telediario.jpg" />
    <episode-num system="xmltv_ns">9.175.</episode-num>
    <rating system="ES"><value>TP</value></rating>
    <star-rating><value>6.2/10</value></star-rating>
  </programme>
</tv>
"""


def guia_de_prueba(inicio: float, fin: float) -> Path:
    marca = time.strftime("%Y%m%d%H%M%S", time.localtime(inicio))
    marca_fin = time.strftime("%Y%m%d%H%M%S", time.localtime(fin))
    ruta = Path(tempfile.mkdtemp()) / "guia.xml"
    ruta.write_text(XMLTV.format(inicio=marca, fin=marca_fin), encoding="utf-8")
    return ruta


class PruebaLimpieza(unittest.TestCase):
    def test_quita_las_etiquetas_de_kodi(self):
        self.assertEqual(catalogo.limpiar_texto_guia("[COLOR red]Hola[/COLOR] mundo"), "Hola mundo")
        self.assertEqual(catalogo.limpiar_texto_guia("[B]Negrita[/B]"), "Negrita")

    def test_quita_los_simbolos_del_principio(self):
        self.assertEqual(catalogo.limpiar_texto_guia("· Descripción"), "Descripción")
        self.assertEqual(catalogo.limpiar_texto_guia("— Otra\n· Línea"), "Otra\nLínea")

    def test_texto_vacio(self):
        self.assertEqual(catalogo.limpiar_texto_guia(None), "")


class PruebaXmltvEnriquecido(unittest.TestCase):
    def setUp(self):
        self.inicio = time.time() + 600
        self.fin = self.inicio + 3600
        self.guia = catalogo.parsear_xmltv(guia_de_prueba(self.inicio, self.fin))
        self.programa = self.guia[catalogo.PREFIJO_NOMBRE + catalogo.clave_nombre("La 1")][0]

    def test_empareja_por_nombre(self):
        self.assertIn(catalogo.PREFIJO_NOMBRE + catalogo.clave_nombre("La 1"), self.guia)

    def test_titulo_sin_etiquetas(self):
        self.assertNotIn("[COLOR", self.programa.titulo)
        self.assertIn("Telediario 1", self.programa.titulo)

    def test_episodio(self):
        self.assertEqual(self.programa.episodio, "temporada 10, episodio 176")

    def test_edad_y_valoracion(self):
        self.assertEqual(self.programa.edad, "todos los públicos")
        self.assertEqual(self.programa.valoracion, "6.2 sobre 10")

    def test_generos_en_espanol_como_categoria(self):
        self.assertEqual(self.programa.categoria, "Informacion, Informativo")

    def test_subtitulo_sin_simbolos_ni_categoria(self):
        self.assertEqual(self.programa.subtitulo, "2026")

    def test_imagen_y_descripcion(self):
        self.assertEqual(self.programa.imagen, "https://ejemplo/telediario.jpg")
        self.assertTrue(self.programa.descripcion.startswith("Informativo de mediodia"))
        self.assertNotIn("[COLOR", self.programa.descripcion)

    def test_detalles(self):
        claves = [c for c, _v in self.programa.detalles()]
        self.assertIn("Episodio", claves)
        self.assertIn("Valoración", claves)
        self.assertIn("Edad recomendada", claves)


class PruebaCobertura(unittest.TestCase):
    def test_separa_los_que_tienen_guia(self):
        inicio = time.time() + 600
        guia = catalogo.parsear_xmltv(guia_de_prueba(inicio, inicio + 3600))
        uno = Canal("La 1", "tv", "", "", "", "", "", (Emision("directo", "http://s/1.m3u8", "m3u8"),))
        dos = Canal("Canal raro", "tv", "", "", "", "", "", (Emision("directo", "http://s/2.m3u8", "m3u8"),))
        con, sin = catalogo.cobertura_guia([uno, dos], guia, "tv")
        self.assertEqual([c.nombre for c in con], ["La 1"])
        self.assertEqual([c.nombre for c in sin], ["Canal raro"])

    def test_parecidos(self):
        candidatos = ["La 1", "La 2", "Antena 3", "Telemadrid"]
        self.assertIn("La 1", catalogo.parecidos("La 1 HD", candidatos))
        self.assertIn("Telemadrid", catalogo.parecidos("Telemadrid HD", candidatos))
        self.assertEqual(catalogo.parecidos("", candidatos), [])


class PruebaMarcasDeNombre(unittest.TestCase):
    def test_separa_calidad_y_avisos(self):
        nombre, calidad, geo, intermitente = m3u.separar_marcas("3Cat Info (1080p) [Geo-blocked]")
        self.assertEqual(nombre, "3Cat Info")
        self.assertEqual(calidad, "1080p")
        self.assertTrue(geo)
        self.assertFalse(intermitente)

    def test_no_24_horas(self):
        nombre, _c, geo, intermitente = m3u.separar_marcas("Bailén TV (720p) [Not 24/7]")
        self.assertEqual(nombre, "Bailén TV")
        self.assertTrue(intermitente)
        self.assertFalse(geo)

    def test_nombre_normal(self):
        self.assertEqual(m3u.separar_marcas("La 1")[0], "La 1")

    def test_se_reflejan_en_el_canal(self):
        lista = '#EXTM3U\n#EXTINF:-1,Canal Uno (1080p) [Geo-blocked] [Not 24/7]\nhttp://s/a.m3u8\n'
        canal = m3u.parsear_m3u(lista, "tv")[0]
        self.assertEqual(canal.nombre, "Canal Uno")
        self.assertEqual(canal.emisiones[0].resolucion, "1080p")
        self.assertEqual(canal.emisiones[0].geo, "ZONA")
        self.assertTrue(canal.intermitente)
        self.assertIn("veinticuatro horas", " ".join(canal.notas()))


class PruebaIptvOrg(unittest.TestCase):
    def test_direcciones(self):
        self.assertEqual(iptvorg.url_lista("pais", "ES"), "https://iptv-org.github.io/iptv/countries/es.m3u")
        self.assertEqual(iptvorg.url_lista("idioma", "spa"), "https://iptv-org.github.io/iptv/languages/spa.m3u")
        self.assertEqual(iptvorg.url_lista("categoria", "news"), "https://iptv-org.github.io/iptv/categories/news.m3u")
        self.assertTrue(iptvorg.url_completa().endswith("index.m3u"))

    def test_tipo_desconocido_devuelve_la_general(self):
        self.assertEqual(iptvorg.url_lista("otra", "es"), iptvorg.url_completa())

    def test_nombre_de_la_lista(self):
        self.assertEqual(iptvorg.nombre_lista("pais", "España"), "iptv-org · País: España")

    def test_indice_de_respaldo_sin_conexion(self):
        original = iptvorg.descargar_json

        def fallar(*_a, **_k):
            raise RuntimeError("sin conexión")

        iptvorg.descargar_json = fallar
        try:
            paises = iptvorg.indice("pais")
        finally:
            iptvorg.descargar_json = original
        self.assertTrue(paises)
        self.assertIn(("España", "es"), paises)


if __name__ == "__main__":
    unittest.main()
