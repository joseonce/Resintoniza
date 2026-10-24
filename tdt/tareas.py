"""Tareas del Programador de Windows y apagado al terminar de grabar.

Una grabación programada solo se hace si la aplicación está abierta a esa hora.
Lo único que arregla eso en Windows es el **Programador de tareas**: se le pide
que abra Resintoniza unos minutos antes de cada grabación pendiente y, si el
equipo está suspendido, que lo despierte (``-WakeToRun``). Al terminar la última
grabación se puede cerrar la aplicación, suspender o apagar el equipo.

Todo se hace con PowerShell, escribiendo la orden en un archivo ``.ps1`` con
marca de orden de bytes y llamándolo con ``-File``: pasar acentos por la línea
de órdenes los rompe (ya pasó con el DNS alternativo).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

registro = logging.getLogger(__name__)
PREFIJO = "Resintoniza-grabacion-"
MINUTOS_ANTES = 5          # cuánto antes de la grabación se abre la aplicación
MAXIMO_TAREAS = 20         # no llenar el Programador de tareas
SEGUNDOS_AVISO = 60        # margen para cancelar un apagado
ACCIONES_FINAL = {
    "nada": "No hacer nada",
    "cerrar": "Cerrar la aplicación",
    "suspender": "Suspender el equipo",
    "apagar": "Apagar el equipo",
}
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def disponible() -> bool:
    return os.name == "nt"


def ejecutable() -> tuple[str, str]:
    """Qué hay que ejecutar para abrir la aplicación: (programa, argumentos)."""
    from .datos import congelada

    if congelada():
        return str(Path(sys.executable).resolve()), ""
    interprete = Path(sys.executable)
    sin_consola = interprete.with_name("pythonw.exe")
    principal = Path(__file__).resolve().parent.parent / "main.py"
    return str(sin_consola if sin_consola.exists() else interprete), f'"{principal}"'


def _powershell(orden: str, espera: int = 60) -> tuple[bool, str]:
    """Ejecuta la orden en un .ps1 con BOM (si va en la línea de órdenes se rompen los acentos)."""
    if not disponible():
        return False, "El Programador de tareas solo existe en Windows."
    archivo = Path(tempfile.gettempdir()) / f"resintoniza_tarea_{int(time.time() * 1000)}.ps1"
    try:
        archivo.write_text(orden, encoding="utf-8-sig")
        proceso = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(archivo)],
            capture_output=True, text=True, timeout=espera, creationflags=SIN_VENTANA)
        salida = (proceso.stdout or "").strip()
        error = (proceso.stderr or "").strip()
        if proceso.returncode != 0:
            registro.warning("PowerShell devolvió %s: %s", proceso.returncode, error or salida)
            return False, error or salida or "no se pudo hablar con el Programador de tareas"
        return True, salida
    except subprocess.TimeoutExpired:
        return False, "el Programador de tareas ha tardado demasiado en responder"
    except Exception as error:  # noqa: BLE001
        registro.exception("Error hablando con el Programador de tareas")
        return False, str(error)
    finally:
        try:
            archivo.unlink()
        except OSError:
            pass


def nombre_tarea(entrada: dict) -> str:
    return f"{PREFIJO}{int(entrada['inicio'])}"


def crear_tarea(nombre: str, momento: float, despertar: bool = True) -> tuple[bool, str]:
    """Crea (o sustituye) una tarea que abre la aplicación a esa hora."""
    programa, argumentos = ejecutable()
    marca = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(momento))
    accion = f"$accion = New-ScheduledTaskAction -Execute '{programa}'"
    if argumentos:
        accion += f" -Argument '{argumentos}'"
    orden = "\n".join([
        "$ErrorActionPreference = 'Stop'",
        accion,
        f"$disparo = New-ScheduledTaskTrigger -Once -At ([datetime]'{marca}')",
        "$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        + ("-WakeToRun " if despertar else "") + "-StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)",
        f"Register-ScheduledTask -TaskName '{nombre}' -Action $accion -Trigger $disparo -Settings $ajustes -Force | Out-Null",
        "Write-Output 'ok'",
    ])
    return _powershell(orden)


def quitar_tarea(nombre: str) -> bool:
    ok, _mensaje = _powershell(
        f"Unregister-ScheduledTask -TaskName '{nombre}' -Confirm:$false -ErrorAction SilentlyContinue; Write-Output 'ok'")
    return ok


def listar_tareas() -> list[str]:
    """Tareas de la aplicación que hay ahora mismo en el Programador."""
    ok, salida = _powershell(
        f"Get-ScheduledTask | Where-Object {{ $_.TaskName -like '{PREFIJO}*' }} | ForEach-Object {{ $_.TaskName }}")
    if not ok:
        return []
    return [linea.strip() for linea in salida.splitlines() if linea.strip()]


def sincronizar(programadas: list[dict], ahora: float | None = None) -> tuple[int, int, str]:
    """Deja en el Programador una tarea por cada grabación pendiente y quita las demás.

    Devuelve (creadas, quitadas, aviso).
    """
    ahora = ahora or time.time()
    pendientes = sorted([e for e in programadas if e.get("estado") == "pendiente" and e["inicio"] > ahora],
                        key=lambda e: e["inicio"])[:MAXIMO_TAREAS]
    quiere = {nombre_tarea(e): e for e in pendientes}
    existen = set(listar_tareas())
    creadas = quitadas = 0
    aviso = ""
    for nombre, entrada in quiere.items():
        if nombre in existen:
            continue
        ok, mensaje = crear_tarea(nombre, entrada["inicio"] - MINUTOS_ANTES * 60)
        if ok:
            creadas += 1
        else:
            aviso = mensaje
            break
    for nombre in existen - set(quiere):
        if quitar_tarea(nombre):
            quitadas += 1
    return creadas, quitadas, aviso


def quitar_todas() -> int:
    quitadas = 0
    for nombre in listar_tareas():
        if quitar_tarea(nombre):
            quitadas += 1
    return quitadas


# --- apagar o suspender al terminar ------------------------------------------
def apagar(modo: str, segundos: int = SEGUNDOS_AVISO) -> tuple[bool, str]:
    """Suspende o apaga el equipo. El apagado se puede cancelar durante un minuto."""
    if not disponible():
        return False, "Solo se puede en Windows."
    try:
        if modo == "apagar":
            subprocess.run(["shutdown", "/s", "/t", str(max(10, segundos)), "/c",
                            "Resintoniza ha terminado de grabar."], check=False, creationflags=SIN_VENTANA)
            return True, f"El equipo se apagará en {max(10, segundos)} segundos; se puede cancelar."
        if modo == "suspender":
            # SetSuspendState duerme el equipo; el primer 0 es «no hibernar».
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], creationflags=SIN_VENTANA)
            return True, "Suspendiendo el equipo."
    except Exception as error:  # noqa: BLE001
        registro.exception("No se pudo %s el equipo", modo)
        return False, str(error)
    return False, "Nada que hacer."


def cancelar_apagado() -> bool:
    if not disponible():
        return False
    try:
        subprocess.run(["shutdown", "/a"], check=False, creationflags=SIN_VENTANA)
        return True
    except Exception:
        return False


# --- inicio automático con Windows ---------------------------------------------
def configurar_arranque_windows(activar: bool) -> bool:
    """Activa o desactiva el inicio automático con Windows en el registro de usuario (HKCU)."""
    if not disponible():
        return False
    try:
        import winreg
        from . import NOMBRE_APP
        clave_run = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, clave_run, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            if activar:
                prog, args = ejecutable()
                comando = f'"{prog}" {args}'.strip()
                winreg.SetValueEx(key, NOMBRE_APP, 0, winreg.REG_SZ, comando)
            else:
                try:
                    winreg.DeleteValue(key, NOMBRE_APP)
                except FileNotFoundError:
                    pass
        return True
    except Exception as error:  # noqa: BLE001
        registro.warning("No se pudo configurar el inicio con Windows: %s", error)
        return False


def comprobar_arranque_windows() -> bool:
    """Comprueba si la clave de arranque con Windows está dada de alta en el registro."""
    if not disponible():
        return False
    try:
        import winreg
        from . import NOMBRE_APP
        clave_run = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, clave_run, 0, winreg.KEY_READ) as key:
            try:
                winreg.QueryValueEx(key, NOMBRE_APP)
                return True
            except FileNotFoundError:
                return False
    except Exception:
        return False

