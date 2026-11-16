# Julio Clip · Actualización 2026.11.15

## Abrir y actualizar
1. Cierra la versión anterior y termina sus tareas.
2. Extrae todo el ZIP en una carpeta nueva. Conserva tu carpeta de datos de Windows.
3. Abre Abrir-Julio-Clip.cmd. Se abre Inicio en tu navegador; deja la consola abierta mientras procesa.
4. Personal no requiere código. Público conserva la activación y los días restantes si usas el mismo usuario de Windows y sus datos. Actualizar no regala ni consume otros 30 días.

## Cambios
- Inicio gris carbón, accesos a las fuentes y herramientas, métricas y gráfico de datos reales. El logo original se conserva, sin cambiar colores ni dibujo.
- Biblioteca con búsqueda por título, categorías, fecha, orden por interés estimado, miniatura según aspecto y confirmación antes de mover a papelera. Descargar y restaurar conservan su funcionamiento.
- YouTube y Kick conservados; integración de canales públicos de Twitch para captura, y videos/VOD/clips compatibles para importación. TikTok publicado y archivos del equipo siguen disponibles. Máximo de importación: 2 GB, sujeto a disco disponible.
- De 1 a 50 clips por video/proceso, hasta 180 segundos por clip. En directos cada sesión se detiene al generar 50; puedes iniciar otra sesión si quieres continuar. No se crean clips para completar una cuota si no hay momentos útiles.
- En Videos publicados eliges cantidad y duración antes del análisis. Revisa las propuestas, acepta/rechaza y exporta las aceptadas en una cola. Puedes aceptar todas. Hay explicaciones de descarte y puntuaciones heurísticas, sin garantías de visitas.
- El modo rápido conserva bloques de aproximadamente 1 minuto; para clips largos se amplía el bloque hasta que quepan. Normal analiza aproximadamente 5 minutos. Se mantiene Terminar y generar clips y la cola de pendientes.
- Editor con línea de tiempo, inicio/final, división mediante tramos a quitar y unión de las partes conservadas del mismo video. No es un editor de varias pistas ni un sustituto completo de CapCut.
- Edición de clips y videos importados, velocidad 0,5× a 2× desde la interfaz, volumen, música propia de hasta 100 MB (mezcla al 20 %), zoom, efecto cálido/blanco y negro, fundidos de entrada/salida y elección del fotograma de portada.
- Original (proporción conservada), vertical 9:16, horizontal 16:9 y cuadrado 1:1; 720p o 1080p, calidad Ligera/Equilibrada/Alta. Arrastra o redimensiona el recuadro manual. Para ver el resultado exacto usa Renderizar vista previa: emplea el mismo motor y ajustes que Guardar copia.
- Guarda un proyecto para recuperar los tiempos y ajustes al volver a editar ese video. El original y la copia importada permanecen; los proyectos son locales.
- Ocho estilos de subtítulos conservados, con corrección manual, tiempos por palabra y renderizado ASS real en el MP4. Preferencias de idioma (incluido español) y estilo guardadas. Equilibrado/Ligero usan búsqueda más corta en Whisper; Alta calidad dedica más cálculo.
- Seguimiento facial opcional, con estabilización y estimación del hablante; modo manual cuando no es fiable. Puedes desactivarlo para reducir cálculo.
- Preferencias: temas carbón/oscuro/claro, acento, animaciones reducidas, escala de texto, formatos, calidad, idioma y sensibilidad. Ligero limita herramientas simultáneas a una; los otros modos a dos. Hilos de transcripción/codificación limitados según modo. No se promete un límite absoluto de RAM/CPU.
- Carpeta de descargas opcional en navegadores que admitan elegir directorio. Si no lo admiten, configura Descargas en el navegador. No se sobrescriben archivos al usar la carpeta elegida.
- Mantenimiento con lista exacta de archivos y confirmación adicional. No borra activación, archivos ajenos ni originales externos. Los bloques pendientes se descartan por separado desde Espacio y papelera. No limpia mientras hay trabajos activos.
- Reproducción HTTP por rangos para no cargar un video entero en la memoria del servidor al abrirlo o adelantarlo.

## Límites de verificación
La selección de interés, los anuncios y el hablante principal se estiman por señales; pueden equivocarse. No se garantiza detectar cada jugada ni todas las conversaciones.
Los subtítulos se comprobaron con Whisper real y una muestra inglesa, además de casos de texto en español. Falta medir la precisión con tu voz real en español y con escenas reales de dos hablantes. Los clips antiguos con letras incrustadas sin base limpia conservan esas letras.
Las pruebas de formatos, audio, 180 segundos, edición, vista previa, biblioteca y limpieza usan videos técnicos. Twitch tiene validación de enlaces y servidores permitidos; puede requerir acceso que la plataforma no ofrece a esta herramienta. No se eluden restricciones. Que un video sea visible en un navegador no garantiza su captura.
Las pruebas no certifican una emisión continua de meses. Se mantienen cola en disco, reintentos y límites de almacenamiento. Comprueba tus primeros clips antes de dejar una sesión larga.

## Fuentes técnicas
- Whisper: https://github.com/ggml-org/whisper.cpp
- Subtítulos ASS/libass: https://ffmpeg.org/ffmpeg-filters.html#ass
- Extractor Twitch de yt-dlp: https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/twitch.py
- API de carpetas en navegadores: https://developer.mozilla.org/en-US/docs/Web/API/Window/showDirectoryPicker
