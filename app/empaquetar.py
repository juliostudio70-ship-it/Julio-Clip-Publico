"""Reempaqueta una entrega descomprimida después de editar Codigo-Fuente."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    source=Path(__file__).resolve().parent
    release=source.parent
    windows=(release/'Julio-Clip-Windows/models/ggml-base.bin').is_file()
    app=release/('Julio-Clip-Windows' if windows else 'Julio-Clip-Mac')
    web=release/'Julio-Clip-Netlify'
    if source.name!='Codigo-Fuente' or not (app/'models/ggml-base.bin').is_file():
        raise SystemExit('Ejecuta este archivo desde Codigo-Fuente dentro de una entrega descomprimida completa.')
    common=('server.py','live.py','monitor.py','media_relay.py','library.py','watermark.py','editing.py','captions.py','preferences.py','projects.py','render_options.py','reframe.py',
            'runtime_support.py','public_quota.py','license_client.py')
    platform_files=('iniciar_windows.py','comprobar_windows.py','Iniciar-Julio-Clip.cmd','Comprobar-Equipo.cmd') if windows else (
        'prepare_mac.py','Iniciar-Julio-Clip.command','Preparar-Herramientas-Mac.command')
    for name in common+platform_files:
        shutil.copy2(source/name,app/name)
    for name in ('certifi-cacert.pem', 'LICENCIA-CERTIFI.txt', 'BarlowCondensed-Bold.ttf', 'BARLOW-OFL.txt'):
        shutil.copy2(source/'resources'/name, app/'resources'/name)
    if windows:
        inventory={p.relative_to(app).as_posix():digest(p)
                   for directory in ('bin','runtime','models','resources','vision')
                   for p in sorted((app/directory).rglob('*')) if p.is_file()}
        (app/'HERRAMIENTAS-SHA256.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
    shutil.copytree(source/'web',app/'web',dirs_exist_ok=True)
    shutil.copytree(source/'web',web,dirs_exist_ok=True,ignore=shutil.ignore_patterns('bridge.html','bridge.js'))
    items=[]
    for name in (app.name,'Julio-Clip-Netlify','Codigo-Fuente','Tutorial-Instalacion'):
        items.extend(p for p in (release/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc' and not p.is_symlink())
    items.append(release/'README.md')
    if windows and (release/'Abrir-Julio-Clip.cmd').is_file():
        items.append(release/'Abrir-Julio-Clip.cmd')
    manifest=release/'MANIFIESTO-SHA256.json'
    manifest.write_text(json.dumps({p.relative_to(release).as_posix():digest(p) for p in sorted(items)},ensure_ascii=False,indent=2),encoding='utf-8')
    items.append(manifest)
    output=release/'Julio-Clip-Completo.zip'
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(items):
            info=zipfile.ZipInfo(p.relative_to(release).as_posix())
            info.create_system=3
            info.external_attr=(0o100755 if p.suffix=='.command' else 0o100644)<<16
            info.compress_type=zipfile.ZIP_DEFLATED
            with p.open('rb') as src,z.open(info,'w') as dest:
                shutil.copyfileobj(src,dest)
    with zipfile.ZipFile(output) as z:
        if z.testzip():
            raise SystemExit('Falló la verificación CRC del ZIP.')
    print('ZIP generado: '+str(output))
    print('Para abrir Julio Clip, ejecuta '+('Abrir-Julio-Clip.cmd' if windows else 'Iniciar-Julio-Clip.command')+'.')

if __name__=='__main__':
    main()
