# De reproductor de listas a cliente IPTV accesible: qué se ha hecho

Este documento nació como investigación de lo que le faltaba a **Resintoniza** para ser un cliente IPTV completo, y además el más accesible. **Todo lo que proponía está implementado.** Aquí queda lo que se hizo, cómo funciona y dónde vive cada pieza, más los avisos y las fuentes consultadas.

Lo que ya existía antes y no se repite: listas JSON con caché y respaldo, extracción de directos (servicios oficiales, YouTube, Twitch y webs), reproductor libmpv con pistas y subtítulos, guía ampliada XMLTV, favoritos, ocultos, orden personal, recordatorios, temporizador, teclas F1 a F12 personalizables, listas accesibles con plantillas de lectura, voz directa y navegador integrado accesible.

---

## 1. Listas M3U: el formato que usa todo el mundo

Un archivo M3U empieza por `#EXTM3U` y describe cada canal con una línea `#EXTINF` seguida de la dirección. No es un estándar formal: son convenciones que popularizaron Kodi, TiviMate, OTT Navigator y Perfect Player, así que **`tdt/m3u.py` lee con tolerancia** y descarta lo que no entiende.

| Atributo | Para qué sirve aquí |
|---|---|
| `tvg-id` | Enlaza el canal con la guía XMLTV, igual que los identificadores de las listas incluidas |
| `tvg-name`, `tvg-logo` | Nombre alternativo e icono |
| `group-title`, `#EXTGRP` | Categoría; se usa como ámbito, así que los filtros ya existentes funcionan |
| `tvg-chno` | Número de canal, para saltar tecleando cifras |
| `tvg-language`, `tvg-country` | Idioma y país |
| `tvg-shift` | Desfase horario de la guía |
| `catchup`, `catchup-source`, `catchup-days` | Ver programas ya emitidos |
| `#EXTVLCOPT` | Agente de usuario y referente por canal, que el reproductor ya sabía enviar |
| `#KODIPROP` | Sirve para **detectar el DRM** y avisar de que esa emisión no se puede reproducir |

Además, si la lista declara su guía en `url-tvg` o `x-tvg-url`, se descarga y se mezcla con las demás. Las listas pueden estar en Internet o ser un archivo del equipo, y el tipo se puede detectar solo (`radio="true"` o un grupo que hable de radio). También se **exportan los favoritos a M3U** para usarlos en otros programas.

## 2. Cuentas Xtream Codes

`tdt/xtream.py` habla la API `player_api.php` con las acciones `get_live_categories`, `get_live_streams`, `get_vod_categories`, `get_vod_streams`, `get_series`, `get_series_info` y `get_short_epg`. De una cuenta salen:

- los canales en directo, con su número, su categoría y su archivo de catch-up;
- la **programación** que da el propio servidor, que se suma a la guía;
- las **películas y series**, en una pestaña propia con búsqueda, categorías y episodios por temporada.

Las direcciones se construyen como manda el formato: `/live/usuario/clave/<id>.m3u8`, `/movie/…` y `/series/…`. La contraseña se guarda cifrada con `CryptProtectData` de Windows (`tdt/cifrado.py`), de modo que solo se puede descifrar con la misma cuenta de usuario y en el mismo equipo.

## 3. Grabar y pausar el directo

La propiedad `stream-record` de libmpv graba mientras ves, sin volver a descargar ni recodificar. **Comprobado con La 1: 6,82 megabytes en 8 segundos**, en un `.mkv` que abre cualquier reproductor.

- **Grabar ahora** con una tecla, a `data/grabaciones`, con aviso sonoro al empezar y al parar y el tamaño al terminar.
- **Grabación programada** desde la guía: se elige cuántos minutos antes empezar, la aplicación graba a su hora y para pasado el final. Si a esa hora la aplicación estaba cerrada, lo dice en lugar de fingir que se grabó.
- **Pausa del directo**: fijando en Ajustes los minutos que se guardan, se retrocede dentro de la emisión y se vuelve al directo con otra tecla.

### 3.1 Grabar en segundo plano (`GrabadorFondo` y `GestorFondo`)

Grabar con el reproductor principal tenía un precio: la grabación sintonizaba el canal, se oía, y cambiar de canal, pausar o detener la cortaba. Ahora **cada grabación abre su propia instancia de libmpv** con `vo=null`, `ao=null` y silencio, en sus propios hilos: descarga la emisión y la escribe, pero no dibuja ni suena nada. Es lo que hace `mpv --vo=null --ao=null --stream-record=archivo`, con la misma receta de opciones que el reproductor (`fflags=+igndts`, búfer del perfil elegido, agente y cabeceras de la emisión).

Qué cambia con eso:

- El **reproductor principal queda libre**: se puede escuchar un canal mientras se graban otros, y pausar, cambiar de canal o detener no le hace nada a la grabación.
- **Varias grabaciones a la vez**, incluso solapadas: el límite se elige en Ajustes (de fábrica 3). Con el modo clásico solo cabía una.
- Si el **directo se corta**, la grabación no se pierde: se reintenta (hasta 20 veces, cada 8 segundos), se vuelve a resolver la dirección por si había caducado y se sigue en un archivo nuevo, que la lista cuenta como «en 2 archivos».
- **Herramientas > Grabación > Grabaciones** enseña arriba lo que se está grabando ahora: canal, programa, estado, cuánto lleva, cuánto le queda y cuánto ocupa, con la lista actualizándose sola cada dos segundos **sin rehacer las filas**, para que el lector de pantalla no pierda el foco. Suprimir (o el menú contextual, o el botón) detiene la que sea, y una programada que está en marcha también se puede parar desde su fila.
- El estado de la reproducción (la tecla de estado) y los datos de la emisión dicen también qué se está grabando, cuánto lleva y cuánto le queda; la pestaña Información lo resume; y al cerrar la ventana con grabaciones en marcha se avisa, con la opción de seguir grabando desde la bandeja del sistema.
- Tiene su **plantilla de lectura propia** («Grabaciones en curso»), así que las columnas y su orden se configuran como en el resto de listas.
- En Ajustes > Grabación se puede volver al **modo clásico**, que sigue siendo lo más barato: graba lo que ya se está descargando, sin bajarlo dos veces. Es el precio del modo nuevo: cada grabación es una conexión más.

Comprobado con emisiones reales: **La 1 en segundo plano, 6,1 megabytes en 18 segundos**, y el archivo resultante lleva imagen y sonido de verdad (mpegts, H.264 1280×720 y AAC 48 kHz estéreo). Y **dos canales grabándose a la vez (La 1 y La 2) mientras un tercer reproductor seguía reproduciendo**, los tres sin estorbarse.

## 4. Catch-up: ver lo que ya se emitió

`tdt/catchup.py` construye la dirección de un programa pasado a partir de la del directo y de la hora de inicio y fin que ya da la guía. Admite las cuatro gramáticas que se usan en la práctica: `default` y `append` (parámetros `utc` y `lutc`), `flussonic` (`…/<inicio>-<duración>.m3u8`), `shift` y `xc` de Xtream Codes (`/timeshift/usuario/clave/<minutos>/<fecha>/<id>`), y la plantilla `catchup-source` del proveedor manda siempre que exista. En la programación aparece «Ver este programa emitido» solo cuando el canal lo permite y el programa ya terminó.

## 5. Accesibilidad: lo que diferencia a esta aplicación

- **Complemento de NVDA** (`nvda_addon/`, empaquetado por `tools/construir_addon.py`): NVDA corta el texto de cada columna a 511 caracteres; el complemento sube el límite a 16.384 y fuerza la lectura fuera del proceso, así se leen enteras las sinopsis largas. Se instala desde Herramientas > Mantenimiento y se desactiva cuando se quiera.
- **Interfaz invisible** (`tdt/globales.py`): con Ctrl+Alt más una tecla se pausa, se cambia de canal, se sube el volumen, se pregunta qué suena o se graba, aunque estés en otro programa. Si otra aplicación ya usa una combinación, se avisa y las demás siguen funcionando.
- **Sonidos identificativos** (`tdt/sonidos.py`): empezar, parar, error, recordatorio, grabación, cambio de canal y tope alcanzado. Se generan con el módulo `wave` en `data/sonidos`, sin descargar nada, y se activan uno a uno.
- **Modo solo audio**: descarta el vídeo y no abre su ventana.
- **Anuncio del programa al cambiar de canal**: «La 1, ahora Telediario, hasta las 16:00. Después, …».
- **Búsqueda en toda la guía**: un título en todos los canales, y de ahí a recordatorio, grabación o ver el canal.
- **Audiodescripción**: se prefiere esa pista cuando existe. Comprobado con La 1, que emite una pista «Audio Descripcion».

## 6. Organizar muchos canales

`tdt/organizar.py` reúne lo que hace falta al pasar de cientos a miles de canales:

- **Numeración**: teclear 1, 0, 3 en la lista salta al canal 103; manda el `tvg-chno` de la lista y, si no lo hay, la posición.
- **Historial** de lo último visto, con vuelta a cualquiera de ellos.
- **Bloqueo por PIN** de canales o de categorías enteras, con el PIN guardado como resumen con sal, nunca en claro.
- **Detección de duplicados** al mezclar listas, por nombre normalizado, con la opción de mostrarlos o unificarlos.

## 7. Robustez de la reproducción

- **Reintento automático** con espera creciente (3, 8 y 20 segundos) cuando se corta el directo, diciendo por qué intento va.
- **Emisión alternativa**: si una falla, se prueba la siguiente del mismo canal sin intervención.
- **Elección de calidad** (`hls-bitrate`) para conexiones lentas.
- **Datos de la emisión** en un diálogo accesible: resolución, imágenes por segundo, códecs, canales de audio, velocidad, búfer, imágenes perdidas y velocidad de descarga.

## 8. Extras

- **Enviar a la tele** (`tdt/casting.py`), por tres caminos: **DLNA o UPnP** con descubrimiento SSDP y control `AVTransport` por SOAP, solo con la biblioteca estándar; **Chromecast** y Google TV con `pychromecast`, ya incluida; y **Fire TV o Android TV**, que se descubren por DIAL. Estos últimos no aceptan una dirección suelta, así que en vez de fallar en silencio se dice qué hacer: instalar en el aparato una aplicación que reciba por DLNA (entonces aparece como DLNA y funciona igual) o duplicar la pantalla de Windows con Miracast, que Fire TV admite de fábrica y que se abre desde el propio diálogo.
- **Copia de seguridad** de ajustes, favoritos, orden, plantillas, recordatorios, grabaciones programadas y perfiles, con restauración que antes guarda el estado actual.
- **Perfiles de uso** con nombre, cada uno con sus favoritos y sus ajustes; cambiar de perfil guarda antes el que estabas usando.
- **Versiones nuevas de la aplicación**: comprobación opcional contra un archivo JSON publicado. Sin dirección configurada no se conecta a ningún sitio y lo dice, en vez de fingir que está al día.

---

## 9. Los dos repositorios clonados en `adjuntos`

A petición del usuario se clonaron y se revisaron dos proyectos, y la aplicación ya sabe hablar con ellos.

### EPG dobleM (`adjuntos/EPG_dobleM`)

Es la guía XMLTV que ya se descargaba, pero solo se estaba aprovechando una parte. Al revisarla apareció esto:

- Publica **cinco variantes** del mismo contenido (634 canales y 82.112 programas en todas): normal, ligera, con los títulos sin temporada ni episodio, con imágenes de fondo y con caracteres especiales. Ahora se eligen en **Herramientas > Guía y recordatorios > Guías de programación**, junto a las guías XMLTV propias que se quieran añadir.
- Algunas variantes traen **etiquetas de color de Kodi** (`[COLOR tomato]…[/COLOR]`) que un lector de pantalla leería en voz alta. Se limpian al leer, igual que los símbolos de adorno del principio de cada línea.
- Cada programa trae mucho más de lo que se mostraba: **géneros en español, año, temporada y episodio, valoración y edad recomendada**, además de una imagen. Todo eso se lee ahora y aparece en la ficha del programa, y se puede poner como columna en las plantillas de lectura. Los géneros DVB en inglés se traducen.
- Publica también la **lista de canales que cubre**. Con ella, **Herramientas > Guía y recordatorios > Cobertura de la guía** dice cuántos canales tienen programación y, para los que no, con qué nombre la tendrían: casi siempre es cuestión de cómo está escrito el nombre en la lista.

### iptv-org (`adjuntos/iptv-org`)

Es el catálogo público de listas M3U más grande que hay, agrupado por país, idioma y categoría, con una API de índices. Encaja directamente con el lector M3U:

- **Archivo > Añadir canales del catálogo de iptv-org** consulta esos índices (en español, y con un índice de respaldo si no hay conexión), comprueba que la lista existe y dice cuántos canales trae antes de guardarla.
- Sus canales se llaman «3Cat Info (1080p) [Geo-blocked]». Ahora la calidad, la restricción por zona y el aviso de «no emite las 24 horas» se separan del nombre y pasan a ser datos del canal, así que **el nombre queda limpio, se lee mejor y se empareja con la guía**.
- Comprobado con la lista de España: 335 canales, 28 intermitentes, y **205 canales con programación** al cruzarlos con la guía ampliada. Los repetidos entre listas se unifican solos.
- iptv-org no publica guías XMLTV ya generadas (hay que ejecutar su recolector), así que no se promete algo que no existe: sus canales se emparejan con la guía que ya se usa.

## 10. Arranque, caché y DNS alternativo

- **Arrancar con lo guardado.** Las listas (JSON y M3U), la guía XMLTV y ahora también los canales de las cuentas Xtream se guardan en `data/cache`. Al abrir, la aplicación usa esa copia y no toca la red salvo que se le pida. La frecuencia se elige en Ajustes: nunca, cada vez que se abre, cada día o cada semana; de fábrica, nunca. Comprobado desconectando la red por completo: 1.953 canales, la lista de iptv-org y la programación, todo desde la caché.
- **DNS alternativo** (`tdt/dns_xdp.py`, a partir de `xdp_manager.py`). Cambia el DNS del adaptador al resolutor público de XDP con DNS sobre HTTPS y lo restaura después. Mejoras sobre el original: los nombres con acentos («Conexión de área local») se pasaban por la línea de órdenes y se rompían, así que ahora la orden va en un archivo con marca de orden de bytes; `InterfaceGuid` ya es texto, de modo que `.ToString('B')` fallaba y el modo salía siempre «automático»; y se distingue lo que hay escrito a mano (`NameServer`) de lo que reparte el router (`DhcpNameServer`), que es lo que hace falta para restaurar de verdad la configuración anterior. Solo se activa cuando la persona lo pide, con el aviso de permisos de Windows.
- **El resultado de la orden con permisos.** Cambiar el DNS necesita permisos de administrador, y aquí se eleva **solo esa orden** (la aplicación no se ejecuta como administrador). El proceso elevado deja su resultado en un archivo, y ahí aparecieron tres fallos reales: el archivo se leía **antes de que el otro proceso lo soltara** (Windows contesta «permiso denegado», el mismo error que da un archivo en uso), los identificadores de proceso se pasaban a `WaitForSingleObject` **sin declarar los tipos** (en 64 bits se truncan y la espera no esperaba), y **PowerShell escribe UTF-8 con marca de orden de bytes**, así que la comprobación de `ERROR:` nunca se cumplía y un fallo se contaba como éxito. Ahora el archivo lo crea la propia aplicación (así es suyo y no hay problema de permisos), el guion escribe al final un `listo.txt` que avisa de que ha terminado, se reintenta la lectura unos segundos, se leen las marcas de orden de bytes y, si aun así no se puede leer el resultado, **se le pregunta al sistema**: si el DNS ya está cambiado, se da por bueno. Al terminar se comprueba de verdad que el adaptador quedó como se pedía, y si no, se dice.
- **Nunca se cambia sin copia.** Antes de tocar nada se guarda lo que tenía el adaptador (modo y servidores) en `data/dns-original.json`, se relee para confirmar que se escribió, y además se deja una **copia fechada** en `data/copias-dns` (se conservan las veinte últimas). Si la copia no se puede escribir, no se cambia el DNS. Al restaurar, la copia solo se borra cuando se ha comprobado que el adaptador ya no usa el DNS alternativo; si algo falla, se conserva para poder intentarlo otra vez. Desde el diálogo se puede guardar esa copia donde se quiera.
- **La conexión correcta.** Las conexiones virtuales (WSL, Hyper-V, máquinas virtuales) aparecían las primeras y es fácil cambiarles el DNS sin querer: ahora van al final y, si se elige una, se avisa de que eso no arregla ningún bloqueo. El alta de DNS sobre HTTPS solo se retira cuando ninguna otra conexión sigue usando el servidor.
- **Importar la configuración de xdp_manager.** Su archivo `xdp_configuracion_original.json` se puede traer desde el diálogo, y se ofrece solo si se encuentra. Al convertirlo se corrige un matiz importante: aquella herramienta anotaba en `dns` los servidores en uso, que con modo automático son los que reparte el router; si se copiaran tal cual como «manuales», al restaurar quedarían fijados unos DNS que nunca se eligieron. Ahora, con modo automático la lista de manuales queda vacía y esos servidores se guardan solo como información, de modo que restaurar devuelve la conexión a pedírselos al router.

## 11. El búfer de recepción y las emisiones que van a tirones

Con una emisión de Mediaset apareció un fallo real y una duda. El fallo: al grabar, **el audio se perdía entero**, porque esa emisión manda los paquetes de audio con la marca de presentación anterior a la de decodificación (`pts < dts`) y el contenedor los rechaza uno a uno. Se arregla con `fflags=+igndts` en el lector de flujos, que reconstruye la marca a partir del `pts`: medido con la emisión real, **de 96 paquetes perdidos en ocho segundos a ninguno**, y el archivo pasó de 3,36 a 4,11 megabytes en el mismo tiempo. Además, las emisiones HLS se guardan ahora en `.ts`, que es copiar lo que llega sin remezclar; `.mp4` ni siquiera consigue escribir la cabecera en directo.

La duda era el «va a tirones». Aquí no se pudo reproducir: con la emisión real, el avance de la reproducción fue de 1,00, cero fotogramas perdidos, desincronía máxima de 0,011 segundos y ningún aviso del reproductor, tanto con la ventana de vídeo abierta como cerrada. Aun así se reforzó la recepción, porque la aplicación estaba **por debajo de lo que trae mpv de fábrica**:

| Ajuste | Antes | Ahora (perfil normal) | De fábrica en mpv |
|---|---|---|---|
| Búfer del demultiplexor | 64 MiB | 192 MiB | 150 MiB |
| Lectura por delante | 1 s | 30 s | 1 s |
| Espera tras un corte | 1 s | 5 s | 1 s |
| Búfer antes de empezar | no | sí | no |
| Búfer de lectura del flujo | 128 KiB | 4 MiB | 128 KiB |
| Espera de red | 20 s | 60 s | 60 s |

El manual de mpv (clonado en `adjuntos/mpv-docs`) describe exactamente este síntoma en `--cache-pause-initial`: «la reproducción empieza, pero la caché de red se queda sin datos enseguida al decodificar más», y recomienda activar esa opción y poner `--cache-secs` y `--cache-pause-wait` en valores parecidos. Eso es lo que hace ahora el perfil normal.

En un directo hay un límite que no depende de nosotros: no se puede guardar por delante más de lo que el servidor haya publicado. Lo que sí da margen es **empezar unos fragmentos por detrás del directo** (`live_start_index`), y por eso el ajuste tiene tres niveles: mínimo (pegado al directo), normal y amplio (más margen a cambio de más retraso). La ficha de datos de la emisión dice cuál está en uso y **cuántos cortes ha habido**, para que se pueda medir en cada caso en lugar de adivinar.

## 12. De grabar un programa a un grabador completo (todo hecho)

Esta sección nació como lista de candidatas, mirando qué tienen los clientes que manda la gente (TiviMate y OTT Navigator en Android, con su multiventana) y los grabadores de verdad (Tvheadend, Kodi y Jellyfin, con sus reglas, sus perfiles y su limpieza). **Está toda implementada.** Aquí queda qué hace cada cosa y dónde vive.

### Reglas de grabación automática (`grabacion.py`, `DialogoReglas`)

Es lo que Tvheadend llama *autorec* y Kodi *timer rules*: «graba siempre lo que lleve *Telediario* en La 1». Cada regla dice qué texto busca (solo en el título o también en la descripción y los detalles), en qué canal o si solo en favoritos, qué días y en qué franja horaria, cuántos minutos antes y después, y cuántas grabaciones pendientes puede tener a la vez.

Lo importante es qué hace con las **repeticiones**, que es donde fallan casi todos: se puede grabar todo, no repetir el mismo episodio, grabarlo solo la primera vez o como mucho una vez por semana. El «mismo episodio» sale de la temporada y el episodio que ya trae la guía ampliada (sección 9); cuando la guía no los da, dos emisiones del mismo título el mismo día se consideran la misma cosa, que es el caso típico de la reposición de la tarde.

Las reglas se repasan al cargar la guía y cada media hora, y también a mano desde su diálogo. Desde cualquier programa de la guía hay «Grabarlo siempre (crear una regla)», que abre el editor con el título y el canal ya puestos.

### Grabar con cabeza

- **Márgenes** de antes y después, generales y **por canal**: para los que siempre empiezan tarde, sin tener que acordarse cada vez.
- **Carpeta por programa**, para que una serie quede junta.
- **Grabar solo el audio**: con `vid=no` el archivo sale con la pista de sonido y nada más. Medido con La 1: **0,68 megabytes en 20 segundos frente a 10**, o sea unos 2 megabytes por minuto en vez de 22. Para tertulias e informativos es la diferencia entre 1,3 gigabytes y 130 megabytes por hora.
- **Conflictos**: al programar (o al programar una regla) se avisa si a esa hora se solapan más grabaciones de las que se pueden hacer a la vez, diciendo la hora y cuántas.
- **Espacio en disco**: antes de grabar se dice cuánto va a ocupar (22 megabytes por minuto medidos, 2 si es solo audio) y cuánto queda libre; y mientras se graba se vigila cada medio minuto: si el disco baja del mínimo, **se paran las grabaciones y se avisa**, en vez de llenar el disco de madrugada.
- **Limpieza automática**, apagada de fábrica: borrar lo de más de X días, dejar solo las N últimas de cada programa y no pasar de Y gigabytes. Las grabaciones marcadas como **protegidas** no se tocan nunca, y antes de borrar a mano se enseña la lista completa.
- **Orden posterior**: una orden que se lanza al terminar cada grabación con `%f` como archivo (lo que Jellyfin llama *post-processing*), para convertir, mover o avisar.
- **Al terminar la última grabación**: no hacer nada, cerrar la aplicación, suspender o apagar el equipo, con el apagado cancelable.

### Grabar con la aplicación cerrada (`tareas.py`)

Lo único que arregla de verdad el «tiene que estar abierta» en Windows es el **Programador de tareas**: si se activa, la aplicación deja allí una tarea por cada grabación pendiente que la abre cinco minutos antes y, si el equipo está suspendido, lo **despierta** (`-WakeToRun`). Se crean y se quitan solas al programar, al terminar o al cancelar. Comprobado creando, listando y borrando una tarea real, sin permisos de administrador. Las órdenes van en un `.ps1` con marca de orden de bytes y se llaman con `-File`, porque pasar acentos por la línea de órdenes los rompe (ya pasó con el DNS).

### Con las grabaciones ya hechas

- **Recortar sin recodificar.** Este libmpv no admite `--ovc=copy` (lo dice claro: «encode codec 'copy' not found»), así que se aprovecha que un MPEG-TS son paquetes de 188 bytes: se busca el tiempo con mpv, se lee `stream-pos` —el byte por el que iba— y se copia ese trozo tal cual. Comprobado: de un archivo de 21 segundos, el corte 5–12 da **7 segundos exactos que se reproducen con imagen y sonido**. El original no se toca.
- **Reanudar donde lo dejaste**: se anota la posición cada quince segundos y al volver a abrir la grabación se ofrece seguir desde ahí.
- **Protegidas**, tamaño total y **gigabytes libres** a la vista en el diálogo, que además dice al abrirse cuántas grabaciones hay en curso, programadas y guardadas.

### Reproducción

- **Multiventana** (`mosaico.py`): hasta cuatro canales a la vez, cada uno con su libmpv dibujando en su panel y **solo uno con sonido**; las cifras eligen cuál suena, espacio pausa, Intro se queda con ese canal en el reproductor grande y Escape cierra. Es la función más valorada de TiviMate y aquí salió casi gratis: la infraestructura ya estaba comprobada con la grabación en segundo plano. Probado con La 1 y La 2 a la vez, con imagen en las dos y cambiando el sonido de una a otra.
- **Nivelador de volumen** entre canales (`dynaudnorm` de ffmpeg): cambiar de emisora ya no da saltos de volumen.
- **Velocidad de reproducción** con corrección de tono y **ajuste del retraso del audio**, para las emisiones que vienen descuadradas.

### Guía y canales

- **Qué empieza ahora**: lo que arranca en los próximos 15, 30, 60, 120 o 180 minutos, en favoritos o en todo, listo para ver, grabar, poner recordatorio o crear una regla de un tirón.
- **Comprobador de canales** (`comprobador.py`): pide unos kilobytes de cada emisión en paralelo y dice cuáles responden, cuáles no y por qué (403 por zona, servidor que no existe —típico del bloqueo del operador—, lista cerrada que ya no emite…). Sin abrir ningún reproductor y sin molestar a lo que se esté escuchando; al terminar ofrece **ocultar los caídos** de una vez. Comprobado con emisiones reales: La 1 responde en 222 milisegundos y un dominio inventado sale como «el nombre del servidor no existe».
- **Sincronizar con una carpeta en la nube**: guarda o trae la configuración entera (ajustes, favoritos, orden, plantillas, recordatorios, programadas, reglas y perfiles) en una carpeta de OneDrive, Dropbox o similar, para llevarla a otro equipo.

### Accesibilidad

- **Sonido propio** para las grabaciones programadas, distinto del de grabar a mano, al empezar y al terminar.
- **Aviso hablado cada X minutos** de lo que se está grabando (apagado de fábrica), y **resumen al abrir el diálogo** de grabaciones: cuántas en curso, cuántas programadas y cuántas guardadas.
- Las listas nuevas (grabaciones en curso, reglas y comprobación de canales) tienen su **plantilla de lectura** propia, como todas las demás.
- En el diálogo de grabaciones, **Intro abre las opciones** de la fila también en las listas de en curso y programadas, no solo en los archivos.
- **Se acabó el pitido al abrir un menú contextual con Intro.** Windows convierte cada pulsación en dos mensajes, la tecla y su carácter. Intro se atendía en `EVT_KEY_DOWN`, que llega después de que el carácter esté puesto en la cola; el menú que se abre a continuación tiene su propio bucle de mensajes, recoge ese carácter, no coincide con ninguna opción y Windows lo da por tecla equivocada. Ahora Intro se atiende en `EVT_CHAR_HOOK` (`ListaAccesible._al_pulsar_gancho`), que llega antes de que el carácter llegue a generarse. Comprobado mirando la cola con `PeekMessage`: antes quedaba un `WM_CHAR` de 13 esperando al abrir el menú, ahora no queda ninguno.
- **Manual de usuario dentro de la aplicación.** `MANUAL.md` se copia junto al ejecutable (en su sitio ya no van el README ni este archivo, que son del proyecto) y **Ayuda > Manual de usuario** lo enseña en el mismo diálogo HTML accesible que el resto de la ayuda: `widgets.markdown_a_html` convierte al vuelo lo poco de Markdown que usa el manual (encabezados con identificador, tablas, listas, negrita, código y enlaces). Comprobado que los dieciocho enlaces del índice encuentran su encabezado y que, pulsados dentro del diálogo, mueven la página en vez de abrir el navegador.
- **Los directos de Mediaset volvían a fallar (403) y las grabaciones salían vacías.** Tres cosas, y hacían falta las tres. El permiso de la sesión (`hdnts`) va en los parámetros de la dirección maestra y ningún reproductor HLS los repite al pedir las sublistas; el CDN de **Fastly** (`livek.mediaset.es`) lo resuelve reescribiendo la lista maestra para que cada variante salga ya firmada (`hdntl`), pero el de **Akamai** (`directos.mediaset.es`) no, y respondía 403 a todas. Se elige ahora el CDN antes que la calidad. Segundo: cerbero devuelve **un token por fuente**, con la posición como clave, y el código cogía siempre el primero; los de Fastly duran cuatro horas y los de Akamai tres minutos, así que una grabación larga se moría igual. Y tercero, el que costó encontrar: **libmpv pide «Range: bytes=0-»**, el CDN contesta 206 y en una respuesta parcial **no firma las variantes**, de modo que aun con el CDN bueno todo daba 403. Se arregla mandando la cabecera `Range` **sin valor**, que es como se le dice a curl (el que descarga dentro de libmpv) que no la mande. Comprobado midiendo la lista maestra: sin «Range», 200 y las seis variantes firmadas; con «Range», 206 y ninguna. Y comprobado de verdad: Telecinco grabada **250 segundos seguidos, 129,5 MB, cero reintentos** (antes moría a los tres minutos), los **doce canales de Mitele** grabando, y en directo H.264 720p con la pausa del directo funcionando. Desactivar el cliente curl de mpv (`curl-enabled=no`) también quitaba la cabecera, pero deja el TLS sin verificar certificados: no vale.
- **Telecinco y Cuatro dejaron de verse porque la lista les cambió la web.** TDTChannels mudó sus dos canales grandes de `mitele.es` a `www.mediasetinfinity.es/directo/<canal>/`. La aplicación reconocía a cada emisora buscando un trozo de texto dentro de la dirección («mitele»), así que la web nueva no encajaba con nadie, no había resolutor, se abría el navegador y salía el error propio de Mediaset («ID: DAI»). Y no quedaba rastro de nada: ese caso ni siquiera se anotaba en el registro. Ahora hay **dos capas**. La primera: cada emisora se reconoce por el **dominio** de su web (`DOMINIOS_PROVEEDOR` con `es_dominio`), de modo que un subdominio nuevo o una marca nueva de la misma casa siguen valiendo; de paso se arregló que «mitele» estuviera también dentro de `mitelefe.com`, que es la web argentina de Telefe y no tiene nada que ver. La segunda, la que hace que esto no vuelva a pasar: si el dominio **no suena de nada**, `resolver_por_nombre` saca el nombre del canal de la ruta (`/directo/telecinco`) y se lo pregunta a Mediaset y a Atresplayer con sus propias direcciones, porque sus APIs solo piden eso, el nombre. Comprobado con direcciones inventadas: `https://una-web-nueva-cualquiera.es/directo/telecinco` y `https://otra-web.example/directos/antena3/` devuelven el directo igual, y queda un aviso en el registro diciendo qué dominio conviene añadir. Una página que no sea un directo (`tvperu.gob.pe/play`) no pregunta nada y sigue yendo al navegador, como antes. El **comprobador de canales** mira ahora también los canales de web oficial: de 120, doce responden, nueve fallan de verdad (403 por zona casi todos) y el resto son de los que solo se ven con el reproductor de su web, que no cuentan como fallo.
- **Escape cierra los cuadros de Sí o No.** El cuadro de mensaje nativo de Windows con solo Sí y No **ignora Escape**: Win32 solo lo admite cuando hay un botón Cancelar, y meter un tercer botón confunde más que ayuda. Comprobado enviando la tecla de verdad: el nativo seguía abierto, `wx.GenericMessageDialog` con `SetEscapeId(wx.ID_NO)` se cierra al momento y responde «No». `widgets.pregunta` lo usa ya, así que quedan arreglados de golpe la treintena de sitios que preguntan (quitar listas, borrar grabaciones, DNS, perfiles, reglas, PIN, recordatorios…), y hay una prueba que impide volver a colar un Sí/No nativo.
- **El navegador integrado se quedaba sin ninguna tecla en los canales que solo se ven en su web.** Ni Escape para cerrar ni Ctrl+B para ir a la barra de botones: la ventana quedaba sin salida. La causa estaba en `actualizar_script()`, que reinstala el script de accesibilidad con `RemoveAllUserScripts()` y `AddUserScript()`. **`RemoveAllUserScripts` borra todos los scripts que se ejecutan al crear cada documento, y wxWidgets instala ahí el suyo**: el que crea `window.tdt`, el puente por donde la página le manda las teclas a la aplicación. Al reinstalar solo el script propio, la página seguía escuchando las teclas y **comiéndoselas** (`preventDefault`) sin poder avisar a nadie. Le pasaba solo a los canales marcados NOEM (VEO7, BOM Cine…), porque son los únicos que se abren primero en segundo plano buscando su emisión y pasan por `mostrar_ventana`; los demás nunca reinstalan el script y por eso Escape siempre les funcionó. Medido en el camino real del canal: con la ventana oculta el puente estaba vivo y, tras mostrarla, muerto. Ahora `_reponer_puente()` vuelve a registrarlo cada vez que se borran los scripts, y el vigilante de teclas comprueba **las dos mitades**, el script y el puente, no solo el script. Comprobado con VEO7 y BOM Cine por su camino entero: Ctrl+B lleva el foco al botón de la barra y Escape cierra la ventana.
- **Escape cierra también el navegador integrado cuando el foco está dentro del vídeo.** Medido: con el foco dentro del WebView2, **wxPython no ve ninguna pulsación** (con el foco en un cuadro de texto de la misma ventana sí la ve), así que todas las teclas de la aplicación dependen del script inyectado en la página. El script sí entra en los marcos, pero **dentro de un marco no existe el puente con la aplicación**, que WebView2 solo pone en el documento principal: el Escape pulsado dentro del reproductor de la web se perdía sin más. Ahora el marco reenvía el aviso al documento de arriba (`window.top.postMessage`) y este lo pasa al puente; comprobado que llega. Y como el problema aparecía también en páginas **sin marcos**, el script se endureció por tres sitios más: se escucha en la **ventana** además de en el documento (la captura de la ventana va antes que la de cualquier documento, así que una web que se quede con las teclas ya no deja la ventana sin salida), con una marca en el evento para no atender dos veces la misma pulsación —comprobado: un mensaje por pulsación—; **en pantalla completa Escape no se roba**, porque ahí lo gasta el propio navegador en salir de ella y la ventana se cierra a la segunda, que es lo que espera cualquiera; y un **vigilante cada cuatro segundos** comprueba que el puente sigue vivo y lo repone, porque las webs de hoy cambian de página sin recargar y el script se perdía sin que saltara ningún aviso de carga. Si aun así no se puede reponer, el foco se lleva a la barra de botones en vez de dejarlo atrapado, porque allí Escape sí cierra. Y los avisos hablados dicen ahora que **Alt+F4 cierra siempre**, que es la salida que no depende de la página.
- **El menú Herramientas, por categorías.** Tenía veinticinco opciones seguidas, que con lector de pantalla es una lista larga de recorrer. Ahora quedan sueltas arriba solo Buscar canal y Ajustes, y el resto están en ocho submenús (Guía y recordatorios, Grabación, Canales y listas, Accesibilidad y teclas, Privacidad, Copias de seguridad, Solucionar problemas y Mantenimiento), sin letras de acceso repetidas dentro de cada uno.

---

## 13. Lo siguiente: investigado y sin hacer

Con lo anterior implementado, esto es lo que sale de mirar otra vez qué hay ahí fuera. Cada idea dice qué es, por qué encaja **en esta aplicación** y qué haría falta.

1. **Subtítulos y transcripción de las grabaciones con Whisper en local.** `whisper.cpp` transcribe sin conexión y sin subir nada a ningún sitio, y saca directamente `.srt` o `.vtt` (`-osrt`, `-ovtt`). Aquí valdría para dos cosas muy distintas y las dos importantes: **subtítulos para quien no oye bien** en emisiones que no los llevan, y **buscar dentro de una grabación** («¿en qué minuto hablan de esto?»). Lo caro es el modelo (unos cientos de megabytes) y el tiempo de proceso; encajaría como orden posterior a la grabación, que ya existe, o como opción en el diálogo de grabaciones.
2. **Sintonizador de televisión de verdad (TDT).** La aplicación se llama Resintoniza y hoy solo ve IPTV. Un **HDHomeRun** en la red publica `discover.json` y `lineup.json` (y hasta `lineup.m3u`), así que sus canales entrarían por el lector M3U que ya hay, con su número y su nombre. Sería la TDT de casa, sin depender de que nadie publique una lista, y el mismo camino sirve para los servidores Tvheadend de la red local.
3. **Avisos del sistema (toast) de Windows.** Los recordatorios y el «ha empezado tu grabación» solo se ven ahora dentro de la aplicación. Con `windows-toasts` o `win11toast` (los dos por WinRT) saldrían en el Centro de notificaciones, que además los guarda y los lee el lector de pantalla aunque estés en otro programa. Encaja con la interfaz invisible que ya existe.
4. **Catálogo de emisoras de Radio Browser.** `api.radio-browser.info` es un directorio comunitario y libre con más de 45.000 emisoras, con búsqueda por país, idioma, etiqueta y códec, sin clave de API. Sería para la radio lo que iptv-org fue para la televisión (sección 9), y con el mismo diálogo de importar.
5. **Podcasts y programas a la carta por RSS.** Quien escucha la radio suele querer el programa de ayer. Leer un RSS de audio y ofrecer los últimos episodios (con descarga y reanudar donde lo dejaste, que ya funciona) es poco código y encaja con lo que ya hay.
6. **Buscar dentro de la guía por voz** y **resumen hablado del día**: «esta noche en tus favoritos hay tres películas y un partido». Con la guía que ya se descarga y la voz que ya está integrada.
7. **Estadísticas de uso**: qué canales ves más, cuánto tiempo, qué grabas. Serviría para ordenar los canales por lo que de verdad usas, no por el orden de la lista.
8. **Grabar el segundo audio** (versión original o audiodescripción) en la misma grabación, o elegir qué pista se guarda cuando la emisión trae varias.
9. **Marcadores dentro de una grabación**: dejar marcas mientras se escucha para volver luego, que en tertulias largas es lo que de verdad hace falta.
10. **Ver lo grabado desde el móvil**: publicar la carpeta de grabaciones por DLNA con el mismo servidor que ya se usa para enviar a la tele.

### Lo que se ha mirado y no conviene

- **Descifrar DRM**: fuera de lugar y de la ley; se sigue detectando y avisando.
- **Recodificar al grabar** para que ocupe menos: pide FFmpeg completo y mucha CPU, y estropea lo que hoy es una copia exacta. Para ahorrar espacio ya está la grabación solo de audio, que no recodifica nada.
- **Servidor para ver la tele desde otro aparato**: eso es otro programa, no una función de este.


## Avisos

- Las credenciales de un proveedor se guardan cifradas con la protección de datos de Windows. Si esa protección no estuviera disponible, la aplicación lo advierte en lugar de guardar la contraseña en claro sin avisar.
- Las emisiones con DRM (Widevine y similares) no se pueden reproducir con libmpv y no se intenta sortearlo: se detectan al leer la lista y se avisa antes de intentarlo.
- El catch-up, la grabación y el archivo dependen de lo que permita cada proveedor; cuando no se puede, se dice.

## Fuentes consultadas

- [Documentación de la API de Xtream Codes](https://github.com/worldofiptvcom/xtream-codes-api-documentation)
- [Cliente Python de Xtream Codes](https://github.com/chazlarson/py-xtream-codes)
- [Referencia del formato M3U para IPTV: atributos, EPG y catch-up](https://uniplayer.net/docs/specs/m3u/)
- [Analizador de listas M3U con etiquetas IPTV](https://github.com/notsurewhoisthis/iptv-m3u-playlist-parser)
- [Etiquetas M3U avanzadas](https://m3u.codes/guides/advanced-m3u-tags/)

Para la sección 12 (el grabador completo, ya implementado):

- [Reglas de grabación automática (autorec) de Tvheadend](https://profyaffle.github.io/versionB/webui/dvr_autorec/) y su [guía electrónica de programas](https://github.com/tvheadend/tvheadend/blob/master/docs/markdown/epg.md), de donde salen las reglas por palabra clave y el control de repeticiones
- [Reglas de grabación (timer rules) en Kodi](https://github.com/djp952/pvr.hdhomerundvr/wiki/Timers-and-Timer-Rules) y sus [ajustes de grabación](https://kodi.wiki/view/Settings/Live_TV/Recording), con los márgenes de inicio y final
- [Post-procesado de grabaciones en Jellyfin](https://jellyfin.org/docs/general/server/live-tv/post-process/), para las órdenes posteriores y la limpieza automática
- [Comparativa de clientes IPTV 2026](https://troypoint.com/the-best-iptv-players/) y [reseña de OTT Navigator](https://iptvranking.com/ott-navigator-review/), de donde vienen la multiventana y el catálogo de películas y series
- El manual de mpv clonado en `adjuntos/mpv-docs`: [modo de codificación](adjuntos/mpv-docs/DOCS/man/encode.rst) (que confirmó que este libmpv no admite `--ovc=copy`) y la propiedad `stream-pos` de [input.rst](adjuntos/mpv-docs/DOCS/man/input.rst), con la que se recorta por bytes

Para la sección 13 (lo siguiente, todavía sin hacer):

- [whisper.cpp para transcribir sin conexión en Windows](https://weesperneonflow.ai/en/blog/2026-06-23-whisper-cpp-setup-guide-local-speech-recognition-2026/) y [cómo genera subtítulos SRT en local](https://localaimaster.com/blog/local-ai-subtitles-whisper)
- [API HTTP de HDHomeRun](http://info.hdhomerun.com/info/http_api) (`discover.json`, `lineup.json`, `lineup.m3u`), para meter la TDT de casa por el lector M3U que ya existe
- [Windows-Toasts](https://pypi.org/project/Windows-Toasts/) y [win11toast](https://pypi.org/project/win11toast/), para que los avisos salgan en el Centro de notificaciones de Windows
- [API de Radio Browser](https://api.radio-browser.info/), directorio libre de más de 45.000 emisoras sin clave de API
