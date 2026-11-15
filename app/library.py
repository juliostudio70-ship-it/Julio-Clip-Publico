"""Biblioteca persistente y papelera limitada al directorio de Julio Clip."""
import json
import math
from pathlib import Path
import re
import shutil
import threading

GUARD = threading.RLock()
NAME = re.compile(r'clip-[0-9a-f]{12}\.mp4\Z')

class MediaStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'papelera').mkdir(exist_ok=True)
        self.index = self.root / 'biblioteca.json'

    def load(self):
        if not self.index.exists():
            return {'clips': [], 'quota_gb': 10, 'max_clips': 50}
        try:
            data = json.loads(self.index.read_text(encoding='utf-8'))
            if not isinstance(data.get('clips'), list):
                raise ValueError()
            return data
        except (ValueError, OSError):
            raise ValueError('La biblioteca está dañada. Conserva los archivos y revisa biblioteca.json antes de continuar.')

    def save(self, data):
        temporary = self.index.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.index)

    def path(self, name, trash=False):
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError('Nombre de clip inválido.')
        return (self.root / 'papelera' if trash else self.root) / name

    def thumbnail(self, name, trash=False):
        return self.path(name, trash).with_suffix('.jpg')

    def caption_base(self, name, trash=False):
        return self.path(name, trash).with_suffix('.clean.mp4')

    def usage(self):
        total=0
        for p in self.root.rglob('*'):
            try:
                if p.is_file() and not p.is_symlink():
                    total+=p.stat().st_size
            except FileNotFoundError:
                # La cola puede terminar y retirar un bloque durante el recuento.
                continue
        return total

    def view(self):
        with GUARD:
            d = self.load()
            clips = [c for c in d['clips'] if not c.get('trash') and self.path(c['name']).is_file()]
            trash = [c for c in d['clips'] if c.get('trash') and self.path(c['name'], True).is_file()]
            def summary(clip):
                result = {key: value for key, value in clip.items() if key not in ('captions', 'signature', 'capture_key', 'dialogue_signature')}
                result['thumbnail'] = self.thumbnail(clip['name'], bool(clip.get('trash'))).is_file()
                return result
            return {'clips': [summary(c) for c in clips], 'trash': [summary(c) for c in trash], 'storage': {'used_gb': round(self.usage()/1024**3, 3), 'quota_gb': d['quota_gb'], 'max_clips': d['max_clips'], 'free_gb': round(shutil.disk_usage(self.root).free/1024**3, 2)}}

    def active_clip(self, name):
        path = self.path(name)
        with GUARD:
            clip = next((c for c in self.load()['clips'] if c['name'] == name and not c.get('trash')), None)
            if clip is None or not path.is_file():
                raise ValueError('El clip ya no está disponible. Revisa Mis clips y la papelera.')
            return clip

    def check_space(self, reserve=256*1024**2):
        d = self.load()
        if self.usage() + reserve > d['quota_gb']*1024**3:
            raise ValueError('Límite de almacenamiento alcanzado. Revisa la biblioteca y vacía la papelera o aumenta el límite.')
        if shutil.disk_usage(self.root).free < 2*1024**3 + reserve:
            raise ValueError('Quedan menos de 2 GB de reserva en el disco. Libera espacio antes de continuar.')

    def configure(self, quota_gb, max_clips):
        quota_gb, max_clips = float(quota_gb), int(max_clips)
        if not math.isfinite(quota_gb) or not 2 <= quota_gb <= 1000 or not 1 <= max_clips <= 500:
            raise ValueError('Usa un límite de 2 a 1000 GB y de 1 a 500 clips.')
        with GUARD:
            d = self.load()
            d.update(quota_gb=quota_gb, max_clips=max_clips)
            self.save(d)
            active = [c for c in d['clips'] if not c.get('trash')]
            for c in active[:-max_clips]:
                self.move(c['name'], True)

    def add(self, clip):
        with GUARD:
            self.path(clip['name'])
            d = self.load()
            d['clips'].append(dict(clip, trash=False))
            self.save(d)
            active = [c for c in d['clips'] if not c.get('trash')]
            # El usuario puede recuperar los clips retirados por el límite.
            for c in active[:-d['max_clips']]:
                self.move(c['name'], True)

    def move(self, name, trash):
        with GUARD:
            d = self.load()
            clip = next((c for c in d['clips'] if c['name'] == name), None)
            if clip is None or bool(clip.get('trash')) == trash:
                raise ValueError('El clip no está disponible en esa ubicación.')
            if not trash and sum(not c.get('trash') for c in d['clips']) >= d['max_clips']:
                raise ValueError('Ya alcanzaste el máximo de clips activos. Aumenta el límite o retira otro clip antes de restaurar.')
            source, dest = self.path(name, not trash), self.path(name, trash)
            if not source.is_file():
                raise ValueError('El archivo del clip no está disponible.')
            thumbnail = self.thumbnail(name, not trash)
            thumbnail_dest = self.thumbnail(name, trash)
            has_thumbnail = thumbnail.is_file()
            source.replace(dest)
            thumbnail_moved = False
            clean, clean_dest = self.caption_base(name, not trash), self.caption_base(name, trash)
            clean_moved = False
            try:
                if has_thumbnail:
                    thumbnail.replace(thumbnail_dest)
                    thumbnail_moved = True
                if clean.is_file():
                    clean.replace(clean_dest)
                    clean_moved = True
                clip['trash'] = trash
                self.save(d)
            except OSError:
                dest.replace(source)
                if thumbnail_moved:
                    thumbnail_dest.replace(thumbnail)
                if clean_moved:
                    clean_dest.replace(clean)
                raise

    def empty_trash(self, confirmed):
        if confirmed is not True:
            raise ValueError('Se requiere confirmación para borrar definitivamente la papelera.')
        with GUARD:
            d = self.load()
            for c in d['clips']:
                if c.get('trash'):
                    path = self.path(c['name'], True)
                    if path.is_file():
                        path.unlink()
                    self.thumbnail(c['name'], True).unlink(missing_ok=True)
                    self.caption_base(c['name'], True).unlink(missing_ok=True)
            d['clips'] = [c for c in d['clips'] if not c.get('trash')]
            self.save(d)
