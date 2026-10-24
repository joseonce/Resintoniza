"""DNS alternativo: para cuando el operador bloquea el acceso a una emisión.

En España, las órdenes de bloqueo que se aplican durante los partidos de fútbol
se ejecutan también por DNS, y de paso dejan sin servicio a páginas y emisiones
que nada tienen que ver. Cambiar el DNS del equipo a un servidor público con
DNS sobre HTTPS suele devolver el acceso a lo que estaba bloqueado por esa vía.

Este módulo es la versión para Resintoniza de la herramienta ``xdp_manager.py``:
usa el resolutor público **XDP AdBlock** (``85.208.114.51``, plantilla
``https://dns.xdp.es/dns-query``), guarda la configuración que tenía el
adaptador antes de tocarla y la restaura cuando se desactiva.

Cambiar el DNS es una configuración del sistema, así que **solo se hace cuando
la persona lo pide** y Windows muestra su propio aviso de permisos: la
aplicación no lo activa por su cuenta ni al iniciarse. Las consultas de estado
(qué adaptadores hay, qué DNS tienen, si resuelve) no necesitan permisos.
"""
from __future__ import annotations

import ctypes
import json
import logging
import subprocess
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

registro = logging.getLogger(__name__)

SERVIDOR = "85.208.114.51"
PLANTILLA_DOH = "https://dns.xdp.es/dns-query"
NOMBRE_SERVICIO = "XDP AdBlock"
ARCHIVO_ORIGINAL = "dns-original.json"
DOMINIO_PRUEBA = "xdp.es"
TIEMPO_MAXIMO = 90


class ErrorDns(RuntimeError):
    """No se pudo consultar o cambiar la configuración de red."""


class PermisoDenegado(ErrorDns):
    """La persona no ha aceptado el aviso de permisos de Windows."""


# --- PowerShell -------------------------------------------------------------
# Los nombres de las conexiones llevan acentos («Conexión de área local») y en la
# línea de órdenes de PowerShell se estropean: la orden se escribe en un archivo
# con marca de orden de bytes y se ejecuta con -File, que sí respeta el texto.
CABECERA_PS = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false\n$ProgressPreference = 'SilentlyContinue'\n"


def _guion(carpeta: Path, comando: str, envolver: str = "") -> Path:
    guion = carpeta / "orden.ps1"
    guion.write_text(CABECERA_PS + (envolver or comando), encoding="utf-8-sig")
    return guion


def _powershell(comando: str, timeout: int = 40) -> str:
    """Ejecuta PowerShell sin permisos especiales y devuelve su salida."""
    carpeta = Path(tempfile.mkdtemp(prefix="resintoniza-ps-"))
    try:
        guion = _guion(carpeta, comando)
        proceso = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(guion)],
            capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ErrorDns(f"No se pudo consultar la configuración de red: {error}") from error
    finally:
        try:
            for archivo in carpeta.iterdir():
                archivo.unlink(missing_ok=True)
            carpeta.rmdir()
        except OSError:
            pass
    salida = (proceso.stdout or b"").decode("utf-8", "replace").strip()
    if proceso.returncode != 0:
        detalle = (proceso.stderr or b"").decode("utf-8", "replace").strip() or salida or "PowerShell devolvió un error."
        raise ErrorDns(detalle[-400:])
    return salida


class _EJECUCION(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
    ]


# Las funciones de Windows se declaran con sus tipos: sin ``argtypes`` ctypes
# manda los identificadores de proceso como enteros de 32 bits y en 64 bits se
# truncan, así que la espera fallaba y se leía el resultado antes de tiempo.
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_EJECUCION)]
_shell32.ShellExecuteExW.restype = wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_kernel32.GetExitCodeProcess.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
ESPERA_ARCHIVO = 10.0     # segundos esperando el resultado del proceso con permisos
ERROR_CANCELADO = 1223    # la persona ha dicho que no en el aviso de Windows


def administrador() -> bool:
    """True si la aplicación ya se está ejecutando con permisos de administrador."""
    try:
        return bool(_shell32.IsUserAnAdmin())
    except Exception:
        return False


def _envoltura(comando: str, salida: Path, listo: Path) -> str:
    """Guion que ejecuta la orden y deja el resultado en un archivo, con un aviso de fin.

    El archivo ``listo.txt`` se escribe el último: hasta que aparece, el archivo
    del resultado puede estar todavía abierto por el proceso con permisos y
    Windows daría «permiso denegado» al leerlo.
    """
    return (
        "$ErrorActionPreference = 'Stop'\n"
        "$resultado = 'OK'\n"
        "try {\n" + comando + "\n} catch {\n  $resultado = 'ERROR: ' + $_.Exception.Message\n}\n"
        f"try {{ Set-Content -LiteralPath '{salida}' -Value $resultado -Encoding UTF8 -Force }} catch {{ }}\n"
        f"try {{ Set-Content -LiteralPath '{listo}' -Value 'FIN' -Encoding UTF8 -Force }} catch {{ }}\n"
        "if ($resultado -like 'ERROR:*') { exit 1 } else { exit 0 }\n")


def _leer_resultado(salida: Path, listo: Path, espera: float = ESPERA_ARCHIVO) -> str:
    """Espera a que el proceso con permisos termine de escribir y lee el resultado.

    Se reintenta durante unos segundos porque el archivo puede estar aún abierto
    (Windows lo cuenta como «permiso denegado») o tardar en verse.
    """
    limite = time.monotonic() + espera
    texto = ""
    while time.monotonic() < limite:
        if listo.exists():
            break
        time.sleep(0.2)
    while time.monotonic() < limite + 2:
        try:
            if salida.exists():
                # utf-8-sig: Windows PowerShell escribe UTF-8 **con** marca de orden
                # de bytes, y esa marca invisible hacía que «ERROR:» no se reconociera.
                texto = salida.read_text(encoding="utf-8-sig", errors="replace").strip().lstrip("﻿")
                if texto:
                    return texto
        except OSError:      # archivo aún abierto por el otro proceso
            registro.debug("El resultado todavía no se puede leer", exc_info=True)
        time.sleep(0.3)
    return texto


def _powershell_elevado(comando: str, timeout: int = TIEMPO_MAXIMO, comprobar=None) -> str:
    """Ejecuta PowerShell con permisos de administrador (Windows pide confirmación).

    El programa sigue funcionando sin permisos especiales: solo se elevan estas
    órdenes concretas, y la persona ve el aviso de Windows antes de nada.

    ``comprobar`` es una función opcional que dice si el cambio ya está hecho.
    Si el proceso termina bien pero no se puede leer su archivo de resultado
    (antivirus, carpeta temporal protegida…), se pregunta al sistema en vez de
    dar por fallado algo que sí se hizo.
    """
    if administrador():
        return _powershell(comando, timeout)
    carpeta = Path(tempfile.mkdtemp(prefix="resintoniza-dns-"))
    salida, listo = carpeta / "salida.txt", carpeta / "listo.txt"
    codigo_salida = None
    try:
        # Los archivos los crea esta parte del programa, sin permisos especiales:
        # así son suyos y el proceso elevado solo tiene que escribir dentro.
        salida.write_text("", encoding="utf-8")
        guion = _guion(carpeta, comando, envolver=_envoltura(comando, salida, listo))
        ejecucion = _EJECUCION()
        ejecucion.cbSize = ctypes.sizeof(_EJECUCION)
        ejecucion.fMask = 0x00000040 | 0x00000400  # conservar el proceso y no mostrar errores del intérprete
        ejecucion.lpVerb = "runas"
        ejecucion.lpFile = "powershell.exe"
        ejecucion.lpParameters = f'-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{guion}"'
        ejecucion.lpDirectory = str(carpeta)
        ejecucion.nShow = 0
        if not _shell32.ShellExecuteExW(ctypes.byref(ejecucion)):
            codigo = ctypes.get_last_error()
            if codigo in (ERROR_CANCELADO, 0):
                raise PermisoDenegado("No se ha dado permiso para cambiar la configuración de red.")
            raise ErrorDns(f"No se pudo pedir permiso de administrador (código {codigo}).")
        if ejecucion.hProcess:
            _kernel32.WaitForSingleObject(wintypes.HANDLE(ejecucion.hProcess), int(timeout * 1000))
            valor = wintypes.DWORD()
            if _kernel32.GetExitCodeProcess(wintypes.HANDLE(ejecucion.hProcess), ctypes.byref(valor)):
                codigo_salida = valor.value
            _kernel32.CloseHandle(wintypes.HANDLE(ejecucion.hProcess))
        texto = _leer_resultado(salida, listo)
    finally:
        try:
            for archivo in carpeta.iterdir():
                archivo.unlink(missing_ok=True)
            carpeta.rmdir()
        except OSError:
            registro.debug("No se pudo limpiar la carpeta temporal del DNS", exc_info=True)
    if texto.startswith("ERROR:"):
        raise ErrorDns(texto[6:].strip())
    if texto:
        return texto
    # Sin resultado legible: manda lo que diga el sistema.
    if comprobar is not None and comprobar():
        registro.info("No se pudo leer el resultado, pero el cambio de DNS sí se aplicó.")
        return "OK"
    if codigo_salida == 0:
        raise ErrorDns("La orden se ejecutó pero el cambio no se ha aplicado. Comprueba el estado de la conexión.")
    if codigo_salida is None:
        raise PermisoDenegado("No se ha dado permiso para cambiar la configuración de red, o la orden no llegó a ejecutarse.")
    raise ErrorDns(f"La orden con permisos de administrador terminó con el código {codigo_salida}.")


# --- consultas (no necesitan permisos) --------------------------------------
def _seguro(nombre: str) -> str:
    return (nombre or "").replace("'", "''")


def adaptadores() -> list[str]:
    """Conexiones de red activas que además tienen configuración DNS (Wi-Fi, Ethernet…).

    Se dejan fuera las que Windows da por levantadas pero no tienen pila de red
    utilizable, y las **virtuales van al final**: la de WSL o la de una máquina
    virtual aparecían las primeras y es fácil cambiarles el DNS por error,
    cuando lo que se quiere tocar es el Wi-Fi o el cable.
    """
    salida = _powershell(
        "$activos = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' }\n"
        "$conDns = (Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue).InterfaceAlias\n"
        "$activos | Where-Object { $conDns -contains $_.Name } |\n"
        "  Select-Object @{n='nombre';e={$_.Name}}, @{n='virtual';e={[bool]$_.Virtual}} |\n"
        "  Sort-Object virtual, nombre | ConvertTo-Json -Compress")
    if not salida:
        return []
    try:
        datos = json.loads(salida)
    except ValueError:
        return [salida.strip()] if salida.strip() else []
    if isinstance(datos, dict):
        datos = [datos]
    nombres = []
    for entrada in datos or []:
        nombre = entrada.get("nombre") if isinstance(entrada, dict) else entrada
        if nombre and str(nombre) not in nombres:
            nombres.append(str(nombre))
    return nombres


def es_virtual(nombre: str) -> bool:
    """True si esa conexión es virtual (WSL, Hyper-V, VPN de una máquina virtual…)."""
    comando = (f"$a = Get-NetAdapter -Name '{_seguro(nombre)}' -ErrorAction SilentlyContinue\n"
               "if ($null -ne $a -and $a.Virtual) { Write-Output 'SI' } else { Write-Output 'NO' }")
    try:
        return _powershell(comando, timeout=25).strip().endswith("SI")
    except ErrorDns:
        return False


def servidores_dns(nombre: str) -> list[str]:
    """Servidores DNS que tiene puestos ese adaptador."""
    salida = _powershell(
        f"(Get-DnsClientServerAddress -InterfaceAlias '{_seguro(nombre)}' -AddressFamily IPv4 -ErrorAction Stop).ServerAddresses | ConvertTo-Json -Compress")
    if not salida:
        return []
    try:
        datos = json.loads(salida)
    except ValueError:
        return [salida.strip()]
    if datos is None:
        return []
    if isinstance(datos, str):
        return [datos]
    return [str(d) for d in datos if d]


def configuracion_actual(nombre: str) -> dict:
    """Qué DNS tiene el adaptador y de dónde vienen.

    Windows guarda en el registro dos valores distintos: ``NameServer`` son los
    que se han puesto a mano y ``DhcpNameServer`` los que da el router. Hay que
    mirar el primero para saber qué había antes y poder devolverlo tal cual;
    la lista que devuelve ``Get-DnsClientServerAddress`` mezcla los dos.
    """
    comando = (
        f"$alias = '{_seguro(nombre)}'\n"
        "$manuales = ''\n$dhcp = ''\n"
        "try {\n"
        "  $a = Get-NetAdapter -Name $alias -ErrorAction Stop\n"
        "  $ruta = 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces\\' + $a.InterfaceGuid\n"
        "  $p = Get-ItemProperty -Path $ruta -ErrorAction Stop\n"
        "  if ($p.NameServer) { $manuales = [string]$p.NameServer }\n"
        "  if ($p.DhcpNameServer) { $dhcp = [string]$p.DhcpNameServer }\n"
        "} catch { }\n"
        "$efectivos = @()\n"
        "try { $efectivos = @((Get-DnsClientServerAddress -InterfaceAlias $alias -AddressFamily IPv4 -ErrorAction Stop).ServerAddresses) } catch { }\n"
        "@{ manuales = $manuales; dhcp = $dhcp; efectivos = $efectivos } | ConvertTo-Json -Compress")
    try:
        datos = json.loads(_powershell(comando) or "{}")
    except ValueError:
        datos = {}
    partir = lambda texto: [t for t in str(texto or "").replace(",", " ").split() if t]  # noqa: E731
    efectivos = datos.get("efectivos") or []
    if isinstance(efectivos, str):
        efectivos = [efectivos]
    manuales = partir(datos.get("manuales"))
    return {
        "modo": "MANUAL" if manuales else "AUTOMATICO",
        "manuales": manuales,
        "dhcp": partir(datos.get("dhcp")),
        "dns": [str(s) for s in efectivos if s],
    }


def modo_dns(nombre: str) -> str:
    """«AUTOMATICO» si los da el router, «MANUAL» si están escritos a mano."""
    return configuracion_actual(nombre)["modo"]


def activo(nombre: str) -> bool:
    """True si ese adaptador ya está usando el DNS alternativo."""
    try:
        return SERVIDOR in servidores_dns(nombre)
    except ErrorDns:
        return False


def resuelve(dominio: str = DOMINIO_PRUEBA, servidor: str = "") -> bool:
    """Comprueba si un dominio se resuelve, con el DNS del sistema o con uno concreto."""
    parametro = f" -Server '{_seguro(servidor)}'" if servidor else ""
    comando = (
        "try {\n"
        f"  $r = Resolve-DnsName -Name '{_seguro(dominio)}' -Type A{parametro} -ErrorAction Stop\n"
        "  if ($r) { Write-Output 'SI' } else { Write-Output 'NO' }\n"
        "} catch { Write-Output 'NO' }")
    try:
        return _powershell(comando, timeout=25).strip().endswith("SI")
    except ErrorDns:
        return False


def estado(nombre: str, comprobar: bool = True) -> dict:
    """Resumen del adaptador: de dónde vienen sus DNS, si el alternativo está puesto y si resuelve."""
    informacion = {"adaptador": nombre, "modo": "", "dns": [], "manuales": [], "dhcp": [], "activo": False, "resuelve": None, "error": ""}
    try:
        informacion.update(configuracion_actual(nombre))
    except ErrorDns as error:
        informacion["error"] = str(error)
        return informacion
    informacion["activo"] = SERVIDOR in informacion["dns"] or SERVIDOR in informacion["manuales"]
    if comprobar:
        informacion["resuelve"] = resuelve()
    return informacion


def texto_estado(informacion: dict) -> str:
    """Frase legible con el estado, para el cuadro de información y la voz."""
    if informacion.get("error"):
        return "No se pudo consultar la configuración de red: " + informacion["error"]
    partes = [f"Conexión {informacion['adaptador']}."]
    if informacion.get("manuales"):
        partes.append("DNS puestos a mano: " + ", ".join(informacion["manuales"]) + ".")
    elif informacion.get("dhcp"):
        partes.append("DNS automáticos del router: " + ", ".join(informacion["dhcp"]) + ".")
    else:
        partes.append("Sin servidores DNS propios.")
    partes.append("El DNS alternativo está activado." if informacion.get("activo") else "El DNS alternativo no está activado.")
    if informacion.get("resuelve") is True:
        partes.append("La resolución de nombres funciona.")
    elif informacion.get("resuelve") is False:
        partes.append("Ahora mismo no se resuelven los nombres de dominio.")
    return " ".join(partes)


# --- configuración guardada -------------------------------------------------
def ruta_original(datos) -> Path:
    return Path(datos.raiz) / ARCHIVO_ORIGINAL


def _leer_original(datos) -> dict:
    ruta = ruta_original(datos)
    if not ruta.exists():
        return {}
    try:
        guardado = json.loads(ruta.read_text(encoding="utf-8"))
        return guardado if isinstance(guardado, dict) else {}
    except (ValueError, OSError):
        return {}


def _escribir_original(datos, configuracion: dict) -> None:
    """Guarda el archivo y comprueba que se ha escrito de verdad."""
    from .datos import guardar_json_atomico

    ruta = ruta_original(datos)
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        guardar_json_atomico(ruta, configuracion)
        vuelto = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ErrorDns(f"No se pudo guardar la copia de la configuración de red en {ruta}: {error}") from error
    if vuelto != configuracion:
        raise ErrorDns(f"La copia de la configuración de red no se guardó bien en {ruta}.")


def carpeta_copias(datos) -> Path:
    ruta = Path(datos.raiz) / "copias-dns"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def copia_de_seguridad(datos, motivo: str = "") -> Path | None:
    """Guarda una copia fechada de la configuración original, antes de tocar nada.

    Así, aunque algo salga mal después (o se borre la copia en uso), siempre
    queda en ``data/copias-dns`` lo que el adaptador tenía antes.
    """
    configuracion = _leer_original(datos)
    if not configuracion:
        return None
    from .datos import guardar_json_atomico

    marca = time.strftime("%Y%m%d-%H%M%S")
    destino = carpeta_copias(datos) / f"dns-original-{marca}{('-' + motivo) if motivo else ''}.json"
    try:
        guardar_json_atomico(destino, configuracion)
    except OSError:
        registro.warning("No se pudo dejar la copia fechada de la configuración de red", exc_info=True)
        return None
    _limpiar_copias(datos)
    return destino


def _limpiar_copias(datos, maximo: int = 20) -> None:
    """Deja solo las últimas copias fechadas, que si no se acumulan."""
    try:
        copias = sorted(carpeta_copias(datos).glob("dns-original-*.json"), key=lambda r: r.stat().st_mtime, reverse=True)
        for sobra in copias[maximo:]:
            sobra.unlink(missing_ok=True)
    except OSError:
        registro.debug("No se pudieron limpiar las copias de la configuración de red", exc_info=True)


def guardar_original(datos, nombre: str) -> dict:
    """Guarda el DNS que tenía el adaptador, si no estaba guardado ya.

    Se guarda lo que estaba escrito a mano, no lo que reparte el router: así,
    al restaurar, una conexión que usaba DNS automáticos vuelve a usarlos.
    Si no se puede leer la configuración o no se puede escribir la copia, se
    lanza ``ErrorDns``: nunca se cambia el DNS sin copia de seguridad.
    """
    configuracion = _leer_original(datos)
    if nombre in configuracion:
        return configuracion[nombre]
    actual = configuracion_actual(nombre)
    manuales = [s for s in actual["manuales"] if s != SERVIDOR]
    if SERVIDOR in actual["manuales"] and not manuales:
        # Ya estaba puesto el alternativo: no hay nada original que guardar.
        return {}
    entrada = {"modo": "MANUAL" if manuales else "AUTOMATICO", "dns": manuales, "dhcp": actual["dhcp"],
               "fecha": int(time.time()), "efectivos": actual.get("dns", [])}
    configuracion[nombre] = entrada
    _escribir_original(datos, configuracion)
    copia_de_seguridad(datos, "antes-de-activar")
    registro.info("Copia de la configuración de red de %s: %s", nombre, entrada)
    return entrada


def olvidar_original(datos, nombre: str) -> None:
    configuracion = _leer_original(datos)
    if configuracion.pop(nombre, None) is not None:
        copia_de_seguridad(datos, "antes-de-restaurar")
        _escribir_original(datos, configuracion)


def exportar_original(datos, destino) -> Path:
    """Guarda la copia de la configuración original donde diga la persona."""
    configuracion = _leer_original(datos)
    if not configuracion:
        raise ErrorDns("Todavía no hay ninguna configuración de red guardada.")
    from .datos import guardar_json_atomico

    destino = Path(destino)
    try:
        guardar_json_atomico(destino, configuracion)
    except OSError as error:
        raise ErrorDns(f"No se pudo guardar la copia: {error}") from error
    return destino


def original_de(datos, nombre: str) -> dict | None:
    return _leer_original(datos).get(nombre)


# --- importar la configuración de la herramienta original --------------------
ARCHIVO_XDP_MANAGER = "xdp_configuracion_original.json"


def candidatos_configuracion(datos) -> list[Path]:
    """Sitios donde puede estar el ``xdp_configuracion_original.json`` de xdp_manager."""
    from .datos import raiz_aplicacion

    posibles = [
        Path(datos.raiz) / ARCHIVO_XDP_MANAGER,
        raiz_aplicacion() / ARCHIVO_XDP_MANAGER,
        Path.home() / "Documents" / ARCHIVO_XDP_MANAGER,
    ]
    guardada = (datos.windows.get("dnsConfiguracionExterna") or "").strip()
    if guardada:
        posibles.insert(0, Path(guardada))
    vistos, salida = set(), []
    for ruta in posibles:
        clave = str(ruta).lower()
        if clave in vistos:
            continue
        vistos.add(clave)
        if ruta.exists():
            salida.append(ruta)
    return salida


def convertir_configuracion(guardado: dict) -> dict:
    """Pasa el formato de ``xdp_manager`` al de aquí.

    Aquella herramienta anotaba en ``dns`` los servidores que estaban en uso, que
    con modo automático son los que reparte el router. Aquí ``dns`` son solo los
    que había escritos a mano, así que en ese caso pasan a ``dhcp`` y la lista de
    manuales queda vacía: al restaurar, la conexión vuelve a pedirlos al router,
    que es lo que de verdad tenía.
    """
    convertido = {}
    for nombre, entrada in (guardado or {}).items():
        if not isinstance(nombre, str) or not isinstance(entrada, dict):
            continue
        servidores = [str(s).strip() for s in entrada.get("dns") or [] if str(s).strip() and str(s).strip() != SERVIDOR]
        modo = str(entrada.get("modo") or "AUTOMATICO").upper()
        if modo == "MANUAL":
            convertido[nombre] = {"modo": "MANUAL", "dns": servidores, "dhcp": []}
        else:
            convertido[nombre] = {"modo": "AUTOMATICO", "dns": [], "dhcp": servidores}
    return convertido


def importar_configuracion(datos, ruta, sustituir: bool = False) -> list[str]:
    """Trae la configuración guardada por xdp_manager. Devuelve los adaptadores importados."""
    ruta = Path(ruta)
    try:
        guardado = json.loads(ruta.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ErrorDns(f"No se pudo leer {ruta.name}: {error}") from error
    if not isinstance(guardado, dict) or not guardado:
        raise ErrorDns(f"{ruta.name} no tiene ninguna configuración de red guardada.")
    convertido = convertir_configuracion(guardado)
    if not convertido:
        raise ErrorDns(f"{ruta.name} no tiene ninguna entrada utilizable.")
    actual = _leer_original(datos)
    importados = []
    for nombre, entrada in convertido.items():
        if nombre in actual and not sustituir:
            continue
        actual[nombre] = entrada
        importados.append(nombre)
    if importados:
        _escribir_original(datos, actual)
    datos.windows["dnsConfiguracionExterna"] = str(ruta)
    return importados


def resumen_configuracion(entrada: dict) -> str:
    """«automáticos del router (212.230.135.2, 212.230.135.1)» o los servidores manuales."""
    if not entrada:
        return ""
    if entrada.get("modo") == "MANUAL" and entrada.get("dns"):
        return "manuales: " + ", ".join(entrada["dns"])
    router = ", ".join(entrada.get("dhcp") or [])
    return f"automáticos del router ({router})" if router else "automáticos del router"


# --- activar y restaurar (necesitan permisos) --------------------------------
def _esperar_estado(nombre: str, queremos_activo: bool, intentos: int = 4) -> bool:
    """Comprueba en el sistema si el cambio ha llegado a aplicarse (tarda un momento)."""
    for numero in range(intentos):
        if activo(nombre) == queremos_activo:
            return True
        time.sleep(0.8 if numero == 0 else 1.5)
    return activo(nombre) == queremos_activo


def doh_registrado() -> bool:
    """¿Está el servidor alternativo dado de alta en Windows como DNS sobre HTTPS?"""
    comando = (f"$s = Get-DnsClientDohServerAddress -ServerAddress '{SERVIDOR}' -ErrorAction SilentlyContinue\n"
               "if ($null -eq $s) { Write-Output 'NO' } else { Write-Output 'SI' }")
    try:
        return _powershell(comando, timeout=25).strip().endswith("SI")
    except ErrorDns:
        return False


def activar(datos, nombre: str) -> str:
    """Pone el DNS alternativo en ese adaptador. Devuelve el texto que informa del resultado."""
    guardar_original(datos, nombre)   # copia de seguridad primero: si falla, no se toca nada
    # El alta como DNS sobre HTTPS va en su propio try: si este Windows no la
    # admite, al menos se cambia el DNS, que es lo que desbloquea la emisión.
    comando = (
        "try {\n"
        f"  $s = Get-DnsClientDohServerAddress -ServerAddress '{SERVIDOR}' -ErrorAction SilentlyContinue\n"
        "  if ($null -eq $s) {\n"
        f"    Add-DnsClientDohServerAddress -ServerAddress '{SERVIDOR}' -DohTemplate '{PLANTILLA_DOH}' -AllowFallbackToUdp $False -AutoUpgrade $True -ErrorAction Stop\n"
        "  } else {\n"
        f"    Set-DnsClientDohServerAddress -ServerAddress '{SERVIDOR}' -DohTemplate '{PLANTILLA_DOH}' -AllowFallbackToUdp $False -AutoUpgrade $True -ErrorAction Stop\n"
        "  }\n"
        "} catch { }\n"
        f"Set-DnsClientServerAddress -InterfaceAlias '{_seguro(nombre)}' -ServerAddresses '{SERVIDOR}' -ErrorAction Stop\n"
        "Clear-DnsClientCache\n")
    _powershell_elevado(comando, comprobar=lambda: activo(nombre))
    if not _esperar_estado(nombre, True):
        raise ErrorDns(f"La orden se ejecutó, pero {nombre} sigue sin usar el DNS alternativo. "
                       "Comprueba si otra aplicación o una directiva del equipo lo está impidiendo.")
    guardado = original_de(datos, nombre)
    volveria = resumen_configuracion(guardado) if guardado else "los DNS automáticos del router"
    cifrado = "con DNS sobre HTTPS" if doh_registrado() else "sin DNS sobre HTTPS (este Windows no lo ha admitido)"
    return f"DNS alternativo activado en {nombre}, {cifrado}. Al restaurar volverá a {volveria}."


def restaurar(datos, nombre: str) -> str:
    """Devuelve el adaptador a la configuración que tenía antes."""
    guardado = original_de(datos, nombre) or {}
    modo = guardado.get("modo", "AUTOMATICO")
    servidores = [s for s in guardado.get("dns", []) if s and s != SERVIDOR]
    if modo == "MANUAL" and servidores:
        direcciones = ",".join(f"'{_seguro(s)}'" for s in servidores)
        orden = f"Set-DnsClientServerAddress -InterfaceAlias '{_seguro(nombre)}' -ServerAddresses @({direcciones}) -ErrorAction Stop\n"
        resumen = "sus servidores DNS de antes: " + ", ".join(servidores)
    else:
        orden = f"Set-DnsClientServerAddress -InterfaceAlias '{_seguro(nombre)}' -ResetServerAddresses -ErrorAction Stop\n"
        resumen = "los DNS automáticos del router"
    # El alta de DNS sobre HTTPS es del equipo, no del adaptador: solo se quita
    # si no queda ninguna otra conexión usando el servidor alternativo.
    comando = (
        orden +
        "Clear-DnsClientCache\n"
        "try {\n"
        f"  $usan = @(Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {{ $_.ServerAddresses -contains '{SERVIDOR}' }})\n"
        f"  $s = Get-DnsClientDohServerAddress -ServerAddress '{SERVIDOR}' -ErrorAction SilentlyContinue\n"
        f"  if (($usan.Count -eq 0) -and ($null -ne $s)) {{ Remove-DnsClientDohServerAddress -ServerAddress '{SERVIDOR}' -Confirm:$false -ErrorAction Stop }}\n"
        "} catch { }\n")
    _powershell_elevado(comando, comprobar=lambda: not activo(nombre))
    if not _esperar_estado(nombre, False):
        # La copia se conserva a propósito: mientras no se haya restaurado de
        # verdad, es lo único que permite volver a la configuración de antes.
        raise ErrorDns(f"La orden se ejecutó, pero {nombre} sigue con el DNS alternativo. "
                       "La copia de tu configuración se conserva para poder intentarlo otra vez.")
    olvidar_original(datos, nombre)
    return f"{nombre} vuelve a usar {resumen}."


def disponible() -> bool:
    """True si el equipo admite estas órdenes (Windows con PowerShell y sus módulos de red)."""
    try:
        return bool(adaptadores())
    except ErrorDns:
        return False
