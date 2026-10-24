"""Guardado seguro de contraseñas con la protección de datos de Windows (DPAPI).

Las credenciales de un proveedor IPTV no deben quedar en claro en
``data/ajustes.json``. Windows ofrece ``CryptProtectData``: cifra con una clave
derivada de la cuenta de usuario, de modo que el texto cifrado solo se puede
descifrar con esa misma cuenta en ese mismo equipo. No hace falta ninguna
biblioteca externa, se llama con ctypes.

Si la llamada al sistema no estuviera disponible (por ejemplo al ejecutar las
pruebas en otro sistema), se recurre a un ofuscado reversible que **no es
seguro**; en ese caso ``seguro()`` devuelve False y la interfaz lo advierte.
"""
from __future__ import annotations

import base64
import ctypes
import logging
from ctypes import wintypes

registro = logging.getLogger(__name__)
PREFIJO_DPAPI = "dpapi:"
PREFIJO_DEBIL = "simple:"
_DESCRIPCION = "Resintoniza"


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(datos: bytes) -> _BLOB:
    bufer = ctypes.create_string_buffer(datos, len(datos))
    return _BLOB(len(datos), ctypes.cast(bufer, ctypes.POINTER(ctypes.c_char)))


def _leer(blob: _BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _liberar(blob: _BLOB) -> None:
    try:
        ctypes.windll.kernel32.LocalFree(blob.pbData)
    except Exception:
        pass


def seguro() -> bool:
    """True si el cifrado del sistema está disponible en este equipo."""
    try:
        return bool(ctypes.windll.crypt32)
    except Exception:
        return False


def _xor(datos: bytes) -> bytes:
    clave = b"Resintoniza"
    return bytes(b ^ clave[i % len(clave)] for i, b in enumerate(datos))


def cifrar(texto: str) -> str:
    """Devuelve el texto cifrado y en base64, listo para guardar en el JSON."""
    if not texto:
        return ""
    crudo = texto.encode("utf-8")
    try:
        entrada = _blob(crudo)
        salida = _BLOB()
        descripcion = ctypes.c_wchar_p(_DESCRIPCION)
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(entrada), descripcion, None, None, None, 0, ctypes.byref(salida)):
            raise OSError(ctypes.get_last_error())
        try:
            return PREFIJO_DPAPI + base64.b64encode(_leer(salida)).decode("ascii")
        finally:
            _liberar(salida)
    except Exception as error:
        registro.warning("Sin cifrado del sistema para las credenciales: %s", error)
        return PREFIJO_DEBIL + base64.b64encode(_xor(crudo)).decode("ascii")


def descifrar(guardado: str) -> str:
    """Recupera el texto original. Devuelve "" si el valor no se puede descifrar."""
    if not guardado:
        return ""
    if guardado.startswith(PREFIJO_DEBIL):
        try:
            return _xor(base64.b64decode(guardado[len(PREFIJO_DEBIL):])).decode("utf-8")
        except Exception:
            return ""
    if not guardado.startswith(PREFIJO_DPAPI):
        return guardado  # valor antiguo en claro: se vuelve a cifrar al guardar
    try:
        crudo = base64.b64decode(guardado[len(PREFIJO_DPAPI):])
        entrada = _blob(crudo)
        salida = _BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(salida)):
            raise OSError(ctypes.get_last_error())
        try:
            return _leer(salida).decode("utf-8")
        finally:
            _liberar(salida)
    except Exception as error:
        registro.warning("No se pudo descifrar una credencial guardada: %s", error)
        return ""
