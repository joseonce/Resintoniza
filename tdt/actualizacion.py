"""Aviso de versiones nuevas de la propia aplicación.

La comprobación es opcional y se apoya en un archivo JSON publicado por quien
distribuye la aplicación, con esta forma::

    {"version": "1.1.0",
     "url": "https://ejemplo/resintoniza-1.1.0.zip",
     "notas": "Grabación programada y listas M3U.",
     "obligatoria": false}

Mientras no se configure una dirección en los ajustes no se conecta a ningún
sitio: la aplicación lo dice claramente en lugar de fingir que está al día.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Callable

from . import VERSION
from .datos import USER_AGENT_APP, descargar_json, url_http

registro = logging.getLogger(__name__)


def numeros(version: str) -> tuple[int, ...]:
    """«1.10.2-beta» → (1, 10, 2). Sirve para comparar versiones."""
    trozos = re.findall(r"\d+", (version or "").split("+")[0])
    return tuple(int(t) for t in trozos[:4]) or (0,)


def es_mas_nueva(candidata: str, actual: str = VERSION) -> bool:
    nueva, vieja = numeros(candidata), numeros(actual)
    longitud = max(len(nueva), len(vieja))
    nueva += (0,) * (longitud - len(nueva))
    vieja += (0,) * (longitud - len(vieja))
    return nueva > vieja


def normalizar_url(url: str) -> str:
    """Convierte URLs web de GitHub en endpoints de la API de Releases."""
    limpia = (url or "").strip()
    if not limpia:
        return ""
    # Convierte ej. https://github.com/usuario/repo/releases... a https://api.github.com/repos/usuario/repo/releases/latest
    coincidencia = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/(?:releases|tree|blob).*)?/?$", limpia, re.IGNORECASE)
    if coincidencia:
        usuario, repo = coincidencia.group(1), coincidencia.group(2)
        return f"https://api.github.com/repos/{usuario}/{repo}/releases/latest"
    return limpia


def comprobar(url: str, actual: str = VERSION) -> dict:
    """Consulta el manifiesto. Devuelve un diccionario con el resultado.

    Claves: ``hay`` (bool), ``version``, ``url``, ``notas``, ``error`` y
    ``configurada`` (False si todavía no hay dirección de comprobación).
    """
    vacio = {"hay": False, "version": "", "url": "", "notas": "", "error": "", "configurada": bool(url)}
    if not url:
        return vacio
    url = normalizar_url(url)
    if not url_http(url):
        return {**vacio, "error": "La dirección de comprobación debe empezar por https:// o http://."}
    try:
        datos = descargar_json(url, timeout=15)
    except Exception as error:
        registro.info("No se pudo comprobar la versión: %s", error)
        return {**vacio, "error": str(error)}
    if not isinstance(datos, dict):
        return {**vacio, "error": "El archivo de versiones no tiene el formato esperado."}
    # Admite formato propio ('version') y la API de GitHub Releases ('tag_name')
    version = str(datos.get("version") or datos.get("tag_name") or "").strip()
    if version.lower().startswith("v") and len(version) > 1 and version[1].isdigit():
        version = version[1:]
    if not version:
        return {**vacio, "error": "El archivo de versiones no indica ninguna versión."}

    # Dirección de descarga: si es GitHub Releases, buscar el asset .zip
    destino = str(datos.get("url") or datos.get("html_url") or "").strip()
    if isinstance(datos.get("assets"), list):
        for asset in datos["assets"]:
            if isinstance(asset, dict) and str(asset.get("name", "")).lower().endswith(".zip"):
                download_url = str(asset.get("browser_download_url") or "").strip()
                if download_url:
                    destino = download_url
                    break

    notas = str(datos.get("notas") or datos.get("body") or "").strip()
    return {
        "hay": es_mas_nueva(version, actual),
        "version": version,
        "url": destino if url_http(destino) else "",
        "notas": notas,
        "error": "",
        "configurada": True,
    }


def resumen(resultado: dict, actual: str = VERSION) -> str:
    """Frase para la barra de estado y para el diálogo."""
    if not resultado.get("configurada"):
        return "La comprobación de versiones nuevas no está configurada; puedes indicar la dirección en Ajustes."
    if resultado.get("error"):
        return "No se pudo comprobar si hay una versión nueva: " + resultado["error"]
    if resultado.get("hay"):
        notas = " " + resultado["notas"] if resultado.get("notas") else ""
        return f"Hay una versión nueva: {resultado['version']} (tienes la {actual})." + notas
    return f"La aplicación está al día: versión {actual}."


# Script de relevo PowerShell transaccional con copia de seguridad y recuperación automática
UPDATE_SCRIPT = r'''
param([string]$Settings)
$ErrorActionPreference = 'Stop'
$c = Get-Content -LiteralPath $Settings -Raw -Encoding UTF8 | ConvertFrom-Json
$target = [IO.Path]::GetFullPath($c.target)
$parent = Split-Path -Parent $target
$work = [IO.Path]::GetFullPath($c.work)
$stage = Join-Path $parent ('.tdt-stage-' + $c.token)
$backup = Join-Path $parent ('.tdt-backup-' + $c.token)
$failed = Join-Path $parent ('.tdt-failed-' + $c.token)
$extract = Join-Path $work 'extract'
$ready = Join-Path $work 'ready'
$swapped = $false
$installed = $false
$committed = $false
$process = $null

function Retry($Action) {
    for ($i = 0; $i -lt 10; $i++) {
        try { & $Action; return } catch {
            if ($i -eq 9) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
}
function Remove-Owned([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -notin @($stage, $backup, $failed, $work)) { throw 'Ruta de limpieza no autorizada.' }
    if (Test-Path -LiteralPath $full) {
        Retry { Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop }
    }
}
function Move-Owned([string]$From, [string]$To) {
    if ($From -notin @($target, $stage, $backup) -or $To -notin @($target, $backup, $failed)) {
        throw 'Ruta de restauracion no autorizada.'
    }
    if ((Split-Path -Parent $From) -ne $parent -or (Split-Path -Parent $To) -ne $parent) {
        throw 'Las carpetas deben estar junto a la instalacion.'
    }
    Retry { [IO.Directory]::Move($From, $To) }
}
function File-Hash([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)) }
    finally { $stream.Dispose(); $sha.Dispose() }
}
function Copy-Tree([string]$From, [string]$To, [bool]$Package) {
    $argsCopy = @($From, $To, '/E', '/COPY:DAT', '/DCOPY:DAT', '/R:2', '/W:1', '/XJ', '/IS', '/IT')
    if ($Package) {
        $argsCopy += @('/XD', 'cache', 'grabaciones', 'perfiles', 'logs', 'navegador')
        $argsCopy += @('/XF', 'ajustes.json', '*.log', '*.tmp')
    }
    & robocopy.exe @argsCopy | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Error de copia: $LASTEXITCODE" }
}
function Open-App([bool]$CheckReady) {
    if ($CheckReady) { $env:RESINTONIZA_UPDATE_READY = $ready } else { Remove-Item Env:RESINTONIZA_UPDATE_READY -ErrorAction SilentlyContinue }
    $exe = Join-Path $target $c.entry
    if ($c.python) {
        $p = Start-Process -FilePath $c.python -ArgumentList ('"' + $exe + '"') -WorkingDirectory $target -PassThru
    } else {
        $p = Start-Process -FilePath $exe -WorkingDirectory $target -PassThru
    }
    return $p
}
try {
    # Esperar al cierre sin matar otras instalaciones por nombre de ejecutable.
    $old = Get-Process -Id $c.pid -ErrorAction SilentlyContinue
    if ($old -and -not $old.WaitForExit(30000)) { throw 'La aplicacion anterior sigue abierta.' }
    # Cerrar cualquier proceso residual o secundario que se ejecute desde la carpeta de instalacion
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($target, [System.StringComparison]::OrdinalIgnoreCase)
    }
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 500
    New-Item -ItemType Directory -Path $extract | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($c.zip, $extract)
    $source = $extract
    if (Test-Path -LiteralPath (Join-Path $extract 'Resintoniza') -PathType Container) {
        $source = Join-Path $extract 'Resintoniza'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $source $c.entry) -PathType Leaf)) {
        throw 'El paquete no contiene la aplicacion.'
    }
    # La instalacion original no se modifica mientras se prepara la nueva.
    if (Get-ChildItem -LiteralPath $target -Recurse -Force | Where-Object {
        $_.Attributes -band [IO.FileAttributes]::ReparsePoint
    }) { throw 'La instalacion contiene enlaces; se conserva la version anterior.' }
    Copy-Tree $target $stage $false
    foreach ($file in Get-ChildItem -LiteralPath $target -File -Recurse -Force) {
        $rel = $file.FullName.Substring($target.Length + 1)
        if ((File-Hash $file.FullName) -ne (File-Hash (Join-Path $stage $rel))) {
            throw "No se pudo preparar una copia completa: $rel"
        }
    }
    Copy-Tree $source $stage $true
    foreach ($file in Get-ChildItem -LiteralPath $source -File -Recurse) {
        $rel = $file.FullName.Substring($source.Length + 1)
        $parts = $rel -split '\\'
        if ($parts -contains 'cache' -or $parts -contains 'grabaciones' -or $parts -contains 'perfiles' -or $parts -contains 'logs' -or $parts -contains 'navegador') { continue }
        if ($file.Name -like 'ajustes*.json') { continue }
        $dest = Join-Path $stage $rel
        if ((File-Hash $file.FullName) -ne (File-Hash $dest)) {
            throw "La verificacion fallo: $rel"
        }
    }
    Move-Owned $target $backup
    $swapped = $true
    Move-Owned $stage $target
    $installed = $true
    $process = Open-App $true
    $limit = [DateTime]::UtcNow.AddSeconds(60)
    while (-not (Test-Path -LiteralPath $ready)) {
        if ($process.HasExited -or [DateTime]::UtcNow -gt $limit) { throw 'La nueva version no confirmo el arranque.' }
        Start-Sleep -Milliseconds 250
    }
    $committed = $true
} catch {
    $problem = $_.Exception.Message
    if ($swapped -and -not $committed) {
        if ($process -and -not $process.HasExited) {
            & taskkill.exe /PID $process.Id /T /F | Out-Null
            $process.WaitForExit(10000) | Out-Null
        }
        try {
            if ($installed) { Move-Owned $target $failed }
            Move-Owned $backup $target
            $swapped = $false
        } catch {
            $problem += "`nNo se pudo restaurar. La copia recuperable esta en: $backup"
        }
    }
    if (-not $swapped -and -not $old) {
        try { $process = Open-App $false } catch { $problem += "`nNo se pudo abrir la version anterior." }
    } elseif (-not $swapped -and $old.HasExited) {
        try { $process = Open-App $false } catch { $problem += "`nNo se pudo abrir la version anterior." }
    }
    $shell = New-Object -ComObject WScript.Shell
    $shell.Popup("La actualizacion no se completo.`n$problem", 10, 'Actualizacion', 48) | Out-Null
} finally {
    $cleanupErrors = @()
    foreach ($path in @($stage, $failed)) {
        try { Remove-Owned $path } catch { $cleanupErrors += $path }
    }
    if ($committed -or -not $swapped) {
        try { Remove-Owned $backup } catch { $cleanupErrors += $backup }
    }
    try { Remove-Owned $work } catch { $cleanupErrors += $work }
    if ($cleanupErrors.Count) {
        $shell = New-Object -ComObject WScript.Shell
        $shell.Popup(('Windows impidio limpiar estos archivos: ' + ($cleanupErrors -join ', ')), 10, 'Actualizacion', 48) | Out-Null
    }
}
'''


def descargar_actualizacion(
    url: str,
    destino: str | Path,
    callback_progreso: Callable[[int, int, int], None] | None = None,
    cancelar: threading.Event | None = None,
) -> None:
    """Descarga el paquete ZIP de actualización reportando progreso."""
    if not url_http(url):
        raise ValueError("La dirección de descarga no es válida.")
    encabezados = {"User-Agent": USER_AGENT_APP, "Accept": "*/*"}
    peticion = urllib.request.Request(url, headers=encabezados)
    with urllib.request.urlopen(peticion, timeout=30) as respuesta, open(destino, "wb") as salida:
        total = int(respuesta.headers.get("Content-Length", 0))
        descargado = 0
        bloque = 65536
        ultimo_pct = -1

        while True:
            if cancelar and cancelar.is_set():
                salida.close()
                try:
                    os.remove(destino)
                except OSError:
                    pass
                return
            pedazo = respuesta.read(bloque)
            if not pedazo:
                break
            salida.write(pedazo)
            descargado += len(pedazo)
            if total > 0 and callback_progreso:
                pct = int((descargado / total) * 100)
                if pct != ultimo_pct:
                    ultimo_pct = pct
                    callback_progreso(pct, descargado, total)


def lanzar_instalador(zip_path: str | Path, ventana=None) -> None:
    """Prepara y ejecuta el relevo transaccional en PowerShell y cierra la app."""
    from .datos import congelada, raiz_aplicacion

    base_dir = raiz_aplicacion()
    work = tempfile.mkdtemp(prefix="resintoniza_update_")
    try:
        package = os.path.join(work, "package.zip")
        shutil.move(str(zip_path), package)
        settings = {
            "target": str(base_dir),
            "work": str(work),
            "zip": str(package),
            "token": uuid.uuid4().hex,
            "pid": os.getpid(),
            "entry": "Resintoniza.exe" if congelada() else "main.py",
            "python": None if congelada() else sys.executable,
        }
        settings_path = os.path.join(work, "settings.json")
        script_path = os.path.join(work, "install.ps1")
        with open(settings_path, "w", encoding="utf-8") as stream:
            json.dump(settings, stream, ensure_ascii=False)
        with open(script_path, "w", encoding="utf-8-sig") as stream:
            stream.write(UPDATE_SCRIPT)
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden", "-File", script_path, "-Settings", settings_path],
            cwd=tempfile.gettempdir(),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True,
        )
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise

    # Cierre limpio de la interfaz y la aplicación
    try:
        if ventana and hasattr(ventana, "salir"):
            ventana.salir()
        else:
            import wx
            app = wx.GetApp()
            if app:
                top = app.GetTopWindow()
                if top and hasattr(top, "salir"):
                    top.salir()
                else:
                    for win in wx.GetTopLevelWindows():
                        try:
                            win.Close(True)
                        except Exception:
                            pass
                    app.ExitMainLoop()
    except Exception:
        pass
    time.sleep(0.5)
    os._exit(0)

