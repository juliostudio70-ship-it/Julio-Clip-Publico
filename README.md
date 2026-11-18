# Julio Clip Público · 2026.11.17.1

Interfaz web local para Windows 10/11 de 64 bits. El procesamiento se realiza en el equipo del cliente. La edición pública requiere una licencia de 30 días y mantiene la misma configuración de validación del servidor.

[Página oficial](https://julio-clip-descarga-70.juliostudio70.chatgpt.site) · [Descargar paquete público completo](https://julio-clip-descarga-70.juliostudio70.chatgpt.site/downloads/Julio-Clip-Publico.zip)

## Reparación de arranque 2026.11.17.1

Motor de respaldo incluido, compilado para x86-64 básico sin AVX, con importaciones públicas del CRT de Windows. El inicio comprueba la integridad y prueba el respaldo si el motor anterior no arranca. Se conserva el código Windows/NTSTATUS y se genera un diagnóstico sin datos personales. La versión se ve en la consola y en la interfaz.

136 pruebas de Python y 4 pruebas de JavaScript pasaron en Windows 10 x64, con Whisper, subtítulos, audio y FFmpeg reales. Ambas ediciones arrancaron incluso retirando temporalmente el motor principal en una copia de prueba. La causa del fallo original del cliente y su Windows 11 siguen sin verificarse. No se certifica compatibilidad universal. No se alteran activaciones, vencimientos ni códigos existentes.

Consulta `app/ARRANQUE-WINDOWS.md`. `app/compatibilidad/` conserva el parche y la procedencia del respaldo; su ejecutable viene en el ZIP público.

## Funciones conservadas

- Transcripción en ventanas cortas con progreso real y cancelación; se sustituye el corte arbitrario de 4 minutos sin mensajes.
- Subtítulos del clip final con tiempos DTW por palabra, revelado progresivo sin adelantar palabras futuras y ajuste manual de desfase.
- Nuevos estilos Deslizar y Construcción, diez en total, renderizados en el MP4.
- PNG propio transparente, guardado localmente, con posición, movimiento, tamaño y opacidad; disponible también en el editor y los proyectos.
- Selector visible para rellenar 9:16 con recorte, conservar plano o fondo desenfocado. Mejor puntuación de historias con planteamiento y desenlace.


- Inicio gris carbón con el logo original, estadísticas locales, biblioteca buscable y preferencias guardadas.
- Hasta 50 clips por proceso, de hasta 180 segundos, según los momentos útiles detectados. Revisión de propuestas y exportación secuencial sin generar relleno.
- Twitch añadido a la validación de enlaces y al extractor; acceso real sujeto a las condiciones de la plataforma.
- Editor con proyectos locales, vista previa renderizada, recorte manual, formatos 9:16/16:9/1:1/original, 720p/1080p, velocidad, volumen, música propia, zoom, filtros, fundidos y portada. Une tramos del mismo video; no es multitrack.
- Limpieza y restablecimiento con lista exacta y confirmación, conservando activación y originales externos. Reproducción HTTP por rangos.
- Diez estilos de subtítulos con tarjetas, ejemplos y opciones de color, resaltado, tamaño, fuente, contorno, sombra y posición.
- Biblioteca con miniaturas verticales 9:16, sin nombres de archivo visibles y recuperación de miniaturas ausentes de clips antiguos.
- Animaciones y karaoke incrustados en el MP4 con FFmpeg/libass. Opción de desactivar las animaciones.
- Tiempos por palabra de Whisper, frases legibles y corrección manual. Cuando faltan tiempos válidos se estima la distribución dentro de la frase.
- Base limpia para corregir o quitar los subtítulos en clips nuevos. Los clips antiguos con letras incrustadas conservan esas letras.
- Desplazamiento facial más estable, agrupación de rostros cercanos y estimación del turno de palabra con voz y movimiento de labios.
- Selección que penaliza cortes de frases, conversaciones repetidas y ausencia de señales de interés. La puntuación no garantiza viralidad.

## Uso normal

Descarga y extrae el ZIP completo; abre `Abrir-Julio-Clip.cmd`. El navegador abre la interfaz local. Conserva la ventana de Julio Clip abierta. Pide tu código al administrador mediante el WhatsApp de la página oficial.

Para actualizar, utiliza una carpeta nueva y conserva tus datos en `%LOCALAPPDATA%/Julio Clip Suscripcion`. Los códigos, activaciones y vencimientos no se regeneran con esta versión.

## Código y dependencias

`app/` contiene el código distribuible y la configuración pública del cliente. No contiene códigos de activación ni claves administrativas. Los ejecutables, el modelo de Whisper y las bibliotecas de visión se distribuyen en el ZIP; no se guardan como archivos grandes en Git.

Para desarrollo, trabaja sobre una copia del paquete descargado y sustituye sus archivos de código por `app/`. Usa su Python, herramientas y carpeta `vision`. Las pruebas requieren las rutas `JULIO_FFMPEG`, `JULIO_FFPROBE` y, para inferencia real, `JULIO_WHISPER`. Ejecuta `python -m unittest discover -s tests -v` y los archivos `tests/test_*.js` con Node. Las tipografías y herramientas de terceros conservan sus licencias incluidas en la entrega.

## Validación y límites

136 pruebas de Python pasaron, incluidas exportaciones con FFmpeg, audio, los diez estilos, resaltado visible, corrección y retirada de subtítulos, papelera y Whisper real; también pasaron las pruebas de JavaScript y la revisión visual del catálogo. La muestra de reconocimiento real es inglesa. La precisión con tu voz en español y los cambios de hablante en tus transmisiones necesitan validación con material real. La selección de momentos y anuncios usa indicios, no comprensión infalible.

Se investigó OpenShorts como referencia, sin copiar su código ni añadir sus APIs externas. La inferencia DTW real se comprobó con voz inglesa; falta el MP4 concreto del cliente para reproducir su equipo y contenido.

Más instrucciones en `app/ACTUALIZACION-2026-11-17.md`.

El panel del propietario se distribuye por separado y no está incluido en este repositorio. Las licencias anteriores conservan su identidad y vencimiento. Pruebas adicionales de proyectos, límites 50/180, vista previa idéntica al MP4 y mantenimiento seguro pasaron. No se certifica la captura continua durante meses, exactitud perfecta de hablantes/anuncios ni compatibilidad universal con todas las PC.
