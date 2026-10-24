"""Pruebas de numeración, historial, bloqueo, duplicados y búsqueda en la guía."""
import time
import unittest

from tdt import organizar
from tdt.catalogo import PREFIJO_NOMBRE, Canal, Emision, Programa, clave_nombre


class DatosFalsos:
    """Sustituto mínimo de tdt.datos.Datos para las pruebas."""

    def __init__(self):
        self.windows = {}

    def guardar(self):
        pass


def canal(nombre, tipo="tv", ambito="Generalistas", numero=0, origen=""):
    return Canal(nombre, tipo, "España", ambito, "", "", nombre, (Emision("directo", f"http://s/{nombre}.m3u8", "m3u8"),), numero=numero, origen=origen)


class PruebaNumeracion(unittest.TestCase):
    def test_numero_propio_o_posicion(self):
        self.assertEqual(organizar.numero_de(canal("A", numero=17), 0), 17)
        self.assertEqual(organizar.numero_de(canal("A"), 4), 5)

    def test_buscar_por_numero_propio(self):
        canales = [canal("A", numero=10), canal("B", numero=20)]
        self.assertEqual(organizar.buscar_numero(canales, 20), 1)
        self.assertEqual(organizar.buscar_numero(canales, 99), -1)

    def test_buscar_por_posicion_si_no_hay_numeros(self):
        canales = [canal("A"), canal("B"), canal("C")]
        self.assertEqual(organizar.buscar_numero(canales, 3), 2)
        self.assertEqual(organizar.buscar_numero(canales, 4), -1)

    def test_marcador_acumula_cifras(self):
        marcador = organizar.Marcador(espera=10)
        self.assertEqual(marcador.pulsar("1", 100.0), 1)
        self.assertEqual(marcador.pulsar("0", 100.2), 10)
        self.assertEqual(marcador.pulsar("3", 100.4), 103)

    def test_marcador_reinicia_tras_la_espera(self):
        marcador = organizar.Marcador(espera=1.0)
        self.assertEqual(marcador.pulsar("1", 100.0), 1)
        self.assertEqual(marcador.pulsar("2", 105.0), 2)


class PruebaHistorial(unittest.TestCase):
    def test_anota_sin_repetir_y_con_el_ultimo_delante(self):
        datos = DatosFalsos()
        organizar.anotar(datos, canal("A"))
        organizar.anotar(datos, canal("B"))
        organizar.anotar(datos, canal("A"))
        self.assertEqual([h["nombre"] for h in organizar.historial(datos)], ["A", "B"])

    def test_limite(self):
        datos = DatosFalsos()
        for numero in range(organizar.LIMITE_HISTORIAL + 20):
            organizar.anotar(datos, canal(f"C{numero}"))
        self.assertEqual(len(organizar.historial(datos)), organizar.LIMITE_HISTORIAL)

    def test_validacion(self):
        limpio = organizar.validar_historial([{"nombre": "A", "tipo": "tv", "hora": 1}, {"nombre": 5}, "x", {"nombre": "B", "tipo": "otro"}])
        self.assertEqual([h["nombre"] for h in limpio], ["A"])


class PruebaBloqueo(unittest.TestCase):
    def test_pin_y_desbloqueo(self):
        datos = DatosFalsos()
        self.assertFalse(organizar.hay_pin(datos))
        self.assertTrue(organizar.comprobar_pin(datos, "lo que sea"))
        organizar.fijar_pin(datos, "1234")
        self.assertTrue(organizar.hay_pin(datos))
        self.assertTrue(organizar.comprobar_pin(datos, "1234"))
        self.assertFalse(organizar.comprobar_pin(datos, "0000"))
        self.assertNotIn("1234", str(datos.windows["bloqueo"]))
        organizar.fijar_pin(datos, "")
        self.assertFalse(organizar.hay_pin(datos))

    def test_bloqueo_por_canal_y_por_grupo(self):
        datos = DatosFalsos()
        organizar.fijar_pin(datos, "1234")
        uno = canal("A")
        self.assertFalse(organizar.bloqueado(datos, uno))
        organizar.alternar_bloqueo_canal(datos, uno)
        self.assertTrue(organizar.bloqueado(datos, uno))
        organizar.alternar_bloqueo_canal(datos, uno)
        self.assertFalse(organizar.bloqueado(datos, uno))
        organizar.alternar_bloqueo_grupo(datos, "Generalistas")
        self.assertTrue(organizar.bloqueado(datos, uno))

    def test_sin_pin_no_hay_bloqueo(self):
        datos = DatosFalsos()
        uno = canal("A")
        organizar.alternar_bloqueo_canal(datos, uno)
        self.assertFalse(organizar.bloqueado(datos, uno))


class PruebaDuplicados(unittest.TestCase):
    def test_encuentra_y_quita(self):
        canales = [canal("La 1", origen="una"), canal("LA 1 HD", origen="otra"), canal("La 2")]
        repetidos = organizar.duplicados(canales)
        self.assertEqual(len(repetidos), 1)
        quedan = organizar.quitar_duplicados(canales)
        self.assertEqual([c.nombre for c in quedan], ["La 1", "La 2"])

    def test_distinto_medio_no_es_duplicado(self):
        canales = [canal("Cadena", "tv"), canal("Cadena", "radio")]
        self.assertEqual(organizar.duplicados(canales), {})


class PruebaBusquedaGuia(unittest.TestCase):
    def test_busca_en_titulo_y_descripcion_sin_tildes(self):
        ahora = time.time()
        uno, dos = canal("La 1"), canal("La 2")
        guias = {
            "tv": {
                PREFIJO_NOMBRE + clave_nombre("La 1"): [Programa(int(ahora + 60), int(ahora + 3600), "Telediario", "Informativo")],
                PREFIJO_NOMBRE + clave_nombre("La 2"): [Programa(int(ahora + 60), int(ahora + 3600), "Cine", "Película clásica")],
            },
            "radio": {},
        }
        self.assertEqual(len(organizar.buscar_en_guia([uno, dos], guias, "telediario", desde=ahora)), 1)
        self.assertEqual(len(organizar.buscar_en_guia([uno, dos], guias, "pelicula", desde=ahora)), 1)
        self.assertEqual(organizar.buscar_en_guia([uno, dos], guias, "", desde=ahora), [])

    def test_no_devuelve_lo_ya_terminado(self):
        ahora = time.time()
        uno = canal("La 1")
        guias = {"tv": {PREFIJO_NOMBRE + clave_nombre("La 1"): [Programa(int(ahora - 7200), int(ahora - 3600), "Telediario")]}, "radio": {}}
        self.assertEqual(organizar.buscar_en_guia([uno], guias, "telediario", desde=ahora), [])


if __name__ == "__main__":
    unittest.main()
