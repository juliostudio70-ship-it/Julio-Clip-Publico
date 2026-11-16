"""Progreso de una sesión y selección local de momentos a partir de imagen, voz y audio."""
from array import array
from collections import deque
import math
import re
from statistics import median
import sys
import threading
import time
import unicodedata
import wave

REACTION = re.compile(r'\b(risa[s]?|gritos?|aplausos?|wow|whoa|oh my god|incre[ií]ble|'
                      r'no (me lo )?(creo|puedo creer)|qu[eé] locura|guau|madre m[ií]a)\b', re.I)
TURN = re.compile(r'\b(pero|entonces|de repente|al final|por eso|resulta que|'
                  r'suddenly|but then|turns out|finally|because)\b', re.I)
FILLER = re.compile(r'\b(eh|mmm|um|uh|este|gracias por ver|suscr[ií]bete|subscribe)\b', re.I)
ANNOTATION = re.compile(r'\[[^\]]+\]|\([^)]*(?:música|music|silencio|silence|inaudible)[^)]*\)', re.I)
WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)
PROMO = re.compile(r'\b(compra ahora|usa el c[oó]digo|patrocinado por|oferta por tiempo limitado|'
                   r'c[oó]digo promocional|env[ií]o gratis|visita nuestra p[aá]gina|anuncio publicitario|'
                   r'ordena ahora|aprovecha la oferta|buy now|use (?:promo )?code|free shipping|'
                   r'sponsored by|limited time offer|visit our website|order now)\b', re.I)
AD_BREAK = re.compile(r'\b(pausa publicitaria|corte comercial|despu[eé]s de estos mensajes|'
                      r'commercial break|after these messages|back after the break)\b', re.I)
AD_RETURN = re.compile(r'\b(ya estamos de vuelta|regresamos al partido|seguimos con el directo|'
                       r'we are back|we.re back|back to the game)\b', re.I)
DISCUSSION = re.compile(r'\b(no estoy de acuerdo|eso no es cierto|est[aá]s diciendo|'
                         r'por primera vez|nunca hab[ií]a|qu[eé] acaba de pasar|'
                         r'i disagree|that.s not true|you.re saying|what just happened)\b', re.I)
SURPRISE = re.compile(r'\b(nadie (?:se lo )?esperaba|no te imaginas|me enter[eé]|me pas[oó]|'
                      r'lo que no sab[ií]a|la verdad es que|el problema fue|sin avisar|'
                      r'inesperad[oa]|no puede ser|that was unexpected|you won.t believe)\b', re.I)
PLAY = re.compile(r'\b(bate[oó]|batea|bateada|batazo|jonr[oó]n|cuadrangular|imparable|'
                  r'ponch[oó]|ponche|atrapada|pega de hit|la pelota se va|home run|line drive|'
                  r'base hit|swung on|strikes him out|strike three|fly ball|ground ball)\b', re.I)
VISUAL_WIDTH, VISUAL_HEIGHT = 48, 28
PIXELS = tuple((y, (y*VISUAL_WIDTH+x)*3) for y in range(3, VISUAL_HEIGHT-3)
               for x in range(3, VISUAL_WIDTH-3))
SAMPLE_COLUMNS = VISUAL_WIDTH-6
SIGNATURE_PIXELS = tuple(row*SAMPLE_COLUMNS+col for row in range(1, VISUAL_HEIGHT-6, 3)
                         for col in range(1, SAMPLE_COLUMNS, 4))
GAMEPLAY=re.compile(r'\b(partida|headshot|respawn|gameplay|fortnite|minecraft|warzone|clutch|gta|counter strike|call of duty)\b',re.I)
GAME_EVENT=re.compile(r'\b(elimin[oó]|eliminado|victoria|ganamos|perdimos|gan[eé]|headshot|clutch|triple kill|no puede ser)\b',re.I)
FREEZE_SECONDS = 2.0
DUPLICATE_REASON = 'Repite una secuencia de un clip que ya se seleccionó.'


def highlight_profile(value):
    if value not in ('auto', 'sports', 'conversation','gameplay'):
        raise ValueError('Elige un perfil de momentos válido.')
    return value


class VisualTrack:
    """Muestras pequeñas y uniformes. El césped y el movimiento son indicios de juego."""

    def __init__(self, raw, rate, duration):
        size = VISUAL_WIDTH*VISUAL_HEIGHT*3
        self.rate, self.duration = rate, duration
        self.samples = []
        self.black = []
        self.frozen = []
        self.signatures = []
        dark_start = None
        previous = None
        steady, steady_start = None, 0.0
        bottom = sum(y >= VISUAL_HEIGHT//2 for y, _ in PIXELS)
        for index, offset in enumerate(range(0, len(raw)-size+1, size)):
            rgb = raw[offset:offset+size]
            light, green, dirt, dark, changed = [], 0, 0, 0, 0
            for p, (y, k) in enumerate(PIXELS):
                red, g, blue = rgb[k:k+3]
                level = (red+2*g+blue)//4
                light.append(level)
                dark += max(red, g, blue) < 34
                if y >= VISUAL_HEIGHT//2:
                    green += g > 45 and g-red > 12 and g-blue > 12
                    dirt += red > 60 and red-g > 10 and g-blue > 10
                if previous is not None:
                    changed += abs(level-previous[p]) > 15
            previous = light
            black = dark > .96*len(PIXELS)
            field = not black and (green >= .30*bottom or (green >= .14*bottom and dirt >= .15*bottom))
            movement = changed/len(PIXELS)
            # Un corte de cámara cambia gran parte de la imagen en una sola muestra.
            self.samples.append((field, movement if not black and movement < .45 else 0))
            self.signatures.append(bytes(light[p] for p in SIGNATURE_PIXELS).hex())
            t = index/rate
            deltas = [abs(a-b) for a, b in zip(light, steady)] if steady is not None else []
            moving = sum(deltas) > .24*len(light) or sum(delta >= 8 for delta in deltas) >= 4
            if black or steady is None or moving:
                if steady is not None and t-steady_start >= FREEZE_SECONDS + 1/rate:
                    self.frozen.append((steady_start, t))
                steady, steady_start = (None if black else light), t
            if black and dark_start is None:
                dark_start = index/rate
            elif not black and dark_start is not None:
                self._add_black(dark_start, index/rate)
                dark_start = None
        decoded = min(duration, len(self.samples)/rate)
        if dark_start is not None:
            self._add_black(dark_start, decoded)
        if steady is not None and decoded-steady_start >= FREEZE_SECONDS + 1/rate:
            self.frozen.append((steady_start, decoded))
        if duration-decoded >= FREEZE_SECONDS:
            self.frozen.append((decoded, duration))
        if not self.samples:
            raise ValueError('No se pudo comprobar la imagen del fragmento.')

    def _add_black(self, start, end):
        if end-start >= max(.65, 1.5/self.rate) or (start == 0 and end >= self.duration-1/self.rate):
            self.black.append((start, end))

    def window(self, start, end):
        return self.samples[max(0, int(start*self.rate)):math.ceil(end*self.rate)]

    def sports_scene(self):
        return sum(field for field, _ in self.samples) >= max(4*self.rate, .10*len(self.samples))

    def black_screen(self, start, end):
        return any(min(end, right)-max(start, left) >= .55 for left, right in self.black)

    def frozen_screen(self, start, end):
        return any(min(end, right)-max(start, left) >= FREEZE_SECONDS for left, right in self.frozen)

    def signature(self, start, end):
        return [self.signatures[min(len(self.signatures)-1, round((start+i)*self.rate))]
                for i in range(int(end-start))]


def repeats_sequence(signature, previous):
    """Busca la misma secuencia durante varios segundos, incluso con recortes desplazados."""
    minimum = max(6, math.ceil(min(len(signature), len(previous))*.40))
    if minimum > min(len(signature), len(previous)):
        return False
    current = [bytes.fromhex(frame) for frame in signature]
    older = [bytes.fromhex(frame) for frame in previous]

    def difference(a, b):
        return sum(abs(x-y) for x, y in zip(a, b))/len(a)

    for offset in range(minimum-len(current), len(older)-minimum+1):
        first = None
        matched = changes = 0
        for i in range(max(0, -offset), min(len(current), len(older)-offset)):
            frame = current[i]
            if difference(frame, older[i+offset]) > 3:
                first = None
                matched = changes = 0
                continue
            if first is None or difference(frame, first) > 3:
                first = frame
                changes += 1
            matched += 1
            if matched >= minimum and changes >= 3:
                return True
    return False


def advertising_ranges(cues, duration):
    ranges = []
    ordered = sorted(cues, key=lambda cue: cue['start'])
    for index, cue in enumerate(ordered):
        if AD_BREAK.search(cue['text']):
            resumed = next((entry['start'] for entry in ordered[index+1:]
                            if entry['start']-cue['end'] <= 120 and AD_RETURN.search(entry['text'])), None)
            end = resumed if resumed is not None else cue['end']+5
            ranges.append((max(0, cue['start']-1), min(duration, end)))
        elif PROMO.search(cue['text']):
            ranges.append((max(0, cue['start']-2), min(duration, cue['end']+2)))
    return ranges


def selection_rejection(start, end, gaps, visual, ads=()):
    if any(start < right and end > left for left, right in gaps):
        return 'Hay un salto en la señal dentro del fragmento.'
    if visual and visual.black_screen(start, end):
        return 'La imagen se queda en negro dentro del fragmento.'
    if visual and visual.frozen_screen(start, end):
        return 'La imagen se queda congelada dentro del fragmento.'
    if any(start < right and end > left for left, right in ads):
        return 'La narración contiene indicios de un anuncio.'
    return None


def sports_anchors(visual, energy, duration, limit):
    """Busca actividad en el campo antes de gastar CPU en la transcripción."""
    candidates = []
    for start in range(math.ceil(duration)):
        nearby = visual.window(start-1, min(duration, start+2))
        motion = [change for field, change in nearby if field]
        if not motion or len(motion) < .45*len(nearby):
            continue
        movement = sum(motion)/len(motion)
        levels = energy[max(0, start-7):start+8]
        baseline = max(180, median(levels)) if levels else 180
        peak = max(energy[max(0, start-1):start+3], default=0)
        rise = peak/baseline
        if movement >= .012 or rise >= 1.35:
            candidates.append((start, movement, rise))
    result = []
    for candidate in sorted(candidates, key=lambda item: -(min(.20, item[1])*12+min(4, item[2]))):
        if all(abs(candidate[0]-previous[0]) >= 9 for previous in result):
            result.append(candidate)
        if len(result) >= min(12, max(3, limit*2)):
            break
    return result


def sports_windows(anchors, duration):
    ranges = []
    for start in sorted(anchor[0] for anchor in anchors):
        left, right = max(0, start-4), min(duration, start+6)
        if ranges and left <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], right)
        else:
            ranges.append((left, right))
    return ranges


def compact_audio(source, destination, ranges):
    """Conserva una tabla para convertir los tiempos de Whisper al video original."""
    mapping = []
    with wave.open(str(source), 'rb') as original, wave.open(str(destination), 'wb') as compact:
        compact.setparams(original.getparams())
        rate = original.getframerate()
        cursor = 0
        for start, end in ranges:
            first = min(original.getnframes(), int(start*rate))
            original.setpos(first)
            data = original.readframes(max(0, int(end*rate)-first))
            frames = len(data)//(original.getnchannels()*original.getsampwidth())
            if not frames:
                continue
            mapping.append((cursor/rate, (cursor+frames)/rate, first/rate))
            compact.writeframes(data)
            compact.writeframes(b'\0'*(rate//3*original.getnchannels()*original.getsampwidth()))
            cursor += frames+rate//3
    return mapping


def restore_cue_times(cues, mapping):
    for cue in cues:
        for left, right, start in mapping:
            if left <= (cue['start']+cue['end'])/2 < right:
                yield dict(cue, start=start+max(0, cue['start']-left),
                           end=start+min(right-left, cue['end']-left))
                break


def sports_start(moment, width, duration, interruptions):
    preferred = min(max(0, moment-min(10, width*.33)), duration-width)
    left, right = 0, duration
    for start, end in interruptions:
        if end <= moment:
            left = max(left, end)
        elif start > moment:
            right = min(right, start)
        else:
            return preferred
    if right-left >= width:
        return min(max(preferred, left), right-width)
    return preferred


def rank_sports(cues, duration, seconds, limit, gaps, visual, anchors, previous=()):
    width = min(duration, seconds)
    ranked = []
    rejects = [dict(start=start, end=end, reason='La imagen se queda en negro.')
               for start, end in visual.black]
    if width < 3 or not anchors:
        return [], rejects or [dict(start=0, end=duration,
                                    reason='No hubo actividad suficiente en un campo de juego visible.')]
    ads = advertising_ranges(cues, duration)
    interruptions = (*gaps, *visual.black, *visual.frozen, *ads)
    for moment, movement, rise in anchors:
        # Se conservan los segundos anteriores a la reacción y el desenlace.
        start = sports_start(moment, width, duration, interruptions)
        end = start+width
        nearby = [cue for cue in cues if cue['start'] < end and cue['end'] > start]
        play = next((cue['text'] for cue in nearby if cue['start'] < moment+7 and
                     cue['end'] > moment-3 and PLAY.search(cue['text'])), None)
        reason = selection_rejection(start, end, gaps, visual, ads)
        if not reason and not play and not (movement >= .022 and rise >= 1.45):
            reason = 'El campo era visible, pero faltó una jugada narrada o una reacción que coincidiera con la acción.'
        if reason:
            rejects.append(dict(start=start, end=end, reason=reason))
        else:
            frames = visual.window(start, end)
            field_context = 8*sum(field for field, _ in frames)/max(1, len(frames))
            score = round(min(98, 42+(22 if play else 0)+min(16, movement*120)+
                              min(18, max(0, rise-1)*8)+field_context))
            ranked.append(dict(start=start, end=end, score=score,
                               title=clip_title(play) if play else 'Posible jugada en el campo',category='sports',reason='Movimiento en el campo y reacción de audio'+('; jugada narrada' if play else '')))
    return choose_moments(ranked, rejects, limit, count_variants=False, visual=visual, previous=previous)


class WorkProgress:
    def __init__(self):
        self.guard = threading.Lock()
        self.reset()

    def reset(self, label='', total=None):
        with self.guard:
            self.label = label
            self.total = total
            self.started = time.monotonic()
            self.fraction = None
            self.remaining = None

    def report(self, fraction, remaining=None):
        with self.guard:
            if fraction is not None:
                if not math.isfinite(fraction) or not 0 <= fraction <= 1:
                    return
                if self.fraction is not None and fraction < self.fraction:
                    return
                self.fraction = fraction
                if remaining is None and fraction >= .05:
                    remaining = (time.monotonic()-self.started) * (1-fraction) / fraction
            if remaining is not None and math.isfinite(remaining) and remaining >= 0:
                self.remaining = math.ceil(remaining)

    def snapshot(self):
        with self.guard:
            return dict(label=self.label, total=self.total, fraction=self.fraction,
                        remaining_seconds=self.remaining, elapsed_seconds=int(time.monotonic()-self.started))


class LiveMonitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.recent = deque(maxlen=12)
        self.clips = deque(maxlen=3)
        self.analysis = WorkProgress()
        self.reset()

    def reset(self):
        with self.lock:
            self.data = dict(recorded_seconds=0, elapsed_seconds=0, recording=False,
                             stage='idle', reviewed=0, highlights=0, rejected=0,
                             generated=0, pending_clips=0, exporting=0, export_total=0)
            self.started = None
            self.base = 0
            self.recent.clear()
            self.clips.clear()
            self.analysis.reset()

    def progress(self, seconds):
        if seconds <= 0:
            return
        with self.lock:
            if self.started is None:
                self.started = time.monotonic()
            self.data['recording'] = True
            self.data['recorded_seconds'] = max(self.data['recorded_seconds'], self.base + seconds)

    def end_capture(self):
        with self.lock:
            self.base = self.data['recorded_seconds']
            self.data['recording'] = False

    def finish(self):
        with self.lock:
            if self.started is not None:
                self.data['elapsed_seconds'] = int(time.monotonic() - self.started)
                self.started = None
            self.data.update(recording=False, stage='idle', exporting=0)

    def stage(self, value):
        with self.lock:
            self.data['stage'] = value

    def reviewed(self, picks, rejects):
        with self.lock:
            self.data['reviewed'] += 1
            self.data['highlights'] += len(picks)
            self.data['rejected'] += len(rejects)
            self.data.update(pending_clips=len(picks), exporting=0, export_total=len(picks))
            self.recent.extend(rejects)

    def exporting(self, position):
        with self.lock:
            self.data.update(stage='exporting', exporting=position)

    def completed(self, clip=None, rejection=None):
        with self.lock:
            self.data['pending_clips'] = max(0, self.data['pending_clips'] - 1)
            if clip:
                self.data['generated'] += 1
                self.clips.append(clip)
            if rejection:
                self.data['rejected'] += 1
                self.recent.append(rejection)

    def snapshot(self):
        with self.lock:
            data = dict(self.data, recent_rejections=list(reversed(self.recent)),
                        recent_clips=list(reversed(self.clips)), analysis=self.analysis.snapshot())
            if self.started is not None:
                data['elapsed_seconds'] = int(time.monotonic() - self.started)
            return data


def audio_energy(path):
    """Medición RMS por segundo del WAV mono de Whisper, sin dependencias externas."""
    if not path.is_file():
        return []
    with wave.open(str(path), 'rb') as audio:
        if audio.getsampwidth() != 2 or audio.getnchannels() != 1:
            return []
        result = []
        while True:
            data = audio.readframes(audio.getframerate())
            if not data:
                return result
            samples = array('h')
            samples.frombytes(data)
            if sys.byteorder != 'little':
                samples.byteswap()
            sampled = samples[::4]
            result.append(math.sqrt(sum(x*x for x in sampled) / len(sampled)))


def clip_title(text):
    text = ANNOTATION.sub('', text).strip(' -–—.,')
    sentences = re.split(r'(?<=[.!?])\s+', text)
    meaningful = next((line for line in sentences if len(WORD.findall(line)) >= 3), text)
    words = meaningful.split()
    title = ' '.join(words[:12])
    if len(title) > 78:
        title = title[:75].rsplit(' ', 1)[0] + '…'
    elif len(words) > 12:
        title = title.rstrip(',;:') + '…'
    return title[:1].upper() + title[1:] if title else 'Momento del directo'


def rank_moments(cues, duration, seconds, limit, gaps=(), energy=(), visual=None, previous=(), threshold=39):
    """Ventanas continuas y sin saltos. Puntúa señales de contexto y de reacción."""
    width = min(duration, seconds)
    if width < 3:
        return [], [dict(start=0, end=duration, reason='El fragmento es demasiado corto.')]
    voiced = [cue for cue in cues if cue['start'] < duration and cue['end'] > 0]
    ads = advertising_ranges(voiced, duration)
    starts = {0.0, round(max(0, duration-width), 3)}
    interruptions = (*gaps, *ads, *(visual.black + visual.frozen if visual else []))
    for left, right in interruptions:
        starts.update((max(0, left-width), min(duration-width, right)))
    interval = 4 if visual is None else max(6, int(width*.4))
    for cue in voiced:
        start = min(max(0, cue['start']-min(5, width*.2)), duration-width)
        # Agrupa anclas cercanas para no contar decenas de variantes de la misma escena.
        starts.add(round(min(duration-width, round(start/interval)*interval), 3))
    for start in range(0, int(duration-width)+1, max(6, int(width*.75))):
        starts.add(float(start))
    baseline = max(250, median(energy)) if energy else 250
    ranked, rejects = [], []
    windows = set()
    for start in sorted(starts):
        end = min(duration, start+width)
        # Busca límites de frase cercanos, conservando la duración y el contexto continuo.
        endings = [cue['end'] for cue in voiced if abs(cue['end']-end) <= min(3, width*.15)]
        if endings:
            aligned_end = min(endings, key=lambda value: abs(value-end))
            aligned_start = max(0, aligned_end-width)
            if not any(cue['start']+.12 < aligned_start < cue['end']-.12 for cue in voiced):
                start, end = aligned_start, aligned_end
        identity = (round(start, 3), round(end, 3))
        if identity in windows:
            continue
        windows.add(identity)
        window = dict(start=start, end=end)
        nearby = [cue for cue in voiced if start <= (cue['start'] + cue['end']) / 2 < end]
        reason = selection_rejection(start, end, gaps, visual, ads)
        if reason:
            rejects.append(dict(window, reason=reason))
            continue
        raw = ' '.join(cue['text'] for cue in nearby)
        speech = ANNOTATION.sub(' ', raw)
        words = WORD.findall(speech)
        if len(words) < 4:
            rejects.append(dict(window, reason='Hay poca conversación clara para entender el momento.'))
            continue
        unique = len({unicodedata.normalize('NFKC', word).casefold() for word in words})
        speech_seconds = min(width, sum(min(end, cue['end'])-max(start, cue['start']) for cue in nearby))
        reactions = len(REACTION.findall(raw))
        turning = len(TURN.findall(speech))
        question_answer = bool(re.search(r'\?\s+[^?]{12,}', speech)) or any(
            len(WORD.findall(reply['text'])) >= 4 and reply['start']-question['end'] <= 2.5 and
            (question['text'].rstrip().endswith('?') or question['text'].lstrip().startswith('¿'))
            for question, reply in zip(nearby, nearby[1:]))
        levels = energy[int(start):math.ceil(end)]
        emphasis = min(12, max(0, (max(levels, default=0)/baseline-1.5)*6))
        context = min(24, unique*.7) + min(12, 18*speech_seconds/width)
        score = 13 + context + min(15, turning*7) + min(16, reactions*8) + emphasis
        score += 10 if question_answer else 0
        score += min(9, speech.count('!')*3)
        score += min(16, len(DISCUSSION.findall(speech))*8)
        surprise = bool(SURPRISE.search(speech))
        score += 12 if surprise else 0
        gameplay=bool(GAMEPLAY.search(speech))
        if gameplay and GAME_EVENT.search(speech):score+=10
        if not (reactions or turning or question_answer or DISCUSSION.search(speech) or surprise or (gameplay and GAME_EVENT.search(speech))):
            score -= 14
        # No premia frases cortadas aunque tengan palabras llamativas.
        clipped = sum(cue['start']+.15 < boundary < cue['end']-.15
                      for cue in voiced for boundary in (start, end))
        score -= min(20, clipped*10)
        distinct_lines = {' '.join(WORD.findall(cue['text'].casefold())) for cue in nearby}
        score -= min(20, 25*(1-len(distinct_lines)/len(nearby)))
        score -= min(18, len(FILLER.findall(speech))*4 + (1-unique/len(words))*12)
        score = min(99, max(0, round(score)))
        if score < threshold:
            reason = ('Corta una frase sin conservar suficiente contexto.' if clipped else
                      'Poca variedad o contexto, sin una reacción o giro claro.')
            rejects.append(dict(window, score=score, reason=reason))
            continue
        informative = [cue['text'] for cue in nearby if len(WORD.findall(cue['text'])) >= 5]
        meaningful = next((line for line in informative if DISCUSSION.search(line) or TURN.search(line)),
                          max(informative, key=lambda line: len(set(WORD.findall(line.casefold()))), default=speech))
        fingerprint = sorted(set(' '.join(words[i:i+3]).casefold() for i in range(len(words)-2)))
        ranked.append(dict(window, score=score, title=clip_title(meaningful), dialogue_signature=fingerprint,category='gameplay' if gameplay else 'conversation',
            reason='Contexto y variedad de conversación'+('; reacción' if reactions else '')+('; pregunta y respuesta' if question_answer else '')+('; sorpresa' if surprise else '')+('; debate' if DISCUSSION.search(speech) else '')))
    return choose_moments(ranked, rejects, limit, count_variants=visual is None, visual=visual, previous=previous)


def choose_moments(ranked, rejects, limit, count_variants, visual=None, previous=()):
    chosen = []
    signatures = list(previous)
    for candidate in sorted(ranked, key=lambda item: (-item['score'], item['start'])):
        if any(candidate['start'] < pick['end'] and candidate['end'] > pick['start'] for pick in chosen):
            if not count_variants:
                continue
            reason = 'Se solapa con otro momento que recibió mejor puntuación.'
        elif candidate.get('dialogue_signature') and any(
            len(set(candidate['dialogue_signature']) & set(pick.get('dialogue_signature', []))) /
            max(1, min(len(candidate['dialogue_signature']), len(pick.get('dialogue_signature', [])))) > .72
            for pick in chosen):
            reason = 'Repite la conversación de otro clip ya seleccionado.'
        elif len(chosen) >= limit:
            reason = 'Otros momentos puntuaron mejor dentro del límite de clips del bloque.'
        else:
            signature = candidate.get('signature') or (visual.signature(candidate['start'], candidate['end']) if visual else [])
            if signature and any(repeats_sequence(signature, seen) for seen in signatures):
                reason = DUPLICATE_REASON
            else:
                chosen.append(dict(candidate, signature=signature) if signature else candidate)
                if signature:
                    signatures.append(signature)
                continue
        rejects.append(dict(candidate, reason=reason))
    if not count_variants:
        distinct = []
        for candidate in rejects:
            center = (candidate['start']+candidate['end'])/2
            if any(pick['start'] <= center < pick['end'] for pick in chosen):
                continue
            if any(previous['reason'] == candidate['reason'] and
                   abs(center-(previous['start']+previous['end'])/2) <=
                   (candidate['end']-candidate['start'])/2 for previous in distinct):
                continue
            distinct.append(candidate)
        rejects = distinct
    return chosen, rejects
