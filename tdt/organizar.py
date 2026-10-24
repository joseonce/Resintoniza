"""Ordenar y encontrar canales cuando la lista tiene miles.

Reúne lo que hace falta al pasar de unos cientos de canales a varias listas
juntas: número de canal para saltar tecleando cifras como en un mando,
historial de lo último visto, bloqueo por PIN de canales o categorías,
detección de duplicados al mezclar listas y búsqueda de un título en toda la
programación.
"""
from __future__ import annotations

import hashlib
import os
import time

from .catalogo import Programa, clave_nombre, plegar, programas_canal

LIMITE_HISTORIAL = 100
CIFRAS_MAXIMAS = 4
ESPERA_CIFRAS = 1.5  # segundos entre cifras para considerar que es el mismo número


# --- numeración -------------------------------------------------------------
def numero_de(canal, posicion: int) -> int:
    """Número del canal: el que trae la lista o, si no, su posición en pantalla."""
    return canal.numero if getattr(canal, "numero", 0) else posicion + 1


def buscar_numero(canales: list, numero: int) -> int:
    """Índice del canal con ese número, o -1. Los números propios de la lista mandan."""
    for indice, canal in enumerate(canales):
        if getattr(canal, "numero", 0) == numero:
            return indice
    return numero - 1 if 1 <= numero <= len(canales) else -1


class Marcador:
    """Acumula las cifras que se teclean seguidas: 1, 0, 3 → canal 103."""

    def __init__(self, espera: float = ESPERA_CIFRAS):
        self.espera = espera
        self.cifras = ""
        self.momento = 0.0

    def pulsar(self, cifra: str, ahora: float | None = None) -> int:
        ahora = ahora if ahora is not None else time.monotonic()
        if ahora - self.momento > self.espera or len(self.cifras) >= CIFRAS_MAXIMAS:
            self.cifras = ""
        self.cifras += cifra
        self.momento = ahora
        return int(self.cifras)

    def reiniciar(self) -> None:
        self.cifras = ""
        self.momento = 0.0


# --- historial --------------------------------------------------------------
def anotar(datos, canal) -> None:
    """Guarda el canal en el historial, sin repetir el último ni pasar del límite."""
    historial = datos.windows.setdefault("historial", [])
    entrada = {"nombre": canal.nombre, "tipo": canal.tipo, "hora": int(time.time())}
    historial[:] = [h for h in historial if not (h.get("nombre") == canal.nombre and h.get("tipo") == canal.tipo)]
    historial.insert(0, entrada)
    del historial[LIMITE_HISTORIAL:]


def historial(datos) -> list[dict]:
    return list(datos.windows.get("historial") or [])


def validar_historial(valor) -> list[dict]:
    limpio = []
    for entrada in valor if isinstance(valor, list) else []:
        if isinstance(entrada, dict) and isinstance(entrada.get("nombre"), str) and entrada.get("tipo") in ("tv", "radio"):
            hora = entrada.get("hora")
            limpio.append({"nombre": entrada["nombre"], "tipo": entrada["tipo"], "hora": hora if isinstance(hora, int) else 0})
    return limpio[:LIMITE_HISTORIAL]


# --- bloqueo por PIN --------------------------------------------------------
def _resumen_pin(pin: str, sal: str) -> str:
    return hashlib.sha256((sal + "|" + (pin or "")).encode("utf-8")).hexdigest()


def bloqueo(datos) -> dict:
    valor = datos.windows.get("bloqueo")
    return valor if isinstance(valor, dict) else {}


def validar_bloqueo(valor) -> dict:
    if not isinstance(valor, dict):
        valor = {}
    canales = [c for c in valor.get("canales") or [] if isinstance(c, str)]
    grupos = [g for g in valor.get("grupos") or [] if isinstance(g, str)]
    return {
        "hash": valor.get("hash") if isinstance(valor.get("hash"), str) else "",
        "sal": valor.get("sal") if isinstance(valor.get("sal"), str) else "",
        "canales": list(dict.fromkeys(canales)),
        "grupos": list(dict.fromkeys(grupos)),
    }


def hay_pin(datos) -> bool:
    estado = bloqueo(datos)
    return bool(estado.get("hash") and estado.get("sal"))


def fijar_pin(datos, pin: str) -> None:
    """Guarda el PIN cifrado. Con ``pin`` vacío se quita el bloqueo."""
    estado = validar_bloqueo(bloqueo(datos))
    if not pin:
        estado["hash"], estado["sal"] = "", ""
    else:
        sal = os.urandom(8).hex()
        estado["sal"], estado["hash"] = sal, _resumen_pin(pin, sal)
    datos.windows["bloqueo"] = estado


def comprobar_pin(datos, pin: str) -> bool:
    estado = bloqueo(datos)
    if not estado.get("hash") or not estado.get("sal"):
        return True
    return _resumen_pin(pin, estado["sal"]) == estado["hash"]


def bloqueado(datos, canal) -> bool:
    """True si el canal o su categoría están bloqueados y hay un PIN puesto."""
    if not hay_pin(datos):
        return False
    estado = bloqueo(datos)
    return canal.nombre in (estado.get("canales") or []) or canal.ambito in (estado.get("grupos") or [])


def alternar_bloqueo_canal(datos, canal) -> bool:
    estado = validar_bloqueo(bloqueo(datos))
    lista = estado["canales"]
    if canal.nombre in lista:
        lista.remove(canal.nombre)
        nuevo = False
    else:
        lista.append(canal.nombre)
        nuevo = True
    datos.windows["bloqueo"] = estado
    return nuevo


def alternar_bloqueo_grupo(datos, grupo: str) -> bool:
    estado = validar_bloqueo(bloqueo(datos))
    lista = estado["grupos"]
    if grupo in lista:
        lista.remove(grupo)
        nuevo = False
    else:
        lista.append(grupo)
        nuevo = True
    datos.windows["bloqueo"] = estado
    return nuevo


# --- duplicados -------------------------------------------------------------
def duplicados(canales: list) -> dict[str, list]:
    """Canales que aparecen en varias listas, agrupados por nombre normalizado."""
    grupos: dict[str, list] = {}
    for canal in canales:
        grupos.setdefault(f"{canal.tipo}|{clave_nombre(canal.nombre)}", []).append(canal)
    return {clave: lista for clave, lista in grupos.items() if len(lista) > 1}


def quitar_duplicados(canales: list) -> list:
    """Deja solo la primera aparición de cada canal (por nombre normalizado y medio)."""
    vistos: set[str] = set()
    salida = []
    for canal in canales:
        clave = f"{canal.tipo}|{clave_nombre(canal.nombre)}"
        if clave in vistos:
            continue
        vistos.add(clave)
        salida.append(canal)
    return salida


# --- búsqueda en la guía ----------------------------------------------------
def buscar_en_guia(canales: list, guias: dict, texto: str, maximo: int = 400, desde: float | None = None) -> list[tuple]:
    """Programas de cualquier canal cuyo título o descripción contenga ``texto``.

    Devuelve una lista de (canal, programa) ordenada por hora de inicio.
    """
    palabras = plegar(texto).split()
    if not palabras:
        return []
    desde = desde if desde is not None else time.time()
    resultados: list[tuple] = []
    for canal in canales:
        programas = programas_canal(guias.get(canal.tipo, {}), canal)
        for programa in programas:
            if programa.fin <= desde:
                continue
            campo = plegar(f"{programa.titulo} {programa.descripcion}")
            if all(palabra in campo for palabra in palabras):
                resultados.append((canal, programa))
                if len(resultados) >= maximo:
                    break
        if len(resultados) >= maximo:
            break
    resultados.sort(key=lambda par: par[1].inicio)
    return resultados


def texto_programa(canal, programa: Programa) -> str:
    return f"{canal.nombre} · {programa.fecha()} {programa.horario()} · {programa.titulo}"
