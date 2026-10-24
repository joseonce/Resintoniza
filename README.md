# Resintoniza

Aplicación de escritorio para **Windows de 64 bits**, escrita en Python y **wxPython**, con interfaz en español y pensada para teclado y lectores de pantalla. Reproduce canales de televisión y emisoras de radio a partir de listas públicas de Internet. Se desarrolló a partir del análisis funcional de una aplicación Android equivalente (ver `analisis/INFORME.md`).

## Qué hace

- **Televisión y radio** a partir de listas públicas (con servidor de respaldo y copia en caché si no hay conexión), más hasta diez listas propias: **M3U y M3U8** (el formato habitual en IPTV, con `tvg-id`, `tvg-logo`, `group-title`, `tvg-chno`, `catchup` y cabeceras `#EXTVLCOPT`), JSON con el mismo formato de las incluidas, de Internet o del propio equipo.
- **Cuentas de proveedor (Xtream Codes)**: servidor, usuario y contraseña. Traen sus canales, su programación y sus **películas y series**, que aparecen en su propia pestaña. La contraseña se guarda cifrada con la protección de datos de Windows, nunca en claro.
- **Catálogo de iptv-org** integrado: Archivo > Añadir canales del catálogo de iptv-org elige país, idioma o categoría de su colección pública y añade esa lista sin escribir ninguna dirección. Se comprueba antes de guardarla y se dice cuántos canales trae.
- **Directos de las webs oficiales**: Telecinco, Cuatro, FDF, Energy, Divinity, Boing, BeMad (Mitele), Antena 3, laSexta, Neox, Nova, Mega, Atreseries (Atresplayer), DMAX, GOL y emisiones Dailymotion se obtienen consultando la API de cada emisora en el momento de reproducir, como hace el APK. Los canales de Atresmedia se añaden a la lista porque la lista pública ya no los incluye.
- Búsqueda sin tildes, filtro por categoría o comunidad, categorías ocultables, favoritos, canales ocultos (mostrar, no mostrar o solo ocultos) y orden personal.
- Varias emisiones por canal, notas del canal (solo España, requiere registro, sin emisión), YouTube, Twitch y web oficial en el navegador.
- Reproductor integrado con **libmpv**: pausa, detener, volumen, silencio, pistas de audio, subtítulos (preferencia de idioma), tamaño de imagen, pantalla completa, canal anterior y siguiente, volver al canal anterior.
- **Guía** de programación con programa actual y siguientes, **temporada y episodio, géneros, año, valoración y edad recomendada**, recordatorios y búsqueda del título en FilmAffinity, IMDb, Rotten Tomatoes y Google. Además de la guía asociada a las listas se usa una **guía ampliada en formato XMLTV** que cubre canales que aquella no trae (Antena 3, laSexta, Neox, Nova, Mega, Atreseries y varias autonómicas), con **cinco variantes a elegir** y sitio para guías propias. Herramientas > Guía y recordatorios > Cobertura de la guía dice qué canales tienen programación y con qué nombre la tendrían los que no.
- **Arranque con lo que ya está guardado**: las listas, la guía y los canales de las cuentas se guardan en `data/cache` y al abrir se usan tal cual, así que la aplicación abre rápido y **funciona sin conexión**. Solo se actualizan cuando lo pides (Ctrl+Mayús+R) o con la frecuencia que elijas en Ajustes: nunca, cada vez, cada día o cada semana. Comprobado: 1.953 canales y su programación cargados con la red desconectada.
- **DNS alternativo** (Herramientas > Solucionar problemas): cuando el operador bloquea el acceso a una emisión, se puede poner un DNS público con DNS sobre HTTPS y volver después a la configuración de siempre, que se guarda antes de tocar nada. Windows pide permiso; la aplicación no lo activa por su cuenta. Si ya usabas la herramienta `xdp_manager`, su `xdp_configuracion_original.json` se puede importar (y se ofrece solo si se encuentra), para que al restaurar quede exactamente lo que tenías.
- Temporizador de apagado, reproducción en la bandeja del sistema al cerrar la ventana, importación y exportación de la configuración, **compatible con la de la aplicación Android**.
- **Grabar en segundo plano**: cada grabación abre **su propio reproductor, sin imagen ni sonido**, así que no ocupa el reproductor principal: puedes escuchar un canal mientras se graban otros, y pausar, cambiar de canal o detener no le afecta. Se pueden encadenar **varias grabaciones programadas a la vez** (el máximo se elige en Ajustes) y, si el directo se corta, la grabación se reanuda sola en otro archivo. En Herramientas > Grabación > Grabaciones se ve **cuánto lleva cada una, cuánto le queda y cuánto ocupa**, y se detiene la que quieras con Suprimir. En Ajustes se puede volver al modo clásico, que graba lo que se está viendo con el reproductor principal sin descargarlo dos veces. No se recodifica nada: el formato lo elige la emisión (`.ts` en HLS, `.mkv` en lo demás).
- **Reglas de grabación automática**: «graba siempre lo que lleve *Telediario* en La 1». Cada regla busca en la guía (en el título o también en la descripción, por canal o solo en favoritos, con días y franja horaria) y **programa sola** las grabaciones, evitando repeticiones por episodio, por título o una vez por semana. Se crean desde Herramientas > Grabación o con «Grabarlo siempre» en cualquier programa de la guía.
- **Grabación con cabeza**: márgenes de antes y después (generales o por canal, para los que empiezan tarde), carpeta por programa, **grabar solo el audio** (2 megabytes por minuto en vez de 22), aviso de conflictos cuando se solapan más grabaciones de las que caben, **espacio libre mínimo** con parada automática si el disco se llena, **limpieza automática** por días, por número de grabaciones de cada programa o por gigabytes (con grabaciones protegidas), orden posterior al terminar, y **cerrar, suspender o apagar** el equipo cuando acabe la última.
- **Grabar con la aplicación cerrada**: si se activa, se crean tareas en el **Programador de Windows** que abren la aplicación (y despiertan el equipo) unos minutos antes de cada grabación programada.
- **Recortar una grabación** sin recodificar, **reanudarla donde la dejaste** y ver de un vistazo cuánto ocupa todo y cuánto espacio queda.
- **Multiventana**: hasta cuatro canales a la vez, cada uno con su reproductor, eligiendo con las cifras cuál suena.
- **Qué empieza ahora**: lo que arranca en los próximos minutos en tus favoritos, listo para grabar, poner recordatorio o crear una regla.
- **Comprobador de canales**: dice en segundo plano qué canales responden y cuáles están caídos, y ofrece ocultarlos, sin tocar lo que estés escuchando.
- **Nivelador de volumen** entre canales, velocidad de reproducción con corrección de tono y ajuste del retraso del audio.
- **Sincronizar con la nube**: la configuración, los favoritos y las reglas se guardan en una carpeta de OneDrive, Dropbox o similar para llevarlos a otro equipo.
- **Pausa del directo**: guardando unos minutos de emisión se puede retroceder y volver luego al directo.
- **Catch-up**: en las listas que lo declaran, la programación ofrece «Ver este programa emitido» para lo ya emitido.
- **Con muchos canales**: número de canal (se teclean las cifras como en un mando), historial, bloqueo por PIN de canales o categorías, aviso de duplicados al mezclar listas y búsqueda de un título en toda la guía.
- **Robustez**: reintentos con espera creciente si se corta el directo, salto automático a otra emisión del mismo canal, elección de calidad en emisiones con varias resoluciones y datos técnicos de la emisión en un diálogo accesible, que además cuenta los cortes que ha habido.
- **Búfer de recepción** en tres niveles (Ajustes > Reproductor): mínimo, pegado al directo; normal, con unos quince segundos de margen; y amplio, más margen a cambio de más retraso. En directo no se puede guardar por delante más de lo que el servidor publica, así que lo que da margen de verdad es empezar unos fragmentos por detrás del directo, y eso es lo que hacen los perfiles.
- **Enviar a la tele**: **DLNA o UPnP** (casi cualquier televisor), **Chromecast** y Google TV, y los **Fire TV o Android TV** se detectan y se explica cómo verlos: con una aplicación receptora DLNA en el aparato, o duplicando la pantalla de Windows, que Fire TV admite de fábrica.
- **Copias de seguridad y perfiles de uso** (por ejemplo «casa» y «trabajo»), cada uno con sus favoritos, su orden y sus ajustes.
- Ajustes: tema claro u oscuro, alto contraste, tamaño de letra, comportamiento al cerrar, subtítulos, tamaño de imagen, calidad, grabación, organización, accesibilidad y actualizaciones.

## Carpeta `data`

Todo lo que la aplicación necesita o genera está en la carpeta `data`, junto al programa (o donde indique la variable de entorno `TDT_DATA`):

| Contenido | Descripción |
|---|---|
| `data/mpv/libmpv-2.dll` | Motor de audio y vídeo. La carpeta compilada ya lo incluye; solo debe haber ese archivo. La aplicación busca versiones nuevas una vez por semana (se puede desactivar en Ajustes) y en Herramientas > Mantenimiento > Buscar actualizaciones del reproductor. Si el reproductor está en uso, la versión nueva se instala al reiniciar. |
| `data/ajustes.json` | Favoritos, ocultos, orden, listas, recordatorios y ajustes. |
| `data/cache/` | Última copia de las listas y de la guía. |
| `data/logs/aplicacion.log` | Registro de errores. |
| `data/navegador/` | Perfil del navegador integrado (caché y cookies de las webs de las emisoras). |
| `data/sonidos/` | Avisos sonoros, generados por la propia aplicación la primera vez. |
| `data/bin/` | Complemento de NVDA listo para instalar. |
| `data/grabaciones/` | Grabaciones (se puede cambiar la carpeta en Ajustes). |
| `data/perfiles/` | Perfiles de uso guardados. |
| `data/dns-original.json` | Configuración DNS que había antes de activar el DNS alternativo, para poder restaurarla. Se puede importar la que guardó `xdp_manager`. |

Al compilar, `data` se copia **limpia**: `data/mpv` con la DLL, los avisos sonoros y el complemento de NVDA. Así la carpeta compilada es una instalación de cero, sin ajustes, caché ni grabaciones de nadie.

## Uso rápido

Abre `Resintoniza.bat` y elige una opción del menú:

1. Crear el entorno virtual e instalar dependencias (`wxPython`, `python-mpv`, `cx_Freeze`).
2. Preparar la carpeta `data` (descarga `libmpv-2.dll`). Si no lo haces, la propia aplicación lo ofrece la primera vez que reproduces algo.
3. Ejecutar desde el código fuente.
4. Ejecutar las pruebas.
5. Compilar con cx_Freeze en `build\Resintoniza` (incluye Python, wxPython, los runtimes de Visual C++, la copia limpia de `data` y, como documentación, `MANUAL.md` y `LICENCIAS.md`).
6. Todo lo anterior seguido.

También admite argumentos: `Resintoniza.bat entorno`, `datos`, `ejecutar`, `pruebas`, `compilar` o `todo`.

Requisitos para desarrollar: Python 3.13 de 64 bits instalado desde python.org con el lanzador `py`. Para usar la carpeta compilada no hace falta instalar nada: copia `build\Resintoniza` completa y abre `Resintoniza.exe`.

Desde la línea de órdenes:

```bat
.venv\Scripts\python.exe main.py
.venv\Scripts\python.exe main.py --preparar
.venv\Scripts\python.exe main.py --comprobar
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe setup_cx.py build_exe
```

## Los menús

La barra de menús tiene cinco menús. **Herramientas** reúne muchas opciones, así que están **agrupadas en submenús** por tarea; solo Buscar canal y Ajustes quedan sueltos arriba, por ser los de todos los días:

| Menú | Contenido |
|---|---|
| **Archivo** | Actualizar listas y guía, añadir lista, catálogo de iptv-org, cuenta de proveedor, exportar e importar la configuración, exportar los favoritos a M3U, salir. |
| **Canal** | Lo que se puede hacer con el canal seleccionado: reproducir, web oficial, programación, favoritos, ocultar, copiar el enlace, orden personal, número y bloqueo por PIN. |
| **Reproducción** | Todo el reproductor: pausa, volumen, canal anterior y siguiente, ventana de vídeo, pantalla completa, multiventana, pistas, calidad, grabación, pausa del directo, enviar a la tele, temporizador y datos de la emisión. |
| **Herramientas** | Buscar canal · Ajustes · **Guía y recordatorios** (buscar en toda la guía, qué empieza ahora, recordatorios, guías de programación, cobertura) · **Grabación** (grabaciones, reglas automáticas) · **Canales y listas** (cuentas de proveedor, categorías visibles, duplicados) · **Accesibilidad y teclas** (personalizar teclas, teclas en segundo plano, plantillas de lectura) · **Privacidad** (PIN, perfiles de uso) · **Copias de seguridad** (copia, sincronizar con la nube) · **Solucionar problemas** (comprobar canales, DNS alternativo, limpiar caché) · **Mantenimiento** (versiones de la aplicación, actualizar libmpv, complemento de NVDA). |
| **Ayuda** | Uso y teclado, manual de usuario (`MANUAL.md`, en el diálogo HTML accesible), teclas actuales, registro de errores, aviso legal y Acerca de. |

Cada opción muestra a la derecha su tecla actual, y los menús se rehacen al cambiarla.

## Teclado y accesibilidad

Los controles son nativos de Windows con etiqueta y nombre accesible. Las listas de canales, emisiones, programación, listas y recordatorios son **listas accesibles en columnas** como las de SocialRSS:

- Flechas arriba y abajo cambian de fila; **izquierda y derecha** leen la fila columna a columna; **Ctrl+1 a Ctrl+9** leen una columna concreta; **Ctrl+0** lee la fila entera con la plantilla de lectura.
- **Plantillas de lectura** (Herramientas > Accesibilidad y teclas > Plantillas de lectura, o Ajustes > Accesibilidad): decides qué columnas tiene cada lista y en qué orden se leen, con modelos rápidos, inserción de campos y vista previa. Por ejemplo, para los canales de televisión: `{nombre}. {ahora}. {estado}. {notas}`.
- En **Ajustes > Accesibilidad** eliges si al moverte por columnas se dice el número de fila, el nombre de la columna y el contenido; si los avisos y el estado de la reproducción se envían por **voz directa** al lector de pantalla (NVDA, JAWS o SAPI mediante accessible_output2) y a braille; y el retardo de la voz.
- Todos los elementos tienen **menú contextual** (tecla Aplicaciones, Mayús+F10 o botón derecho): reproducir, elegir emisión, web oficial, programación, favoritos, ocultar, orden personal, copiar; en la guía, ver canal, recordatorio y búsqueda del título.
- **Programación**: el botón Programación, Ctrl+G o el menú contextual abren la programación completa del canal seleccionado; la pestaña Guía muestra la programación desde ahora de cualquier canal.

**La ventana principal solo tiene las listas**: no hay botones ni deslizadores del reproductor, porque todo se maneja con las teclas de función y desde los menús. El canal en reproducción aparece en el título de la ventana y el estado en la barra inferior, que F12 lee en voz alta.

**La ventana de vídeo no se abre sola.** Quien no necesite la imagen no se encuentra con una ventana de por medio: el sonido va por su cuenta y la barra de estado recuerda una vez que la imagen está a un toque de tecla. **F10** la abre y la cierra, **F11** la pone a pantalla completa y **Escape** la cierra sin parar el sonido; dentro hay un texto que explica qué se puede hacer y botones para cerrarla o ponerla a pantalla completa. Si prefieres que se abra sola, se activa en Ajustes > Reproductor, y en ese caso aparece **sin robar el foco**, así que sigues en la lista de canales.

### Reproductor en F1 a F12 y teclas personalizables

Como en SocialRSS, el reproductor se maneja con teclas de función que funcionan **en toda la aplicación**, también con un diálogo abierto:

| Tecla | Acción |
|---|---|
| F1 | Diálogo rápido de favoritos (Intro reproduce) |
| F2 | Reproducir o pausar |
| F3 | Recargar la emisión (si se corta el directo) |
| F4 | Detener |
| F5 / F6 | Bajar / subir el volumen |
| F7 / F8 | Canal anterior / siguiente |
| F9 | Silenciar o activar el sonido |
| F10 | Mostrar u ocultar la ventana de vídeo |
| F11 | Pantalla completa (Escape sale) |
| F12 | Decir el estado de la reproducción |
| Ctrl+Alt+R | Grabar o detener la grabación |
| Ctrl+Alt+Z / Ctrl+Alt+X | Retroceder 30 segundos del directo / volver al directo |
| Ctrl+Alt+U / Ctrl+Alt+C | Modo solo audio / calidad de la emisión |
| Ctrl+Alt+D / Ctrl+Alt+T | Datos técnicos de la emisión / enviar a la tele |
| Ctrl+Mayús+H / Ctrl+N | Historial de canales / ir a un número de canal |
| Ctrl+Alt+M | Multiventana: varios canales a la vez |
| Ctrl+Alt+N | Nivelar el volumen entre canales |
| Ctrl+Alt+G / Ctrl+Alt+A | Reglas de grabación automática / qué empieza ahora en favoritos |
| Ctrl+Mayús+F | Buscar en toda la guía |
| Ctrl+B | En el navegador integrado, cambiar entre la página y la barra de botones |

En la lista de canales, **teclear las cifras** salta a ese número, como en un mando a distancia.

Todas las teclas se cambian en **Herramientas > Accesibilidad y teclas > Personalizar teclas** (Ctrl+K): por secciones, con captura de la combinación, aviso de conflictos y restaurar por acción, sección o todo. Los menús, los menús contextuales y **Ayuda > Teclas actuales** se construyen a partir del catálogo de teclas, así que siempre muestran la combinación vigente. Las teclas del reproductor solo admiten teclas de función o combinaciones con Ctrl o Alt, porque actúan aunque el foco esté en un campo de texto.

### Casi todo se ve con el reproductor de la aplicación

Al pulsar Reproducir, la aplicación **busca siempre la dirección real del directo** para verlo con su propio reproductor, que es el accesible. Solo si no la encuentra recurre al navegador:

| Tipo de canal | Cómo se obtiene la emisión |
|---|---|
| Emisión directa en la lista | Se reproduce tal cual |
| Telecinco, Cuatro, Antena 3, laSexta, DMAX, GOL… | Servicio oficial de la emisora, igual que el APK |
| **YouTube** (más de 140 canales) | Se averigua qué vídeo emite el canal y se pide su lista HLS al servicio del reproductor de YouTube |
| **Twitch** (26 canales) | Firma de reproducción de Twitch y lista HLS del canal |
| Webs de emisoras (Telemadrid, À Punt, Aragón TV, La Xarxa…) | Se lee la web y sus scripts; si no aparece, se abre en segundo plano y se detecta lo que pide la página |
| Sin emisión (DMAX cuando no emite, Ten, VEO7…) | Se abre su web en el navegador integrado |

Si el canal no está emitiendo en ese momento, la aplicación lo dice en lugar de dejar una pantalla en blanco.

### Canales que solo funcionan desde su web: se detecta su emisión

Cerca de cien canales (Telemadrid, À Punt, Aragón TV, La 7 de Castilla y León, La Xarxa, Navarra TV, RTVCE, RTP…) no publican una dirección de emisión en la lista: el APK los ve con su navegador integrado. Aquí la aplicación hace algo mejor:

1. Al pulsar Reproducir abre la web **en segundo plano y en silencio**, y dice «Buscando la emisión de X en su web…».
2. Vigila las peticiones de la página, incluidas las de sus marcos, hasta encontrar la lista HLS o DASH del directo, descartando las de publicidad y medición. Si hace falta, pulsa el botón de reproducir de la web y acepta el aviso de cookies.
3. Cuando la encuentra, **reproduce esa dirección con el reproductor de la aplicación** (con la referencia y el agente de la web) y cierra el navegador. A partir de ahí es una emisión normal: teclas, pistas de audio, subtítulos, pantalla completa y grabación de estado.
4. Si en unos veinte segundos no aparece, se muestra la web para verla a mano, como antes.

También funciona a mano: en el navegador integrado, el botón **Reproducir en la aplicación** usa la última emisión detectada.

### Canales que solo emiten desde su web: navegador integrado accesible

Los canales marcados «se ve en su web oficial» (DMAX, Ten, Squirrel, VEO7, DKISS, BOM Cine…) no tienen emisión directa en la lista; la aplicación Android los ve con su navegador integrado. Aquí ocurre lo mismo: Reproducir abre la web de la emisora en una ventana con **Edge WebView2**. Sigue la técnica de la librería **wx-accessible-webview** (la accesibilidad se resuelve desde dentro de la página, no desde el control nativo): en cada página se inyecta un script que añade una región de estado en español que el lector anuncia, un puente de teclas y el control del vídeo de la web.

- **Ctrl+B** cambia entre la página y la barra de botones, y **Escape** cierra la ventana desde cualquier sitio (también dentro de la página) y devuelve el foco a la lista de canales. Las teclas del reproductor conservan su función: F5 y F6 cambian el volumen del vídeo de la web. El foco nunca se queda dentro de los marcos de otras webs, para que esas teclas siempre respondan.
- Las **teclas del reproductor** funcionan dentro de la página: F2 reproduce o pausa el vídeo de la web, F4 lo detiene, F5 y F6 cambian su volumen, F9 lo silencia y F12 dice su estado. F1, F7, F8 y las demás siguen actuando sobre la aplicación.
- Barra de botones nativa: Ir a la página, Reproducir el vídeo, Atrás, Adelante, Recargar, Navegador externo y Cerrar; campo de dirección y campo de estado legibles.
- Al cargar, intenta arrancar el vídeo: primero el `<video>` de la página, si no, **pulsa el botón de reproducir de la web** (por clase, identificador o `aria-label`, con la misma tabla que usa el APK) y acepta los avisos de cookies. Si el reproductor está dentro de un marco, ofrece abrirlo como página principal.
- Si la web no está emitiendo (DMAX, Ten y otros solo emiten a veces), lo dice con claridad en lugar de quedarse en silencio.

Se desactiva en Ajustes > Reproductor («Canales web en la app» y «YouTube en la app», los mismos ajustes que el APK) para usar el navegador predeterminado. El perfil de WebView2 se guarda en `data/navegador`. La ayuda (Uso y teclado, Teclas actuales) usa los diálogos HTML accesibles de la misma librería, con encabezados y tablas navegables.

| Tecla | Acción |
|---|---|
| Tab / Mayús+Tab, Alt | Recorrer controles, abrir menús |
| Ctrl+F | Buscar canal |
| Flechas, Intro | Elegir canal, reproducir |
| Izquierda, Derecha, Ctrl+1…9, Ctrl+0 | Leer la fila por columnas, una columna, la fila entera |
| Aplicaciones / Mayús+F10 | Menú contextual del elemento |
| Ctrl+P / Ctrl+W | Reproducir / web oficial |
| Ctrl+G / Ctrl+Mayús+G | Programación del canal / ver en la guía |
| Ctrl+D / Ctrl+H | Favorito / ocultar o mostrar |
| Ctrl+Mayús+C / Ctrl+Mayús+I | Copiar enlace / leer la información del canal |
| Alt+Arriba / Alt+Abajo | Mover en el orden personal |
| Ctrl+Mayús+B | Volver al canal anterior |
| Ctrl+Mayús+A / Ctrl+Mayús+T | Pista de audio / subtítulos |
| Ctrl+E / Ctrl+R | Temporizador / recordatorios |
| Ctrl+Mayús+R / Ctrl+L | Actualizar listas / añadir lista |
| Ctrl+, / Ctrl+K / Ctrl+F1 / Ctrl+Q | Ajustes / personalizar teclas / ayuda / salir |

### Accesibilidad añadida

- **Avisos sonoros** para empezar, parar, error de emisión, recordatorio, grabación, cambio de canal y tope alcanzado; se activan uno a uno en Ajustes.
- **Anuncio del programa al sintonizar**: «La 1, ahora Telediario, hasta las 16:00. Después, …».
- **Modo solo audio**: no se descarga ni se muestra el vídeo. Útil para la radio y para escuchar la tele de fondo.
- **Audiodescripción**: cuando la emisión trae esa pista, se selecciona sola y se avisa. Comprobado con La 1, que la emite.
- **Complemento de NVDA** (Herramientas > Mantenimiento > Instalar el complemento de NVDA): amplía a 16.384 el límite de 511 caracteres por columna, para que se lean enteras las descripciones largas de la guía. Se genera en `data/bin` y se desactiva cuando se quiera desde el administrador de complementos.
- **Interfaz invisible**: con la aplicación en segundo plano, Ctrl+Alt más una tecla pausa, cambia de canal, sube el volumen, dice qué suena o graba, sin volver a la ventana. Se activa en Ajustes > Accesibilidad y las combinaciones se cambian en Herramientas > Accesibilidad y teclas.

## Diferencias con el APK

- Sin cuentas de la aplicación original, suscripciones, anuncios ni sincronización en la nube.
- Las webs que el APK abre en su navegador integrado (YouTube, Twitch, páginas web y las emisoras que solo funcionan con WebView, como RTPA o 7TV Andalucía) se abren en el navegador predeterminado de Windows.
- Los recordatorios avisan mientras la aplicación está abierta.
- Las restricciones geográficas, el registro y la disponibilidad dependen de cada emisora, igual que en Android.

## Archivos

- `main.py`: arranque; `--preparar` y `--comprobar`.
- `tdt/datos.py`: carpeta `data`, ajustes compatibles con el APK, caché y descarga de libmpv.
- `tdt/catalogo.py`: listas, marcas `extra_info`, filtros y guía.
- `tdt/proveedores.py`: directos de Atresplayer, Mitele, DMAX, GOL y Dailymotion, y cabeceras de reproducción.
- `tdt/reproductor.py`: integración de libmpv (pistas, calidad, grabación, pausa del directo y estadísticas).
- `tdt/m3u.py`, `tdt/xtream.py`, `tdt/catchup.py`: listas M3U, cuentas de proveedor y programas ya emitidos.
- `tdt/grabacion.py`, `tdt/organizar.py`, `tdt/sonidos.py`, `tdt/globales.py`, `tdt/casting.py`: grabación, numeración e historial, avisos sonoros, teclas en segundo plano y envío a la tele.
- `tdt/respaldo.py`, `tdt/actualizacion.py`, `tdt/cifrado.py`: copias y perfiles, versiones nuevas y contraseñas cifradas.
- `tdt/interfaz.py`, `tdt/dialogos.py`, `tdt/widgets.py`: interfaz wxPython.
- `tdt/iptvorg.py`: catálogo público de iptv-org (índices por país, idioma y categoría).
- `tdt/dns_xdp.py`: DNS alternativo para bloqueos del operador, con copia y restauración de la configuración.
- `nvda_addon/`, `tools/construir_addon.py`: complemento de NVDA y su empaquetado.
- `tdt/accesible.py`, `tdt/plantillas.py`, `tdt/teclas.py`, `tdt/voz.py`: listas accesibles en columnas, plantillas de lectura, catálogo de teclas y voz directa al lector de pantalla.
- `tdt/navegador.py`, `tdt/servidor.py`, `tdt/extractor.py`: navegador integrado accesible, página propia para YouTube y extracción de las emisiones de YouTube, Twitch y webs.
- `tdt/comprobador.py`, `tdt/mosaico.py`, `tdt/tareas.py`: comprobador de canales, multiventana y tareas del Programador de Windows.
- `MANUAL.md`: manual de usuario, y la fuente de Ayuda > Manual de usuario (`widgets.markdown_a_html` lo convierte al vuelo). Es el único documento que se copia junto al ejecutable, con `LICENCIAS.md`; este README y `MEJORAS.md` son del proyecto y no se incluyen en la compilación.
- `MEJORAS.md`: investigación y estado de las mejoras de cliente IPTV.
- `setup_cx.py`, `Resintoniza.bat`: compilación y tareas.
- `tests/`: pruebas unitarias.
- `analisis/`: descompilación JADX del APK e informe (`INFORME.md`).
- `LICENCIAS.md`: componentes y atribuciones.
