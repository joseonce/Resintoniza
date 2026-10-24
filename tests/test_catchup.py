"""Pruebas de las direcciones de catch-up (programas ya emitidos)."""
import time
import unittest

from tdt import catchup
from tdt.catalogo import Canal, Emision


def canal(**cambios):
    base = dict(nombre="Canal", tipo="tv", pais="", ambito="", web="", logo="", epg_id="",
                emisiones=(Emision("directo", "http://s/canal/index.m3u8", "m3u8"),))
    base.update(cambios)
    return Canal(**base)


class PruebaCatchup(unittest.TestCase):
    def setUp(self):
        self.ahora = 1_700_000_000.0
        self.inicio = self.ahora - 7200
        self.fin = self.inicio + 3600

    def test_sin_catchup(self):
        self.assertFalse(catchup.disponible(canal(), self.inicio, self.fin, self.ahora))
        self.assertEqual(catchup.url_programa(canal(), "http://s/x.m3u8", self.inicio, self.fin, self.ahora), "")

    def test_disponible_solo_para_lo_ya_emitido(self):
        c = canal(catchup="default", catchup_dias=7)
        self.assertTrue(catchup.disponible(c, self.inicio, self.fin, self.ahora))
        # Todavía se está emitiendo.
        self.assertFalse(catchup.disponible(c, self.ahora - 60, self.ahora + 600, self.ahora))
        # Más allá del plazo del proveedor.
        viejo = self.ahora - 20 * 24 * 3600
        self.assertFalse(catchup.disponible(c, viejo, viejo + 3600, self.ahora))

    def test_default_anade_parametros(self):
        url = catchup.url_programa(canal(catchup="default"), "http://s/canal/index.m3u8", self.inicio, self.fin, self.ahora)
        self.assertIn("utc=" + str(int(self.inicio)), url)
        self.assertIn("lutc=" + str(int(self.ahora)), url)

    def test_default_conserva_los_parametros_previos(self):
        url = catchup.url_programa(canal(catchup="default"), "http://s/canal/index.m3u8?token=abc", self.inicio, self.fin, self.ahora)
        self.assertIn("token=abc", url)
        self.assertIn("utc=", url)

    def test_flussonic_reescribe_la_ruta(self):
        url = catchup.url_programa(canal(catchup="flussonic"), "http://s/canal/index.m3u8", self.inicio, self.fin, self.ahora)
        self.assertEqual(url, f"http://s/canal/{int(self.inicio)}-3600.m3u8")

    def test_xtream_construye_timeshift(self):
        url = catchup.url_programa(canal(catchup="xc"), "http://s/usuario/clave/1234.ts", self.inicio, self.fin, self.ahora)
        momento = time.strftime("%Y-%m-%d:%H-%M", time.localtime(self.inicio))
        self.assertEqual(url, f"http://s/timeshift/usuario/clave/60/{momento}/1234.ts")

    def test_plantilla_del_proveedor_manda(self):
        c = canal(catchup="default", catchup_fuente="http://s/archivo?start=${start}&end=${end}")
        url = catchup.url_programa(c, "http://s/canal/index.m3u8", self.inicio, self.fin, self.ahora)
        self.assertEqual(url, f"http://s/archivo?start={int(self.inicio)}&end={int(self.fin)}")

    def test_plantilla_relativa(self):
        c = canal(catchup="default", catchup_fuente="?utc={utc}&dur={duration}")
        url = catchup.url_programa(c, "http://s/canal/index.m3u8", self.inicio, self.fin, self.ahora)
        self.assertIn("utc=" + str(int(self.inicio)), url)
        self.assertIn("dur=3600", url)
        self.assertTrue(url.startswith("http://s/canal/index.m3u8?"))

    def test_plantilla_con_fecha(self):
        c = canal(catchup="default", catchup_fuente="http://s/{Y}/{m}/{d}/{H}-{M}.m3u8")
        url = catchup.url_programa(c, "http://s/canal/index.m3u8", self.inicio, self.fin, self.ahora)
        esperado = time.strftime("http://s/%Y/%m/%d/%H-%M.m3u8", time.localtime(self.inicio))
        self.assertEqual(url, esperado)


if __name__ == "__main__":
    unittest.main()
