"""Comprobación local y sin descargas de la distribución portátil Windows."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import struct
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server
from watermark import export_args

ROOT = Path(__file__).resolve().parent

def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def verify_inventory(root, engine_optional=False):
    root = Path(root).resolve()
    inventory = root / 'HERRAMIENTAS-SHA256.json'
    if not inventory.is_file():
        raise ValueError('Falta HERRAMIENTAS-SHA256.json. Extrae de nuevo el ZIP completo.')
    entries = json.loads(inventory.read_text(encoding='utf-8'))
    if not isinstance(entries, dict) or len(entries) < 5:
        raise ValueError('El inventario de herramientas no es válido.')
    for name, expected in entries.items():
        path = (root / name).resolve()
        if root not in path.parents:
            raise ValueError('El inventario contiene una ruta fuera de la aplicación.')
        if engine_optional and (name=='bin/whisper-cli.exe' or name.startswith('bin/whisper-respaldo/')):
            continue
        if not path.is_file():
            raise ValueError('Falta %s. Extrae TODO el ZIP, sin mover los ejecutables por separado.' % name)
        if sha256(path) != expected:
            raise ValueError('El archivo %s está incompleto o cambió. Extrae otra vez la entrega original.' % name)
    return len(entries)

def preflight(root=ROOT):
    if sys.platform != 'win32' or struct.calcsize('P') != 8 or sys.getwindowsversion().major < 10:
        raise ValueError('Esta versión requiere Windows 10 u 11 de 64 bits (Intel/AMD).')
    count = verify_inventory(root,engine_optional=True)
    checks = server.requirements()
    missing = [name for name, ready in checks.items() if not ready]
    if missing:
        if 'whisper-cli' in missing:
            from engine_windows import ENGINES
            report=ENGINES.report(root)
            server.DATA.mkdir(parents=True,exist_ok=True)
            (server.DATA/'diagnostico-arranque.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            detail='; '.join(x['engine']+': '+x.get('exit_code',str(x.get('os_error',x.get('reason'))))+' · '+x.get('message','') for x in report['checks'])
            raise ValueError('El motor de voz no pudo iniciarse. '+detail+' Informe: diagnostico-arranque.json en tu carpeta de datos de Julio Clip.')
        raise ValueError('No funcionan estas dependencias: %s. Ejecuta Comprobar-Equipo.cmd y conserva su informe.' % ', '.join(missing))
    return {'archivos_verificados': count, 'herramientas': checks}

def media_check(root=ROOT):
    """Ejecuta CPU, modelo y exportación reales; no toca la biblioteca del usuario."""
    with tempfile.TemporaryDirectory(prefix='julio-prueba-') as temporary:
        temp = Path(temporary)
        output = temp / 'transcripcion'
        start = time.monotonic()
        server.run([server.tool('whisper-cli'), '-m', str(root/'models/ggml-base.bin'),
                    '-f', str(root/'resources/prueba-motor.wav'), '-l', 'en', '-ng',
                    '-t', '2', '-oj', '-of', str(output)], timeout=300)
        transcript = json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
        text = ' '.join(s.get('text', '') for s in transcript.get('transcription', []))
        if 'country' not in text.lower():
            raise ValueError('El motor se ejecutó, pero la muestra de control no produjo el texto esperado.')
        inference_seconds = round(time.monotonic() - start, 2)
        source = temp/'original.mp4'
        server.run([server.tool('ffmpeg'), '-nostdin', '-y', '-f', 'lavfi', '-i',
                    'color=c=0x405060:s=640x360:r=25', '-i', str(root/'resources/prueba-motor.wav'),
                    '-t', '3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], timeout=60)
        probe = json.loads(server.run([server.tool('ffprobe'), '-v', 'error', '-show_format',
                                     '-show_streams', '-of', 'json', str(source)], timeout=30))
        for enabled in (True, False):
            clip = temp / ('con-marca.mp4' if enabled else 'sin-marca.mp4')
            server.run(export_args(server.tool('ffmpeg'), source, clip, 0, 3, probe,
                                   root/'web/logo-julio.jpg', enabled), timeout=90)
            result = json.loads(server.run([server.tool('ffprobe'), '-v', 'error', '-show_format',
                                           '-show_streams', '-of', 'json', str(clip)], timeout=30))
            if {s['codec_type'] for s in result['streams']} != {'video', 'audio'} or clip.stat().st_size < 1000:
                raise ValueError('Falló la comprobación del clip de prueba con audio.')
        return {'inferencia_real': True, 'segundos_inferencia': inference_seconds,
                'exportacion_con_y_sin_marca': True, 'audio': True,
                'muestra': 'Técnica en inglés; no evalúa tu directo ni la precisión en español.'}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--media', action='store_true')
    args = parser.parse_args()
    report = {'correcto': False, 'entorno': platform.platform(),
              'Netlify_real_verificado': False, 'YouTube_real_verificado': False}
    try:
        print('Comprobando archivos, CPU y herramientas incluidas...', flush=True)
        report.update(preflight())
        if args.media:
            print('Probando la IA y dos exportaciones reales. Puede tardar varios minutos...', flush=True)
            report['video_ia'] = media_check()
        report['correcto'] = True
        print('Comprobaciones solicitadas: CORRECTAS.', flush=True)
    except Exception as error:
        report['error'] = str(error) if isinstance(error, ValueError) else 'No se pudo completar la comprobación. Revisa permisos y vuelve a extraer la entrega.'
        print('ERROR: ' + report['error'], flush=True)
    from engine_windows import ENGINES
    report['engine']=ENGINES.report(ROOT)
    server.DATA.mkdir(parents=True, exist_ok=True)
    path = server.DATA/'diagnostico-equipo.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Informe: ' + str(path), flush=True)
    return 0 if report['correcto'] else 1

if __name__ == '__main__':
    sys.exit(main())
