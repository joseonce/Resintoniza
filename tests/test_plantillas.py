import unittest

from tdt import datos, plantillas


class Plantillas(unittest.TestCase):
    def test_columnas_en_orden_y_sin_repetir(self):
        self.assertEqual([c for c, _ in plantillas.columnas("{ahora}. {nombre} ({nombre}) {estado}")], ["ahora", "nombre", "estado"])
        self.assertEqual(plantillas.columnas("{ahora}")[0][1], "Ahora")

    def test_validacion_y_valor_por_defecto(self):
        self.assertTrue(plantillas.plantilla_valida("canales_tv", "{nombre} {ahora}"))
        self.assertFalse(plantillas.plantilla_valida("canales_tv", "{inventado}"))
        self.assertFalse(plantillas.plantilla_valida("canales_tv", "sin campos"))
        windows = {"accesibilidad": {"plantillas": {"canales_tv": "{inventado}", "emisiones": "{numero}: {url}"}}}
        self.assertEqual(plantillas.texto_plantilla(windows, "canales_tv"), plantillas.definicion("canales_tv")["default"])
        self.assertEqual(plantillas.texto_plantilla(windows, "emisiones"), "{numero}: {url}")
        self.assertEqual(plantillas.texto_plantilla({}, "listas"), plantillas.definicion("listas")["default"])

    def test_renderizado_limpia_separadores(self):
        texto = plantillas.renderizar("{nombre}. {ahora}. {estado}. {notas}", {"nombre": "La 1", "ahora": "", "estado": "favorito", "notas": ""})
        self.assertEqual(texto, "La 1. favorito.")
        self.assertEqual(plantillas.renderizar("{estado}. {hora}. {titulo}", {"estado": "", "hora": "15:00", "titulo": "Telediario"}), "15:00. Telediario")
        for definicion in plantillas.PLANTILLAS:
            self.assertTrue(plantillas.ejemplo(definicion["clave"], definicion["default"]))
            for _nombre, preset in definicion["presets"]:
                self.assertTrue(plantillas.plantilla_valida(definicion["clave"], preset))

    def test_ajustes_de_accesibilidad(self):
        limpio = datos.validar_ajustes({"windows": {"accesibilidad": {"voz": False, "retardoVoz": 900, "decirFila": "sí", "plantillas": {"canales_tv": "{nombre}", "x": 3}}}})
        acc = limpio["windows"]["accesibilidad"]
        self.assertFalse(acc["voz"])
        self.assertEqual(acc["retardoVoz"], 120)
        self.assertTrue(acc["decirFila"])
        self.assertEqual(acc["plantillas"], {"canales_tv": "{nombre}"})

    def test_actualizacion_libmpv(self):
        self.assertEqual(datos.hash_version("mpv v0.41.0-1023-g69e63f425"), "69e63f425")
        self.assertEqual(datos.hash_paquete("mpv-dev-x86_64-20260903-git-69e63f425a.7z"), "69e63f425a")
        self.assertFalse(datos.actualizacion_disponible("mpv v0.41.0-1023-g69e63f425", "mpv-dev-x86_64-20260903-git-69e63f425a.7z"))
        self.assertTrue(datos.actualizacion_disponible("mpv v0.41.0-1023-g69e63f425", "mpv-dev-x86_64-20260910-git-0123abcdef.7z"))
        self.assertFalse(datos.actualizacion_disponible("", "mpv-dev-x86_64-20260910-git-0123abcdef.7z"))

    def test_colocar_libmpv_con_la_dll_bloqueada(self):
        """El «WinError 32» de oct 2026: la DLL vieja estaba cargada y se intentaba sobrescribir."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as origen, tempfile.TemporaryDirectory() as carpeta:
            extraida = Path(origen) / datos.LIBMPV
            extraida.write_bytes(b"nueva")
            vieja = Path(carpeta) / datos.LIBMPV
            vieja.write_bytes(b"vieja")
            # Abierta sin permiso de borrado, como Windows tiene una DLL cargada.
            with open(vieja, "rb"):
                final = datos.colocar_libmpv(extraida, Path(carpeta))
            self.assertEqual(final.name, datos.DLL_NUEVA)
            self.assertEqual(vieja.read_bytes(), b"vieja")
            self.assertEqual(final.read_bytes(), b"nueva")
            self.assertFalse((Path(carpeta) / datos.DLL_DESCARGA).exists())
            # Libre, se sustituye directamente.
            final = datos.colocar_libmpv(extraida, Path(carpeta))
            self.assertEqual(final.name, datos.LIBMPV)
            self.assertEqual(vieja.read_bytes(), b"nueva")
            # Con en_uso se deja siempre para el siguiente arranque.
            self.assertEqual(datos.colocar_libmpv(extraida, Path(carpeta), en_uso=True).name, datos.DLL_NUEVA)

    def test_actualizacion_pendiente_al_arrancar(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as raiz:
            falso = SimpleNamespace(raiz=Path(raiz))
            carpeta = datos.carpeta_mpv(falso)
            carpeta.mkdir()
            (carpeta / datos.LIBMPV).write_bytes(b"v" * 2_000_000)
            (carpeta / datos.DLL_NUEVA).write_bytes(b"n" * 2_000_000)
            with open(carpeta / datos.LIBMPV, "rb"):
                self.assertFalse(datos.aplicar_actualizacion_pendiente(falso, intentos=2, espera=0.01))
            self.assertTrue(datos.aplicar_actualizacion_pendiente(falso))
            self.assertEqual((carpeta / datos.LIBMPV).read_bytes()[:1], b"n")
            self.assertFalse((carpeta / datos.DLL_NUEVA).exists())
            (carpeta / datos.DLL_NUEVA).write_bytes(b"a medias")
            self.assertFalse(datos.aplicar_actualizacion_pendiente(falso))
            self.assertFalse((carpeta / datos.DLL_NUEVA).exists())

    def test_reinicio(self):
        import os
        import subprocess
        import sys

        orden = datos.orden_reinicio(1234)
        self.assertEqual(orden[-1], "--esperar-pid=1234")
        self.assertEqual(datos.pid_a_esperar(orden[1:]), 1234)
        self.assertIsNone(datos.pid_a_esperar(["--esperar-pid=x"]))
        self.assertIsNone(datos.pid_a_esperar([]))
        hijo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"])
        self.assertTrue(datos.esperar_proceso(hijo.pid, 10))
        hijo.wait()
        self.assertFalse(datos.esperar_proceso(os.getpid(), 0.05))

    def test_comprobar_actualizacion_github(self):
        from unittest.mock import patch
        from tdt import actualizacion

        payload_github = {
            "tag_name": "v1.2.0",
            "html_url": "https://github.com/joseonce/Resintoniza/releases/tag/v1.2.0",
            "body": "Novedades de la versión 1.2.0",
            "assets": [
                {
                    "name": "Resintoniza.zip",
                    "browser_download_url": "https://github.com/joseonce/Resintoniza/releases/download/v1.2.0/Resintoniza.zip"
                }
            ]
        }
        with patch("tdt.actualizacion.descargar_json", return_value=payload_github):
            res = actualizacion.comprobar("https://api.github.com/repos/joseonce/Resintoniza/releases/latest", actual="1.0.0")
            self.assertTrue(res["hay"])
            self.assertEqual(res["version"], "1.2.0")
            self.assertEqual(res["url"], "https://github.com/joseonce/Resintoniza/releases/download/v1.2.0/Resintoniza.zip")
            self.assertEqual(res["notas"], "Novedades de la versión 1.2.0")

            # También admite la URL web de GitHub y la normaliza a la API
            res_web = actualizacion.comprobar("https://github.com/joseonce/Resintoniza/releases/latest", actual="1.0.0")
            self.assertTrue(res_web["hay"])
            self.assertEqual(res_web["version"], "1.2.0")

    def test_normalizar_url_github(self):
        from tdt.actualizacion import normalizar_url
        esperada = "https://api.github.com/repos/joseonce/Resintoniza/releases/latest"
        self.assertEqual(normalizar_url("https://github.com/joseonce/Resintoniza"), esperada)
        self.assertEqual(normalizar_url("https://github.com/joseonce/Resintoniza/"), esperada)
        self.assertEqual(normalizar_url("https://github.com/joseonce/Resintoniza/releases"), esperada)
        self.assertEqual(normalizar_url("https://github.com/joseonce/Resintoniza/releases/latest"), esperada)
        self.assertEqual(normalizar_url("https://github.com/joseonce/Resintoniza.git"), esperada)
        self.assertEqual(normalizar_url(esperada), esperada)
        self.assertEqual(normalizar_url("https://ejemplo.com/version.json"), "https://ejemplo.com/version.json")
        self.assertEqual(normalizar_url(""), "")




if __name__ == "__main__":
    unittest.main()
