"""Recortes y pistas de subtítulos para los MP4 de la biblioteca."""
import math
import re

from watermark import MAX_CLIP_SECONDS, OUTPUT_SIZES, encoding_args, layout_graph
from reframe import title_filter
from captions import THEMES, FONTS, phrases, shifted

MAX_CUTS = 8


def subtitles_enabled(options):
    enabled = options.get('subtitles', False)
    if not isinstance(enabled, bool):
        raise ValueError('Activa o desactiva la opción de subtítulos.')
    return enabled


def burn_subtitles_enabled(options):
    burn = options.get('burn_subtitles', False)
    if type(burn) is not bool or (burn and not subtitles_enabled(options)):
        raise ValueError('Activa los subtítulos para incrustarlos en el video.')
    return burn


def subtitle_settings(options):
    style = options.get('subtitle_style', {})
    if not isinstance(style, dict):
        raise ValueError('Revisa el estilo de los subtítulos.')
    color = style.get('color', '#FFFFFF')
    size = style.get('size', 'medium')
    position = style.get('position', 'bottom')
    if (not isinstance(color, str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}', color)
            or size not in ('small', 'medium', 'large') or position not in ('top', 'center', 'bottom')):
        raise ValueError('Revisa el color, tamaño y posición de los subtítulos.')
    theme, font = style.get('theme', 'classic'), style.get('font', 'barlow')
    accent, animations = style.get('accent', '#A8E986'), style.get('animations', True)
    outline, shadow = style.get('outline', 2), style.get('shadow', 1)
    if (theme not in THEMES or font not in FONTS or type(animations) is not bool or
            not isinstance(accent, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', accent) or
            type(outline) not in (int, float) or not math.isfinite(outline) or not 0 <= outline <= 6 or
            type(shadow) not in (int, float) or not math.isfinite(shadow) or not 0 <= shadow <= 4):
        raise ValueError('Revisa el estilo, fuente, contorno y animaciones de los subtítulos.')
    return dict(color=color.upper(), size=size, position=position, theme=theme, font=font,
                accent=accent.upper(), animations=animations, outline=outline, shadow=shadow)


def subtitle_render_style(style):
    red, green, blue = style['color'][1:3], style['color'][3:5], style['color'][5:7]
    size = {'small': 13, 'medium': 16, 'large': 19}[style['size']]
    # force_style usa la numeración de alineación interna de libass.
    alignment = 6 if style['position'] == 'top' else 2
    return (f'FontName=Barlow Condensed,FontSize={size},Bold=-1,PrimaryColour=&H00{blue}{green}{red},'
            f'Alignment={alignment},OutlineColour=&H0010151B,BorderStyle=1,Outline=2,Shadow=1,'
            'MarginL=28,MarginR=28,MarginV=41')


def kept_ranges(options, duration):
    def interval(item):
        try:
            start, end = float(item['start']), float(item['end'])
        except (KeyError, TypeError, ValueError):
            raise ValueError('Introduce un inicio y un final en segundos.')
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration):
            raise ValueError('Los tiempos deben estar en orden y dentro del video.')
        return start, end

    start, end = interval(options)
    cuts = options.get('remove', [])
    if not isinstance(cuts, list) or len(cuts) > MAX_CUTS:
        raise ValueError('Puedes quitar hasta ocho tramos por edición.')
    kept = []
    for left, right in sorted(interval(cut) for cut in cuts):
        if left < start or right > end:
            raise ValueError('Los tramos a quitar deben quedar dentro de la selección y no solaparse.')
        if left > start:
            kept.append((start, left))
        start = right
    if start < end:
        kept.append((start, end))
    length = sum(right-left for left, right in kept)
    if length < .25 or length > MAX_CLIP_SECONDS + 1e-9:
        raise ValueError('Conserva entre 0,25 segundos y un minuto de video.')
    return kept


def trim_args(ffmpeg, source, output, probe, ranges, format_name='original', track=False, title=None):
    has_audio = any(s['codec_type'] == 'audio' for s in probe['streams'])
    filters, inputs = [], []
    for i, (start, end) in enumerate(ranges):
        filters.append(f'[0:v:0]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]')
        inputs.append(f'[v{i}]')
        if has_audio:
            filters.append(f'[0:a:0]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]')
            inputs.append(f'[a{i}]')
    filters.append(''.join(inputs) + f'concat=n={len(ranges)}:v=1:a={int(has_audio)}[video]' +
                   ('[audio]' if has_audio else ''))
    video = 'video'
    if format_name in OUTPUT_SIZES:
        layout, video = layout_graph(OUTPUT_SIZES[format_name], None, video, track)
        filters.extend(layout)
    if title:
        filters.append(f'[{video}]{title_filter(title)}[titled]')
        video = 'titled'
    args = [ffmpeg, '-nostdin', '-y', '-i', str(source), '-filter_complex', ';'.join(filters), '-map', f'[{video}]']
    if has_audio:
        args += ['-map', '[audio]']
    return args + encoding_args(probe, sum(end-start for start, end in ranges), output)


def whisper_cues(transcription):
    yield from phrases(transcription)


def retime_cues(cues, ranges):
    result = []
    offset = 0
    for start, end in ranges:
        for cue in cues:
            left, right = max(start, cue['start']), min(end, cue['end'])
            if right-left >= .001:
                result.append(shifted(cue, left, right, offset-start))
        offset += end-start
    return result


def srt_text(cues):
    def timestamp(seconds):
        seconds, ms = divmod(round(seconds*1000), 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f'{hours:02}:{minutes:02}:{seconds:02},{ms:03}'

    return ''.join(f"{i}\n{timestamp(cue['start'])} --> {timestamp(cue['end'])}\n{cue['text']}\n\n"
                   for i, cue in enumerate(cues, 1))


def visible_cues(cues, duration):
    """Acota los tiempos al MP4 y evita superponer dos subtítulos."""
    result = []
    for cue in sorted(cues, key=lambda item: item['start']):
        start = max(0, cue['start'])
        end = min(duration, cue['end'])
        text = ' '.join(cue['text'].split())
        if not text or end-start < .06:
            continue
        if result and start < result[-1]['end']:
            if start-result[-1]['start'] < .06:
                continue
            result[-1]['end'] = start
        item = shifted(cue, start, end)
        if item['text']:
            result.append(item)
    return result
