"""Pruebas de las reglas de grabación automática, la limpieza y los conflictos.

Todo lo que se prueba aquí es lógica pura: no hace falta ni libmpv ni interfaz.
"""
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tdt import grabacion  # noqa: E402
from tdt.catalogo import Programa  # noqa: E402


def canal(nombre="La 1", tipo="tv"):
    return SimpleNamespace(nombre=nombre, tipo=tipo, epg_id="")


def programa(titulo="Telediario", minutos_desde_ahora=60, duracion=60, descripcion="", episodio=""):
    inicio = time.time() + minutos_desde_ahora * 60
    return Programa(int(inicio), int(inicio + duracion * 60), titulo, descripcion=descripcion, episodio=episodio)


class PruebaCoincidencias(unittest.TestCase):
    def test_busca_en_el_titulo_sin_tildes_ni_mayusculas(self):
        regla = grabacion.regla_nueva("informacion")
        self.assertTrue(grabacion.coincide_regla(regla, canal(), programa("La INFORMACIÓN del día")))

    def test_no_busca_en_la_descripcion_salvo_que_se_pida(self):
        regla = grabacion.regla_nueva("ciclismo")
        prog = programa("Deportes", descripcion="Hoy, ciclismo")
        self.assertFalse(grabacion.coincide_regla(regla, canal(), prog))
        regla["campo"] = "todo"
        self.assertTrue(grabacion.coincide_regla(regla, canal(), prog))

    def test_canal_concreto(self):
        regla = grabacion.regla_nueva("Telediario", "La 1")
        self.assertTrue(grabacion.coincide_regla(regla, canal("La 1"), programa()))
        self.assertFalse(grabacion.coincide_regla(regla, canal("La 2"), programa()))

    def test_solo_favoritos(self):
        regla = grabacion.regla_nueva("Telediario")
        regla["soloFavoritos"] = True
        self.assertFalse(grabacion.coincide_regla(regla, canal(), programa(), favorito=False))
        self.assertTrue(grabacion.coincide_regla(regla, canal(), programa(), favorito=True))

    def test_franja_horaria(self):
        regla = grabacion.regla_nueva("Telediario")
        prog = programa()
        hora = time.localtime(prog.inicio)
        regla["desde"] = time.strftime("%H:%M", hora)
        regla["hasta"] = "23:59" if hora.tm_hour < 23 else "23:59"
        self.assertTrue(grabacion.coincide_regla(regla, canal(), prog))
        regla["desde"], regla["hasta"] = "00:00", "00:01"
        self.assertEqual(grabacion.coincide_regla(regla, canal(), prog), hora.tm_hour == 0 and hora.tm_min <= 1)

    def test_dias_de_la_semana(self):
        regla = grabacion.regla_nueva("Telediario")
        prog = programa()
        dia = time.localtime(prog.inicio).tm_wday
        regla["dias"] = [dia]
        self.assertTrue(grabacion.coincide_regla(regla, canal(), prog))
        regla["dias"] = [(dia + 1) % 7]
        self.assertFalse(grabacion.coincide_regla(regla, canal(), prog))

    def test_regla_parada(self):
        regla = grabacion.regla_nueva("Telediario")
        regla["activa"] = False
        self.assertFalse(grabacion.coincide_regla(regla, canal(), programa()))


class PruebaRepeticiones(unittest.TestCase):
    def test_mismo_episodio_no_se_repite(self):
        regla = grabacion.regla_nueva("Serie")
        c, p = canal(), programa("Serie", episodio="T1 E2")
        entrada = grabacion.nueva_programada(c, p)
        self.assertTrue(grabacion.es_repeticion(regla, [entrada], c, p))
        otro = programa("Serie", minutos_desde_ahora=1500, episodio="T1 E3")
        self.assertFalse(grabacion.es_repeticion(regla, [entrada], c, otro))

    def test_solo_la_primera_vez(self):
        regla = grabacion.regla_nueva("Serie")
        regla["repeticiones"] = "titulo"
        c = canal()
        entrada = grabacion.nueva_programada(c, programa("Serie", episodio="T1 E2"))
        self.assertTrue(grabacion.es_repeticion(regla, [entrada], c, programa("Serie", 3000, episodio="T9 E9")))

    def test_todas(self):
        regla = grabacion.regla_nueva("Serie")
        regla["repeticiones"] = "todas"
        c = canal()
        entrada = grabacion.nueva_programada(c, programa("Serie"))
        self.assertFalse(grabacion.es_repeticion(regla, [entrada], c, programa("Serie")))

    def test_una_vez_por_semana(self):
        regla = grabacion.regla_nueva("Serie")
        regla["repeticiones"] = "semana"
        c = canal()
        entrada = grabacion.nueva_programada(c, programa("Serie"))
        self.assertTrue(grabacion.es_repeticion(regla, [entrada], c, programa("Serie", 60 * 24 * 3)))
        self.assertFalse(grabacion.es_repeticion(regla, [entrada], c, programa("Serie", 60 * 24 * 9)))

    def test_sin_episodio_la_reposicion_del_mismo_dia_cuenta_como_repeticion(self):
        regla = grabacion.regla_nueva("Cine")
        c = canal()
        entrada = grabacion.nueva_programada(c, programa("Cine de tarde"))
        self.assertTrue(grabacion.es_repeticion(regla, [entrada], c, programa("Cine de tarde", 60 * 6)))
        self.assertFalse(grabacion.es_repeticion(regla, [entrada], c, programa("Cine de tarde", 60 * 30)))


class PruebaProgramadasDeReglas(unittest.TestCase):
    def test_programa_lo_que_encaja(self):
        regla = grabacion.regla_nueva("Telediario")
        c = canal()
        candidatos = [(c, [programa("Telediario 1"), programa("Otra cosa", 200), programa("Telediario 2", 400)], False)]
        nuevas = grabacion.programadas_de_reglas([regla], candidatos, [])
        self.assertEqual([n["titulo"] for n in nuevas], ["Telediario 1", "Telediario 2"])
        self.assertEqual(nuevas[0]["regla"], "Telediario")

    def test_no_repite_lo_ya_programado(self):
        regla = grabacion.regla_nueva("Telediario")
        c = canal()
        prog = programa("Telediario 1")
        entradas = [grabacion.nueva_programada(c, prog, regla["antes"], regla["despues"], regla["texto"])]
        self.assertEqual(grabacion.programadas_de_reglas([regla], [(c, [prog], False)], entradas), [])

    def test_respeta_el_maximo(self):
        regla = grabacion.regla_nueva("Cine")
        regla["maximo"] = 1
        regla["repeticiones"] = "todas"
        c = canal()
        programas = [programa("Cine 1", 100), programa("Cine 2", 300), programa("Cine 3", 500)]
        self.assertEqual(len(grabacion.programadas_de_reglas([regla], [(c, programas, False)], [])), 1)

    def test_no_mira_mas_alla_del_limite(self):
        regla = grabacion.regla_nueva("Cine")
        c = canal()
        lejano = programa("Cine de la semana que viene", 60 * 24 * 20)
        self.assertEqual(grabacion.programadas_de_reglas([regla], [(c, [lejano], False)], []), [])

    def test_aplica_los_margenes_de_la_regla(self):
        regla = grabacion.regla_nueva("Cine")
        regla["antes"], regla["despues"] = 3, 7
        c, prog = canal(), programa("Cine")
        nueva = grabacion.programadas_de_reglas([regla], [(c, [prog], False)], [])[0]
        self.assertEqual(nueva["inicio"], int(prog.inicio) - 180)
        self.assertEqual(nueva["fin"], int(prog.fin) + 420)


class PruebaConflictos(unittest.TestCase):
    def test_detecta_solapes(self):
        ahora = time.time()
        entradas = [{"canal": f"C{i}", "tipo": "tv", "titulo": "x", "inicio": int(ahora + 60),
                     "fin": int(ahora + 3600), "estado": "pendiente"} for i in range(4)]
        self.assertTrue(grabacion.conflictos(entradas, maximo=3))
        self.assertFalse(grabacion.conflictos(entradas, maximo=4))

    def test_sin_solape_no_hay_conflicto(self):
        ahora = time.time()
        entradas = [{"canal": "A", "tipo": "tv", "titulo": "x", "inicio": int(ahora + 60), "fin": int(ahora + 600), "estado": "pendiente"},
                    {"canal": "B", "tipo": "tv", "titulo": "y", "inicio": int(ahora + 900), "fin": int(ahora + 1200), "estado": "pendiente"}]
        self.assertFalse(grabacion.conflictos(entradas, maximo=1))


class PruebaLimpieza(unittest.TestCase):
    def test_nombre_del_programa(self):
        self.assertEqual(grabacion.nombre_programa("La 1 - Telediario - 20260908-2100"), "La 1 - Telediario")
        self.assertEqual(grabacion.nombre_programa("La 1 - Telediario - 20260908-2100 (2)"), "La 1 - Telediario")
        self.assertEqual(grabacion.nombre_programa("grabacion suelta"), "grabacion suelta")

    def test_podar_historial(self):
        ahora = time.time()
        entradas = [
            {"canal": "A", "titulo": "vieja", "inicio": int(ahora - 200 * 86400), "fin": int(ahora - 199 * 86400), "estado": "hecha"},
            {"canal": "B", "titulo": "reciente", "inicio": int(ahora - 86400), "fin": int(ahora - 82800), "estado": "hecha"},
            {"canal": "C", "titulo": "pendiente", "inicio": int(ahora + 86400), "fin": int(ahora + 90000), "estado": "pendiente"},
        ]
        self.assertEqual(grabacion.podar_programadas(entradas, ahora), 1)
        self.assertEqual([e["titulo"] for e in entradas], ["reciente", "pendiente"])


class PruebaRetencion(unittest.TestCase):
    """La limpieza usa archivos de verdad, en una carpeta temporal."""

    def setUp(self):
        import tempfile

        self.carpeta = Path(tempfile.mkdtemp(prefix="resintoniza_pruebas_"))
        self.datos = SimpleNamespace(raiz=self.carpeta, windows={
            "carpetaGrabaciones": str(self.carpeta), "grabacionesProtegidas": [],
            "retencionDias": 0, "retencionGigas": 0, "retencionPorPrograma": 0})

    def tearDown(self):
        import shutil

        shutil.rmtree(self.carpeta, ignore_errors=True)

    def crear(self, nombre, dias=0, tamano=1000):
        ruta = self.carpeta / nombre
        ruta.write_bytes(b"x" * tamano)
        marca = time.time() - dias * 86400
        import os

        os.utime(ruta, (marca, marca))
        return ruta

    def test_por_dias(self):
        vieja = self.crear("La 1 - A - 20260101-1000.ts", dias=40)
        self.crear("La 1 - B - 20260901-1000.ts", dias=1)
        self.datos.windows["retencionDias"] = 30
        fuera = [a["ruta"] for a in grabacion.sobrantes(self.datos)]
        self.assertEqual(fuera, [vieja])

    def test_protegidas_no_se_borran(self):
        vieja = self.crear("La 1 - A - 20260101-1000.ts", dias=40)
        self.datos.windows["retencionDias"] = 30
        self.datos.windows["grabacionesProtegidas"] = [vieja.name]
        self.assertEqual(grabacion.sobrantes(self.datos), [])

    def test_por_programa(self):
        self.crear("La 1 - Serie - 20260901-1000.ts", dias=1)
        self.crear("La 1 - Serie - 20260902-1000.ts", dias=2)
        vieja = self.crear("La 1 - Serie - 20260903-1000.ts", dias=3)
        self.datos.windows["retencionPorPrograma"] = 2
        self.assertEqual([a["ruta"] for a in grabacion.sobrantes(self.datos)], [vieja])

    def test_limpiar_borra_de_verdad(self):
        vieja = self.crear("La 1 - A - 20260101-1000.ts", dias=40)
        self.datos.windows["retencionDias"] = 30
        self.assertEqual(grabacion.limpiar_carpeta(self.datos), [vieja.name])
        self.assertFalse(vieja.exists())

    def test_margenes_por_canal(self):
        self.datos.windows["margenAntes"], self.datos.windows["margenDespues"] = 1, 3
        self.assertEqual(grabacion.margenes(self.datos, "La 1"), (1, 3))
        self.datos.windows["margenesCanal"] = {"La 1": [5, 10]}
        self.assertEqual(grabacion.margenes(self.datos, "La 1"), (5, 10))
        self.assertEqual(grabacion.margenes(self.datos, "La 2"), (1, 3))

    def test_destino_con_carpeta_por_programa(self):
        self.datos.windows["carpetaPorPrograma"] = True
        destino = grabacion.destino_de(self.datos, "La 1", "Telediario")
        self.assertEqual(destino.parent.name, "Telediario")
        self.assertTrue(destino.parent.is_dir())

    def test_estimacion_de_tamano(self):
        self.assertAlmostEqual(grabacion.tamano_estimado(3600), 22 * 60, delta=1)
        self.assertLess(grabacion.tamano_estimado(3600, solo_audio=True), grabacion.tamano_estimado(3600) / 5)


class PruebaValidacionReglas(unittest.TestCase):
    def test_descarta_lo_que_no_vale(self):
        self.assertEqual(grabacion.validar_reglas([{"texto": "  "}, "no soy un dict", {"sin": "texto"}]), [])

    def test_normaliza(self):
        regla = grabacion.validar_reglas([{"texto": " Cine ", "campo": "raro", "repeticiones": "raro",
                                           "antes": 999, "dias": [1, 9, "x"], "desde": "25:00", "hasta": "22:30"}])[0]
        self.assertEqual(regla["texto"], "Cine")
        self.assertEqual(regla["campo"], "titulo")
        self.assertEqual(regla["repeticiones"], "episodio")
        self.assertEqual(regla["antes"], 60)
        self.assertEqual(regla["dias"], [1])
        self.assertEqual(regla["desde"], "")
        self.assertEqual(regla["hasta"], "22:30")

    def test_texto_legible(self):
        regla = grabacion.regla_nueva("MasterChef", "La 1")
        self.assertIn("MasterChef", grabacion.texto_regla(regla))
        self.assertIn("La 1", grabacion.texto_regla(regla))


if __name__ == "__main__":
    unittest.main()
