"""Composición de la marca de agua; no requiere paquetes de imágenes."""
import math
from fractions import Fraction
from reframe import followed_panel, title_filter

DEFAULT_OPACITY = 0.30
POSITION_SECONDS = 8
MAX_CLIP_SECONDS = 180
OUTPUT_SIZES = {'vertical': (720, 1280), 'square': (720, 720), 'landscape': (1280, 720)}


def layout_settings(payload, allow_split=False):
    format_name = payload.get('format', 'original')
    if not isinstance(format_name, str) or format_name not in ('original', *OUTPUT_SIZES):
        raise ValueError('Elige formato Original, Vertical 9:16 Horizontal 16:9 o Cuadrado 1:1.')
    split = payload.get('split')
    if split is None:
        return format_name, None
    if not allow_split:
        raise ValueError('La pantalla dividida está disponible solo en directos de Kick.')
    if format_name != 'vertical' or not isinstance(split, dict) or set(split) != {'camera', 'game'}:
        raise ValueError('La pantalla dividida necesita formato vertical y dos encuadres.')
    regions = {}
    for name, rect in split.items():
        if (not isinstance(rect, (tuple, list)) or len(rect) != 4
                or any(type(n) is not int or not 0 <= n <= 100 for n in rect)):
            raise ValueError('Usa porcentajes enteros de 0 a 100 para el encuadre.')
        x, y, w, h = rect
        if w < 5 or h < 5 or x+w > 100 or y+h > 100:
            raise ValueError('El encuadre debe quedar dentro del video y medir al menos 5 % por lado.')
        regions[name] = tuple(rect)
    return format_name, regions

def settings(payload):
    enabled = payload.get('watermark', True)
    if not isinstance(enabled, bool):
        raise ValueError('La opción de marca de agua debe ser verdadera o falsa.')
    opacity = float(payload.get('watermark_opacity', DEFAULT_OPACITY))
    if not math.isfinite(opacity) or not 0.15 <= opacity <= 0.50:
        raise ValueError('La intensidad de marca debe estar entre 15 y 50 %.')
    return enabled, opacity

def display_size(probe):
    videos = [s for s in probe.get('streams', []) if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')]
    if not videos:
        raise ValueError('No se encontró una pista de video.')
    stream = videos[0]
    width, height = int(stream['width']), int(stream['height'])
    rotation = float(stream.get('tags', {}).get('rotate', 0))
    for side in stream.get('side_data_list', []):
        if 'rotation' in side:
            rotation = float(side['rotation'])
    if round(rotation) % 180 == 90:
        width, height = height, width
    if width < 32 or height < 32:
        raise ValueError('El video es demasiado pequeño para exportarlo.')
    return width, height

def export_args(ffmpeg, source, output, start, end, probe, logo, enabled=True, opacity=DEFAULT_OPACITY,
                max_duration=MAX_CLIP_SECONDS, format_name='original', split=None, track=False, title=None, render_options=None):
    args = [ffmpeg, '-nostdin', '-y', '-ss', str(start), '-i', str(source)]
    video = '0:v:0'
    graph = []
    from render_options import options, size as output_size, quality_args
    values = options(render_options or {})
    size = output_size(format_name, values['resolution'])
    if size is None and render_options is not None and 'resolution' in render_options:
        iw,ih=display_size(probe);short=values['resolution']
        size=(round(iw/ih*short)//2*2,short) if iw>=ih else (short,round(ih/iw*short)//2*2)
    if size:
        graph, video = layout_graph(size, split, track=track, fit=values['fit'], frame=(values['frame_x'], values['frame_y']))
    if enabled and not (render_options or {}).get('custom_watermark'):
        width, height = size or display_size(probe)
        # Región del logo dentro del original suministrado de 1280 x 1280.
        # El archivo se conserva íntegro; el recorte y la transparencia son filtros de video.
        lw, lh = 900, 790
        # Máximo 14 % del ancho y 12 % de la altura; conserva proporción.
        scale = min(width * 0.14 / lw, height * 0.12 / lh)
        mark_w, mark_h = max(2, int(lw*scale)), max(2, int(lh*scale))
        margin = max(2, round(min(width, height) * 0.035))
        clock = 'mod(floor(t/%s),4)' % POSITION_SECONDS
        x = 'if(lt(%s,2),W-w-%s,%s)' % (clock, margin, margin)
        y = 'if(eq(%s,0)+eq(%s,3),%s,H-h-%s)' % (clock, clock, margin, margin)
        if video == '0:v:0':
            graph.append('[0:v:0]setpts=PTS-STARTPTS[base]')
            video = 'base'
        graph.append(f'[1:v:0]crop=900:790:190:140,format=rgba,colorkey=0x000000:0.12:0.08,'
                     f'scale={mark_w}:{mark_h},colorchannelmixer=aa={opacity:.3f}[logo]')
        graph.append(f"[{video}][logo]overlay=x='{x}':y='{y}':eval=frame:shortest=1[vout]")
        video = 'vout'
        args += ['-loop', '1', '-i', str(logo)]
    if title:
        graph.append(f'[{video}]setpts=PTS-STARTPTS,{title_filter(title)}[titled]')
        video = 'titled'
    if graph:
        args += ['-filter_complex', ';'.join(graph), '-map', f'[{video}]']
    else:
        args += ['-map', video]
    encoded = encoding_args(probe, end-start, output, max_duration)
    if render_options is not None:
        crf, preset = quality_args(values)
        encoded[encoded.index('-crf')+1] = crf
        encoded[encoded.index('-preset')+1] = preset
    return args + ['-map', '0:a:0?'] + encoded


def fit_panel(width, height):
    return (f'scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2:reset_sar=1,'
            f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x151619,setsar=1')


def layout_graph(size, split, source='0:v:0', track=False, fit='auto', frame=(.5,.5)):
    width, height = size
    if not split:
        if fit == 'crop' and not track:
            x,y = frame
            return [f'[{source}]setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2:reset_sar=1,crop={width}:{height}:(iw-ow)*{x}:(ih-oh)*{y},setsar=1[layout]'], 'layout'
        if fit == 'contain' and not track:
            return [f'[{source}]setpts=PTS-STARTPTS,{fit_panel(width,height)}[layout]'], 'layout'
        if track:
            return [f'[{source}]setpts=PTS-STARTPTS,{followed_panel(width, height)}[layout]'], 'layout'
        if height > width:
            small_w, small_h = width//4, height//4
            return [f'[{source}]setpts=PTS-STARTPTS,split=2[front_src][back_src]',
                    f'[front_src]scale={width}:{height}:force_original_aspect_ratio=decrease:'
                    'force_divisible_by=2:reset_sar=1[front]',
                    f'[back_src]scale={small_w}:{small_h}:force_original_aspect_ratio=increase:'
                    f'force_divisible_by=2:reset_sar=1,crop={small_w}:{small_h},boxblur=10:2,'
                    f'scale={width}:{height}:flags=fast_bilinear,setsar=1[back]',
                    '[back][front]overlay=(W-w)/2:(H-h)/2:shortest=1[layout]'], 'layout'
        return [f'[{source}]setpts=PTS-STARTPTS,{fit_panel(width, height)}[layout]'], 'layout'
    camera_height = round(height*.35)//2*2
    graph = ['[0:v:0]setpts=PTS-STARTPTS,split=2[cam_source][game_source]']
    for name, output, panel_height, source in (
            ('camera', 'face', camera_height, 'cam_source'),
            ('game', 'play', height-camera_height, 'game_source')):
        x, y, w, h = split[name]
        crop = (f'crop=w=trunc(iw*{w}/200)*2:h=trunc(ih*{h}/200)*2:'
                f'x=trunc(iw*{x}/200)*2:y=trunc(ih*{y}/200)*2')
        graph.append(f'[{source}]{crop},{fit_panel(width, panel_height)}[{output}]')
    graph.append('[face][play]vstack=inputs=2[layout]')
    return graph, 'layout'

def encoding_args(probe, duration, output, max_duration=MAX_CLIP_SECONDS):
    args = []
    video = next((s for s in probe.get('streams', []) if s.get('codec_type') == 'video'), {})
    try:
        rate = Fraction(video.get('avg_frame_rate', '30'))
    except (ValueError, ZeroDivisionError):
        rate = Fraction(30)
    if rate <= 0:
        rate = Fraction(30)
    if duration + 1/rate > max_duration:
        # Con un número entero de fotogramas por minuto, el último no supera el límite.
        frames = max(1, round(rate * max_duration))
        args += ['-fps_mode', 'cfr', '-r', str(Fraction(frames, max_duration))]
        duration = min(duration, max_duration)
    args += ['-t', str(duration), '-c:v', 'libx264', '-crf', '18', '-preset', 'medium', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(output)]
    return args
