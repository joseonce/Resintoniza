"""Plantillas de lectura: qué columnas tiene cada lista y en qué orden se leen.

Igual que en SocialRSS, cada plantilla es un texto con campos entre llaves,
por ejemplo ``{nombre}. {ahora}. {estado}``. Cada campo que aparece es una
columna de la lista accesible, en ese orden; el lector de pantalla lee la
fila columna a columna. El texto completo (con sus separadores) se usa al
leer la fila entera con Ctrl+0.
"""
from __future__ import annotations

import re

ENCABEZADOS = {
    "nombre": "Canal", "ahora": "Ahora", "siguiente": "Después", "categoria": "Categoría", "pais": "País", "estado": "Estado",
    "notas": "Notas", "emisiones": "Emisiones", "fuente": "Lista", "web": "Web",
    "numero": "Número", "tipo": "Tipo", "formato": "Formato", "calidad": "Calidad", "idioma": "Idioma", "zona": "Zona", "url": "Dirección",
    "hora": "Hora", "dia": "Día", "titulo": "Título", "duracion": "Duración", "descripcion": "Descripción", "canal": "Canal",
    "aviso": "Aviso", "fecha": "Fecha", "minutos": "Minutos antes", "accion": "Acción", "tecla": "Tecla",
    "transcurrido": "Lleva grabando", "restante": "Le queda", "tamano": "Tamaño", "archivo": "Archivo",
    "texto": "Busca", "donde": "Dónde", "cuando": "Cuándo", "repeticiones": "Repeticiones", "detalle": "Detalle",
    "respuesta": "Respuesta", "programadas": "Programadas",
    "servidor": "Servidor", "usuario": "Usuario", "valoracion": "Valoración",
    "subtitulo": "Detalles", "episodio": "Episodio", "edad": "Edad recomendada",
}

PLANTILLAS = [
    {
        "clave": "canales_tv", "nombre": "Canales de televisión",
        "campos": [("nombre", "nombre del canal"), ("numero", "número de canal"), ("ahora", "programa en emisión"), ("siguiente", "programa siguiente"), ("categoria", "categoría o comunidad"), ("pais", "país"), ("estado", "favorito, oculto o bloqueado"), ("notas", "solo España, requiere registro, sin emisión"), ("emisiones", "número de emisiones"), ("fuente", "lista de procedencia"), ("web", "web oficial")],
        "default": "{nombre}. {ahora}. {estado}. {notas}",
        "presets": [("Por defecto (canal, ahora, estado, notas)", "{nombre}. {ahora}. {estado}. {notas}"), ("Solo el nombre", "{nombre}"), ("Con número de canal", "{numero}. {nombre}. {ahora}. {estado}"), ("Con categoría", "{nombre}. {categoria}. {ahora}. {estado}"), ("Completo", "{numero}. {nombre}. {categoria}. {pais}. {ahora}. {siguiente}. {estado}. {notas}. {emisiones}")],
        "ejemplo": {"nombre": "La 1", "numero": "1", "ahora": "Ahora 15:00–16:00: Telediario 1", "siguiente": "Después 16:00–17:30: La Promesa", "categoria": "Generalistas", "pais": "España", "estado": "favorito", "notas": "solo España", "emisiones": "2 emisiones", "fuente": "Lista pública · Televisión", "web": "https://www.rtve.es/play/"},
    },
    {
        "clave": "canales_radio", "nombre": "Emisoras de radio",
        "campos": [("nombre", "nombre de la emisora"), ("numero", "número de emisora"), ("ahora", "programa en emisión"), ("siguiente", "programa siguiente"), ("categoria", "categoría o comunidad"), ("pais", "país"), ("estado", "favorito, oculto o bloqueado"), ("notas", "avisos"), ("emisiones", "número de emisiones"), ("fuente", "lista de procedencia"), ("web", "web oficial")],
        "default": "{nombre}. {ahora}. {estado}",
        "presets": [("Por defecto (emisora, ahora, estado)", "{nombre}. {ahora}. {estado}"), ("Solo el nombre", "{nombre}"), ("Con número", "{numero}. {nombre}. {estado}"), ("Con categoría", "{nombre}. {categoria}. {estado}")],
        "ejemplo": {"nombre": "Radio Nacional", "numero": "1", "ahora": "Ahora 15:00–16:00: 14 horas", "siguiente": "Después 16:00–19:00: Las tardes de RNE", "categoria": "Generalistas", "pais": "España", "estado": "", "notas": "", "emisiones": "3 emisiones", "fuente": "Lista pública · Radio", "web": "https://www.rtve.es/radio/"},
    },
    {
        "clave": "emisiones", "nombre": "Emisiones de un canal",
        "campos": [("numero", "número de emisión"), ("tipo", "directo, web oficial, YouTube…"), ("formato", "m3u8, mp3…"), ("calidad", "HD o SD"), ("idioma", "idioma"), ("zona", "solo España, solo Cataluña"), ("url", "dirección")],
        "default": "{numero}: {tipo}. {calidad}. {zona}",
        "presets": [("Por defecto", "{numero}: {tipo}. {calidad}. {zona}"), ("Con formato", "{numero}: {tipo} {formato}. {calidad}. {idioma}. {zona}"), ("Con dirección", "{numero}: {tipo}. {url}")],
        "ejemplo": {"numero": "Emisión 1", "tipo": "Directo", "formato": "m3u8", "calidad": "HD", "idioma": "Castellano", "zona": "solo España", "url": "https://ejemplo.es/directo.m3u8"},
    },
    {
        "clave": "programacion", "nombre": "Programación (guía)",
        "campos": [("hora", "hora de inicio y fin"), ("dia", "día"), ("titulo", "título"), ("categoria", "categoría"), ("estado", "ahora, próximo o terminado"), ("duracion", "duración"), ("descripcion", "descripción"), ("canal", "canal"), ("episodio", "temporada y episodio"), ("valoracion", "valoración"), ("edad", "edad recomendada"), ("subtitulo", "géneros y año")],
        "default": "{estado}. {hora}. {titulo}. {categoria}",
        "presets": [("Por defecto", "{estado}. {hora}. {titulo}. {categoria}"), ("Título primero", "{titulo}. {hora}. {estado}"), ("Con episodio", "{estado}. {hora}. {titulo}. {episodio}. {categoria}"), ("Con día y descripción", "{dia} {hora}. {titulo}. {categoria}. {descripcion}"), ("Completo", "{estado}. {dia} {hora}. {titulo}. {episodio}. {categoria}. {valoracion}. {edad}"), ("Breve", "{hora}. {titulo}")],
        "ejemplo": {"hora": "15:00–16:00", "dia": "lunes 7", "titulo": "Telediario 1", "categoria": "Noticias", "estado": "Ahora", "duracion": "60 minutos", "descripcion": "Informativo de mediodía.", "canal": "La 1", "episodio": "temporada 3, episodio 450", "valoracion": "6.0 sobre 10", "edad": "todos los públicos", "subtitulo": "2026"},
    },
    {
        "clave": "listas", "nombre": "Listas de reproducción",
        "campos": [("nombre", "nombre de la lista"), ("tipo", "televisión o radio"), ("url", "dirección"), ("fuente", "oficial o propia")],
        "default": "{nombre}. {tipo}. {fuente}",
        "presets": [("Por defecto", "{nombre}. {tipo}. {fuente}"), ("Con dirección", "{nombre}. {tipo}. {url}")],
        "ejemplo": {"nombre": "Lista pública · Televisión", "tipo": "Televisión", "url": "https://ejemplo.es/lists/tv.json", "fuente": "oficial"},
    },
    {
        "clave": "favoritos", "nombre": "Canales favoritos (diálogo rápido)",
        "campos": [("nombre", "nombre del canal"), ("tipo", "televisión o radio"), ("ahora", "programa en emisión"), ("categoria", "categoría")],
        "default": "{nombre}. {tipo}. {ahora}",
        "presets": [("Por defecto", "{nombre}. {tipo}. {ahora}"), ("Solo el nombre", "{nombre}"), ("Con categoría", "{nombre}. {categoria}. {tipo}")],
        "ejemplo": {"nombre": "La 1", "tipo": "Televisión", "ahora": "Ahora 15:00–16:00: Telediario 1", "categoria": "Generalistas"},
    },
    {
        "clave": "teclas", "nombre": "Editor de teclas",
        "campos": [("accion", "acción"), ("tecla", "tecla actual"), ("estado", "predeterminada o personalizada")],
        "default": "{accion}. {tecla}. {estado}",
        "presets": [("Por defecto", "{accion}. {tecla}. {estado}"), ("Tecla primero", "{tecla}. {accion}")],
        "ejemplo": {"accion": "Reproducir o pausar", "tecla": "F2", "estado": "predeterminada"},
    },
    {
        "clave": "recordatorios", "nombre": "Recordatorios",
        "campos": [("fecha", "día y hora del programa"), ("canal", "canal"), ("titulo", "título"), ("minutos", "minutos de antelación")],
        "default": "{fecha}. {canal}. {titulo}. {minutos}",
        "presets": [("Por defecto", "{fecha}. {canal}. {titulo}. {minutos}"), ("Breve", "{titulo}. {fecha}")],
        "ejemplo": {"fecha": "07/09 21:00", "canal": "La 1", "titulo": "MasterChef", "minutos": "aviso 5 minutos antes"},
    },
    {
        "clave": "grabaciones", "nombre": "Grabaciones",
        "campos": [("fecha", "día y hora"), ("canal", "canal"), ("titulo", "título"), ("duracion", "duración"), ("estado", "pendiente, grabando o terminada")],
        "default": "{fecha}. {canal}. {titulo}. {estado}",
        "presets": [("Por defecto", "{fecha}. {canal}. {titulo}. {estado}"), ("Con duración", "{fecha}. {canal}. {titulo}. {duracion}. {estado}"), ("Breve", "{titulo}. {fecha}")],
        "ejemplo": {"fecha": "07/09 21:00", "canal": "La 1", "titulo": "MasterChef", "duracion": "90 minutos", "estado": "Pendiente"},
    },
    {
        "clave": "grabaciones_curso", "nombre": "Grabaciones en curso",
        "campos": [("canal", "canal"), ("titulo", "título"), ("estado", "grabando, reanudando o con error"), ("transcurrido", "tiempo grabado"), ("restante", "tiempo que queda"), ("tamano", "tamaño del archivo"), ("archivo", "nombre del archivo")],
        "default": "{canal}. {titulo}. {estado}. {transcurrido}. {restante}. {tamano}",
        "presets": [("Por defecto", "{canal}. {titulo}. {estado}. {transcurrido}. {restante}. {tamano}"), ("Breve", "{canal}. {transcurrido}. {restante}"), ("Con archivo", "{canal}. {titulo}. {transcurrido}. {tamano}. {archivo}")],
        "ejemplo": {"canal": "La 1", "titulo": "MasterChef", "estado": "Grabando", "transcurrido": "lleva 12 minutos", "restante": "quedan 78 minutos", "tamano": "310,4 megabytes", "archivo": "La 1 - MasterChef - 20260908-2200.ts"},
    },
    {
        "clave": "reglas", "nombre": "Reglas de grabación automática",
        "campos": [("texto", "lo que busca"), ("donde", "canal o canales"), ("cuando", "días y horas"), ("repeticiones", "qué hace con las repeticiones"), ("programadas", "grabaciones que ha puesto"), ("estado", "activa o parada")],
        "default": "{texto}. {donde}. {estado}. {programadas}",
        "presets": [("Por defecto", "{texto}. {donde}. {estado}. {programadas}"), ("Completa", "{texto}. {donde}. {cuando}. {repeticiones}. {programadas}. {estado}"), ("Breve", "{texto}. {donde}")],
        "ejemplo": {"texto": "MasterChef", "donde": "en La 1", "cuando": "los lunes entre las 22:00 y las 23:59", "repeticiones": "No repetir el mismo episodio", "programadas": "2 programadas", "estado": "activa"},
    },
    {
        "clave": "comprobacion", "nombre": "Comprobación de canales",
        "campos": [("nombre", "canal"), ("estado", "responde o no"), ("detalle", "qué ha contestado"), ("respuesta", "tiempo de respuesta"), ("tipo", "televisión o radio")],
        "default": "{nombre}. {estado}. {detalle}",
        "presets": [("Por defecto", "{nombre}. {estado}. {detalle}"), ("Con tiempo", "{nombre}. {estado}. {respuesta}. {detalle}"), ("Breve", "{nombre}. {estado}")],
        "ejemplo": {"nombre": "La 1", "estado": "Responde", "detalle": "responde correctamente", "respuesta": "222 milisegundos", "tipo": "Televisión"},
    },
    {
        "clave": "historial", "nombre": "Historial de canales",
        "campos": [("nombre", "canal"), ("tipo", "televisión o radio"), ("fecha", "cuándo se vio")],
        "default": "{nombre}. {tipo}. {fecha}",
        "presets": [("Por defecto", "{nombre}. {tipo}. {fecha}"), ("Solo el nombre", "{nombre}")],
        "ejemplo": {"nombre": "La 1", "tipo": "Televisión", "fecha": "07/09 20:15"},
    },
    {
        "clave": "vod", "nombre": "Películas y series",
        "campos": [("titulo", "título"), ("tipo", "película, serie o episodio"), ("categoria", "categoría"), ("valoracion", "valoración"), ("descripcion", "sinopsis")],
        "default": "{titulo}. {tipo}. {categoria}",
        "presets": [("Por defecto", "{titulo}. {tipo}. {categoria}"), ("Con valoración", "{titulo}. {categoria}. {valoracion}"), ("Con sinopsis", "{titulo}. {categoria}. {descripcion}")],
        "ejemplo": {"titulo": "Amanece que no es poco", "tipo": "Película", "categoria": "Cine español", "valoracion": "8,1", "descripcion": "Un ingeniero y su padre llegan a un pueblo peculiar."},
    },
    {
        "clave": "busqueda_guia", "nombre": "Búsqueda en la guía",
        "campos": [("titulo", "título"), ("canal", "canal"), ("hora", "hora"), ("dia", "día"), ("categoria", "categoría"), ("estado", "ahora o próximo"), ("descripcion", "descripción"), ("episodio", "temporada y episodio"), ("valoracion", "valoración")],
        "default": "{titulo}. {canal}. {dia} {hora}",
        "presets": [("Por defecto", "{titulo}. {canal}. {dia} {hora}"), ("Canal primero", "{canal}. {dia} {hora}. {titulo}"), ("Con episodio", "{titulo}. {episodio}. {canal}. {dia} {hora}"), ("Con descripción", "{titulo}. {canal}. {dia} {hora}. {descripcion}")],
        "ejemplo": {"titulo": "Telediario 1", "canal": "La 1", "hora": "15:00–16:00", "dia": "lunes 7", "categoria": "Noticias", "estado": "Próximo", "descripcion": "Informativo de mediodía.", "episodio": "temporada 3, episodio 450", "valoracion": "6.0 sobre 10"},
    },
    {
        "clave": "cuentas", "nombre": "Cuentas de proveedor",
        "campos": [("nombre", "nombre de la cuenta"), ("servidor", "servidor"), ("usuario", "usuario"), ("tipo", "televisión o radio"), ("estado", "estado de la cuenta")],
        "default": "{nombre}. {servidor}. {estado}",
        "presets": [("Por defecto", "{nombre}. {servidor}. {estado}"), ("Con usuario", "{nombre}. {servidor}. {usuario}. {estado}")],
        "ejemplo": {"nombre": "Mi proveedor", "servidor": "http://ejemplo.tv:8080", "usuario": "usuario1", "tipo": "Televisión", "estado": "activa hasta el 31/12/2026"},
    },
]


def definicion(clave: str) -> dict:
    for plantilla in PLANTILLAS:
        if plantilla["clave"] == clave:
            return plantilla
    raise KeyError(clave)


def encabezado(campo: str) -> str:
    return ENCABEZADOS.get(campo, campo.title())


def columnas(texto: str) -> list[tuple[str, str]]:
    """Campos de una plantilla en orden de aparición, sin repetir, con su encabezado."""
    resultado, vistos = [], set()
    for campo in re.findall(r"{(\w+)}", texto or ""):
        if campo not in vistos:
            vistos.add(campo)
            resultado.append((campo, encabezado(campo)))
    return resultado


def plantilla_valida(clave: str, texto: str) -> bool:
    campos = {c for c, _ in definicion(clave)["campos"]}
    encontrados = re.findall(r"{(\w+)}", texto or "")
    return bool(encontrados) and all(c in campos for c in encontrados)


def texto_plantilla(ajustes_windows: dict, clave: str) -> str:
    """Plantilla configurada (o la predeterminada si falta o no es válida)."""
    guardadas = ajustes_windows.get("accesibilidad", {}).get("plantillas", {}) if ajustes_windows else {}
    texto = guardadas.get(clave, "")
    return texto if plantilla_valida(clave, texto) else definicion(clave)["default"]


def pulir(texto: str) -> str:
    """Limpia separadores sueltos que dejan los campos vacíos."""
    limpio = re.sub(r"\s+", " ", texto or "").strip()
    limpio = re.sub(r"(?:[\s.,;:·—\-–]*\.){2,}", ".", limpio)
    limpio = re.sub(r"^[\s.,;:·—\-–]+", "", limpio)
    limpio = re.sub(r"\.\s*\.", ".", limpio)
    return limpio.strip()


def renderizar(texto: str, valores: dict) -> str:
    """Rellena la plantilla con los valores de una fila y la deja legible."""

    def sustituir(coincidencia):
        return str(valores.get(coincidencia.group(1), "") or "")

    return pulir(re.sub(r"{(\w+)}", sustituir, texto or ""))


def ejemplo(clave: str, texto: str) -> str:
    return renderizar(texto, definicion(clave)["ejemplo"])
