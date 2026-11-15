"""Encuadre facial local y títulos incrustados en el video."""
import math
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import re
import shutil
import sys
from textwrap import wrap

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / 'models/face_detection_yunet_2023mar.onnx'
FONT = ROOT / 'resources/BarlowCondensed-Bold.ttf'
SAMPLE_RATE = 8
VOICE_RATE = 8000
TITLE_POSITIONS = {'top': .13, 'center': .46, 'bottom': .74}
TITLE_SIZES = {'small': .068, 'medium': .091, 'large': .12}


@lru_cache(maxsize=1)
def vision():
    if not MODEL.is_file():
        return None
    bundled = ROOT / 'vision'
    if bundled.is_dir():
        sys.path.insert(0, str(bundled))
    try:
        import cv2
        import numpy
        cv2.setNumThreads(1)
        return cv2, numpy
    except (ImportError, AttributeError, OSError):
        return None


def styling(payload, format_name, split=None):
    track = payload.get('follow_face', False)
    if type(track) is not bool:
        raise ValueError('Activa o desactiva el seguimiento de cara.')
    if track and (format_name != 'vertical' or split):
        raise ValueError('El seguimiento de cara necesita formato vertical sin pantalla dividida.')
    if track and vision() is None:
        raise ValueError('El seguimiento de cara requiere el motor incluido en la edición Windows actualizada.')
    title = payload.get('overlay_title')
    if title is None:
        return track, None
    if not isinstance(title, dict) or not isinstance(title.get('text'), str):
        raise ValueError('Escribe un título válido.')
    raw = title['text']
    content = ' '.join(raw.split())
    if len(raw) > 64 or any(ord(char) < 32 and not char.isspace() for char in raw):
        raise ValueError('El título admite hasta 64 caracteres.')
    if not content:
        return track, None
    color = title.get('color', '#FFFFFF')
    position = title.get('position', 'top')
    size = title.get('size', 'medium')
    style = title.get('style', 'plate')
    duration = title.get('duration', 'intro')
    if (not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color)
            or position not in ('top', 'center', 'bottom') or size not in ('small', 'medium', 'large')
            or style not in ('plate', 'outline') or duration not in ('intro', 'full')):
        raise ValueError('Revisa el color, tamaño, posición, estilo y duración del título.')
    if not FONT.is_file():
        raise ValueError('Falta la tipografía del título. Abre la edición actualizada de Julio Clip.')
    return track, dict(text=content, color=color.upper(), position=position,
                       size=size, style=style, duration=duration)


def prepare_title(folder, title):
    lines = wrap(title['text'], width=24)
    (folder / 'title.txt').write_text('\n'.join(lines), encoding='utf-8')
    shutil.copyfile(FONT, folder / 'title-font.ttf')
    return dict(title, longest=max(map(len, lines)), lines=len(lines))


def title_filter(title):
    fraction = TITLE_SIZES[title['size']]
    width_limit = .79 / (max(1, title['longest']) * .68)
    y = TITLE_POSITIONS[title['position']]
    color = title['color'][1:]
    box = ':box=1:boxcolor=black@0.68:boxborderw=12' if title['style'] == 'plate' else ''
    enable = ":enable='lt(t,3)'" if title['duration'] == 'intro' else ''
    return ("drawtext=fontfile=title-font.ttf:textfile=title.txt:expansion=none:"
            f"fontcolor=0x{color}:fontsize='max(10,min(w*{fraction:.5f},w*{width_limit:.5f}))':"
            f"x=(w-tw)/2:y='min(h*{y},max(0,h-th-h*0.12))':"
            f"borderw=2:bordercolor=black@0.92:line_spacing=3{box}{enable}")


def voice_activity(data, frames, np):
    """Actividad sonora por instante de video, con umbral adaptado al clip."""
    samples = np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768
    block = VOICE_RATE // SAMPLE_RATE
    wanted = frames*block
    samples = np.pad(samples[:wanted], (0, max(0, wanted-len(samples))))
    levels = np.sqrt(np.mean(samples.reshape(frames, 5, block//5)**2, axis=2))
    peak = float(np.percentile(levels, 95))
    floor = float(np.percentile(levels, 20))
    threshold = max(.003, peak*.10, min(floor*2.3, peak*.65))
    return (levels > threshold).mean(axis=1)


def mouth_patch(gray, row, cv, np):
    eyes = sorted((row[4:6], row[6:8]), key=lambda point: point[0])
    horizontal = eyes[1] - eyes[0]
    distance = float(np.linalg.norm(horizontal))
    if distance < 9:
        return None
    vertical = np.array([-horizontal[1], horizontal[0]], dtype=np.float32)
    mouth = (row[10:12] + row[12:14]) / 2
    corner = mouth - .70*horizontal - 1.02*vertical
    source = np.float32([corner, corner+1.4*horizontal, corner+1.57*vertical])
    destination = np.float32([(0, 0), (31, 0), (0, 39)])
    transform = cv.getAffineTransform(source, destination)
    return cv.warpAffine(gray, transform, (32, 40), borderMode=cv.BORDER_REPLICATE).astype(np.float32)


def mouth_motion(previous, current, np):
    if previous is None or current is None:
        return 0
    difference = current-previous
    reference = difference[2:16, 4:28]
    lighting = np.median(reference)
    face = np.abs(reference-lighting).mean()
    lips = np.abs(difference[21:38, 5:27]-lighting).mean()
    return max(0., float(lips-1.15*face-.7))


@dataclass
class FaceTrack:
    center: tuple
    patch: object
    last_seen: int
    evidence: deque = field(default_factory=lambda: deque(maxlen=6))


class SpeakerFocus:
    """Cruza movimiento de labios con audio y exige un turno estable antes de cambiar."""

    def __init__(self):
        self.tracks = {}
        self.next_id = 0
        self.candidate = None
        self.confirmations = 0

    def update(self, index, boxes, patches, voice, np, cut=False):
        if cut:
            self.tracks.clear()
            self.candidate, self.confirmations = None, 0
        self.tracks = {key: track for key, track in self.tracks.items() if index-track.last_seen <= 4}
        matches, used = {}, set()
        distances = sorted((math.dist(box[:2], track.center), i, key)
                           for i, box in enumerate(boxes) for key, track in self.tracks.items())
        for distance, i, key in distances:
            if distance < .12 and i not in matches and key not in used:
                matches[i] = key
                used.add(key)
        scores = []
        for i, (box, patch) in enumerate(zip(boxes, patches)):
            key = matches.get(i)
            if key is None:
                key = self.next_id
                self.next_id += 1
                self.tracks[key] = FaceTrack(box[:2], patch, index)
            track = self.tracks[key]
            motion = mouth_motion(track.patch, patch, np) if track.last_seen == index-1 else 0
            if track.last_seen < index-1:
                track.evidence.clear()
            track.center, track.patch, track.last_seen = box[:2], patch, index
            track.evidence.append(motion*voice)
            if len(track.evidence) >= 4:
                scores.append((sum(track.evidence)/len(track.evidence), key, i))
        winner = None
        if len(boxes) >= 2 and len(scores) >= 2 and voice >= .20:
            scores.sort(reverse=True)
            best, key, position = scores[0]
            other = scores[1][0]
            if best >= 1.65 and best-other >= 1.0 and best >= 1.55*other:
                winner = key
        if winner is None:
            self.candidate, self.confirmations = None, 0
        elif winner == self.candidate:
            self.confirmations += 1
        else:
            self.candidate, self.confirmations = winner, 1
        return boxes[position] if self.confirmations >= 3 else None


class FacePath:
    """Mantiene el sujeto cercano, filtra el temblor y vuelve al centro si se pierde."""

    def __init__(self, crop_fraction=None):
        self.center = (.5, .5)
        self.subject = None
        self.missing = 0
        self.detected = 0
        self.crop_fraction = crop_fraction

    def update(self, boxes, cut=False, speaker=None):
        if cut:
            self.subject = None
            self.missing = 0
        selected = speaker
        if selected is None and boxes and self.subject is not None:
            selected = min(boxes, key=lambda box: math.dist(box[:2], self.subject))
            if math.dist(selected[:2], self.subject) > .20:
                selected = None
        if selected is None and boxes and (self.subject is None or self.missing >= 4):
            selected = max(boxes, key=lambda box: box[2])
        if selected is not None:
            self.detected += 1
            self.subject = tuple(selected[:2])
            self.missing = 0
            target = self.subject
            if speaker is None and self.crop_fraction and len(boxes) > 1:
                important = [box for box in boxes if box[2] >= max(b[2] for b in boxes)*.35]
                left = min(box[0]-(box[3]/2 if len(box) > 3 else .04) for box in important)
                right = max(box[0]+(box[3]/2 if len(box) > 3 else .04) for box in important)
                if right-left < self.crop_fraction*.84:
                    target = ((left+right)/2, self.subject[1])
            if cut or self.detected == 1:
                self.center = target
            else:
                self.center = tuple(old + max(-.08, min(.08, .55*(new-old))) if abs(new-old) > .018 else old
                                    for old, new in zip(self.center, target))
        else:
            self.missing += 1
            if self.missing > 4:
                self.center = tuple(old + max(-.04, min(.04, .20*(.5-old))) for old in self.center)
        return self.center


def face_commands(folder, source, ranges, size, ffmpeg, run, cancel=None, progress=None, has_audio=True):
    cv, np = vision()
    width, height = size
    ratio = width / height
    sample_w, sample_h = (384, max(96, round(384/ratio/32)*32)) if ratio >= 1 else (
        max(96, round(384*ratio/32)*32), 384)
    detector = cv.FaceDetectorYN.create(str(MODEL), '', (sample_w, sample_h), .72, .3, 100)
    points, offset, total_detections = [], 0, 0
    duration = sum(end-start for start, end in ranges)
    if progress:
        progress.reset('Siguiendo caras y turnos de palabra…', duration)
    for start, end in ranges:
        path = FacePath(min(1, height*9/16/width))
        speakers, voices = SpeakerFocus(), None
        filters = f'fps={SAMPLE_RATE},scale={sample_w}:{sample_h}:flags=fast_bilinear'
        sample_path = folder/'encuadre.bgr'
        run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-threads', '2', '-ss', str(start),
             '-i', str(source), '-t', str(end-start), '-map', '0:V:0', '-an',
             '-vf', filters, '-pix_fmt', 'bgr24', '-threads', '1', '-c:v', 'rawvideo',
             '-f', 'rawvideo', str(sample_path)], cancel=cancel)
        frame_bytes = sample_h*sample_w*3
        frame_count = sample_path.stat().st_size//frame_bytes
        positions, previous = [], None
        with sample_path.open('rb') as frames:
            for i in range(frame_count):
                if cancel is not None and cancel.is_set():
                    raise ValueError('Operación cancelada.')
                data = frames.read(frame_bytes)
                frame = np.frombuffer(data, dtype=np.uint8).reshape(sample_h, sample_w, 3)
                _, rows = detector.detect(frame)
                boxes = [] if rows is None else [((float(x)+float(w)/2)/sample_w,
                                                   (float(y)+float(h)/2)/sample_h, float(w*h)*float(score),
                                                   float(w)/sample_w, float(h)/sample_h)
                                                  for x, y, w, h, *_, score in rows]
                tiny = cv.resize(frame, (24, 16), interpolation=cv.INTER_AREA)
                cut = previous is not None and cv.absdiff(tiny, previous).mean() > 44
                if voices is None and has_audio and len(boxes) >= 2:
                    pcm = run([ffmpeg, '-nostdin', '-v', 'error', '-ss', str(start), '-i', str(source),
                               '-t', str(end-start), '-map', '0:a:0', '-vn', '-ac', '1',
                               '-af', f'highpass=f=150,lowpass=f=3400,aresample={VOICE_RATE}:async=1:first_pts=0',
                               '-f', 's16le', 'pipe:1'], cancel=cancel)
                    voices = voice_activity(pcm, frame_count, np)
                speaker = None
                if voices is not None:
                    patches = [None]*len(boxes)
                    if len(boxes) >= 2:
                        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
                        patches = [mouth_patch(gray, row, cv, np) for row in rows]
                    speaker = speakers.update(i, boxes, patches, float(voices[i]), np, cut)
                positions.append((*path.update(boxes, cut, speaker), cut))
                previous = tiny
                if progress:
                    progress.report(min(1, (offset+i/SAMPLE_RATE)/duration))
        sample_path.unlink()
        if path.detected:
            first = next((position[:2] for position in positions if position[:2] != (.5, .5)), (.5, .5))
            for i in range(min(len(positions), 4)):
                if positions[i][:2] != (.5, .5):
                    break
                positions[i] = (*first, positions[i][2])
        total_detections += path.detected
        points.extend((offset+i/SAMPLE_RATE, x, y, cut or i == 0)
                      for i, (x, y, cut) in enumerate(positions or [(.5, .5, True)]))
        offset += end-start
    if total_detections == 0:
        return False
    # Los comandos contienen solo números; el texto de usuario va en un archivo separado.
    with (folder / 'face-track.txt').open('w', encoding='ascii') as stream:
        for index, (t, x, y, _) in enumerate(points):
            next_t, next_x, next_y, cut = points[min(index+1, len(points)-1)]
            dx, dy = (0, 0) if cut or next_t <= t else ((next_x-x)/(next_t-t), (next_y-y)/(next_t-t))
            stream.write(f"{t:.6f} crop@face x 'iw*({x:.6f}+({dx:.6f})*(t-{t:.6f}))-ow/2', "
                         f"crop@face y 'ih*({y:.6f}+({dy:.6f})*(t-{t:.6f}))-oh/2';\n")
    return True


def followed_panel(width, height):
    return (
        "scale=w='max(2,trunc(iw*sar/2)*2)':h=ih,setsar=1,sendcmd=f=face-track.txt,"
        f"crop@face=w='min(iw,trunc(ih*{width}/{height}/2)*2)':"
        f"h='min(ih,trunc(iw*{height}/{width}/2)*2)':x=(iw-ow)/2:y=(ih-oh)/2,"
        f"scale={width}:{height}:flags=fast_bilinear,setsar=1"
    )
