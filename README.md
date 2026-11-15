# Julio Clip Público · 2026.11.14

Interfaz web local para Windows 10/11 de 64 bits. El procesamiento se realiza en el equipo del cliente. La edición pública requiere una licencia de 30 días y mantiene la misma configuración de validación del servidor.

[Página oficial](https://julio-clip-descarga-70.juliostudio70.chatgpt.site) · [Descargar paquete público completo](https://julio-clip-descarga-70.juliostudio70.chatgpt.site/downloads/Julio-Clip-Publico.zip)

## Esta actualización

- Ocho estilos de subtítulos con tarjetas, ejemplos y opciones de color, resaltado, tamaño, fuente, contorno, sombra y posición.
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

103 pruebas de Python pasaron, incluidas exportaciones con FFmpeg, audio, los ocho estilos, resaltado visible, corrección y retirada de subtítulos, papelera y Whisper real; también pasaron las pruebas de JavaScript y la revisión visual del catálogo. La muestra de reconocimiento real es inglesa. La precisión con tu voz en español y los cambios de hablante en tus transmisiones necesitan validación con material real. La selección de momentos y anuncios usa indicios, no comprensión infalible.

Más instrucciones en `app/ACTUALIZACION-2026-11-14.md`.
