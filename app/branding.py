"""Imágenes propias inmutables y composición sobre el resultado final."""
import hashlib
import math
import re
from pathlib import Path

POSITIONS=('moving','top-left','top-right','bottom-left','bottom-right')

def settings(payload):
    key=payload.get('custom_watermark')
    if key is not None and (not isinstance(key,str) or not re.fullmatch('[0-9a-f]{32}',key)):
        raise ValueError('Vuelve a seleccionar tu PNG de marca de agua.')
    position=payload.get('watermark_position','moving');scale=payload.get('watermark_scale',.14)
    if position not in POSITIONS or type(scale) not in (int,float) or not math.isfinite(scale) or not .08<=scale<=.30:
        raise ValueError('Revisa la posición y el tamaño (8–30 %) de la marca.')
    return dict(custom_watermark=key,watermark_position=position,watermark_scale=scale)

def image(root,key):
    settings({'custom_watermark':key})
    path=Path(root)/'watermarks'/(key+'.png')
    if not path.is_file():raise ValueError('No se encuentra esa marca. Importa de nuevo tu PNG transparente.')
    return path

def store(root,data,ffmpeg,run):
    if not 32<=len(data)<=8*1024**2 or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Selecciona una imagen PNG transparente de hasta 8 MB.')
    width=int.from_bytes(data[16:20],'big');height=int.from_bytes(data[20:24],'big')
    if not 8<=width<=4096 or not 8<=height<=4096 or width*height>12000000:
        raise ValueError('El PNG debe medir entre 8 y 4096 píxeles por lado, hasta 12 megapíxeles.')
    folder=Path(root)/'watermarks';folder.mkdir(exist_ok=True);key=hashlib.sha256(data).hexdigest()[:32]
    path=folder/(key+'.png');temporary=folder/(key+'.part')
    try:
        temporary.write_bytes(data)
        raw=run([ffmpeg,'-nostdin','-v','error','-i',str(temporary),'-frames:v','1','-vf','scale=64:64,format=rgba','-f','rawvideo','pipe:1'])
        if len(raw)!=64*64*4 or not any(a<240 for a in raw[3::4]) or not any(a>20 for a in raw[3::4]):
            raise ValueError('La imagen no tiene transparencia. Exporta tu logo como PNG sin fondo.')
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)
    return dict(id=key,width=width,height=height,message='Marca transparente guardada en este equipo.')

def overlay_args(ffmpeg,source,output,logo,width,height,opacity,values):
    from watermark import encoding_args
    margin=max(4,round(min(width,height)*.035));position=values['watermark_position']
    if position=='moving':
        clock='mod(floor(t/8),4)';x=f'if(lt({clock},2),W-w-{margin},{margin})';y=f'if(eq({clock},0)+eq({clock},3),{margin},H-h-{margin})'
    else:
        x=str(margin) if position.endswith('left') else f'W-w-{margin}'
        y=str(margin) if position.startswith('top') else f'H-h-{margin}'
    maximum=max(8,round(width*values['watermark_scale']))
    graph=f'[1:v]scale={maximum}:{max(8,round(height*.18))}:force_original_aspect_ratio=decrease,format=rgba,colorchannelmixer=aa={opacity:.3f}[mark];[0:v][mark]overlay=x=\'{x}\':y=\'{y}\':shortest=1:eval=frame[v]'
    return [ffmpeg,'-nostdin','-y','-i',str(source),'-loop','1','-i',str(logo),'-filter_complex',graph,
            '-map','[v]','-map','0:a:0?','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',str(output)]
