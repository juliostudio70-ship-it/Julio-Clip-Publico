"""Tiempos de palabras, correcciones y subtítulos ASS animados para libass."""
import math
import re

THEMES = ('classic', 'dynamic', 'word', 'bounce', 'zoom', 'karaoke', 'minimal', 'impact', 'slide', 'build')
FONTS = {'barlow': 'Barlow Condensed', 'sans': 'Arial', 'serif': 'Georgia'}


def timed_words(text, start, end):
    words = text.split()
    weights = [max(1, len(re.sub(r'\W', '', word))) for word in words]
    total, cursor, result = sum(weights), start, []
    for word, weight in zip(words, weights):
        right = cursor + (end-start)*weight/total
        result.append(dict(text=word, start=round(cursor, 3), end=round(right, 3)))
        cursor = right
    return result


def token_words(tokens, start, end):
    valid=[token for token in tokens if isinstance(token.get('text'),str) and token['text'].strip()
           and not token['text'].startswith(('[','<|'))]
    if valid and all(type(t.get('t_dtw')) in (int,float) and math.isfinite(t['t_dtw']) and
                     start-.1<=t['t_dtw']/100<=end+.1 for t in valid):
        groups=[]
        for t in valid:
            if groups and not t['text'][0].isspace():groups[-1]['text']+=t['text']
            else:groups.append(dict(text=t['text'].strip(),start=max(start,t['t_dtw']/100-.025)))
        for i,w in enumerate(groups):
            w['end']=max(w['start']+.02,min(end,groups[i+1]['start'] if i+1<len(groups) else end))
        if all(start<=w['start']<w['end']<=end+.03 for w in groups):return groups
    result = []
    for token in tokens:
        text = token.get('text', '')
        offsets = token.get('offsets', {})
        if not isinstance(text, str) or not text or text.startswith('[_') or text.startswith('<|'):
            continue
        left, right = offsets.get('from', -1)/1000, offsets.get('to', -1)/1000
        if not (start-.05 <= left < right <= end+.05):
            continue
        if not text[0].isspace() and result:
            result[-1]['text'] += text
            result[-1]['end'] = min(end, right)
        else:
            result.append(dict(text=text.strip(), start=max(start, left), end=min(end, right)))
    return result


def phrases(transcription):
    """Preserva tiempos reales de Whisper; usa aproximación sólo si faltan tokens."""
    previous = None
    for segment in transcription.get('transcription', []):
        offsets = segment.get('offsets', {})
        start, end = offsets.get('from', 0)/1000, offsets.get('to', 0)/1000
        text = ' '.join(segment.get('text', '').split())
        if not text or end <= start or re.fullmatch(r'\[[^\]]+\]|\((?:música|silencio|inaudible)\)', text, re.I):
            continue
        # Sólo elimina repeticiones duplicadas por solapamiento, no frases repetidas deliberadamente.
        if previous and text.casefold() == previous[0] and start < previous[1]+.08:
            continue
        previous = text.casefold(), end
        words = token_words(segment.get('tokens', []), start, end)
        estimated = not words or ''.join(w['text'] for w in words).casefold() != ''.join(text.split()).casefold()
        if estimated:
            words = timed_words(text, start, end)
        group = []
        for word in words:
            if group and (len(group) >= 7 or word['end']-group[0]['start'] > 3.2 or
                          word['start']-group[-1]['end'] > .5):
                yield dict(start=group[0]['start'], end=group[-1]['end'],
                           text=' '.join(w['text'] for w in group), words=group, timing_estimated=estimated)
                group = []
            group.append(word)
            if re.search(r'[.!?…]$', word['text']) and len(group) >= 2:
                yield dict(start=group[0]['start'], end=group[-1]['end'],
                           text=' '.join(w['text'] for w in group), words=group, timing_estimated=estimated)
                group = []
        if group:
            yield dict(start=group[0]['start'], end=group[-1]['end'],
                       text=' '.join(w['text'] for w in group), words=group, timing_estimated=estimated)


def shifted(cue, left, right, offset=0):
    result = dict(cue, start=round(left+offset, 3), end=round(right+offset, 3))
    if cue.get('words'):
        words = [dict(word, start=round(max(left, word['start'])+offset, 3),
                      end=round(min(right, word['end'])+offset, 3))
                 for word in cue['words'] if word['end'] > left and word['start'] < right]
        result['words'] = [word for word in words if word['end'] > word['start']]
        result['text'] = ' '.join(word['text'] for word in result['words'])
    return result


def corrected(cues, edits):
    if edits is None:
        return cues
    if not isinstance(edits, list) or len(edits) != len(cues) or len(edits) > 300:
        raise ValueError('La corrección debe conservar las frases y sus tiempos originales.')
    result = []
    for cue, text in zip(cues, edits):
        if not isinstance(text, str) or len(text) > 240 or any(ord(c) < 32 and not c.isspace() for c in text):
            raise ValueError('Cada frase admite hasta 240 caracteres de texto.')
        text = ' '.join(text.split())
        if not text:
            continue
        words = cue.get('words', [])
        replacements = text.split()
        if len(words) == len(replacements):
            words = [dict(word, text=value) for word, value in zip(words, replacements)]
        else:
            words = timed_words(text, cue['start'], cue['end'])
        result.append(dict(cue, text=text, words=words,
                           timing_estimated=cue.get('timing_estimated', False) or len(replacements) != len(cue.get('words', []))))
    return result


def ass_text(cues, style, width, height):
    """Cada efecto está en el ASS que FFmpeg incrusta, no sólo en CSS."""
    def color(value):
        return '&H00' + value[5:7] + value[3:5] + value[1:3]

    def stamp(value):
        centis = max(0, round(value*100))
        seconds, centis = divmod(centis, 100)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f'{hours}:{minutes:02}:{seconds:02}.{centis:02}'

    def safe(text):
        return text.replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\n', ' ')

    theme, animated = style['theme'], style['animations']
    size = round(min(height*.064, width*.071)*{'small': .8, 'medium': 1, 'large': 1.2}[style['size']])
    size = max(12, size)
    outline = 0 if theme == 'minimal' else style['outline']
    alignment = {'top': 8, 'center': 5, 'bottom': 2}[style['position']]
    margin = round(height*.10)
    primary, accent = color(style['color']), color(style['accent'])
    primary_tag, accent_tag = '&H'+primary[4:]+'&', '&H'+accent[4:]+'&'
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONTS[style['font']]},{size},{primary},{accent},&H00151A21,&H90000000,-1,0,0,0,100,100,0,0,1,{outline},{style['shadow']},{alignment},{round(width*.07)},{round(width*.07)},{margin},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = []
    def emit(start, end, text, tags=''):
        if end-start >= .02:
            events.append(f'Dialogue: 0,{stamp(start)},{stamp(end)},Default,,0,0,0,,{{{tags}}}{text}\n')

    for original in cues:
        delay=style.get('offset_ms',0)/1000
        cue=dict(original,start=original['start']+delay,end=original['end']+delay)
        if original.get('words'):
            cue['words']=[dict(w,start=w['start']+delay,end=w['end']+delay) for w in original['words']]
        words = cue.get('words') or timed_words(cue['text'], cue['start'], cue['end'])
        if not words:
            continue
        if style.get('reveal','progressive')=='progressive':
            for index,word in enumerate(words):
                end=min(cue['end'],word['end']+.10,words[index+1]['start'] if index+1<len(words) else cue['end'])
                if end<=word['start']:
                    continue
                shown=[word] if theme in ('word','bounce','zoom','slide') else words[:index+1]
                content=' '.join((r'{\1c'+accent_tag+'}'+safe(w['text'])+r'{\1c'+primary_tag+'}')
                    if theme in ('dynamic','karaoke') and i==len(shown)-1 else safe(w['text']) for i,w in enumerate(shown))
                tags=r'\fad(30,40)' if animated else ''
                if animated and theme in ('bounce','impact','build'):
                    tags+=r'\fscx90\fscy90\t(0,100,\fscx106\fscy106)\t(100,170,\fscx100\fscy100)'
                if animated and theme=='zoom':
                    tags+=r'\fscx92\fscy92\t(0,170,\fscx104\fscy104)'
                if animated and theme=='slide':
                    px=round(width/2)
                    py=round(height*({'top':.12,'center':.5,'bottom':.88}[style['position']]))
                    tags+=f'\\move({px},{py+20},{px},{py},0,120)'
                emit(max(0,word['start']),end,content.upper() if theme=='impact' else content,tags)
            continue
        fade = r'\fad(100,100)' if animated else ''
        if not animated or theme in ('classic', 'minimal', 'impact'):
            tags = fade
            if theme == 'impact':
                tags += r'\fscx112\fscy112\t(0,160,\fscx100\fscy100)' if animated else ''
            emit(cue['start'], cue['end'], safe(cue['text']).upper() if theme == 'impact' else safe(cue['text']), tags)
        elif theme == 'karaoke':
            content, cursor = '', cue['start']
            for word in words:
                # La pausa también ocupa tiempo de karaoke; no adelanta las palabras siguientes.
                pause = round(max(0, word['start']-cursor)*100)
                if pause:
                    content += f'{{\\k{pause}}} '
                content += f"{{\\kf{max(1, round((word['end']-word['start'])*100))}}}{safe(word['text'])} "
                cursor = word['end']
            emit(cue['start'], cue['end'], content.strip(), r'\1c'+accent_tag+r'\2c'+primary_tag+fade)
        else:
            for index, word in enumerate(words):
                left = word['start']
                right = words[index+1]['start'] if index+1 < len(words) else cue['end']
                right = max(word['end'], right)
                if theme == 'dynamic':
                    content = ' '.join((r'{\1c'+accent_tag+r'}'+safe(w['text'])+r'{\1c'+primary_tag+'}')
                                       if i == index else safe(w['text']) for i, w in enumerate(words))
                    emit(left, right, content)
                else:
                    tags = r'\fad(45,45)'
                    if theme == 'bounce':
                        tags += r'\fscx88\fscy88\t(0,80,\fscx110\fscy110)\t(80,180,\fscx100\fscy100)'
                    elif theme == 'zoom':
                        tags += r'\fscx90\fscy90\t(0,220,\fscx104\fscy104)'
                    emit(left, right, safe(word['text']), tags)
    return header + ''.join(events)
