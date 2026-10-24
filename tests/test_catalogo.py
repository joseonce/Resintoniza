import json
import tempfile
import time
import unittest
from pathlib import Path

from tdt import catalogo, datos, proveedores

RAIZ = Path(__file__).resolve().parent.parent
MUESTRA_TV = {
    "license": {"source": "x", "url": "y"},
    "epg": {"json": "https://www.tdtchannels.com/epg/TV.json"},
    "countries": [
        {"name": "Spain", "ambits": [
            {"name": "Generalistas", "channels": [
                {"name": "La 1", "web": "https://www.rtve.es/play/videos/directo/la-1/", "logo": "", "epg_id": "La1.TV",
                 "options": [{"format": "m3u8", "url": "https://ejemplo.es/la1.m3u8", "geo2": "SP", "res": "HD", "lang": None}], "extra_info": ["GEO"]},
                {"name": "Telecinco", "web": "https://www.mitele.es/directo/telecinco", "logo": "", "epg_id": "Telecinco.TV", "options": [], "extra_info": ["EXTA", "GEO"]},
                {"name": "DMAX", "web": "https://dmax.marca.com/en-directo", "logo": "", "epg_id": "DMax.TV", "options": [], "extra_info": ["NOEM"]},
            ]},
            {"name": "Deportivos", "channels": [
                {"name": "GOL PLAY", "web": "https://www.goltelevision.com/en-directo/gol_live", "logo": "", "epg_id": "Gol.TV",
                 "options": [{"format": "m3u8", "url": "https://geo.dailymotion.com/player/x1k3pa.html?video=k5cyQ3rl70nCl7Fhb5W", "geo2": None, "res": None, "lang": None}], "extra_info": ["EXTB", "UAGB"]},
                {"name": "Canal YT", "web": "https://ejemplo.es", "logo": "", "epg_id": "", "options": [{"format": "youtube", "url": "https://www.youtube.com/embed/live_stream?channel=UC123", "geo2": None, "res": None, "lang": None}], "extra_info": [], "referer": "https://player.ejemplo.es/"},
            ]},
        ]},
    ],
}


class Ajustes(unittest.TestCase):
    def test_valida_exportacion_del_apk(self):
        exportado = {"tvChannels": [{"channelName": "La 1", "favorite": True, "hide": False, "position": 3}], "radioChannels": [], "tvCommunitiesRemoved": ["Int. Asia"], "showOnlyFavoritesTv": True, "userSettings": {"darkMode": "1", "playerSubtitle": "es", "hiddenChannelsVisibility": 2, "closeOnExit": "1"}}
        limpio = datos.validar_ajustes(exportado)
        self.assertEqual(limpio["tvChannels"][0]["position"], 3)
        self.assertEqual(limpio["userSettings"]["playerSubtitle"], "es")
        self.assertEqual(limpio["userSettings"]["hiddenChannelsVisibility"], 2)
        self.assertEqual(limpio["tvCommunitiesRemoved"], ["Int. Asia"])
        self.assertTrue(limpio["showOnlyFavoritesTv"])
        self.assertEqual(limpio["windows"]["tamanoLetra"], 11)

    def test_rechaza_valores_incorrectos(self):
        limpio = datos.validar_ajustes({"userSettings": {"darkMode": "9", "playerSubtitle": 5}, "windows": {"tamanoLetra": 900, "listas": [{"nombre": "x", "url": "ftp://no", "tipo": "tv"}]}})
        self.assertEqual(limpio["userSettings"]["darkMode"], "2")
        self.assertEqual(limpio["userSettings"]["playerSubtitle"], "off")
        self.assertEqual(limpio["windows"]["tamanoLetra"], 11)
        self.assertEqual(limpio["windows"]["listas"], [])
        with self.assertRaises(ValueError):
            datos.validar_ajustes([1, 2])

    def test_datos_conserva_copia_de_ajustes_danados(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            (raiz / "ajustes.json").write_text("{esto no es json", encoding="utf-8")
            d = datos.Datos(raiz)
            self.assertTrue(d.aviso)
            self.assertTrue(list(raiz.glob("ajustes-danados-*.json")))
            d.fijar_estado_canal("tv", "La 1", favorite=True)
            d.guardar()
            de_nuevo = datos.Datos(raiz)
            self.assertTrue(de_nuevo.estado_canal("tv", "La 1")["favorite"])
            de_nuevo.fijar_estado_canal("tv", "La 1", favorite=False)
            self.assertEqual(de_nuevo.ajustes["tvChannels"], [])


class Listas(unittest.TestCase):
    def setUp(self):
        self.canales = catalogo.parsear_lista(MUESTRA_TV, "tv", "prueba")

    def test_marcas_del_apk(self):
        por_nombre = {c.nombre: c for c in self.canales}
        la1 = por_nombre["La 1"]
        self.assertEqual([e.tipo for e in la1.emisiones], ["directo", "web"])
        self.assertTrue(la1.geo)
        self.assertIn("HD", la1.emisiones[0].etiqueta(1))
        tele5 = por_nombre["Telecinco"]
        self.assertEqual([e.tipo for e in tele5.emisiones], ["ext", "web"])
        self.assertEqual(tele5.emisiones[0].url, "https://www.mitele.es/directo/telecinco")
        self.assertTrue(por_nombre["DMAX"].sin_emision)
        gol = por_nombre["GOL PLAY"]
        self.assertEqual(gol.emisiones[0].tipo, "ext")
        self.assertEqual(gol.user_agent, catalogo.UA_UAGB)
        yt = por_nombre["Canal YT"]
        self.assertEqual(yt.emisiones[0].tipo, "youtube")
        self.assertEqual(yt.emisiones[0].url, "https://www.youtube.com/channel/UC123/live")
        self.assertEqual(yt.referer, "https://player.ejemplo.es/")

    def test_atresmedia_se_anade_una_vez(self):
        con = catalogo.insertar_atresmedia(self.canales)
        nombres = [c.nombre for c in con]
        self.assertIn("Antena 3", nombres)
        self.assertEqual(nombres.count("Antena 3"), 1)
        self.assertEqual(catalogo.insertar_atresmedia(con), con)
        antena = next(c for c in con if c.nombre == "Antena 3")
        self.assertEqual(antena.emisiones[0].tipo, "ext")
        self.assertEqual(proveedores.codigo_proveedor(antena.emisiones[0].url), 1)

    def test_filtros_y_orden(self):
        with tempfile.TemporaryDirectory() as carpeta:
            d = datos.Datos(Path(carpeta))
            todos = catalogo.filtrar(self.canales, d, "tv")
            self.assertEqual(len(todos), 5)
            self.assertEqual([c.nombre for c in catalogo.filtrar(self.canales, d, "tv", texto="tele")], ["Telecinco"])
            d.fijar_estado_canal("tv", "DMAX", hide=True)
            self.assertNotIn("DMAX", [c.nombre for c in catalogo.filtrar(self.canales, d, "tv")][:4])
            d.usuario["hiddenChannelsVisibility"] = 1
            self.assertNotIn("DMAX", [c.nombre for c in catalogo.filtrar(self.canales, d, "tv")])
            self.assertEqual([c.nombre for c in catalogo.filtrar(self.canales, d, "tv", vista="ocultos")], ["DMAX"])
            d.fijar_estado_canal("tv", "GOL PLAY", favorite=True)
            self.assertEqual([c.nombre for c in catalogo.filtrar(self.canales, d, "tv", vista="favoritos")], ["GOL PLAY"])
            d.fijar_estado_canal("tv", "Canal YT", position=0)
            self.assertEqual(catalogo.filtrar(self.canales, d, "tv")[0].nombre, "Canal YT")
            d.comunidades_ocultas("tv").append("Deportivos")
            self.assertEqual([c.nombre for c in catalogo.filtrar(self.canales, d, "tv")], ["La 1", "Telecinco"])
            self.assertEqual(len(catalogo.filtrar(self.canales, d, "tv", ambito="Deportivos")), 2)

    def test_lista_real_si_esta_descargada(self):
        ruta = RAIZ / "analisis" / "tv.json"
        if not ruta.exists():
            self.skipTest("Sin lista descargada")
        canales = catalogo.parsear_lista(json.loads(ruta.read_text(encoding="utf-8")), "tv", "oficial")
        self.assertGreater(len(canales), 500)
        tele5 = next(c for c in canales if c.nombre == "Telecinco")
        self.assertEqual(tele5.emisiones[0].tipo, "ext")
        self.assertTrue(all(c.emisiones for c in canales if not c.sin_emision or c.web))

    def test_guia(self):
        ahora = int(time.time())
        guia = catalogo.parsear_guia([{"name": "La1.TV", "events": [{"hi": ahora - 600, "hf": ahora + 600, "t": "Ahora", "d": "desc", "g": "NEWS"}, {"hi": ahora + 600, "hf": ahora + 1200, "t": "Luego"}, {"hi": 5, "hf": 1, "t": "mal"}]}])
        programas = guia["La1.TV"]
        self.assertEqual(len(programas), 2)
        actual, siguiente = catalogo.ahora_y_siguiente(programas)
        self.assertEqual(actual.titulo, "Ahora")
        self.assertEqual(actual.categoria_es(), "Noticias")
        self.assertEqual(siguiente.titulo, "Luego")
        with self.assertRaises(ValueError):
            catalogo.parsear_guia({"no": "lista"})


class Proveedores(unittest.TestCase):
    def test_codigos(self):
        self.assertEqual(proveedores.codigo_proveedor("https://www.mitele.es/directo/cuatro"), 10)
        self.assertEqual(proveedores.codigo_proveedor("https://www.rtpa.es/tpa-en-directo"), 106)
        self.assertEqual(proveedores.codigo_proveedor("https://ejemplo.es"), -1)

    def test_mediaset_infinity_tambien_es_mitele(self):
        """Telecinco y Cuatro se mudaron a mediasetinfinity.es (sep 2026); la API es la misma."""
        self.assertEqual(proveedores.codigo_proveedor("https://www.mediasetinfinity.es/directo/telecinco/"), 10)
        self.assertEqual(proveedores.codigo_proveedor("https://www.mediasetinfinity.mediaset.es/directo/cuatro/"), 10)

    def test_mitelefe_no_es_mediaset(self):
        """«mitele» está dentro de «mitelefe.com», que es la web argentina de Telefe."""
        self.assertEqual(proveedores.codigo_proveedor("https://www.mitelefe.com/telefe-en-vivo"), -1)

    def test_el_dominio_manda_no_el_texto(self):
        """Un subdominio nuevo de la misma casa se sigue reconociendo; uno ajeno, no."""
        self.assertEqual(proveedores.codigo_proveedor("https://movil.atresplayer.com/directos/antena3/"), 1)
        self.assertEqual(proveedores.codigo_proveedor("https://ejemplo.es/?destino=atresplayer.com"), -1)
        self.assertEqual(proveedores.codigo_proveedor("https://directos.mediaset.es/x/master.m3u8"), 10)

    def test_si_la_lista_muda_el_canal_se_resuelve_por_su_nombre(self):
        """Aunque la web cambie de dominio, la API de la casa solo pide el nombre del canal."""
        pedidas = []

        def peticion(url, origin="", cuerpo=None, cabeceras=None, timeout=15):
            pedidas.append(url)
            if url.endswith("/geo"):
                return {"country": "ES"}
            if "caronte" in url:
                return {"cerbero": "https://cerbero.mediaset.es/auth", "bbx": "BBX",
                        "dls": [{"format": "hls", "drm": False, "stream": "https://livek.mediaset.es/t5.m3u8", "quality": "hd", "adtype": "linear"}]}
            if "mab.mediaset" in url:
                return {"gbx": "GBX"}
            return {"tokens": {"1": {"cdn": "?token=abc"}}}

        fuente = proveedores.resolver("https://una-web-nueva.example/directo/telecinco", peticion)
        self.assertEqual(fuente.url, "https://livek.mediaset.es/t5.m3u8?token=abc")
        self.assertIn("https://caronte.mediaset.es/delivery/channel/mmc/telecinco/mtweb", pedidas)

    def test_una_pagina_cualquiera_sigue_yendo_al_navegador(self):
        """Sin «directo» en la ruta no hay nombre de canal que preguntar: no se inventa nada."""
        def peticion(url, origin="", cuerpo=None, cabeceras=None, timeout=15):
            raise AssertionError("no se debe preguntar a nadie por " + url)

        with self.assertRaises(proveedores.ProveedorNoSoportado):
            proveedores.resolver("https://www.tvperu.gob.pe/play", peticion)

    def test_nombre_del_canal_dentro_de_la_direccion(self):
        """El nombre del canal se saca de detrás de «directo», con barra final o sin ella."""
        self.assertEqual(proveedores.slug_directo("https://www.mitele.es/directo/telecinco"), "telecinco")
        self.assertEqual(proveedores.slug_directo("https://www.mediasetinfinity.es/directo/telecinco/"), "telecinco")
        self.assertEqual(proveedores.slug_directo("https://www.atresplayer.com/directos/antena3/"), "antena3")
        self.assertEqual(proveedores.slug_directo("https://ejemplo.es/canal/uno"), "uno")

    def test_mitele_simulado(self):
        respuestas = {
            "https://cerbero.mediaset.es/geo": {"country": "ES"},
            "https://caronte.mediaset.es/delivery/channel/mmc/telecinco/mtweb": {"cerbero": "https://cerbero.mediaset.es/auth", "bbx": "BBX", "dls": [
                {"format": "hls", "drm": False, "stream": "https://cdn.es/t5-ctv.m3u8", "quality": "hd", "adtype": "linear"},
                {"format": "hls", "drm": False, "stream": "https://cdn.es/t5.m3u8?x=1", "quality": "hd", "adtype": "ssai"},
                {"format": "dash", "drm": True, "stream": "https://cdn.es/t5.mpd"},
            ]},
            "https://mab.mediaset.es/1.0.0/get?oid=mtmw&eid=/api/mtmw/v3/gbx/mtweb/telecinco": {"gbx": "GBX"},
            "https://cerbero.mediaset.es/auth": {"tokens": {"1": {"cdn": "?token=abc"}}},
        }

        def peticion(url, origin="", cuerpo=None, cabeceras=None, timeout=15):
            if url == "https://cerbero.mediaset.es/auth":
                self.assertEqual(cuerpo, {"bbx": "BBX", "gbx": "GBX"})
            return respuestas[url]

        # La barra final de Mediaset Infinity no debe colarse en el nombre del canal.
        for pagina in ("https://www.mitele.es/directo/telecinco", "https://www.mediasetinfinity.es/directo/telecinco/"):
            fuente = proveedores.resolver(pagina, peticion)
            self.assertEqual(fuente.url, "https://cdn.es/t5.m3u8?x=1&token=abc")
            self.assertEqual(fuente.origin, proveedores.ORIGEN_MITELE)

    def test_mitele_elige_el_cdn_que_firma_la_lista(self):
        """Se prefiere Fastly y se usa SU token, no siempre el primero.

        Akamai no mete el permiso de sesión en la lista maestra, así que sus
        sublistas dan 403; y cerbero devuelve un token por fuente, con la
        posición como clave. Además hay que pedir que no se mande «Range»:
        con una respuesta parcial el CDN devuelve la lista sin firmar.
        """
        respuestas = {
            "https://cerbero.mediaset.es/geo": {"country": "ES"},
            "https://caronte.mediaset.es/delivery/channel/mmc/telecinco/mtweb": {"cerbero": "https://cerbero.mediaset.es/auth", "bbx": "BBX", "dls": [
                {"format": "hls", "drm": False, "stream": "https://directos.mediaset.es/t5.m3u8", "quality": "hd", "adtype": "linear"},
                {"format": "hls", "drm": False, "stream": "https://livek.mediaset.es/t5.m3u8", "quality": "sd", "adtype": "csai"},
            ]},
            "https://mab.mediaset.es/1.0.0/get?oid=mtmw&eid=/api/mtmw/v3/gbx/mtweb/telecinco": {"gbx": "GBX"},
            "https://cerbero.mediaset.es/auth": {"tokens": {"1": {"cdn": "?corto=akamai"}, "2": {"cdn": "?largo=fastly"}}},
        }
        fuente = proveedores.resolver("https://www.mitele.es/directo/telecinco", lambda url, *a, **k: respuestas[url])
        self.assertEqual(fuente.url, "https://livek.mediaset.es/t5.m3u8?largo=fastly")
        self.assertTrue(fuente.sin_rango)
        self.assertIn("Range:", fuente.cabeceras())

    def test_atresplayer_simulado(self):
        respuestas = {
            "https://api.atresplayer.com/client/v1/ipLocation": {"country": "ES"},
            "https://api.atresplayer.com/client/v1/url?href=/directos/antena3/": {"href": "https://api.atresplayer.com/canal"},
            "https://api.atresplayer.com/canal": {"urlVideo": "https://api.atresplayer.com/video"},
            "https://api.atresplayer.com/video": {"sourcesLive": [{"src": "https://cdn.atres.es/a3.mpd", "drm": True}, {"src": "https://cdn.atres.es/a3.m3u8"}]},
        }
        fuente = proveedores.resolver("https://www.atresplayer.com/directos/antena3/", lambda url, *a, **k: respuestas[url])
        self.assertEqual(fuente.url, "https://cdn.atres.es/a3.m3u8")
        respuestas["https://api.atresplayer.com/client/v1/ipLocation"] = {"country": "FR"}
        with self.assertRaises(proveedores.ErrorProveedor):
            proveedores.resolver("https://www.atresplayer.com/directos/antena3/", lambda url, *a, **k: respuestas[url])

    def test_no_soportado_y_cabeceras(self):
        with self.assertRaises(proveedores.ProveedorNoSoportado):
            proveedores.resolver("https://www.rtpa.es/tpa-en-directo")
        canal = catalogo.parsear_lista(MUESTRA_TV, "tv", "p")[0]
        fuente = proveedores.fuente_directa(canal, canal.emisiones[0])
        self.assertEqual(fuente.origin, "https://ejemplo.es")
        self.assertEqual(fuente.cabeceras(), ["Origin: https://ejemplo.es"])


if __name__ == "__main__":
    unittest.main()
