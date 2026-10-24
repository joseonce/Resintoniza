"""Pruebas del DNS alternativo: copia de seguridad, conversión y resultado del proceso elevado.

No se cambia ninguna configuración de red: se prueban las piezas que rodean a
PowerShell, que es donde estaban los fallos (la marca de orden de bytes en el
archivo de resultado y la copia de seguridad antes de tocar nada).
"""
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tdt import dns_xdp  # noqa: E402


class PruebaResultado(unittest.TestCase):
    """El archivo que deja el proceso con permisos de administrador."""

    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp(prefix="prueba_dns_"))

    def tearDown(self):
        shutil.rmtree(self.carpeta, ignore_errors=True)

    def test_lee_quitando_la_marca_de_orden_de_bytes(self):
        """Windows PowerShell escribe UTF-8 con BOM: si no se quita, «ERROR:» no se reconocía."""
        salida, listo = self.carpeta / "salida.txt", self.carpeta / "listo.txt"
        salida.write_text("ERROR: algo falló", encoding="utf-8-sig")
        listo.write_text("FIN", encoding="utf-8-sig")
        texto = dns_xdp._leer_resultado(salida, listo, espera=1)
        self.assertTrue(texto.startswith("ERROR:"), repr(texto))
        self.assertIn("algo falló", texto)

    def test_sin_archivo_devuelve_vacio(self):
        self.assertEqual(dns_xdp._leer_resultado(self.carpeta / "no.txt", self.carpeta / "tampoco.txt", espera=0.5), "")

    def test_la_envoltura_escribe_los_dos_archivos(self):
        guion = dns_xdp._envoltura("Get-Date", self.carpeta / "salida.txt", self.carpeta / "listo.txt")
        self.assertIn("Get-Date", guion)
        self.assertIn("salida.txt", guion)
        self.assertIn("listo.txt", guion)
        self.assertIn("$resultado = 'OK'", guion)
        self.assertLess(guion.index("salida.txt"), guion.index("listo.txt"))  # el aviso de fin va el último


class PruebaCopia(unittest.TestCase):
    """Nunca se cambia el DNS sin guardar antes lo que había."""

    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp(prefix="prueba_dns_datos_"))
        self.datos = SimpleNamespace(raiz=self.carpeta, windows={})
        self.actual = {"modo": "MANUAL", "manuales": ["1.1.1.1", "1.0.0.1"], "dhcp": ["192.168.1.1"],
                       "dns": ["1.1.1.1", "1.0.0.1"]}
        self.original = dns_xdp.configuracion_actual
        dns_xdp.configuracion_actual = lambda nombre: self.actual

    def tearDown(self):
        dns_xdp.configuracion_actual = self.original
        shutil.rmtree(self.carpeta, ignore_errors=True)

    def test_guarda_lo_que_habia_y_deja_copia_fechada(self):
        entrada = dns_xdp.guardar_original(self.datos, "Wi-Fi")
        self.assertEqual(entrada["modo"], "MANUAL")
        self.assertEqual(entrada["dns"], ["1.1.1.1", "1.0.0.1"])
        self.assertIn("fecha", entrada)
        guardado = json.loads(dns_xdp.ruta_original(self.datos).read_text(encoding="utf-8"))
        self.assertIn("Wi-Fi", guardado)
        self.assertTrue(list(dns_xdp.carpeta_copias(self.datos).glob("dns-original-*.json")))

    def test_no_pisa_una_copia_anterior(self):
        primera = dns_xdp.guardar_original(self.datos, "Wi-Fi")
        self.actual = {"modo": "MANUAL", "manuales": ["9.9.9.9"], "dhcp": [], "dns": ["9.9.9.9"]}
        segunda = dns_xdp.guardar_original(self.datos, "Wi-Fi")
        self.assertEqual(primera["dns"], segunda["dns"])

    def test_automatico_no_guarda_manuales(self):
        self.actual = {"modo": "AUTOMATICO", "manuales": [], "dhcp": ["192.168.1.1"], "dns": ["192.168.1.1"]}
        entrada = dns_xdp.guardar_original(self.datos, "Wi-Fi")
        self.assertEqual(entrada["modo"], "AUTOMATICO")
        self.assertEqual(entrada["dns"], [])
        self.assertEqual(entrada["dhcp"], ["192.168.1.1"])

    def test_si_ya_estaba_el_alternativo_no_hay_nada_que_guardar(self):
        self.actual = {"modo": "MANUAL", "manuales": [dns_xdp.SERVIDOR], "dhcp": [], "dns": [dns_xdp.SERVIDOR]}
        self.assertEqual(dns_xdp.guardar_original(self.datos, "Wi-Fi"), {})
        self.assertFalse(dns_xdp.ruta_original(self.datos).exists())

    def test_olvidar_deja_copia_antes(self):
        dns_xdp.guardar_original(self.datos, "Wi-Fi")
        copias_antes = len(list(dns_xdp.carpeta_copias(self.datos).glob("*.json")))
        time.sleep(1.1)   # las copias llevan la hora en el nombre
        dns_xdp.olvidar_original(self.datos, "Wi-Fi")
        self.assertIsNone(dns_xdp.original_de(self.datos, "Wi-Fi"))
        self.assertGreater(len(list(dns_xdp.carpeta_copias(self.datos).glob("*.json"))), copias_antes)

    def test_exportar(self):
        dns_xdp.guardar_original(self.datos, "Wi-Fi")
        destino = self.carpeta / "copia.json"
        dns_xdp.exportar_original(self.datos, destino)
        self.assertIn("Wi-Fi", json.loads(destino.read_text(encoding="utf-8")))

    def test_exportar_sin_nada_avisa(self):
        with self.assertRaises(dns_xdp.ErrorDns):
            dns_xdp.exportar_original(self.datos, self.carpeta / "vacio.json")

    def test_no_se_guarda_si_no_se_puede_escribir(self):
        """Si la copia no se puede escribir, se avisa: sin copia no se toca el DNS."""
        self.datos.raiz = self.carpeta / "sub" / "carpeta.json"
        self.datos.raiz.parent.mkdir(parents=True, exist_ok=True)
        self.datos.raiz.write_text("no soy una carpeta", encoding="utf-8")
        with self.assertRaises(dns_xdp.ErrorDns):
            dns_xdp.guardar_original(self.datos, "Wi-Fi")


class PruebaConversion(unittest.TestCase):
    """El formato de xdp_manager: con modo automático, sus «dns» son los del router."""

    def test_automatico_pasa_a_dhcp(self):
        convertido = dns_xdp.convertir_configuracion({"Wi-Fi": {"modo": "AUTOMATICO", "dns": ["212.230.135.2", "212.230.135.1"]}})
        self.assertEqual(convertido["Wi-Fi"], {"modo": "AUTOMATICO", "dns": [], "dhcp": ["212.230.135.2", "212.230.135.1"]})

    def test_manual_se_conserva(self):
        convertido = dns_xdp.convertir_configuracion({"Ethernet": {"modo": "MANUAL", "dns": ["8.8.8.8"]}})
        self.assertEqual(convertido["Ethernet"], {"modo": "MANUAL", "dns": ["8.8.8.8"], "dhcp": []})

    def test_se_quita_el_propio_alternativo(self):
        convertido = dns_xdp.convertir_configuracion({"Wi-Fi": {"modo": "MANUAL", "dns": [dns_xdp.SERVIDOR]}})
        self.assertEqual(convertido["Wi-Fi"]["dns"], [])

    def test_resumen_legible(self):
        self.assertIn("212.230.135.2", dns_xdp.resumen_configuracion({"modo": "AUTOMATICO", "dhcp": ["212.230.135.2"]}))
        self.assertIn("manuales", dns_xdp.resumen_configuracion({"modo": "MANUAL", "dns": ["8.8.8.8"]}))


if __name__ == "__main__":
    unittest.main()
