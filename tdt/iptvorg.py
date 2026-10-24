"""Catálogo público de iptv-org: miles de canales por país, idioma y categoría.

El proyecto iptv-org publica listas M3U ya hechas y una API con los índices::

    https://iptv-org.github.io/iptv/index.m3u              todas
    https://iptv-org.github.io/iptv/countries/es.m3u       por país
    https://iptv-org.github.io/iptv/languages/spa.m3u      por idioma
    https://iptv-org.github.io/iptv/categories/news.m3u    por categoría
    https://iptv-org.github.io/api/countries.json          índices de la API

Como la aplicación ya sabe leer M3U, aquí solo hace falta ofrecer los índices
en español y construir la dirección de la lista elegida. Los nombres de sus
canales llevan la calidad y unos avisos entre corchetes («(1080p)»,
«[Geo-blocked]», «[Not 24/7]») que ``tdt.m3u`` convierte en datos del canal.

iptv-org solo recopila enlaces publicados por terceros: no aloja nada y cada
emisora conserva sus derechos, igual que con el resto de listas.
"""
from __future__ import annotations

import logging

from .datos import descargar_json

registro = logging.getLogger(__name__)
BASE_LISTAS = "https://iptv-org.github.io/iptv/"
BASE_API = "https://iptv-org.github.io/api/"
TIPOS = {
    "pais": ("countries", "País"),
    "idioma": ("languages", "Idioma"),
    "categoria": ("categories", "Categoría"),
}
# Categorías de iptv-org traducidas; las que falten se muestran tal cual.
CATEGORIAS = {
    "animation": "Animación", "auto": "Motor", "business": "Economía", "classic": "Clásicos", "comedy": "Comedia",
    "cooking": "Cocina", "culture": "Cultura", "documentary": "Documentales", "education": "Educación",
    "entertainment": "Entretenimiento", "family": "Familiar", "general": "Generalistas", "kids": "Infantil",
    "legislative": "Parlamentarios", "lifestyle": "Estilo de vida", "movies": "Cine", "music": "Música",
    "news": "Noticias", "outdoor": "Aire libre", "relax": "Relax", "religious": "Religiosos", "science": "Ciencia",
    "series": "Series", "shop": "Teletienda", "sports": "Deportes", "travel": "Viajes", "weather": "El tiempo",
    "undefined": "Sin clasificar",
}
# Índice mínimo por si no hay conexión con la API: lo más buscado desde España.
RESPALDO = {
    "pais": [("España", "es"), ("Andorra", "ad"), ("Argentina", "ar"), ("Chile", "cl"), ("Colombia", "co"),
             ("Estados Unidos", "us"), ("Francia", "fr"), ("Italia", "it"), ("México", "mx"), ("Portugal", "pt"),
             ("Reino Unido", "uk"), ("Alemania", "de")],
    "idioma": [("Español", "spa"), ("Catalán", "cat"), ("Gallego", "glg"), ("Euskera", "eus"), ("Inglés", "eng"),
               ("Francés", "fra"), ("Portugués", "por"), ("Italiano", "ita")],
    "categoria": [(nombre, clave) for clave, nombre in sorted(CATEGORIAS.items(), key=lambda p: p[1])],
}
# Traducciones de los países más habituales; el resto se deja en su idioma original.
PAISES = {
    "Spain": "España", "Andorra": "Andorra", "Argentina": "Argentina", "Chile": "Chile", "Colombia": "Colombia",
    "United States": "Estados Unidos", "France": "Francia", "Italy": "Italia", "Mexico": "México",
    "Portugal": "Portugal", "United Kingdom": "Reino Unido", "Germany": "Alemania", "Brazil": "Brasil",
    "Peru": "Perú", "Uruguay": "Uruguay", "Venezuela": "Venezuela", "Ecuador": "Ecuador", "Cuba": "Cuba",
    "Morocco": "Marruecos", "Netherlands": "Países Bajos", "Belgium": "Bélgica", "Switzerland": "Suiza",
    "Ireland": "Irlanda", "Canada": "Canadá", "Japan": "Japón", "China": "China", "Russia": "Rusia",
}
IDIOMAS = {
    "Spanish": "Español", "Catalan": "Catalán", "Galician": "Gallego", "Basque": "Euskera", "English": "Inglés",
    "French": "Francés", "Portuguese": "Portugués", "Italian": "Italiano", "German": "Alemán", "Arabic": "Árabe",
    "Russian": "Ruso", "Chinese": "Chino", "Japanese": "Japonés",
}


def url_lista(tipo: str, codigo: str) -> str:
    """Dirección de la lista M3U de ese país, idioma o categoría."""
    carpeta = TIPOS.get(tipo, ("", ""))[0]
    codigo = (codigo or "").strip().lower()
    if not carpeta or not codigo:
        return BASE_LISTAS + "index.m3u"
    return f"{BASE_LISTAS}{carpeta}/{codigo}.m3u"


def url_completa() -> str:
    """La lista con todos los canales del proyecto (son muchos miles)."""
    return BASE_LISTAS + "index.m3u"


def _traducir(nombre: str, tabla: dict) -> str:
    return tabla.get(nombre, nombre)


def indice(tipo: str, timeout: int = 20) -> list[tuple[str, str]]:
    """(nombre en español, código) de los países, idiomas o categorías disponibles.

    Si la API no responde se devuelve un índice de respaldo con lo más usado,
    para que se pueda seguir añadiendo listas sin conexión con ese servidor.
    """
    carpeta = TIPOS.get(tipo, ("", ""))[0]
    if not carpeta:
        return []
    try:
        datos = descargar_json(BASE_API + carpeta + ".json", timeout=timeout)
    except Exception as error:
        registro.info("Índice de iptv-org (%s) no disponible: %s", tipo, error)
        return list(RESPALDO.get(tipo, []))
    if not isinstance(datos, list):
        return list(RESPALDO.get(tipo, []))
    salida = []
    for entrada in datos:
        if not isinstance(entrada, dict):
            continue
        codigo = str(entrada.get("code") or entrada.get("id") or "").strip()
        nombre = str(entrada.get("name") or "").strip()
        if not codigo or not nombre:
            continue
        if tipo == "pais":
            nombre = _traducir(nombre, PAISES)
        elif tipo == "idioma":
            nombre = _traducir(nombre, IDIOMAS)
        else:
            nombre = CATEGORIAS.get(codigo.lower(), nombre)
        salida.append((nombre, codigo.lower()))
    salida.sort(key=lambda par: par[0].lower())
    if not salida:
        return list(RESPALDO.get(tipo, []))
    # Lo más buscado desde España, primero: el índice de idiomas trae miles de
    # entradas y la mayoría no tiene ninguna lista publicada.
    preferidos = [c for _n, c in RESPALDO.get(tipo, [])]
    delante = [par for c in preferidos for par in salida if par[1] == c]
    return delante + [par for par in salida if par not in delante]


def nombre_lista(tipo: str, nombre: str) -> str:
    """Nombre con el que se guarda la lista en la aplicación."""
    etiqueta = TIPOS.get(tipo, ("", "listas"))[1]
    return f"iptv-org · {etiqueta}: {nombre}"


def existe(url: str, timeout: int = 15) -> tuple[bool, int]:
    """Comprueba que esa lista existe y cuántos canales trae. (existe, canales).

    No todos los idiomas y categorías del índice tienen lista publicada, así
    que conviene mirarlo antes de guardarla y decírselo a quien la añade.
    """
    import urllib.error
    import urllib.request

    from .datos import USER_AGENT_APP

    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT_APP, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            texto = respuesta.read(8 * 1024 * 1024).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        registro.info("La lista %s no está disponible: %s", url, error)
        return False, 0
    return "#EXTINF" in texto, texto.count("#EXTINF")


# iptv-org no publica guías XMLTV ya generadas: su repositorio de guías hay que
# ejecutarlo para obtenerlas. Sus canales españoles se emparejan igualmente con
# la guía ampliada que ya usa la aplicación, por nombre de canal.
GUIA_PROPIA = False
