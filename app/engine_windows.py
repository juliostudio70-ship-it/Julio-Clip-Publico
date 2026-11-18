"""Selección de motores incluidos, comprobación de integridad y diagnóstico."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import threading
import time
from runtime_support import child_options

MESSAGES={
    'missing':'El ejecutable no está en la carpeta extraída.',
    'integrity':'Un archivo del motor está incompleto o fue modificado. Extrae de nuevo el ZIP.',
    'library':'Windows no pudo cargar una biblioteca del motor. Consulta ARRANQUE-WINDOWS.md y conserva este código de error.',
    'architecture':'El ejecutable o una biblioteca no corresponde a la arquitectura de Windows.',
    'cpu':'El motor usó una instrucción que este procesador no admite.',
    'security':'Windows o una protección del equipo impidió ejecutar este archivo. Revisa su aviso; no desactives las protecciones.',
    'memory':'Windows no pudo reservar memoria suficiente para el motor.',
    'timeout':'El motor no terminó su comprobación inicial en 60 segundos.',
    'startup':'El motor terminó con un error durante su arranque.',
}

def category(code):
    code=code&0xffffffff
    if code in (126,127,0xc0000135,0xc0000139,0xc0000142):return 'library'
    if code in (193,216,0xc000007b,0xc000012f):return 'architecture'
    if code in (0xc000001d,):return 'cpu'
    if code in (5,225,226,577,0xc0000022,0xc0000428):return 'security'
    if code in (8,14,0xc0000017,0xc000009a):return 'memory'
    return 'startup'

def version(root):
    try:return (Path(root)/'VERSION.txt').read_text(encoding='utf-8-sig').strip()[:40]
    except OSError:return 'sin versión'

class Engines:
    def __init__(self):
        self.guard=threading.RLock()
        self.cache={}
    def clear(self):
        with self.guard:self.cache.clear()
    def select(self,root):
        root=Path(root).resolve()
        candidates=[('compatible',root/'bin/whisper-cli.exe'),('respaldo',root/'bin/whisper-respaldo/whisper-cli.exe')]
        manifest=root/'HERRAMIENTAS-SHA256.json'
        fingerprint=[]
        for p in [manifest,*[p for _,p in candidates],*sorted((root/'bin/whisper-respaldo').glob('*.dll'))]:
            try:fingerprint.append((str(p),p.stat().st_mtime_ns,p.stat().st_size))
            except OSError:fingerprint.append((str(p),None,None))
        with self.guard:
            old=self.cache.get(str(root))
            if old and old[0]==fingerprint:return old[1]
            invalid=False
            try:
                inventory=json.loads(manifest.read_text(encoding='utf-8'))
                if not isinstance(inventory,dict):inventory={};invalid=True
            except (OSError,ValueError):inventory={};invalid=manifest.exists()
            checks=[];selected=None
            for name,path in candidates:
                row={'engine':name,'ok':False}
                if invalid:row.update(reason='integrity')
                elif not path.is_file():row.update(reason='missing')
                else:
                    files=[path]+(list(path.parent.glob('*.dll')) if name=='respaldo' else [])
                    expected=[k for k in inventory if k==path.relative_to(root).as_posix() or
                              name=='respaldo' and k.startswith('bin/whisper-respaldo/')]
                    mismatch=any(not (root/k).is_file() or hashlib.sha256((root/k).read_bytes()).hexdigest()!=inventory[k] for k in expected)
                    mismatch=mismatch or bool(inventory) and any(p.relative_to(root).as_posix() not in inventory for p in files)
                    if mismatch:row.update(reason='integrity')
                    else:
                        started=time.monotonic()
                        try:
                            p=subprocess.run([str(path),'--help'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,cwd=path.parent,timeout=60,**child_options())
                            row.update(ok=p.returncode==0,exit_code=f'0x{p.returncode&0xffffffff:08X}')
                            if p.returncode:row['reason']=category(p.returncode)
                        except subprocess.TimeoutExpired:row['reason']='timeout'
                        except OSError as e:
                            code=getattr(e,'winerror',None) or getattr(e,'errno',None) or 0
                            row.update(reason=category(code),os_error=code)
                        row['seconds']=round(time.monotonic()-started,2)
                if not row['ok']:row['message']=MESSAGES[row['reason']]
                checks.append(row)
                if row['ok']:
                    selected=str(path)
                    break
            self.cache[str(root)]=(fingerprint,selected,checks)
            return selected
    def report(self,root):
        self.select(root)
        with self.guard:
            _,path,checks=self.cache[str(Path(root).resolve())]
            return {'version':version(root),'windows_build':getattr(__import__('sys').getwindowsversion(),'build',None) if os.name=='nt' else None,
                'architecture':platform.machine(),'selected':next((x['engine'] for x in checks if x['ok']),None),'checks':list(checks)}

ENGINES=Engines()
