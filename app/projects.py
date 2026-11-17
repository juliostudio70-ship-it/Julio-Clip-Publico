"""Borradores locales, sin rutas externas ni acceso al sistema de archivos ajeno."""
import json
from pathlib import Path
import threading
from editing import kept_ranges, subtitle_settings
from render_options import options
GUARD=threading.RLock()

class Projects:
    def __init__(self,root):self.root=Path(root);self.file=self.root/'proyectos.json'
    def load(self):
        if not self.file.is_file():return {}
        try:return json.loads(self.file.read_text(encoding='utf-8'))
        except ValueError:raise ValueError('El archivo de proyectos no se pudo leer. Consérvalo antes de continuar.') from None
    def get(self,name):
        with GUARD:return self.load().get(name)
    def save(self,name,draft,duration):
        if not isinstance(draft,dict):raise ValueError('Proyecto inválido')
        allowed={'name','start','end','remove','subtitles','burn_subtitles','subtitle_style','caption_edits','format',
                 'follow_face','overlay_title','resolution','quality','fit','speed','volume','zoom','frame_x','frame_y','effect','fade','cover_time','music',
                 'custom_watermark','watermark','watermark_opacity','watermark_position','watermark_scale'}
        if set(draft)-allowed:raise ValueError('El proyecto contiene opciones desconocidas')
        import branding
        kept_ranges(draft,duration);options(draft);subtitle_settings(draft);branding.settings(draft)
        with GUARD:
            data=self.load();data[name]=draft
            temporary=self.file.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temporary.replace(self.file)
        return {'message':'Proyecto guardado. Se recuperará al volver a abrir este video.'}
