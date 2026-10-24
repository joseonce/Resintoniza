"""Pruebas de grabación, cuentas Xtream, cifrado, copias y actualizaciones."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from tdt import actualizacion, cifrado, datos as modulo_datos, grabacion, respaldo, sonidos, xtream
from tdt.catalogo import Canal, Emision, Programa


class DatosFalsos:
    def __init__(self, raiz):
        self.raiz = Path(raiz)
        self.windows = {"carpetaGrabaciones": ""}
        self.ajustes = {"windows": self.windows, "userSettings": {}, "tvChannels": [], "radioChannels": [],
                        "tvCommunitiesRemoved": [], "radioCommunitiesRemoved": [],
                        "showOnlyFavoritesTv": False, "showOnlyFavoritesRadio": False}

    def guardar(self):
        pass


class PruebaGrabacion(unittest.TestCase):
    def test_nombre_de_archivo_valido_en_windows(self):
        nombre = grabacion.nombre_archivo('La 1', 'Cine: ¿qué? <raro>/"', 1_700_000_000)
        for prohibido in '<>:"/\\|?*':
            self.assertNotIn(prohibido, nombre)
        self.assertTrue(nombre.endswith(".mkv"))
        self.assertIn("La 1", nombre)

    def test_no_pisa_una_grabacion_anterior(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "grabacion.mkv"
            destino.write_bytes(b"x")
            libre = grabacion.ruta_libre(destino)
            self.assertNotEqual(libre, destino)
            self.assertFalse(libre.exists())

    def test_programada_y_sus_momentos(self):
        canal = Canal("La 1", "tv", "", "", "", "", "La1", (Emision("directo", "http://s/x.m3u8", "m3u8"),))
        ahora = time.time()
        programa = Programa(int(ahora + 600), int(ahora + 4200), "Cine")
        entrada = grabacion.nueva_programada(canal, programa, minutos_antes=2)
        self.assertEqual(entrada["inicio"], int(programa.inicio) - 120)
        self.assertEqual(entrada["estado"], "pendiente")
        self.assertFalse(grabacion.toca_empezar(entrada, ahora))
        self.assertTrue(grabacion.toca_empezar(entrada, entrada["inicio"] + 5))
        entrada["estado"] = "grabando"
        self.assertFalse(grabacion.toca_parar(entrada, entrada["fin"]))
        self.assertTrue(grabacion.toca_parar(entrada, entrada["fin"] + grabacion.MARGEN_FIN + 1))

    def test_caducada(self):
        entrada = {"estado": "pendiente", "inicio": 100, "fin": 200}
        self.assertTrue(grabacion.caducada(entrada, 300))
        self.assertFalse(grabacion.caducada(entrada, 150))

    def test_validacion_de_las_guardadas(self):
        limpias = grabacion.validar_programadas([
            {"canal": "La 1", "tipo": "tv", "titulo": "X", "inicio": 10, "fin": 20, "estado": "raro"},
            {"canal": "La 1", "tipo": "tv", "titulo": "X", "inicio": 30, "fin": 20},
            "basura",
        ])
        self.assertEqual(len(limpias), 1)
        self.assertEqual(limpias[0]["estado"], "pendiente")

    def test_carpeta_personalizada(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            self.assertEqual(grabacion.carpeta(datos), Path(carpeta) / "grabaciones")
            propia = Path(carpeta) / "otra"
            datos.windows["carpetaGrabaciones"] = str(propia)
            self.assertEqual(grabacion.carpeta(datos), propia)
            self.assertTrue(propia.exists())


class PruebaBuffer(unittest.TestCase):
    """El búfer de recepción: tres niveles, y el de en medio por defecto."""

    def test_los_tres_niveles(self):
        from tdt.reproductor import BUFERES, OPCIONES_BUFER, opciones_buffer

        self.assertEqual({clave for _n, clave in BUFERES}, set(OPCIONES_BUFER))
        for nivel in OPCIONES_BUFER:
            ajuste = opciones_buffer(nivel)
            self.assertLess(ajuste["live_start_index"], 0, nivel)
            self.assertGreater(ajuste["readahead"], 0, nivel)
            self.assertGreaterEqual(ajuste["espera"], 1.0, nivel)

    def test_a_mas_margen_mas_de_todo(self):
        from tdt.reproductor import opciones_buffer

        minimo, normal, amplio = (opciones_buffer(n) for n in ("minimo", "normal", "amplio"))
        # Medido: retrasarse mucho del directo no ayuda, así que solo el nivel
        # amplio se aparta, y el margen lo dan el tamaño y la espera.
        self.assertLessEqual(amplio["live_start_index"], normal["live_start_index"])
        self.assertLess(minimo["readahead"], normal["readahead"])
        self.assertLess(normal["readahead"], amplio["readahead"])
        self.assertLess(minimo["espera"], normal["espera"])

    def test_el_manual_de_mpv_pide_esperar_parecido_a_lo_que_se_guarda(self):
        from tdt.reproductor import opciones_buffer

        for nivel in ("normal", "amplio"):
            ajuste = opciones_buffer(nivel)
            self.assertEqual(ajuste["cache_secs"], ajuste["readahead"], nivel)
            self.assertTrue(ajuste["inicial"], nivel)

    def test_nivel_desconocido_usa_el_normal(self):
        from tdt.reproductor import opciones_buffer

        self.assertEqual(opciones_buffer("loquesea"), opciones_buffer("normal"))

    def test_ajuste_guardado(self):
        limpio = modulo_datos.validar_ajustes({})
        self.assertEqual(limpio["windows"]["bufferRecepcion"], "normal")
        limpio = modulo_datos.validar_ajustes({"windows": {"bufferRecepcion": "amplio"}})
        self.assertEqual(limpio["windows"]["bufferRecepcion"], "amplio")
        limpio = modulo_datos.validar_ajustes({"windows": {"bufferRecepcion": "gigante"}})
        self.assertEqual(limpio["windows"]["bufferRecepcion"], "normal")


class PruebaGrabacionFormato(unittest.TestCase):
    def test_la_extension_decide_el_contenedor(self):
        self.assertTrue(grabacion.nombre_archivo("La 1", extension=".ts").endswith(".ts"))
        self.assertTrue(grabacion.nombre_archivo("La 1", extension="ts").endswith(".ts"))
        self.assertTrue(grabacion.nombre_archivo("La 1").endswith(".mkv"))

    def test_se_reconocen_las_grabaciones_de_los_tres_tipos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            destino = grabacion.carpeta(datos)
            for nombre in ("a.ts", "b.mkv", "c.mp4", "d.txt"):
                (destino / nombre).write_bytes(b"x")
            nombres = {a["ruta"].name for a in grabacion.archivos(datos)}
            self.assertEqual(nombres, {"a.ts", "b.mkv", "c.mp4"})


class PruebaCifrado(unittest.TestCase):
    def test_ida_y_vuelta(self):
        guardado = cifrado.cifrar("contraseña secreta")
        self.assertNotIn("contraseña secreta", guardado)
        self.assertEqual(cifrado.descifrar(guardado), "contraseña secreta")

    def test_vacio_y_basura(self):
        self.assertEqual(cifrado.cifrar(""), "")
        self.assertEqual(cifrado.descifrar(""), "")
        self.assertEqual(cifrado.descifrar("dpapi:no-es-base64-valido"), "")


class PruebaXtream(unittest.TestCase):
    def test_cuenta_normaliza_el_servidor_y_cifra(self):
        cuenta = xtream.Cuenta.crear("Mi proveedor", "ejemplo.tv:8080/", "usuario", "clave")
        self.assertEqual(cuenta.servidor, "http://ejemplo.tv:8080")
        self.assertNotIn("clave", cuenta.secreto)
        self.assertEqual(cuenta.contrasena, "clave")

    def test_ida_y_vuelta_por_json(self):
        cuenta = xtream.Cuenta.crear("Proveedor", "http://ejemplo.tv:8080", "usuario", "clave", "radio")
        vuelta = xtream.Cuenta.desde_json(cuenta.a_json())
        self.assertEqual(vuelta.nombre, "Proveedor")
        self.assertEqual(vuelta.tipo, "radio")
        self.assertEqual(vuelta.contrasena, "clave")

    def test_json_invalido(self):
        self.assertIsNone(xtream.Cuenta.desde_json({"servidor": "ftp://x", "usuario": "u"}))
        self.assertIsNone(xtream.Cuenta.desde_json({"servidor": "http://x", "usuario": ""}))
        self.assertIsNone(xtream.Cuenta.desde_json("no soy un objeto"))

    def test_direcciones_de_reproduccion(self):
        cuenta = xtream.Cuenta.crear("P", "http://ejemplo.tv:8080", "usuario", "cl ave")
        self.assertEqual(xtream.url_directo(cuenta, "77"), "http://ejemplo.tv:8080/live/usuario/cl%20ave/77.m3u8")
        self.assertEqual(xtream.url_pelicula(cuenta, "5", "mkv"), "http://ejemplo.tv:8080/movie/usuario/cl%20ave/5.mkv")
        self.assertEqual(xtream.url_episodio(cuenta, "9"), "http://ejemplo.tv:8080/series/usuario/cl%20ave/9.mp4")

    def test_convierte_los_canales_del_servidor(self):
        cuenta = xtream.Cuenta.crear("P", "http://ejemplo.tv", "u", "c")
        respuestas = {
            "get_live_streams": [
                {"name": "La 1", "stream_id": 1, "num": 5, "category_id": "3", "epg_channel_id": "La1.es", "tv_archive": 1, "tv_archive_duration": 3, "stream_icon": "http://i/1.png"},
                {"name": "", "stream_id": 2},
            ],
            "get_live_categories": [{"category_id": "3", "category_name": "Nacionales"}],
        }
        original = xtream._pedir
        xtream._pedir = lambda cuenta_, parametros, timeout=0: respuestas[parametros["action"]]
        try:
            canales = xtream.canales(cuenta)
        finally:
            xtream._pedir = original
        self.assertEqual(len(canales), 1)
        self.assertEqual(canales[0].nombre, "La 1")
        self.assertEqual(canales[0].numero, 5)
        self.assertEqual(canales[0].ambito, "Nacionales")
        self.assertEqual(canales[0].catchup, "xc")
        self.assertEqual(canales[0].catchup_dias, 3)
        self.assertIn("/live/u/c/1.m3u8", canales[0].emisiones[0].url)


class PruebaRespaldo(unittest.TestCase):
    def test_copia_y_lectura(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            datos.ajustes["windows"]["volumen"] = 42
            respaldo.guardar_perfil(datos, "casa")
            destino = Path(carpeta) / "copia.zip"
            respaldo.crear_copia(datos, destino)
            self.assertTrue(destino.exists())
            ajustes, perfiles = respaldo.leer_copia(destino)
            self.assertIn("windows", ajustes)
            self.assertEqual(perfiles, ["casa"])

    def test_copia_invalida(self):
        with tempfile.TemporaryDirectory() as carpeta:
            malo = Path(carpeta) / "no.zip"
            malo.write_text("no soy un zip")
            with self.assertRaises(ValueError):
                respaldo.leer_copia(malo)

    def test_perfiles(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = DatosFalsos(carpeta)
            respaldo.guardar_perfil(datos, "trabajo")
            self.assertEqual(respaldo.listar_perfiles(datos), ["trabajo"])
            self.assertIn("windows", respaldo.cargar_perfil(datos, "trabajo"))
            self.assertTrue(respaldo.eliminar_perfil(datos, "trabajo"))
            self.assertEqual(respaldo.listar_perfiles(datos), [])
            with self.assertRaises(ValueError):
                respaldo.guardar_perfil(datos, "  ")


class PruebaActualizacion(unittest.TestCase):
    def test_comparacion_de_versiones(self):
        self.assertTrue(actualizacion.es_mas_nueva("1.10.0", "1.9.9"))
        self.assertTrue(actualizacion.es_mas_nueva("2.0", "1.99.99"))
        self.assertFalse(actualizacion.es_mas_nueva("1.0.0", "1.0.0"))
        self.assertFalse(actualizacion.es_mas_nueva("0.9", "1.0"))

    def test_sin_direccion_no_se_conecta(self):
        resultado = actualizacion.comprobar("")
        self.assertFalse(resultado["hay"])
        self.assertFalse(resultado["configurada"])
        self.assertIn("no está configurada", actualizacion.resumen(resultado))

    def test_direccion_no_valida(self):
        resultado = actualizacion.comprobar("ftp://ejemplo")
        self.assertTrue(resultado["error"])


class PruebaSonidos(unittest.TestCase):
    def test_genera_los_avisos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            rutas = sonidos.generar(Path(carpeta))
            self.assertEqual(len(rutas), len(sonidos.CATALOGO))
            for ruta in rutas:
                self.assertTrue(ruta.exists())
                self.assertGreater(ruta.stat().st_size, 1000)

    def test_preferencias(self):
        sonidos.configurar(True, {"error": False})
        self.assertTrue(sonidos.activo("inicio"))
        self.assertFalse(sonidos.activo("error"))
        sonidos.configurar(False, {})
        self.assertFalse(sonidos.activo("inicio"))
        sonidos.configurar(True, {})


if __name__ == "__main__":
    unittest.main()
