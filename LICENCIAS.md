# Avisos y componentes

**Resintoniza** es una aplicación independiente desarrollada por **ANÓNIMO**. No está afiliada, asociada ni respaldada por ninguna cadena, emisora, plataforma o proyecto de terceros, ni sus marcas se usan en ella.

La aplicación **no emite, no aloja y no redistribuye ningún contenido**. Descarga listas de canales y guías de programación publicadas en Internet y, al reproducir, se conecta al servidor de la emisora correspondiente, que ofrece su señal bajo sus propios términos y condiciones. Las restricciones por zona, los registros y la protección de las señales no se modifican en ningún caso.

## Origen de los datos

- Listas de canales de televisión y radio en formato JSON, con servidor de respaldo y copia en caché local. Las direcciones concretas están en `tdt/catalogo.py` y se pueden cambiar o ampliar desde la propia aplicación (pestaña Información).
- Guía de programación asociada a esas listas, en formato JSON.
- Guía adicional en formato XMLTV, del proyecto público EPG dobleM: https://github.com/davidmuma/EPG_dobleM . Se usa la guía tal cual la publica su autor, sin modificarla; la aplicación solo la lee y limpia para leerla en voz alta. Si te resulta útil, su autor acepta donaciones en el propio repositorio.
- Catálogo de canales de iptv-org, listas M3U públicas por país, idioma y categoría: https://github.com/iptv-org/iptv , con licencia libre. iptv-org recopila enlaces publicados por terceros y no aloja ningún contenido; cada emisora conserva sus derechos.
- Los directos de YouTube y Twitch se obtienen de los servicios públicos de reproducción de esas plataformas, los mismos que usan sus reproductores web.

Cada proveedor de datos y cada emisora conserva sus propios derechos y condiciones de uso.

## Componentes incluidos en la distribución

- Python: licencia PSF, https://www.python.org/psf/license/
- wxPython y wxWidgets: wxWindows Library Licence, https://www.wxwidgets.org/about/licence/
- libmpv (mpv, FFmpeg y otros): GPL v2 o posterior / LGPL. Compilación de shinchiro, https://github.com/shinchiro/mpv-winbuild-cmake . Código fuente: https://github.com/mpv-player/mpv y https://ffmpeg.org/
- python-mpv: https://github.com/jaseg/python-mpv
- accessible_output2 (voz para lectores de pantalla): https://github.com/accessibleapps/accessible_output2
- wx-accessible-webview (diálogos y navegador accesibles): https://github.com/CommunityAccess/wx-accessible-webview
- Microsoft Edge WebView2: https://developer.microsoft.com/microsoft-edge/webview2/
- Vulkan Loader (vulkan-1.dll, Khronos Group): Apache 2.0, https://github.com/KhronosGroup/Vulkan-Loader
- Runtimes de Visual C++ de Microsoft, incluidos por cx_Freeze: https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist
- cx_Freeze (herramienta de empaquetado): https://github.com/marcelotduarte/cx_Freeze

Durante la preparación de `data/mpv` se descarga `7zr.exe` de 7-Zip (Igor Pavlov, https://www.7-zip.org/) solo para extraer el paquete de libmpv; se elimina después.

## DNS alternativo

La opción de DNS alternativo configura el equipo para usar el resolutor público **XDP AdBlock** (`85.208.114.51`, con DNS sobre HTTPS en `https://dns.xdp.es/dns-query`), de https://xdp.es . La aplicación no está asociada a ese servicio: solo escribe la dirección en la configuración de red de Windows, igual que se haría a mano, y guarda la configuración anterior para restaurarla. Cambiar el DNS es una preferencia del propio equipo; el acceso a cada servicio sigue dependiendo de sus condiciones. La idea y el procedimiento vienen de la herramienta `xdp_manager.py` del propio usuario.

- pychromecast, para el envío a Chromecast y Google TV: https://github.com/home-assistant-libs/pychromecast . Arrastra zeroconf, casttube, protobuf y requests. El envío por DLNA y la detección de Fire TV no necesitan ninguna biblioteca.

## Complemento de NVDA

El complemento `resintonizaListViewFix`, incluido en `data/bin` y con su código en `nvda_addon/`, amplía el límite de lectura por columna de NVDA. Está inspirado en el complemento equivalente de SocialRSS Accessible Suite y funciona con NVDA (NV Access, https://www.nvaccess.org/), que se distribuye bajo licencia GPL v2. El complemento no modifica NVDA de forma permanente: al desactivarlo, todo queda como estaba.

## Cuentas de proveedor

La aplicación no incluye, no recomienda y no distribuye ninguna lista ni cuenta de proveedor IPTV. Se limita a hablar los formatos públicos M3U y Xtream Codes con los datos que aporte cada persona, que es responsable de tener derecho a usarlos.
