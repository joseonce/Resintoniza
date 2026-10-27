"""Pruebas del script de actualización transaccional PowerShell en instalaciones desechables."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path

from tdt.actualizacion import UPDATE_SCRIPT

OLD_APP = "from pathlib import Path\nPath('old-started').write_text('ok')\n"
NEW_APP = "import os\nfrom pathlib import Path\nPath(os.environ['RESINTONIZA_UPDATE_READY']).write_text('ready')\n"


class PruebaTransaccionActualizacion(unittest.TestCase):
    def run_case(self, mode: str):
        with tempfile.TemporaryDirectory(prefix="tdt_test_") as root_str:
            root = Path(root_str)
            target = root / "Instalacion Resintoniza"
            work = root / "work"
            target.mkdir()
            work.mkdir()

            (target / "main.py").write_text(OLD_APP, encoding="utf-8")
            (target / "data").mkdir()
            (target / "data" / "ajustes.json").write_text('{"mis": "ajustes"}', encoding="utf-8")
            (target / "data" / "grabaciones").mkdir()
            (target / "data" / "grabaciones" / "grabacion.ts").write_text("video grabacion", encoding="utf-8")
            (target / "personal.txt").write_text("archivo propio del usuario", encoding="utf-8")

            package = work / "package.zip"
            if mode == "invalid_zip":
                package.write_bytes(b"corrupted zip bytes")
            else:
                with zipfile.ZipFile(package, "w") as archive:
                    content = 'raise RuntimeError("error arranque")' if mode == "bad_start" else (
                        'import time; time.sleep(20)' if mode == "no_ready" else NEW_APP
                    )
                    archive.writestr("Resintoniza/main.py", content)
                    archive.writestr("Resintoniza/nuevo_archivo.txt", "nuevo contenido")
                    # Intento de sobrescribir ajustes en el paquete: el instalador debe ignorarlo
                    archive.writestr("Resintoniza/data/ajustes.json", '{"intento": "sobrescribir"}')

            script = UPDATE_SCRIPT
            # Evitar popups interactivos durante las pruebas automáticas
            script = "\n".join(line for line in script.splitlines() if "$shell.Popup(" not in line)

            if mode == "no_ready":
                script = script.replace(".AddSeconds(60)", ".AddSeconds(1)")

            script_path = work / "install.ps1"
            script_path.write_text(script, encoding="utf-8-sig")

            settings = {
                "target": str(target),
                "work": str(work),
                "zip": str(package),
                "token": uuid.uuid4().hex,
                "pid": 2147483647,
                "entry": "main.py",
                "python": sys.executable,
            }
            settings_path = work / "settings.json"
            settings_path.write_text(json.dumps(settings), encoding="utf-8")

            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(script_path), "-Settings", str(settings_path)],
                capture_output=True, timeout=45
            )

            import time
            time.sleep(0.3)

            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            self.assertFalse(work.exists(), "No se limpiaron los temporales")
            self.assertEqual(sorted(p.name for p in root.iterdir()), [target.name])

            # Los datos de usuario SIEMPRE deben preservarse
            self.assertEqual((target / "data" / "ajustes.json").read_text(encoding="utf-8"), '{"mis": "ajustes"}')
            self.assertEqual((target / "data" / "grabaciones" / "grabacion.ts").read_text(encoding="utf-8"), "video grabacion")
            self.assertEqual((target / "personal.txt").read_text(encoding="utf-8"), "archivo propio del usuario")

            if mode == "success":
                self.assertEqual((target / "main.py").read_text(encoding="utf-8"), NEW_APP)
                self.assertTrue((target / "nuevo_archivo.txt").exists())
            else:
                # En caso de fallo o rollback, se conserva la versión anterior
                self.assertEqual((target / "main.py").read_text(encoding="utf-8"), OLD_APP)
                self.assertFalse((target / "nuevo_archivo.txt").exists())

    def test_actualizacion_exitosa(self):
        self.run_case("success")

    def test_actualizacion_zip_invalido(self):
        self.run_case("invalid_zip")

    def test_actualizacion_rollback_si_falla_arranque(self):
        self.run_case("bad_start")


if __name__ == "__main__":
    unittest.main()
