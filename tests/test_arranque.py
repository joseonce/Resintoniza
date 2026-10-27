"""Pruebas del arranque con listas guardadas y del DNS alternativo."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from tdt import datos as modulo_datos, dns_xdp


class DatosFalsos:
    def __init__(self, raiz):
        self.raiz = Path(raiz)
        self.windows = {}


class PruebaFrecuencia(unittest.TestCase):
    def setUp(self):
        self.ahora = 1_700_000_000.0
        self.windows = {"ultimaComprobacion": self.ahora - 3 * 3600}

    def test_nunca_no_actualiza(self):
        self.windows["frecuenciaActualizacion"] = "nunca"
        self.assertFalse(modulo_datos.toca_actualizar(self.windows, self.ahora))

    def test_siempre_actualiza(self):
        self.windows["frecuenciaActualizacion"] = "siempre"
        self.assertTrue(modulo_datos.toca_actualizar(self.windows, self.ahora))

    def test_diaria_y_semanal(self):
        self.windows["frecuenciaActualizacion"] = "diaria"
        self.assertFalse(modulo_datos.toca_actualizar(self.windows, self.ahora))
        self.windows["ultimaComprobacion"] = self.ahora - 25 * 3600
        self.assertTrue(modulo_datos.toca_actualizar(self.windows, self.ahora))
        self.windows["frecuenciaActualizacion"] = "semanal"
        self.assertFalse(modulo_datos.toca_actualizar(self.windows, self.ahora))
        self.windows["ultimaComprobacion"] = self.ahora - 8 * 24 * 3600
        self.assertTrue(modulo_datos.toca_actualizar(self.windows, self.ahora))

    def test_sin_ajuste_no_actualiza(self):
        self.assertFalse(modulo_datos.toca_actualizar({}, self.ahora))

    def test_valor_predeterminado(self):
        limpio = modulo_datos.validar_ajustes({})
        self.assertEqual(limpio["windows"]["frecuenciaActualizacion"], "nunca")

    def test_migra_el_ajuste_antiguo(self):
        antiguo = modulo_datos.validar_ajustes({"windows": {"actualizarAlIniciar": True}})
        self.assertEqual(antiguo["windows"]["frecuenciaActualizacion"], "siempre")
        antiguo = modulo_datos.validar_ajustes({"windows": {"actualizarAlIniciar": False}})
        self.assertEqual(antiguo["windows"]["frecuenciaActualizacion"], "nunca")

    def test_el_ajuste_nuevo_manda(self):
        limpio = modulo_datos.validar_ajustes({"windows": {"actualizarAlIniciar": True, "frecuenciaActualizacion": "diaria"}})
        self.assertEqual(limpio["windows"]["frecuenciaActualizacion"], "diaria")

    def test_valor_invalido(self):
        limpio = modulo_datos.validar_ajustes({"windows": {"frecuenciaActualizacion": "cuando sea"}})
        self.assertEqual(limpio["windows"]["frecuenciaActualizacion"], "nunca")

    def test_minimizar_a_bandeja(self):
        limpio = modulo_datos.validar_ajustes({})
        self.assertFalse(limpio["windows"]["minimizarABandeja"])
        limpio = modulo_datos.validar_ajustes({"windows": {"minimizarABandeja": True}})
        self.assertTrue(limpio["windows"]["minimizarABandeja"])
        limpio = modulo_datos.validar_ajustes({"windows": {"minimizarABandeja": "si"}})
        self.assertFalse(limpio["windows"]["minimizarABandeja"])

    def test_iniciar_minimizado_y_con_windows(self):
        limpio = modulo_datos.validar_ajustes({})
        self.assertFalse(limpio["windows"]["iniciarMinimizado"])
        self.assertFalse(limpio["windows"]["iniciarConWindows"])
        self.assertTrue(limpio["windows"]["comprobarActualizaciones"])
        self.assertIn("github.com", limpio["windows"]["urlActualizaciones"])

        # Si venía vacío de ajustes antiguos, restaura el valor por defecto de GitHub
        limpio_vacio = modulo_datos.validar_ajustes({"windows": {"urlActualizaciones": "   "}})
        self.assertIn("github.com", limpio_vacio["windows"]["urlActualizaciones"])
        # Si venía una URL web de GitHub, se normaliza automáticamente a la API
        limpio_web = modulo_datos.validar_ajustes({"windows": {"urlActualizaciones": "https://github.com/joseonce/Resintoniza"}})
        self.assertEqual(limpio_web["windows"]["urlActualizaciones"], "https://api.github.com/repos/joseonce/Resintoniza/releases/latest")

        limpio = modulo_datos.validar_ajustes({"windows": {"iniciarMinimizado": True, "iniciarConWindows": True}})
        self.assertTrue(limpio["windows"]["iniciarMinimizado"])
        self.assertTrue(limpio["windows"]["iniciarConWindows"])

        limpio = modulo_datos.validar_ajustes({"windows": {"iniciarMinimizado": "si", "iniciarConWindows": 123}})
        self.assertFalse(limpio["windows"]["iniciarMinimizado"])
        self.assertFalse(limpio["windows"]["iniciarConWindows"])


class PruebaCacheDeTexto(unittest.TestCase):
    def test_usa_la_copia_guardada_sin_red(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = modulo_datos.Datos(Path(carpeta))
            url = "https://ejemplo.es/lista.m3u"
            destino = datos.ruta_cache(url).with_suffix(".m3u")
            destino.write_text("#EXTM3U\n#EXTINF:-1,Canal\nhttp://s/a.m3u8\n", encoding="utf-8")
            texto, aviso = datos.obtener_texto(url, refrescar=False)
            self.assertIn("#EXTINF", texto)
            self.assertEqual(aviso, "")

    def test_sin_copia_y_sin_red_avisa(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = modulo_datos.Datos(Path(carpeta))
            with self.assertRaises(RuntimeError):
                datos.obtener_texto("https://ejemplo.invalido/lista.m3u", refrescar=True)


class PruebaDns(unittest.TestCase):
    def test_escapa_las_comillas_del_nombre(self):
        self.assertEqual(dns_xdp._seguro("Wi-Fi de 'casa'"), "Wi-Fi de ''casa''")

    def test_texto_de_estado(self):
        manual = {"adaptador": "Wi-Fi", "modo": "MANUAL", "manuales": ["85.208.114.51"], "dhcp": ["1.1.1.1"], "dns": ["85.208.114.51"], "activo": True, "resuelve": True}
        texto = dns_xdp.texto_estado(manual)
        self.assertIn("Wi-Fi", texto)
        self.assertIn("está activado", texto)
        automatico = {"adaptador": "Ethernet", "modo": "AUTOMATICO", "manuales": [], "dhcp": ["192.168.1.1"], "dns": ["192.168.1.1"], "activo": False, "resuelve": False}
        texto = dns_xdp.texto_estado(automatico)
        self.assertIn("automáticos del router", texto)
        self.assertIn("no está activado", texto)
        self.assertIn("no se resuelven", texto)

    def test_texto_de_estado_con_error(self):
        self.assertIn("No se pudo", dns_xdp.texto_estado({"adaptador": "X", "error": "fallo"}))

    def test_guarda_y_olvida_la_configuracion_original(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            original = dns_xdp.configuracion_actual
            dns_xdp.configuracion_actual = lambda nombre: {"modo": "MANUAL", "manuales": ["1.1.1.1", "1.0.0.1"], "dhcp": ["192.168.1.1"], "dns": ["1.1.1.1"]}
            try:
                guardado = dns_xdp.guardar_original(datos, "Wi-Fi")
                self.assertEqual(guardado["modo"], "MANUAL")
                self.assertEqual(guardado["dns"], ["1.1.1.1", "1.0.0.1"])
                self.assertEqual(dns_xdp.original_de(datos, "Wi-Fi")["dns"], ["1.1.1.1", "1.0.0.1"])
                # No se pisa lo guardado si se vuelve a activar.
                dns_xdp.configuracion_actual = lambda nombre: {"modo": "MANUAL", "manuales": [dns_xdp.SERVIDOR], "dhcp": [], "dns": [dns_xdp.SERVIDOR]}
                self.assertEqual(dns_xdp.guardar_original(datos, "Wi-Fi")["dns"], ["1.1.1.1", "1.0.0.1"])
                dns_xdp.olvidar_original(datos, "Wi-Fi")
                self.assertIsNone(dns_xdp.original_de(datos, "Wi-Fi"))
            finally:
                dns_xdp.configuracion_actual = original

    def test_no_guarda_como_original_el_dns_alternativo(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            original = dns_xdp.configuracion_actual
            dns_xdp.configuracion_actual = lambda nombre: {"modo": "MANUAL", "manuales": [dns_xdp.SERVIDOR], "dhcp": ["192.168.1.1"], "dns": [dns_xdp.SERVIDOR]}
            try:
                self.assertEqual(dns_xdp.guardar_original(datos, "Wi-Fi"), {})
                self.assertIsNone(dns_xdp.original_de(datos, "Wi-Fi"))
            finally:
                dns_xdp.configuracion_actual = original

    def test_activar_y_restaurar_arman_las_ordenes(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            ordenes = []
            original_config, original_elevado = dns_xdp.configuracion_actual, dns_xdp._powershell_elevado
            original_activo, original_doh = dns_xdp.activo, dns_xdp.doh_registrado
            dns_xdp.configuracion_actual = lambda nombre: {"modo": "AUTOMATICO", "manuales": [], "dhcp": ["192.168.1.1"], "dns": ["192.168.1.1"]}
            dns_xdp._powershell_elevado = lambda comando, timeout=0, comprobar=None: ordenes.append(comando) or "OK"
            dns_xdp.doh_registrado = lambda: True
            try:
                dns_xdp.activo = lambda nombre: True    # tras activar, el sistema ya lo tiene puesto
                mensaje = dns_xdp.activar(datos, "Wi-Fi")
                self.assertIn("Wi-Fi", mensaje)
                self.assertIn(dns_xdp.SERVIDOR, ordenes[0])
                self.assertIn("Set-DnsClientServerAddress", ordenes[0])
                self.assertIn("Clear-DnsClientCache", ordenes[0])
                # Se guardó que antes era automático, así que al restaurar se resetea.
                dns_xdp.activo = lambda nombre: False   # y tras restaurar, ya no
                mensaje = dns_xdp.restaurar(datos, "Wi-Fi")
                self.assertIn("automáticos", mensaje)
                self.assertIn("-ResetServerAddresses", ordenes[1])
                self.assertIn("Remove-DnsClientDohServerAddress", ordenes[1])
            finally:
                dns_xdp.configuracion_actual, dns_xdp._powershell_elevado = original_config, original_elevado
                dns_xdp.activo, dns_xdp.doh_registrado = original_activo, original_doh

    def test_no_se_activa_sin_poder_guardar_la_copia(self):
        """Si la copia de seguridad no se puede escribir, no se toca el DNS."""
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            (Path(carpeta) / dns_xdp.ARCHIVO_ORIGINAL).mkdir()   # una carpeta donde iría el archivo
            llamadas = []
            original_config, original_elevado = dns_xdp.configuracion_actual, dns_xdp._powershell_elevado
            dns_xdp.configuracion_actual = lambda nombre: {"modo": "MANUAL", "manuales": ["1.1.1.1"], "dhcp": [], "dns": ["1.1.1.1"]}
            dns_xdp._powershell_elevado = lambda comando, timeout=0, comprobar=None: llamadas.append(comando) or "OK"
            try:
                with self.assertRaises(dns_xdp.ErrorDns):
                    dns_xdp.activar(datos, "Wi-Fi")
                self.assertEqual(llamadas, [])
            finally:
                dns_xdp.configuracion_actual, dns_xdp._powershell_elevado = original_config, original_elevado

    def test_si_no_se_restaura_de_verdad_se_conserva_la_copia(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            dns_xdp.ruta_original(datos).write_text(json.dumps({"Wi-Fi": {"modo": "MANUAL", "dns": ["1.1.1.1"]}}), encoding="utf-8")
            original_elevado, original_activo = dns_xdp._powershell_elevado, dns_xdp.activo
            dns_xdp._powershell_elevado = lambda comando, timeout=0, comprobar=None: "OK"
            dns_xdp.activo = lambda nombre: True     # el sistema sigue con el alternativo
            try:
                with self.assertRaises(dns_xdp.ErrorDns):
                    dns_xdp.restaurar(datos, "Wi-Fi")
                self.assertIsNotNone(dns_xdp.original_de(datos, "Wi-Fi"))
            finally:
                dns_xdp._powershell_elevado, dns_xdp.activo = original_elevado, original_activo

    def test_convierte_la_configuracion_de_xdp_manager(self):
        # Aquella herramienta anotaba en "dns" los servidores en uso: con modo
        # automático son los del router, y aquí no deben quedar como manuales.
        convertido = dns_xdp.convertir_configuracion({"Wi-Fi": {"modo": "AUTOMATICO", "dns": ["212.230.135.2", "212.230.135.1"]}})
        self.assertEqual(convertido["Wi-Fi"], {"modo": "AUTOMATICO", "dns": [], "dhcp": ["212.230.135.2", "212.230.135.1"]})
        manual = dns_xdp.convertir_configuracion({"Ethernet": {"modo": "MANUAL", "dns": ["1.1.1.1"]}})
        self.assertEqual(manual["Ethernet"], {"modo": "MANUAL", "dns": ["1.1.1.1"], "dhcp": []})

    def test_convertir_descarta_lo_que_no_vale(self):
        self.assertEqual(dns_xdp.convertir_configuracion({}), {})
        self.assertEqual(dns_xdp.convertir_configuracion({"Wi-Fi": "no soy un objeto"}), {})
        # El propio servidor alternativo no cuenta como configuración anterior.
        convertido = dns_xdp.convertir_configuracion({"Wi-Fi": {"modo": "MANUAL", "dns": [dns_xdp.SERVIDOR]}})
        self.assertEqual(convertido["Wi-Fi"]["dns"], [])

    def test_importar_configuracion_guardada(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            ruta = Path(carpeta) / dns_xdp.ARCHIVO_XDP_MANAGER
            ruta.write_text(json.dumps({"Wi-Fi": {"modo": "AUTOMATICO", "dns": ["212.230.135.2", "212.230.135.1"]}}), encoding="utf-8")
            self.assertEqual(dns_xdp.importar_configuracion(datos, ruta), ["Wi-Fi"])
            guardado = dns_xdp.original_de(datos, "Wi-Fi")
            self.assertEqual(guardado["modo"], "AUTOMATICO")
            self.assertIn("212.230.135.2", dns_xdp.resumen_configuracion(guardado))
            self.assertEqual(datos.windows["dnsConfiguracionExterna"], str(ruta))
            # Sin sustituir no se pisa lo que ya hay.
            self.assertEqual(dns_xdp.importar_configuracion(datos, ruta), [])
            self.assertEqual(dns_xdp.importar_configuracion(datos, ruta, sustituir=True), ["Wi-Fi"])

    def test_importar_archivo_invalido(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            malo = Path(carpeta) / "malo.json"
            malo.write_text("no soy json", encoding="utf-8")
            with self.assertRaises(dns_xdp.ErrorDns):
                dns_xdp.importar_configuracion(datos, malo)
            vacio = Path(carpeta) / "vacio.json"
            vacio.write_text("{}", encoding="utf-8")
            with self.assertRaises(dns_xdp.ErrorDns):
                dns_xdp.importar_configuracion(datos, vacio)

    def test_encuentra_la_configuracion_en_la_carpeta_de_datos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            (Path(carpeta) / dns_xdp.ARCHIVO_XDP_MANAGER).write_text("{}", encoding="utf-8")
            candidatos = dns_xdp.candidatos_configuracion(datos)
            self.assertIn(Path(carpeta) / dns_xdp.ARCHIVO_XDP_MANAGER, candidatos)

    def test_restaurar_con_lo_importado_deja_los_automaticos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            ruta = Path(carpeta) / dns_xdp.ARCHIVO_XDP_MANAGER
            ruta.write_text(json.dumps({"Wi-Fi": {"modo": "AUTOMATICO", "dns": ["212.230.135.2"]}}), encoding="utf-8")
            dns_xdp.importar_configuracion(datos, ruta)
            ordenes = []
            original, original_activo = dns_xdp._powershell_elevado, dns_xdp.activo
            dns_xdp._powershell_elevado = lambda comando, timeout=0, comprobar=None: ordenes.append(comando) or "OK"
            dns_xdp.activo = lambda nombre: False
            try:
                mensaje = dns_xdp.restaurar(datos, "Wi-Fi")
            finally:
                dns_xdp._powershell_elevado, dns_xdp.activo = original, original_activo
            self.assertIn("-ResetServerAddresses", ordenes[0])
            self.assertIn("automáticos", mensaje)

    def test_restaurar_devuelve_los_dns_manuales(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            ruta = dns_xdp.ruta_original(datos)
            ruta.write_text(json.dumps({"Wi-Fi": {"modo": "MANUAL", "dns": ["1.1.1.1", "1.0.0.1"]}}), encoding="utf-8")
            ordenes = []
            original_elevado, original_activo = dns_xdp._powershell_elevado, dns_xdp.activo
            dns_xdp._powershell_elevado = lambda comando, timeout=0, comprobar=None: ordenes.append(comando) or "OK"
            dns_xdp.activo = lambda nombre: False
            try:
                mensaje = dns_xdp.restaurar(datos, "Wi-Fi")
            finally:
                dns_xdp._powershell_elevado, dns_xdp.activo = original_elevado, original_activo
            self.assertIn("1.1.1.1", mensaje)
            self.assertIn("@('1.1.1.1','1.0.0.1')", ordenes[0])
            self.assertNotIn("ResetServerAddresses", ordenes[0])


if __name__ == "__main__":
    unittest.main()
