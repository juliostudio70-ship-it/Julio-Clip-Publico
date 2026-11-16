"""Ajustes validados y filtros reales del editor; sin paquetes externos."""
import math
from watermark import MAX_CLIP_SECONDS


def options(payload):
    result={key:payload.get(key,default) for key,default in {
        'resolution':720,'quality':'balanced','fit':'auto','speed':1.0,'volume':1.0,
        'zoom':1.0,'frame_x':.5,'frame_y':.5,'effect':'none','fade':False,'cover_time':None,'music':False}.items()}
    if type(result['resolution']) is not int or result['resolution'] not in (720,1080):
        raise ValueError('Elige resolución 720p o 1080p.')
    if result['quality'] not in ('light','balanced','high') or result['fit'] not in ('auto','crop','contain'):
        raise ValueError('Elige la calidad y el tipo de encuadre.')
    for name,low,high in [('speed',.25,4),('volume',0,2),('zoom',1,3),('frame_x',0,1),('frame_y',0,1)]:
        value=result[name]
        if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('Revisa el ajuste '+name+'.')
    if result['effect'] not in ('none','warm','bw') or type(result['fade']) is not bool or type(result['music']) is not bool:
        raise ValueError('Efecto inválido.')
    if result['cover_time'] is not None and (type(result['cover_time']) not in (int,float) or
            not math.isfinite(result['cover_time']) or not 0<=result['cover_time']<=MAX_CLIP_SECONDS):
        raise ValueError('La portada debe estar dentro del clip.')
    return result


def size(format_name,resolution=720):
    return {'vertical':(resolution,round(resolution*16/9)//2*2),
            'landscape':(round(resolution*16/9)//2*2,resolution),
            'square':(resolution,resolution)}.get(format_name)


def quality_args(values):
    return {'light':('25','veryfast'),'balanced':('20','fast'),'high':('18','medium')}[values['quality']]


def tempo(speed):
    filters=[]
    while speed<.5:
        filters.append('atempo=0.5');speed/=.5
    while speed>2:
        filters.append('atempo=2');speed/=2
    return ','.join(filters+['atempo='+str(speed)])


def post_args(ffmpeg,source,output,probe,values,duration,music=None):
    """Se aplica al mismo archivo usado por vista previa y exportación."""
    speed=values['speed'];length=duration/speed
    if length>MAX_CLIP_SECONDS+1e-8:
        raise ValueError('La copia editada no puede superar 3 minutos. Recorta o aumenta la velocidad.')
    video=['setpts=PTS/'+str(speed)]
    z=values['zoom'];x=values['frame_x'];y=values['frame_y']
    if z!=1:
        from watermark import display_size
        width,height=display_size(probe)
        video += [f'crop=trunc(iw/{z}/2)*2:trunc(ih/{z}/2)*2:(iw-ow)*{x}:(ih-oh)*{y}',f'scale={width}:{height}']
    if values['effect']=='bw':video.append('hue=s=0')
    if values['effect']=='warm':video.append('colorbalance=rs=.07:bs=-.05')
    if values['fade']:
        seconds=min(.35,length/4)
        video += [f'fade=t=in:st=0:d={seconds}',f'fade=t=out:st={max(0,length-seconds)}:d={seconds}']
    has_audio=any(s.get('codec_type')=='audio' for s in probe['streams'])
    graph=['[0:v]'+','.join(video)+'[v]'];args=[ffmpeg,'-nostdin','-y','-i',str(source)]
    if has_audio:
        graph.append(f'[0:a]{tempo(speed)},volume={values["volume"]},aresample=async=1:first_pts=0[a0]')
    if music:
        args += ['-stream_loop','-1','-i',str(music)]
        graph.append('[1:a]volume=0.2,asetpts=PTS-STARTPTS[music]')
        graph.append('[a0][music]amix=inputs=2:duration=first:normalize=0[a]' if has_audio else '[music]anull[a]')
    elif has_audio:graph.append('[a0]anull[a]')
    crf,preset=quality_args(values)
    args += ['-filter_complex',';'.join(graph),'-map','[v]']
    if has_audio or music:args+=['-map','[a]']
    return args+['-t',str(length),'-c:v','libx264','-crf',crf,'-preset',preset,'-pix_fmt','yuv420p',
                '-c:a','aac','-b:a','192k','-movflags','+faststart',str(output)]


def retime_speed(cues,speed):
    result=[]
    for cue in cues:
        item=dict(cue,start=cue['start']/speed,end=cue['end']/speed)
        if 'words' in cue:
            item['words']=[dict(w,start=w['start']/speed,end=w['end']/speed) for w in cue['words']]
        result.append(item)
    return result
