# Julio Clip 2026.11.17.1 · Inicio en Windows

1. Cierra la versión anterior y extrae TODO el ZIP nuevo en una carpeta nueva de tu usuario. No abras el programa dentro del ZIP ni muevas sus ejecutables por separado.
2. Abre `Abrir-Julio-Clip.cmd`. El inicio comprueba el motor de voz y prueba automáticamente el motor de respaldo incluido si el primero no arranca. La primera comprobación de cada motor admite hasta 60 segundos.
3. Tus clips y la activación se conservan en la carpeta de datos de tu usuario de Windows; actualizar en ese mismo usuario no consume otro código ni reinicia los días restantes. No borres esa carpeta.

Si ambos motores fallan, la ventana muestra sus códigos reales y crea `diagnostico-arranque.json` en la carpeta de datos. `Comprobar-Equipo.cmd` genera además `diagnostico-equipo.json`. Estos informes identifican la versión, arquitectura, compilación de Windows y resultados del motor, sin incluir códigos de licencia ni nombres o rutas personales.

El respaldo está compilado para x86-64 básico, sin exigir AVX/AVX2 ni instalar Visual C++. Resuelve localmente la búsqueda de bytes que el compilador anterior importaba mediante un contrato privado de Windows. Mantiene las bibliotecas públicas de Windows 10/11 y el mismo modelo. Esto ofrece otra ruta de arranque, pero no identifica por sí solo la causa del fallo en el cliente.

Si aparece un bloqueo de seguridad, consulta el aviso del equipo; no desactives sus protecciones. Para errores de procesador, arquitectura, archivos modificados o tiempo agotado, el informe conserva la causa separada. No copies DLL de páginas desconocidas.

## Qué se ha verificado

La reparación incluye selección automática del motor, control de integridad y diagnóstico. Se prueba con transcripción y vídeo reales en Windows 10 x64. El informe del cliente solo decía que Whisper no arrancó: **todavía no conocemos su causa exacta ni hemos probado su Windows 11**. No se promete compatibilidad con todas las computadoras.

Procedencia, huella y parche del motor de respaldo: `bin/whisper-respaldo/PROCEDENCIA.json` y `memchr_compat.c`. Código y licencia MIT de whisper.cpp: https://github.com/ggml-org/whisper.cpp/releases/tag/v1.7.6.
