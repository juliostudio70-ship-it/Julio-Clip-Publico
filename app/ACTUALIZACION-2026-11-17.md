# Julio Clip · Actualización 2026.11.17

## Qué se corrigió
- La transcripción se divide en ventanas de unos 20 segundos de audio con contexto solapado y tiempos absolutos. La captura del directo conserva sus bloques configurados; esta mejora afecta a cómo se transcribe el audio dentro de ellos.
- Se eliminó el corte fijo por cuatro minutos sin mensajes de progreso. Cada ventana tiene un límite de ejecución y se puede cancelar. El progreso muestra bloques de audio realmente terminados; la estimación empieza cuando hay datos suficientes.
- Los subtítulos de los clips se alinean con el audio del MP4 realmente recortado usando los tiempos DTW por palabra del Whisper incluido. Para analizar momentos se usa la transcripción más ligera; el cálculo adicional de sincronía se reserva a los subtítulos.
- «Seguir la voz» revela palabras a medida que se pronuncian y oculta palabras futuras. Puedes escoger «Mostrar la frase completa» si prefieres leerla antes. Se añadieron Deslizar y Construcción: diez estilos. Los efectos se renderizan en el MP4.
- Ajuste de sincronización de −3000 a +3000 ms: positivo retrasa el texto, negativo lo adelanta. No altera el audio. Este ajuste se aplica al texto incrustado; el SRT conserva los tiempos originales de reconocimiento.
- Se mantiene la corrección manual. Los tiempos automáticos son estimaciones: revisa tus primeros clips, especialmente con música, acentos, ruido o varias personas.

## Tu marca de agua
En Directos o Videos publicados, abre «Tu propia marca de agua», selecciona un PNG transparente de hasta 8 MB y activa «Usar mi marca». El archivo se guarda en tu equipo. Puedes elegir esquina o movimiento entre esquinas, tamaño de 8 a 30 % del ancho e intensidad. Una imagen sin transparencia se rechaza con una explicación.

La selección se toma al iniciar cada operación. Cambiarla no modifica los trabajos que ya están en cola. Quitar marca desactiva tanto el logo predeterminado como el propio en exportaciones nuevas desde el original.

En el editor, «Añadir mi PNG de marca de agua a esta copia» es independiente y está apagado al abrirlo. Conserva las letras y marcas que ya formen parte de la imagen original: no promete borrarlas. Una marca nueva se aplica después de la velocidad, recorte y efectos, y antes de los subtítulos. Los proyectos guardan sus opciones y el identificador de la imagen.

## Encuadre y selección
En «Encuadre para exportar» puedes escoger plano completo con fondo desenfocado, recortar para rellenar o conservar plano con franjas. Recortar llena el 9:16 pero puede eliminar contenido lateral; comprueba la vista previa. Se conservan el seguimiento de cara y el ajuste manual del editor, 720p/1080p y los formatos 9:16, 16:9, 1:1 y original.

La selección reconoce mejor conversaciones tranquilas con planteamiento y desenlace, además de reacciones, preguntas y respuestas. Se mantienen los filtros de anuncios, congelamientos, solapamientos y repeticiones. La puntuación no garantiza viralidad ni detectar todas las jugadas. No se generan clips de relleno para alcanzar la cantidad solicitada.

## Pruebas
128 pruebas Python pasaron, sin fallos ni omisiones, incluidas exportaciones reales, formatos, audio, subtítulos, editor, papelera, cola y Whisper real. Cuatro pruebas JavaScript pasaron. Diez casos nuevos verificaron tiempos DTW, revelado sin palabras futuras, silencios, ventanas y cancelación, PNG/alfa, cinco posiciones y texto realmente renderizado. Se volvió a comprobar el flujo HTTP con PNG propio: proyecto, vista previa, MP4 idéntico, descarga, papelera/restauración y conservación de la activación.

La muestra de voz real fue inglesa. No tuvimos el MP4 del cliente de la captura para reproducir exactamente su equipo/archivo. Se corrigió el mecanismo que provocaba el aviso de los cuatro minutos, pero no se certifica que cualquier video o PC termine en un tiempo fijo. La alineación más precisa puede tardar más que transcribir sin tiempos por palabra. No se certifican meses continuos de emisión ni precisión perfecta en español o cambios de hablante.

## Actualizar
Cierra la versión anterior tras terminar sus tareas. Extrae el ZIP nuevo en otra carpeta y abre Abrir-Julio-Clip.cmd. Conserva %LOCALAPPDATA%/Julio Clip y %LOCALAPPDATA%/Julio Clip Suscripcion. Tu licencia activa conserva instalación y vencimiento; no necesitas otro código para actualizar en el mismo Windows. La Personal sigue sin suscripción. No se regeneró ningún código ni se modificó Supabase.

## Investigación utilizada
Se revisó OpenShorts como referencia técnica, sin ejecutar su aplicación ni copiar su código al producto. Su arquitectura incluye reconocimiento por palabra, reencuadre y selección; algunos modos usan proveedores externos. Julio Clip conserva su procesamiento local y no añade APIs de pago ni Docker.
- OpenShorts, revisión a75d8a20f94daebbf7a590ab0750e376bb46a3b6: https://github.com/mutonby/openshorts/tree/a75d8a20f94daebbf7a590ab0750e376bb46a3b6
- Reconocimiento y tiempos: https://github.com/mutonby/openshorts/blob/a75d8a20f94daebbf7a590ab0750e376bb46a3b6/transcribe_backends.py
- Whisper.cpp 1.7.6, salida JSON y DTW: https://github.com/ggml-org/whisper.cpp/blob/v1.7.6/examples/cli/cli.cpp
