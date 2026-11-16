"""Preferencias locales y mantenimiento limitado a archivos gestionados."""
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
from datetime import datetime, timedelta

GUARD = threading.RLock()
DEFAULTS = {'theme': 'charcoal', 'accent': '#d7a4a6', 'reduced_motion': False, 'ui_scale': 100,
            'performance': 'balanced', 'format': 'original', 'resolution': 720, 'quality': 'balanced',
            'fit': 'auto', 'language': 'auto', 'follow_face': False, 'sensitivity': 'balanced',
            'clip_seconds': 30, 'clip_count': 2, 'subtitle_style': {}}


class Preferences:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def load(self):
        path = self.root/'preferencias.json'
        with GUARD:
            if not path.exists():
                return dict(DEFAULTS)
            try:
                return dict(DEFAULTS, **json.loads(path.read_text(encoding='utf-8')))
            except (ValueError, TypeError):
                raise ValueError('Conserva preferencias.json: no se pudo leer la configuración.') from None

    def save(self, values):
        from editing import subtitle_settings
        if not isinstance(values, dict) or set(values)-set(DEFAULTS):
            raise ValueError('Configuración desconocida.')
        data = dict(self.load(), **values)
        for key, choices in {'theme': ('charcoal', 'dark', 'light'), 'performance': ('light', 'balanced', 'high'),
                'format': ('original', 'vertical', 'landscape', 'square'), 'resolution': (720, 1080),
                'quality': ('light', 'balanced', 'high'), 'fit': ('auto', 'crop', 'contain'),
                'language': ('auto', 'es', 'en'), 'sensitivity': ('selective', 'balanced', 'discovery')}.items():
            if data[key] not in choices:
                raise ValueError('Revisa '+key+'.')
        if (type(data['ui_scale']) is not int or not 85 <= data['ui_scale'] <= 120 or
                type(data['clip_seconds']) is not int or not 1 <= data['clip_seconds'] <= 180 or
                type(data['clip_count']) is not int or not 1 <= data['clip_count'] <= 50 or
                type(data['resolution']) is not int or type(data['follow_face']) is not bool or
                type(data['reduced_motion']) is not bool or not re.fullmatch(r'#[0-9a-fA-F]{6}', data['accent'])):
            raise ValueError('Revisa los límites de la configuración.')
        data['subtitle_style'] = subtitle_settings({'subtitle_style': data['subtitle_style']})
        with GUARD:
            temp = self.root/'preferencias.tmp'
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(self.root/'preferencias.json')
        return data

    def record_analysis(self, source_key, duration, candidates):
        with GUARD:
            path=self.root/'historial.json'
            history=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []
            identity=hashlib.sha256(str(source_key).encode()).hexdigest()
            if not any(x['id']==identity for x in history):
                history.append(dict(id=identity, created=int(time.time()), duration=duration, candidates=candidates))
                temp=path.with_suffix('.tmp')
                temp.write_text(json.dumps(history[-10000:]), encoding='utf-8');temp.replace(path)

    def dashboard(self, clips, busy, live):
        path=self.root/'historial.json'
        try:
            history=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []
        except ValueError:
            history=[]
        now=datetime.now();month=now.strftime('%Y-%m')
        def date(clip):
            return datetime.fromtimestamp(clip['created']) if type(clip.get('created')) in (int,float) else None
        scores=[c['interest'] for c in clips if isinstance(c.get('interest'),(int,float)) and math.isfinite(c['interest'])]
        return dict(clips_month=sum(bool(date(c) and date(c).strftime('%Y-%m')==month) for c in clips),
            jobs_running=int(bool(busy))+int(bool(live.get('running'))), videos_analyzed=len(history),
            clips_finished=len(clips), best_interest=max(scores) if scores else None,
            days=[dict(label=(now-timedelta(days=n)).strftime('%d/%m'),
                count=sum(bool(date(c) and date(c).date()==(now-timedelta(days=n)).date()) for c in clips))
                  for n in range(6,-1,-1)])

    def managed(self, temporary_only=False):
        # No inferir archivos del usuario por extensión: sólo nombres propios conocidos.
        from library import MediaStore
        names=set()
        if not temporary_only:
            for clip in MediaStore(self.root).load()['clips']:
                for trash in (False,True):
                    for path in (MediaStore(self.root).path(clip['name'],trash),
                                 MediaStore(self.root).thumbnail(clip['name'],trash),
                                 MediaStore(self.root).caption_base(clip['name'],trash)):
                        names.add(path.relative_to(self.root).as_posix())
            names.update(('biblioteca.json','preferencias.json','historial.json','proyectos.json','imported.video','music.audio','editor-preview.mp4'))
        for path in self.root.iterdir():
            if path.name.startswith(('exportando-','analizando-','importando-','upload-','preview-')):
                if path.is_dir() and not path.is_symlink():
                    names.update(p.relative_to(self.root).as_posix() for p in path.rglob('*') if p.is_file() and not p.is_symlink())
                elif path.is_file():
                    names.add(path.name)
        return [name for name in sorted(names) if (self.root/name).is_file() and not (self.root/name).is_symlink()
                and self.root.resolve() in (self.root/name).resolve().parents]

    def plan(self, temporary_only=False):
        files=self.managed(temporary_only)
        records=[dict(path=n,bytes=(self.root/n).stat().st_size,modified=(self.root/n).stat().st_mtime_ns) for n in files]
        token=hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()
        return dict(files=records, confirmation=token, bytes=sum(x['bytes'] for x in records),
                    preserved=['Licencia e identificación de instalación','Licencias del servidor','Archivos externos','Bloques pendientes del directo'])

    def clear(self, confirmation, phrase, temporary_only=False):
        plan=self.plan(temporary_only)
        if confirmation!=plan['confirmation'] or phrase!=('LIMPIAR TEMPORALES' if temporary_only else 'RESTABLECER JULIO CLIP'):
            raise ValueError('La lista cambió o falta la confirmación. Revisa los archivos antes de borrar.')
        for item in plan['files']:
            (self.root/item['path']).unlink()
        return len(plan['files'])
