"""Publicador a GitHub: crea el repositorio si no existe, sube el código fuente y publica la release con el ZIP limpio."""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

def get_token() -> str:
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"].strip()
    candidatos = [
        Path(__file__).resolve().parent.parent.parent / "youtube1" / "github_token.txt",
        Path(__file__).resolve().parent.parent.parent / "github_token.txt",
        Path(__file__).resolve().parent.parent / "github_token.txt",
    ]
    for c in candidatos:
        if c.exists():
            for line in c.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("ghp_"):
                    return line
    return ""

TOKEN = get_token()
REPO_OWNER = "joseonce"
REPO_NAME = "Resintoniza"
try:
    from tdt import VERSION
except ImportError:
    VERSION = "1.0.1"
TAG_NAME = f"v{VERSION}"
RELEASE_NAME = f"Resintoniza {TAG_NAME}"
RAIZ = Path(__file__).resolve().parent.parent
ZIP_PATH = RAIZ / "build" / "Resintoniza.zip"

HEADERS_AUTH = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "ResintonizaPublisher/1.0"
}


def api_request(url: str, data=None, method=None, headers=None):
    hdrs = dict(HEADERS_AUTH)
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def verificar_o_crear_repositorio():
    print(f"[1/4] Verificando repositorio {REPO_OWNER}/{REPO_NAME} en GitHub...")
    try:
        repo = api_request(f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}")
        print(f"  Repositorio ya existente: {repo.get('html_url')}")
        return repo
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("  Creando nuevo repositorio en GitHub...")
            payload = json.dumps({
                "name": REPO_NAME,
                "description": "Televisión y radio en directo para Windows, accesible y en español",
                "private": False,
                "has_issues": True,
                "has_projects": True,
                "has_wiki": False
            }).encode("utf-8")
            repo = api_request("https://api.github.com/user/repos", data=payload, method="POST",
                               headers={"Content-Type": "application/json"})
            print(f"  Repositorio creado con éxito: {repo.get('html_url')}")
            return repo
        raise


def subir_codigo_fuente():
    print(f"\n[2/4] Preparando y subiendo código fuente a GitHub (rama main)...")
    # Configurar git
    subprocess.run(["git", "init", "-b", "main"], cwd=RAIZ, check=True)
    subprocess.run(["git", "config", "user.name", REPO_OWNER], cwd=RAIZ, check=True)
    subprocess.run(["git", "config", "user.email", f"{REPO_OWNER}@users.noreply.github.com"], cwd=RAIZ, check=True)

    remote_url = f"https://{TOKEN}@github.com/{REPO_OWNER}/{REPO_NAME}.git"
    # Actualizar o añadir remote
    proc = subprocess.run(["git", "remote", "get-url", "origin"], cwd=RAIZ, capture_output=True, text=True)
    if proc.returncode == 0:
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=RAIZ, check=True)
    else:
        subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=RAIZ, check=True)

    # Añadir archivos ignorando los de usuario (.gitignore)
    subprocess.run(["git", "add", "-A"], cwd=RAIZ, check=True)
    subprocess.run(["git", "commit", "-m", f"Versión {VERSION}: Normalización de enlaces de GitHub Releases y soporte en actualizaciones"], cwd=RAIZ, check=False)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=RAIZ, check=True)
    clean_remote = f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git"
    subprocess.run(["git", "remote", "set-url", "origin", clean_remote], cwd=RAIZ, check=True)
    print("  Código fuente subido correctamente a GitHub!")


def crear_o_obtener_release():
    print(f"\n[3/4] Comprobando o creando Release {TAG_NAME}...")
    try:
        rel = api_request(f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/tags/{TAG_NAME}")
        print(f"  Release existente encontrada (ID: {rel.get('id')})")
        return rel
    except urllib.error.HTTPError as e:
        if e.code == 404:
            cuerpo = (
                f"### Resintoniza {TAG_NAME}\n\n"
                "Televisión y radio en directo para Windows, accesible y en español.\n\n"
                "#### Novedades de esta versión:\n"
                "- Compatibilidad y normalización automática de enlaces de GitHub Releases: ahora se pueden introducir tanto enlaces a la API de GitHub como enlaces web del navegador (ej. `https://github.com/joseonce/Resintoniza/releases/latest`), reconociéndose y traduciéndose automáticamente.\n"
                "- Restauración automática de la dirección predeterminada de actualizaciones de GitHub (`https://api.github.com/repos/joseonce/Resintoniza/releases/latest`) en configuraciones existentes que tenían el campo vacío.\n"
                "- Opción en Ajustes > Grabación para elegir el formato de grabaciones de TV entre MP4 y MPEG-TS.\n"
                "- Opciones de inicio minimizado e inicio automático con Windows.\n"
                "- Grabación en segundo plano y programada con margen configurable.\n"
                "- Accesibilidad total con lectores de pantalla (NVDA, JAWS, SAPI).\n\n"
                "#### Descarga:\n"
                "Descarga el archivo `Resintoniza.zip` adjunto abajo, descomprímelo en cualquier carpeta y ejecuta `Resintoniza.exe`."
            )
            payload = json.dumps({
                "tag_name": TAG_NAME,
                "target_commitish": "main",
                "name": RELEASE_NAME,
                "body": cuerpo,
                "draft": False,
                "prerelease": False
            }).encode("utf-8")
            rel = api_request(f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases", data=payload, method="POST",
                              headers={"Content-Type": "application/json"})
            print(f"  Release creada: {rel.get('html_url')}")
            return rel
        raise


def subir_zip_a_release(release):
    print(f"\n[4/4] Subiendo {ZIP_PATH.name} a GitHub Releases...")
    if not ZIP_PATH.exists():
        raise SystemExit(f"No existe {ZIP_PATH}. Ejecuta antes tools/comprimir.py")

    tamano = ZIP_PATH.stat().st_size
    tamano_mb = tamano / (1024 * 1024)
    file_name = ZIP_PATH.name

    # Si ya existía un asset con este nombre, borrarlo antes
    for asset in release.get("assets", []):
        if asset.get("name") == file_name:
            print(f"  Eliminando asset anterior {file_name} (ID: {asset['id']})...")
            req = urllib.request.Request(
                f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/assets/{asset['id']}",
                headers=HEADERS_AUTH,
                method="DELETE"
            )
            with urllib.request.urlopen(req) as resp:
                pass
            print("  Asset anterior eliminado.")
            break

    upload_url = release.get("upload_url", "").split("{")[0] + f"?name={file_name}"
    print(f"  Subiendo {file_name} ({tamano_mb:.2f} MB)...")
    with open(ZIP_PATH, "rb") as f:
        data = f.read()

    headers = dict(HEADERS_AUTH)
    headers["Content-Type"] = "application/zip"
    headers["Content-Length"] = str(tamano)

    req = urllib.request.Request(upload_url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        print(f"  [ÉXITO] Archivo subido correctamente!")
        print(f"  URL de descarga directa: {res.get('browser_download_url')}")


def cerrar_issue_1():
    print("\n[5/5] Comprobando y cerrando Issue #1 en GitHub...")
    try:
        payload = json.dumps({"state": "closed"}).encode("utf-8")
        api_request(f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/1",
                    data=payload, method="PATCH", headers={"Content-Type": "application/json"})
        print("  Issue #1 cerrado con éxito en GitHub.")
    except Exception as err:
        print(f"  Nota al cerrar Issue #1: {err}")


def main():
    repo = verificar_o_crear_repositorio()
    subir_codigo_fuente()
    rel = crear_o_obtener_release()
    subir_zip_a_release(rel)
    cerrar_issue_1()
    print("\n========================================================")
    print(f"  [PUBLICACIÓN COMPLETADA CON ÉXITO]")
    print(f"  Repositorio: {repo.get('html_url')}")
    print(f"  Releases:    {rel.get('html_url')}")
    print("========================================================")


if __name__ == "__main__":
    main()
