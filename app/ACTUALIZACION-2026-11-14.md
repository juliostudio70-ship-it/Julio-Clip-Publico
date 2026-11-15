# Julio Clip · Actualización 2026.11.14

## Cómo actualizar

Cierra la captura con «Terminar y generar clips» y espera a que termine la cola. Cierra Julio Clip. Extrae la entrega nueva en una carpeta nueva y abre `Abrir-Julio-Clip.cmd` de la edición que utilizas. Conserva tu carpeta de datos de Windows: no borres `%LOCALAPPDATA%/Julio Clip` ni `%LOCALAPPDATA%/Julio Clip Suscripcion`.

Personal sigue sin activación. Público conserva el mismo servidor y la misma configuración de licencias. Esta actualización no registra códigos nuevos, no vuelve a activar códigos ni modifica vencimientos. No entregues el ZIP Completo a clientes: contiene tus archivos privados. Para clientes utiliza sólo `Julio-Clip-Publico.zip`.

## Subtítulos

Activa «Subtítulos automáticos» y deja marcada «Dejar subtítulos visibles en el MP4». Elige una tarjeta: Clásico, Dinámico, Palabra por palabra, Rebote, Zoom, Karaoke, Minimalista o Impacto. Puedes cambiar color, resaltado, tamaño, tipografía, contorno, sombra, posición y animaciones. El ejemplo de la tarjeta es ilustrativo; el MP4 usa los tiempos del audio.

Whisper entrega ahora el JSON completo con tiempos por token. Se agrupan palabras, pausas y frases legibles. Cuando no hay tiempos válidos por palabra, se estima su distribución dentro de la frase: no se presenta como alineación exacta. El modelo sigue siendo multilingüe y local; los nombres propios, ruido y voces simultáneas pueden requerir corrección. Arial y Georgia son tipografías del sistema Windows; Condensada viene incluida.

Para corregir un clip: Mis clips → Editar → activa subtítulos → Corregir palabras → cambia el texto → Guardar copia MP4. Los tiempos de las frases no cambian. Si cambias el número de palabras, se estima su reparto dentro de la frase. Una frase vacía se omite. Los clips nuevos con texto incrustado guardan una base limpia para permitir corregirlo o desactivarlo sin duplicarlo. Esa base ocupa espacio y acompaña al clip al moverlo a la papelera, restaurarlo o borrarlo. Los clips antiguos que no tengan base limpia conservan sus letras incrustadas.

Para conservar sólo una pista opcional de subtítulos, desmarca «Dejar subtítulos visibles en el MP4». Las animaciones requieren incrustación: una pista SRT/mov_text no lleva animaciones.

## Encuadre y momentos

Mis clips muestra ahora una galería de miniaturas 9:16, duración, formato, puntuación estimada y botones en posiciones consistentes. Los nombres de archivo no se muestran en las tarjetas. Pulsar una miniatura abre el editor/vista previa. La miniatura no cambia el formato del MP4. Las miniaturas ausentes de clips antiguos se recuperan desde su video al consultarlas, sin modificarlo.

El seguimiento limita la velocidad de desplazamiento, mantiene juntas caras cercanas que caben en el recorte y cruza actividad de voz con movimiento de labios para estimar el turno de palabra. No identifica al hablante con certeza: con empate, silencio o caras lejanas puede mantener el encuadre. Si varias personas no caben en 9:16, un recorte no puede garantizar mostrarlas completas a la vez.

La selección valora preguntas y respuestas, giros, reacciones y frases sorprendentes; penaliza ventanas que cortan frases, repeticiones y conversación sin señales de interés. Conserva los filtros de anuncios, congelamientos, negro y duplicados visuales. La puntuación es una estimación heurística sobre la transcripción, el audio y la imagen, no una garantía de viralidad ni una comprensión infalible. Los anuncios sin indicios reconocibles pueden requerir revisión.

## Comprobaciones y límites

Se probaron los ocho estilos con FFmpeg real, audio decodificable, píxeles visibles, cambio de resaltado, animaciones desactivadas, corrección y exportación sin letras, papelera/restauración y transcripción real con el modelo incluido. La muestra de reconocimiento incluida es inglesa: no certifica la exactitud del reconocimiento de tu voz en español. El cambio de hablante se valida con señales de control; hace falta probarlo en tus videos reales con varias personas.

Documentación técnica utilizada: [ASS y animaciones](https://aegisub.org/docs/latest/ass_tags/) y [whisper.cpp CLI](https://github.com/ggml-org/whisper.cpp/blob/master/examples/cli/README.md).
