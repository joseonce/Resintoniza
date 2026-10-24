"""Pruebas del comprobador de canales y de las tareas de Windows (sin tocar la red ni el sistema)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tdt import comprobador, tareas  # noqa: E402
from tdt.catalogo import Canal, Emision  # noqa: E402


def canal(nombre="La 1", tipo_emision="directo", url="https://ejemplo.es/directo.m3u8"):
    return Canal(nombre, "tv", "España", "", "", "", "", (Emision(tipo_emision, url, "m3u8"),))


class PruebaComprobador(unittest.TestCase):
    def test_solo_se_comprueban_las_directas(self):
        self.assertTrue(comprobador.comprobable(canal()))
        self.assertFalse(comprobador.comprobable(canal(tipo_emision="youtube")))

    def test_tambien_se_comprueban_las_webs_oficiales(self):
        self.assertTrue(comprobador.comprobable(canal(tipo_emision="ext", url="https://www.mitele.es/directo/fdf")))

    def test_web_solo_de_navegador_no_cuenta_como_fallo(self):
        """Muchos canales solo se ven con el reproductor de su web: eso no es un fallo."""
        resultado = comprobador.comprobar_canal(canal(tipo_emision="ext", url="https://web-que-no-conozco.example/pagina"))
        self.assertEqual(resultado["estado"], "omitido")
        self.assertIn("reproductor de su web", resultado["detalle"])
        self.assertIn("web-que-no-conozco.example", resultado["detalle"])

    def test_canal_sin_emisiones(self):
        vacio = Canal("Nada", "tv", "", "", "", "", "", ())
        resultado = comprobador.comprobar_canal(vacio)
        self.assertEqual(resultado["estado"], "omitido")
        self.assertIn("no tiene emisiones", resultado["detalle"])

    def test_emision_de_youtube_se_omite(self):
        resultado = comprobador.comprobar_canal(canal(tipo_emision="youtube", url="https://youtube.com/@canal"))
        self.assertEqual(resultado["estado"], "omitido")

    def test_motivos_en_castellano(self):
        self.assertIn("no contesta", comprobador._motivo(TimeoutError("timed out")))
        self.assertIn("nombre del servidor", comprobador._motivo(OSError("getaddrinfo failed")))
        self.assertIn("certificado", comprobador._motivo(Exception("CERTIFICATE_VERIFY_FAILED")))

    def test_resumen(self):
        resultados = [{"estado": "ok"}, {"estado": "error"}, {"estado": "omitido"}]
        texto = comprobador.resumen(resultados)
        self.assertIn("3 canales", texto)
        self.assertIn("1 responden", texto)
        self.assertIn("no se han podido comprobar", texto)

    def test_cabeceras_de_la_fuente(self):
        fuente = SimpleNamespace(url="https://x", user_agent="UA", origin="https://o", referer="https://r", cookie="c=1")
        cabeceras = comprobador._cabeceras(fuente)
        self.assertEqual(cabeceras["User-Agent"], "UA")
        self.assertEqual(cabeceras["Origin"], "https://o")
        self.assertEqual(cabeceras["Cookie"], "c=1")


class PruebaTareas(unittest.TestCase):
    def test_nombre_de_la_tarea(self):
        nombre = tareas.nombre_tarea({"inicio": 1757275200})
        self.assertTrue(nombre.startswith(tareas.PREFIJO))
        self.assertIn("1757275200", nombre)

    def test_ejecutable_existe(self):
        programa, _argumentos = tareas.ejecutable()
        self.assertTrue(Path(programa).exists(), programa)

    def test_acciones_finales(self):
        self.assertEqual(set(tareas.ACCIONES_FINAL), {"nada", "cerrar", "suspender", "apagar"})

    def test_apagar_con_modo_desconocido_no_hace_nada(self):
        ok, _mensaje = tareas.apagar("nada")
        self.assertFalse(ok)


class PruebaCuadrosDeDialogo(unittest.TestCase):
    """El cuadro de Sí o No debe cerrarse con Escape (el nativo de Windows no lo hace)."""

    @classmethod
    def setUpClass(cls):
        import wx

        cls.wx = wx
        cls.app = wx.App(False)
        cls.marco = wx.Frame(None)

    @classmethod
    def tearDownClass(cls):
        cls.marco.Destroy()
        cls.app.Destroy()

    def test_escape_responde_que_no(self):
        from tdt.widgets import dialogo_pregunta

        dialogo = dialogo_pregunta(self.marco, "¿Seguir?", "Prueba")
        try:
            self.assertEqual(dialogo.GetEscapeId(), self.wx.ID_NO)
            self.assertIsInstance(dialogo, self.wx.GenericMessageDialog)
        finally:
            dialogo.Destroy()

    def test_no_quedan_cuadros_nativos_de_si_o_no(self):
        carpeta = Path(__file__).resolve().parent.parent / "tdt"
        culpables = [
            f"{ruta.name}:{numero}"
            for ruta in carpeta.glob("*.py")
            for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1)
            if "YES_NO" in linea and "CANCEL" not in linea and "GenericMessageDialog" not in linea
        ]
        self.assertEqual(culpables, [], "Usa widgets.pregunta: con Sí y No a secas Escape no cierra.")


if __name__ == "__main__":
    unittest.main()
