"""Julio Clip: controlador local, Python 3.8+, sin paquetes pip."""
import argparse
from collections import deque
from contextlib import contextmanager, nullcontext
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
from statistics import median
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from watermark import MAX_CLIP_SECONDS, display_size, export_args, layout_settings, settings as watermark_settings
from reframe import FONT, face_commands, prepare_title, styling, vision
from captions import ass_text, corrected
from library import GUARD as LIBRARY_GUARD, MediaStore
from license_client import LicenseGate
from live import LiveController, capture_input, kick_channel, youtube_runtime_args
from editing import (burn_subtitles_enabled, kept_ranges, retime_cues, srt_text, subtitle_settings,
                     subtitle_render_style, subtitles_enabled, trim_args, visible_cues, whisper_cues)
from runtime_support import default_data_dir, child_options
from public_quota import PublicQuota
from monitor import (DUPLICATE_REASON, VISUAL_HEIGHT, VISUAL_WIDTH, VisualTrack, WorkProgress, audio_energy,
                     choose_moments, clip_title, compact_audio, highlight_profile, rank_moments, rank_sports,
                     repeats_sequence, restore_cue_times, sports_anchors, sports_windows)

ROOT = Path(__file__).resolve().parent
PUBLIC = (ROOT / 'edicion-publica').is_file()
REQUIRES_SUBSCRIPTION = True
LICENSE_CONFIG = ROOT / 'license-client.json'
LICENSE = None
DESKTOP = False
DATA = default_data_dir(public=PUBLIC)
if LICENSE_CONFIG.is_file():
    DATA = DATA.with_name('Julio Clip Suscripcion')
if not PUBLIC or '--smoke' in sys.argv:
    DATA = Path(os.environ.get('JULIO_DATA', str(DATA)))
TOKEN = secrets.token_urlsafe(32)
STATE = {'status': 'Listo', 'busy': False, 'source': None, 'source_platform': None,
         'source_duration': None, 'clips': [], 'suggestions': [], 'edits': {}}
LOCK = threading.Lock()
PREVIEW_LOCK = threading.Lock()
THUMBNAIL_LOCK = threading.Lock()
PUBLISHED_JOB = None
PUBLISHED_ACTIONS = {'youtube', 'analyze', 'export', 'upload'}
LIVE = None
SHUTDOWN = threading.Event()
CLIP_DURATIONS = (20, 30, 40, 50, MAX_CLIP_SECONDS)
YOUTUBE_HOSTS = ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be')
MAX_SOURCE_BYTES = 2 * 1024**3
LICENSE_REQUIRED = 'Activa o renueva tu licencia de Julio Clip para continuar.'


class UnreadableMedia(ValueError):
    pass


class FrozenExport(UnreadableMedia):
    pass


def check_license():
    if LICENSE and not LICENSE.allowed():
        raise ValueError(LICENSE_REQUIRED)


def monitor_license():
    while not SHUTDOWN.wait(5):
        live_running = LIVE and LIVE.snapshot()['running']
        job = PUBLISHED_JOB
        if (live_running or (job and job.status == 'running')) and not LICENSE.allowed():
            if live_running:
                LIVE.stop()
            if job:
                job.request_cancel()


class PublishedJob:
    def __init__(self, action):
        self.id = secrets.token_hex(12)
        self.action = action
        self.progress = WorkProgress()
        self.progress.reset('Preparando la operación…')
        self.cancel = threading.Event()
        self.guard = threading.Lock()
        self.status = 'running'

    def is_set(self):
        return SHUTDOWN.is_set() or self.cancel.is_set()

    def check(self):
        if self.is_set():
            raise ValueError('Operación cancelada.')

    def request_cancel(self):
        with self.guard:
            if self.status != 'running':
                return False
            self.cancel.set()
            self.status = 'cancelling'
            return True

    @contextmanager
    def commit(self):
        with self.guard:
            self.check()
            yield
            self.status = 'complete'

    def end(self, successful):
        with self.guard:
            if self.status != 'complete':
                self.status = 'cancelled' if self.is_set() else 'complete' if successful else 'error'

    def snapshot(self):
        with self.guard:
            return dict(self.progress.snapshot(), id=self.id, action=self.action, status=self.status)

def live_clip_settings(options):
    seconds = options.get('clip_seconds', 30)
    count = options.get('clips_per_block', 2)
    if type(seconds) is not int or seconds not in CLIP_DURATIONS:
        raise ValueError('Elige una duración de 20, 30, 40, 50 o 60 segundos.')
    if type(count) is not int or not 1 <= count <= 10:
        raise ValueError('Elige entre 1 y 10 clips por bloque.')
    return seconds, count

def tool(name):
    local = ROOT / 'bin' / (name + ('.exe' if os.name == 'nt' else ''))
    return str(local) if local.is_file() else shutil.which(name)

def requirements():
    result = {}
    for name in ('ffmpeg', 'ffprobe', 'whisper-cli', 'yt-dlp'):
        exe = tool(name)
        try:
            p = subprocess.run([exe, '--version' if name == 'yt-dlp' else ('--help' if name == 'whisper-cli' else '-version')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, **child_options()) if exe else None
            result[name] = bool(p and p.returncode == 0)
        except (OSError, subprocess.TimeoutExpired):
            result[name] = False
    result['modelo'] = (ROOT / 'models/ggml-base.bin').is_file()
    result['logo'] = (ROOT / 'web/logo-julio.jpg').is_file()
    runtime = tool('qjs') or tool('node')
    try:
        p = subprocess.run([runtime, '-e', 'console.log(1+1)'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, **child_options()) if runtime else None
        result['runtime-youtube'] = bool(p and p.returncode == 0 and p.stdout.strip() == b'2')
    except (OSError, subprocess.TimeoutExpired):
        result['runtime-youtube'] = False
    return result

def run(args, timeout=14400, cancel=None, on_line=None, stall_timeout=None, cwd=None):
    if cancel is None:
        cancel = SHUTDOWN
    if not args[0]:
        raise ValueError('Falta una herramienta. Consulta el diagnóstico y el tutorial.')
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=cwd, **child_options())
    deadline = time.monotonic() + timeout
    readers = []
    output = deque(maxlen=128)
    errors = deque(maxlen=24)
    last_progress = time.monotonic()
    if on_line:
        def read_lines(pipe, save):
            nonlocal last_progress
            with pipe:
                for line in pipe:
                    if save:
                        output.append(line)
                    else:
                        errors.append(line)
                    if on_line(line):
                        last_progress = time.monotonic()

        for pipe, save in ((proc.stdout, True), (proc.stderr, False)):
            reader = threading.Thread(target=read_lines, args=(pipe, save), daemon=True)
            readers.append(reader)
            reader.start()
    try:
        while True:
            if (cancel and cancel.is_set()) or time.monotonic() >= deadline:
                raise ValueError('Tarea detenida o tiempo de ejecución agotado.')
            if readers:
                if proc.poll() is not None:
                    break
                if stall_timeout and time.monotonic()-last_progress >= stall_timeout:
                    raise ValueError('Whisper no informó avances durante 4 minutos. Puedes reintentar con el modo rápido.')
                time.sleep(.2)
                continue
            try:
                stdout, stderr = proc.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                (proc.wait if readers else proc.communicate)(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                (proc.wait if readers else proc.communicate)()
        for reader in readers:
            reader.join(timeout=3)
    if proc.returncode:
        if proc.returncode in (-1073741795, 3221225501, -4):
            raise ValueError('La herramienta terminó con una instrucción no válida. Revisa su compilación y la compatibilidad con la CPU de este equipo.')
        if Path(args[0]).stem.lower() in ('ffmpeg', 'ffprobe'):
            detail = (b''.join(errors) if readers else stderr).lower()
            if any(pattern in detail for pattern in (b'invalid data found when processing input',
                   b'ebml header parsing failed', b'moov atom not found', b'could not find codec parameters')):
                raise UnreadableMedia('No se pudo leer el video de este fragmento.')
        # No devolver rutas, cookies ni registros de terceros al navegador.
        raise ValueError('La herramienta falló. Comprueba compatibilidad, formato, espacio y permisos del video.')
    return b''.join(output) if readers else stdout

def inspect_media(path, cancel=None):
    return json.loads(run([tool('ffprobe'), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], cancel=cancel))

def extract_audio(source, audio, cancel=None, progress=None, duration=None):
    extraction = [tool('ffmpeg'), '-nostdin', '-y', '-i', str(source), '-vn',
                  '-af', 'aresample=16000:async=1:first_pts=0', '-ar', '16000',
                  '-ac', '1', '-c:a', 'pcm_s16le', str(audio)]
    if progress and duration:
        run_encoding(extraction, progress, 'Preparando el audio…', duration, cancel)
    else:
        run(extraction, cancel=cancel)


def transcribe(source, audio, transcript, cancel=None, progress=None, duration=None, fast=False):
    extract_audio(source, audio, cancel, progress, duration)
    return whisper_audio(audio, transcript, cancel, progress, duration, fast)


def whisper_audio(audio, transcript, cancel=None, progress=None, duration=None, fast=False):
    model = ROOT / 'models/ggml-base.bin'
    if not model.is_file():
        raise ValueError('Falta el modelo local ggml-base.bin. Consulta el tutorial.')
    command = [tool('whisper-cli'), '-m', str(model), '-f', str(audio), '-l', 'auto', '-ng', '-t', '2',
               '-ojf', '-ml', '64', '-sow', '-mc', '0', '-of', str(transcript.with_suffix(''))]
    if fast:
        command += ['-bs', '1', '-bo', '1']
    if progress:
        progress.reset('Convirtiendo el audio en texto…', duration)
        last = -1
        def whisper_line(line):
            nonlocal last
            match = re.search(rb'progress\s*=\s*(\d+)\s*%', line)
            if match:
                percent = min(100, int(match[1]))
                if percent > last:
                    last = percent
                    progress.report(percent / 100)
                    return True
            return False
        run(command + ['-pp'], cancel=cancel, on_line=whisper_line, stall_timeout=240)
    else:
        run(command, cancel=cancel)
    return json.loads(transcript.read_text(encoding='utf-8'))


def scan_video(source, duration, cancel):
    rate = min(3, 1800/duration)
    filters = f'setpts=PTS-STARTPTS,fps={rate:.9f},scale={VISUAL_WIDTH}:{VISUAL_HEIGHT}:flags=fast_bilinear'
    raw = run([tool('ffmpeg'), '-nostdin', '-v', 'error', '-threads', '2', '-i', str(source),
               '-map', '0:v:0', '-an', '-vf', filters, '-pix_fmt', 'rgb24', '-threads', '1',
               '-c:v', 'rawvideo', '-f', 'rawvideo', 'pipe:1'], cancel=cancel)
    if not raw:
        raise UnreadableMedia('El fragmento llegó sin imágenes decodificables.')
    return VisualTrack(raw, rate, duration)


def review_highlights(source, probe, seconds, limit, profile, folder, cancel,
                      progress=None, stage=None, fast=False, gaps=(), previous=()):
    duration = float(probe['format']['duration'])
    if duration < 3:
        return [], [dict(start=0, end=duration, reason='El fragmento es demasiado corto.')], None

    def report(label, status='searching'):
        if progress:
            progress.reset(label)
        if stage:
            stage(status)

    report('Comprobando imagen, congelamientos y movimiento…')
    visual = scan_video(source, duration, cancel)
    if any(start <= .34 and end >= duration-max(.34, 1/visual.rate) for start, end in visual.black):
        return [], [dict(start=0, end=duration, reason='El fragmento se queda en negro.')], None
    if any(start <= .34 and end >= duration-max(.34, 1/visual.rate) for start, end in visual.frozen):
        return [], [dict(start=0, end=duration, reason='La imagen se queda congelada durante el fragmento.')], None
    sports = profile == 'sports' or (profile == 'auto' and visual.sports_scene())
    audio, transcript = folder/'audio.wav', folder/'transcript.json'
    cues, energy = [], []
    if any(stream['codec_type'] == 'audio' for stream in probe['streams']):
        extract_audio(source, audio, cancel, progress, duration)
        energy = audio_energy(audio)
    if profile == 'sports':
        anchors = sports_anchors(visual, energy, duration, limit)
        if anchors and energy:
            compact = folder/'jugadas.wav'
            mapping = compact_audio(audio, compact, sports_windows(anchors, duration))
            if mapping:
                report('Transcribiendo alrededor de las posibles jugadas…', 'transcribing')
                result = whisper_audio(compact, transcript, cancel, progress, mapping[-1][1], True)
                cues = list(restore_cue_times(whisper_cues(result), mapping))
        report('Comparando la acción en el campo con el audio y la narración…')
        picks, rejects = rank_sports(cues, duration, seconds, limit, gaps, visual, anchors, previous)
        return picks, rejects, None
    if energy:
        report('Convirtiendo el audio en texto…', 'transcribing')
        result = whisper_audio(audio, transcript, cancel, progress, duration, fast)
        cues = list(whisper_cues(result))
    report('Comparando imagen, conversación, contexto y reacciones…')
    candidates = limit*2 if sports else limit
    picks, rejects = rank_moments(cues, duration, seconds, candidates, gaps, energy, visual, previous)
    if sports:
        anchors = sports_anchors(visual, energy, duration, limit)
        plays, rejected_plays = rank_sports(cues, duration, seconds, candidates, gaps, visual, anchors, previous)
        picks, rejects = choose_moments(picks+plays, rejects+rejected_plays, limit, count_variants=False)
    return picks, rejects, cues

def run_encoding(args, progress, label, duration, cancel, cwd=None):
    progress.reset(label, duration)
    def line_callback(line):
        key, _, value = line.strip().partition(b'=')
        if key == b'out_time_us':
            try:
                progress.report(max(0, min(1, int(value)/(duration*1_000_000))))
            except ValueError:
                pass
    return run(args[:1] + ['-progress', 'pipe:1', '-nostats'] + args[1:],
               cancel=cancel, on_line=line_callback, cwd=cwd)


def transcribe_clip(source, folder, duration, job=None, *, cancel=None, progress=None, fast=False):
    cancel = job if job is not None else cancel
    if not any(s['codec_type'] == 'audio' for s in inspect_media(source, cancel)['streams']):
        return []
    transcription = transcribe(source, folder/'voz.wav', folder/'voz.json', cancel,
                               progress=job.progress if job else progress, duration=duration, fast=fast)
    return retime_cues(list(whisper_cues(transcription)), [(0, duration)])

def publish_clip(store, name, metadata, render, captions=None, cancel=None, job=None,
                 composition=None, progress=None, burn_subtitles=False, subtitle_style=None,
                 verify_motion=False):
    store.check_space()
    with tempfile.TemporaryDirectory(prefix='exportando-', dir=store.root) as work:
        folder = Path(work)
        rendered = folder / 'video.mp4'
        cwd = None
        if composition:
            source, probe, ranges, follow_face, title = composition
            track = follow_face and face_commands(
                folder, source, ranges, display_size(probe), tool('ffmpeg'), run, cancel,
                job.progress if job else progress,
                has_audio=any(stream['codec_type'] == 'audio' for stream in probe['streams']))
            if follow_face:
                metadata.update(face_requested=True, follow_face=track)
            if title:
                metadata['overlay_title'] = title
            args = render(rendered, track=track, title=prepare_title(folder, title) if title else None)
            cwd = folder
        else:
            args = render(rendered)
        if job:
            run_encoding(args, job.progress, 'Exportando el clip…', metadata['end']-metadata['start'], cancel, cwd)
        else:
            if progress:
                progress.reset('Codificando el MP4…')
            run(args, cancel=cancel, cwd=cwd)
        duration = metadata['end']-metadata['start']
        if verify_motion:
            try:
                frozen = scan_video(rendered, duration, cancel).frozen_screen(0, duration)
            except UnreadableMedia as error:
                raise FrozenExport('El video exportado no se pudo reproducir.') from error
            if frozen:
                raise FrozenExport('El video exportado se queda congelado dentro del clip.')
        cues = visible_cues(captions(rendered, folder), duration) if captions else []
        if captions and not cues and not metadata.get('burned_subtitles') and not metadata.get('captions_edited'):
            metadata['no_caption_speech'] = True
        if cues and not metadata.get('burned_subtitles'):
            if job:
                job.progress.reset('Añadiendo los subtítulos…')
            srt = folder / 'subtitulos.srt'
            srt.write_text(srt_text(cues), encoding='utf-8')
            subtitled = folder / 'video-subtitulado.mp4'
            store.check_space(rendered.stat().st_size)
            args = [tool('ffmpeg'), '-nostdin', '-y', '-i', str(rendered)]
            if burn_subtitles:
                fonts = folder / 'fonts'
                fonts.mkdir()
                shutil.copyfile(FONT, fonts / 'BarlowCondensed-Bold.ttf')
                caption_style = subtitle_settings({'subtitle_style': subtitle_style or {}})
                (folder/'subtitulos.ass').write_text(ass_text(cues, caption_style,
                    *display_size(inspect_media(rendered, cancel))), encoding='utf-8')
                args += ['-map', '0:v:0', '-map', '0:a:0?', '-vf',
                         'ass=subtitulos.ass:fontsdir=fonts',
                         '-c:v', 'libx264', '-crf', '18', '-preset', 'fast', '-pix_fmt', 'yuv420p', '-c:a', 'copy']
                metadata['burned_subtitles'] = True
                metadata['subtitle_style'] = caption_style
                clean = folder/'video-limpio.mp4'
                shutil.copyfile(rendered, clean)
            else:
                args += ['-i', str(srt), '-map', '0:v:0', '-map', '0:a:0?', '-map', '1:s:0',
                         '-c:v', 'copy', '-c:a', 'copy', '-c:s', 'mov_text', '-disposition:s:0', 'default']
            run(args + ['-movflags', '+faststart', str(subtitled)], cancel=cancel, cwd=folder if burn_subtitles else None)
            rendered = subtitled
        thumb = folder / 'miniatura.jpg'
        if job:
            job.progress.reset('Creando la miniatura…')
        try:
            position = max(0, min(4, (metadata['end']-metadata['start'])*.3))
            run([tool('ffmpeg'), '-nostdin', '-y', '-ss', str(position), '-i', str(rendered),
                 '-map', '0:v:0', '-frames:v', '1', '-vf', 'scale=480:-2', '-q:v', '5', str(thumb)],
                timeout=30, cancel=cancel)
        except ValueError:
            if cancel and cancel.is_set():
                raise
        with job.commit() if job else nullcontext():
            if cancel and cancel.is_set():
                raise ValueError('Operación cancelada.')
            check_license()
            if (folder/'video-limpio.mp4').is_file():
                (folder/'video-limpio.mp4').replace(store.caption_base(name))
                metadata['editable_captions'] = True
            rendered.replace(store.path(name))
            if thumb.is_file() and thumb.stat().st_size:
                thumb.replace(store.thumbnail(name))
            store.add(dict(metadata, name=name, subtitles=bool(cues), captions=cues,
                           thumbnail=store.thumbnail(name).is_file(), created=int(time.time())))

def edit_result(request_id, **result):
    edits = dict(STATE.get('edits', {}), **{request_id: result})
    STATE['edits'] = dict(list(edits.items())[-16:])


def ensure_thumbnail(store, name):
    """Recupera miniaturas ausentes sin bloquear la captura ni la papelera."""
    destination = store.thumbnail(name)
    if destination.is_file():
        return destination
    if not THUMBNAIL_LOCK.acquire(timeout=15):
        raise ValueError('La miniatura se está preparando.')
    try:
        clip = store.active_clip(name)
        if destination.is_file():
            return destination
        position = max(0, min(4, (clip['end']-clip['start'])*.3))
        with tempfile.TemporaryDirectory(prefix='miniatura-', dir=store.root) as work:
            temporary = Path(work)/'miniatura.jpg'
            run([tool('ffmpeg'), '-nostdin', '-y', '-threads', '1', '-ss', str(position),
                 '-i', str(store.path(name)), '-map', '0:v:0', '-frames:v', '1',
                 '-vf', 'scale=480:-2', '-q:v', '5', '-threads', '1', str(temporary)], timeout=20)
            with LIBRARY_GUARD:
                store.active_clip(name)
                temporary.replace(destination)
        return destination
    finally:
        THUMBNAIL_LOCK.release()

def live_gaps(path, probe, stop):
    raw = run([tool('ffprobe'), '-v', 'error', '-select_streams', 'v:0',
               '-show_entries', 'packet=pts_time', '-of', 'csv=p=0', str(path)], cancel=stop)
    timestamps = sorted(float(line) for line in raw.splitlines()
                        if re.fullmatch(rb'-?[0-9]+(?:\.[0-9]+)?', line))
    pairs = list(zip(timestamps, timestamps[1:]))
    distances = [end-start for start, end in pairs if end > start]
    if not distances:
        return []
    interval = median(distances)
    origin = float(probe['format'].get('start_time', 0))
    return [(start+interval-origin, end-origin) for start, end in pairs
            if end-start > max(.5, interval*6)]

def consume_live(path, options, stop):
    monitor = live().monitor
    monitor.stage('waiting')
    plan = path.with_suffix('.plan')
    duration = 0
    analyzed = False
    try:
        if stop.is_set():
            return
        store = MediaStore(DATA)
        store.check_space()
        probe = inspect_media(path, stop)
        format_name, split = ('original', None) if PUBLIC else layout_settings(
            options, allow_split=options.get('platform') == 'Kick')
        follow, title = (False, None) if PUBLIC else styling(options, format_name, split)
        burn = not PUBLIC and burn_subtitles_enabled(options)
        caption_style = subtitle_settings(options) if burn else None
        if not any(stream['codec_type'] == 'video' for stream in probe.get('streams', [])):
            raise UnreadableMedia('El fragmento llegó sin pista de video.')
        try:
            duration = float(probe['format']['duration'])
        except (KeyError, TypeError, ValueError):
            raise UnreadableMedia('El fragmento llegó sin tiempos de video válidos.') from None
        if not math.isfinite(duration) or duration <= 0:
            raise UnreadableMedia('El fragmento llegó sin tiempos de video válidos.')
        gaps = live_gaps(path, probe, stop)
        relative = path.relative_to(DATA)
        capture_key = None
        if len(relative.parts) >= 4 and relative.parts[0] == 'live':
            capture_key = options.get('capture_key') or relative.parts[1]
        previous = [clip['signature'] for clip in store.load()['clips']
                    if capture_key and clip.get('capture_key') == capture_key and clip.get('signature')][-20:]
        cues = None
        rejects = []
        # Un reintento conserva el orden de un bloque que pudo haber exportado parte de sus clips.
        if not PUBLIC and plan.is_file():
            saved = json.loads(plan.read_text(encoding='utf-8'))
            picks, rejects = saved['picks'], saved['rejects']
        else:
            with tempfile.TemporaryDirectory(prefix='analizando-', dir=path.parent) as work:
                folder = Path(work)
                if PUBLIC:
                    monitor.stage('transcribing')
                    transcription = transcribe(path, folder/'audio.wav', folder/'transcript.json', stop,
                                               progress=monitor.analysis, duration=duration,
                                               fast=options.get('fast_mode', False))
                    monitor.stage('searching')
                    picks = propose(transcription, duration=duration, seconds=30, limit=2, gaps=gaps)
                else:
                    seconds, count = live_clip_settings(options)
                    picks, rejects, cues = review_highlights(
                        path, probe, seconds, count, options.get('profile', 'auto'), folder, stop,
                        monitor.analysis, monitor.stage, options.get('fast_mode', False), gaps, previous)
            if not PUBLIC:
                temporary = plan.with_suffix('.plan.tmp')
                temporary.write_text(json.dumps(dict(picks=picks, rejects=rejects)), encoding='utf-8')
                temporary.replace(plan)
        monitor.reviewed(picks, rejects)
        analyzed = True
        enabled, opacity = watermark_settings(options)
        quota = PublicQuota(DATA) if PUBLIC and picks else None
        for i, pick in enumerate(picks):
            if stop.is_set():
                return
            start, end = pick['start'], min(duration, pick['end'])
            if end-start < 3:
                monitor.completed()
                continue
            # Identificador estable: evita duplicar clips si se reintenta un bloque.
            import hashlib
            key = str(relative) + ':' + str(i)
            name = 'clip-' + hashlib.sha256(key.encode()).hexdigest()[:12] + '.mp4'
            if any(c['name'] == name for c in store.load()['clips']):
                monitor.completed()
                continue
            signature = pick.get('signature', [])
            if signature and any(repeats_sequence(signature, seen) for seen in previous):
                monitor.completed(rejection=dict(start=start, end=end, reason=DUPLICATE_REASON))
                continue
            monitor.exporting(i+1)
            marked = quota.reserve(name, enabled) if quota else enabled
            captions = None
            if not PUBLIC and subtitles_enabled(options):
                if cues is None or any(cue['start'] < start < cue['end'] or cue['start'] < end < cue['end']
                                       for cue in cues):
                    captions = lambda output, folder: transcribe_clip(output, folder, end-start, cancel=stop, fast=True)
                else:
                    captions = lambda _output, _folder: retime_cues(cues, [(start, end)])
            try:
                composition = (path, probe, [(start, end)], follow, title) if follow or title else None
                publish_clip(store, name, {'start': start, 'end': end, 'watermark': marked, 'automatic': True,
                                           'title': pick.get('title') or clip_title(pick.get('text', '')),
                                           'interest': pick.get('score') if 'title' in pick else None,
                                           'format': format_name, 'split': bool(split),
                                           'capture_key': capture_key, 'signature': signature},
                             lambda output, **style: export_args(tool('ffmpeg'), path, output, start, end, probe,
                                                        ROOT / 'web/logo-julio.jpg', marked, opacity,
                                                        max_duration=30 if PUBLIC else MAX_CLIP_SECONDS,
                                                        format_name=format_name, split=split, **style),
                             captions, stop, composition=composition, progress=monitor.analysis if composition else None,
                             burn_subtitles=burn, subtitle_style=caption_style, verify_motion=not PUBLIC)
            except FrozenExport as error:
                monitor.completed(rejection=dict(start=start, end=end, reason=str(error)))
                continue
            except Exception:
                if quota and not store.path(name).exists():
                    quota.release(name)
                raise
            monitor.completed(dict(name=name, title=pick.get('title') or clip_title(pick.get('text', ''))))
            if signature:
                previous.append(signature)
        if plan.is_file():
            plan.unlink()
    except UnreadableMedia as e:
        if analyzed:
            raise
        monitor.reviewed([], [dict(start=0, end=duration, reason=str(e))])
        plan.unlink(missing_ok=True)
    finally:
        for suffix in ('.wav', '.json', '.plan.tmp'):
            path.with_suffix(suffix).unlink(missing_ok=True)

def live():
    global LIVE
    if LIVE is None or LIVE.root != DATA:
        LIVE = LiveController(DATA, tool, consume_live)
    return LIVE

def https_url(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('Introduce un enlace HTTPS válido.')
    p = urlparse(value)
    if p.scheme != 'https' or p.username is not None or p.password is not None or p.port is not None:
        raise ValueError('Introduce un enlace HTTPS válido.')
    return p

def youtube_url(value):
    if https_url(value).hostname not in YOUTUBE_HOSTS:
        raise ValueError('Utiliza una dirección HTTPS de YouTube o youtu.be.')
    return value

def start_live(payload):
    url = payload['url']
    is_kick = not PUBLIC and https_url(url).hostname in ('kick.com', 'www.kick.com')
    url = kick_channel(url) if is_kick else youtube_url(url)
    watermark_settings(payload)
    payload = dict(payload)
    payload.pop('platform', None)
    if PUBLIC:
        payload = dict(payload, clip_seconds=30, clips_per_block=2, subtitles=False)
        payload.pop('format', None)
        payload.pop('split', None)
        payload.pop('profile', None)
        payload.pop('follow_face', None)
        payload.pop('overlay_title', None)
        payload.pop('burn_subtitles', None)
        if PublicQuota(DATA).status()['clips'] <= 0:
            raise ValueError('Ya usaste los dos clips de las últimas 24 horas.')
    else:
        subtitles_enabled(payload)
        burn_subtitles_enabled(payload)
        subtitle_settings(payload)
        if 'profile' in payload:
            highlight_profile(payload['profile'])
        payload['clip_seconds'], payload['clips_per_block'] = live_clip_settings(payload)
        format_name, split = layout_settings(payload, allow_split=is_kick)
        styling(payload, format_name, split)
        if is_kick:
            payload['platform'] = 'Kick'
    if not (ROOT / 'models/ggml-base.bin').is_file():
        raise ValueError('Falta el modelo de IA. La captura automática necesita las dependencias completas.')
    live().start(url, payload)


def kick_preview(url):
    url = kick_channel(https_url(url).geturl())
    if not tool('yt-dlp') or not tool('ffmpeg'):
        raise ValueError('La vista previa necesita yt-dlp y FFmpeg.')
    if not PREVIEW_LOCK.acquire(False):
        raise ValueError('Ya se está preparando una vista previa de Kick.')
    try:
        capture = LiveController(DATA, tool, consume_live)
        media = capture._resolve(url, timeout=30)[0]
        frame = run([tool('ffmpeg'), '-nostdin', *capture_input(media, kick=True),
                     '-map', '0:v:0', '-frames:v', '1', '-vf', 'scale=960:-2',
                     '-f', 'image2pipe', '-c:v', 'mjpeg', 'pipe:1'], timeout=25)
        if not frame.startswith(b'\xff\xd8'):
            raise ValueError('No se pudo obtener un fotograma del directo de Kick.')
        return frame
    except OSError as error:
        raise ValueError('No se pudo abrir la vista previa de Kick.') from error
    finally:
        PREVIEW_LOCK.release()

def published_platform(value):
    p = https_url(value)
    path = p.path.rstrip('/')
    if p.hostname == 'youtu.be':
        if re.fullmatch(r'/[A-Za-z0-9_-]+', path):
            return 'YouTube'
    elif p.hostname in YOUTUBE_HOSTS:
        if (path == '/watch' and re.fullmatch(r'[A-Za-z0-9_-]+', parse_qs(p.query).get('v', [''])[0])
                or re.fullmatch(r'/(?:shorts|live|embed|v|clip)/[A-Za-z0-9_-]+', path)):
            return 'YouTube'
    elif p.hostname in ('tiktok.com', 'www.tiktok.com'):
        if re.fullmatch(r'/@[\w.-]+/video/[0-9]+|/t/[A-Za-z0-9_-]+', path):
            return 'TikTok'
    elif p.hostname in ('vm.tiktok.com', 'vt.tiktok.com'):
        if re.fullmatch(r'/[A-Za-z0-9_-]+', path):
            return 'TikTok'
    raise ValueError('Pega el enlace HTTPS de un video publicado individual de YouTube o TikTok.')

def import_published(url, job=None):
    platform = published_platform(url)
    runtime = youtube_runtime_args(tool) if platform == 'YouTube' else []
    if platform == 'YouTube' and not runtime:
        raise ValueError('Falta el runtime JavaScript para YouTube. Ejecuta Comprobar-Equipo.cmd.')
    extractors = r'youtube$,youtube:clip$' if platform == 'YouTube' else r'TikTok$,vm\.tiktok$'
    STATE['status'] = f'Importando video de {platform}…'
    MediaStore(DATA).check_space(MAX_SOURCE_BYTES)
    with tempfile.TemporaryDirectory(prefix='importando-', dir=DATA) as work:
        folder = Path(work)
        command = [tool('yt-dlp'), '--ignore-config', '--no-plugin-dirs', '--use-extractors', extractors,
                   '--no-playlist', '--max-filesize', '2G', '--match-filters',
                   'live_status!=?is_live & live_status!=?is_upcoming',
                   '-f', 'best[ext=mp4]/best', '-o', str(folder/'source.%(ext)s')]
        try:
            if job:
                job.progress.reset(f'Descargando video de {platform}…')
                def download_line(line):
                    if line.startswith(b'JULIO '):
                        try:
                            update = json.loads(line[6:])
                            size = update.get('total_bytes') or update.get('total_bytes_estimate')
                            received = update.get('downloaded_bytes')
                            fraction = min(1, received/size) if size and received is not None else None
                            job.progress.report(fraction, update.get('eta'))
                        except (ValueError, TypeError, AttributeError):
                            pass
                command += ['--newline', '--progress', '--progress-delta', '1',
                            '--progress-template', 'download:JULIO %(progress)j']
                run(command + runtime + ['--', url], cancel=job, on_line=download_line)
                job.progress.reset('Verificando el video descargado…')
            else:
                run(command + runtime + ['--', url])
        except ValueError as error:
            raise ValueError(f'No se pudo importar el video de {platform}. Comprueba que sea accesible o usa un archivo del equipo.') from error
        files = [p for p in folder.iterdir() if p.is_file() and re.fullmatch(r'source\.(?!part$|ytdl$)[a-zA-Z0-9]+', p.name)]
        if len(files) != 1:
            raise ValueError('No se descargó un video publicado. Revisa que haya terminado de emitirse y que pese hasta 2 GB.')
        source = files[0]
        if not 0 < source.stat().st_size <= MAX_SOURCE_BYTES:
            raise ValueError('El video debe pesar hasta 2 GB.')
        probe = inspect_media(source, job)
        if not any(track['codec_type'] == 'video' and not track.get('disposition', {}).get('attached_pic')
                   for track in probe['streams']):
            raise ValueError('La publicación no contiene una pista de video.')
        duration = float(probe['format']['duration'])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('No se pudo determinar la duración del video.')
        destination = DATA / 'imported.video'
        with job.commit() if job else nullcontext():
            source.replace(destination)
            STATE.update(source=str(destination), source_platform=platform, source_duration=duration,
                         suggestions=[], status=f'Video de {platform} listo para recortar.')

def bounds(start, end):
    start, end = float(start), float(end)
    if not all(math.isfinite(x) for x in (start, end)) or start < 0 or end <= start or end-start > MAX_CLIP_SECONDS + 1e-9:
        raise ValueError('El final debe estar después del inicio. Usa un inicio no negativo y un clip de hasta 60 segundos.')
    return start, end

def propose(transcription, *, duration=None, seconds=None, limit=6, gaps=()):
    """Selección por palabras clave; no predice viralidad."""
    segments = transcription.get('transcription', [])
    candidates = []
    for s in segments:
        start = s.get('offsets', {}).get('from', 0) / 1000
        end = s.get('offsets', {}).get('to', 0) / 1000
        text = s.get('text', '').strip()
        if not text or end <= start:
            continue
        clip_start = max(0, start-2)
        if seconds is None:
            clip_end = min(end+20, start+MAX_CLIP_SECONDS)
            if duration is not None:
                clip_end = min(clip_end, duration)
                if clip_end <= clip_start:
                    continue
        else:
            if duration < seconds or start >= duration:
                continue
            clip_start = min(clip_start, duration-seconds)
            clip_end = clip_start+seconds
        if any(clip_start < right and clip_end > left for left, right in gaps):
            continue
        normalized = text.lower()
        score = sum(normalized.count(w) for w in ('importante', 'secreto', 'increíble', 'cómo', 'por qué', '?', '!'))
        candidates.append({'start': clip_start, 'end': clip_end, 'text': text, 'score': score})
    chosen = []
    for c in sorted(candidates, key=lambda c: c['score'], reverse=True):
        if all(c['end'] <= x['start'] or c['start'] >= x['end'] for x in chosen):
            chosen.append(c)
        if len(chosen) == limit:
            break
    if seconds is not None:
        return chosen
    # Conserva la selección previa al reintentar bloques, aplicando el nuevo límite al exportar.
    for clip in chosen:
        clip['end'] = min(clip['end'], clip['start']+MAX_CLIP_SECONDS)
    return sorted(chosen, key=lambda c: c['start'])

def process(action, payload, job=None):
    successful = False
    try:
        if PUBLIC:
            raise ValueError('La edición pública crea clips de directos de YouTube.')
        if action == 'youtube':
            import_published(payload['url'], job)
            successful = True
            return
        elif action == 'analyze':
            source = STATE['source']
            if not source:
                raise ValueError('Primero importa un video.')
            profile = highlight_profile(payload.get('profile', 'auto'))
            probe = inspect_media(source, job)
            duration = float(probe['format']['duration'])
            STATE['source_duration'] = duration
            STATE['status'] = 'Revisando momentos…'
            with tempfile.TemporaryDirectory(prefix='analizando-', dir=DATA) as work:
                folder = Path(work)
                picks, _, _ = review_highlights(source, probe, 30, 6, profile, folder, job,
                                               progress=job.progress if job else None)
            suggestions = [dict(start=pick['start'], end=pick['end'], score=pick['score'], title=pick['title'],
                                text=pick['title']) for pick in picks]
            with job.commit() if job else nullcontext():
                STATE['suggestions'] = suggestions
        elif action == 'export':
            source = STATE['source']
            if not source:
                raise ValueError('Primero importa un video.')
            start, end = bounds(payload['start'], payload['end'])
            enabled, opacity = watermark_settings(payload)
            format_name, _ = layout_settings(payload)
            follow, title = styling(payload, format_name)
            probe = inspect_media(source, job)
            if end > float(probe['format']['duration']):
                raise ValueError('El final supera la duración del video.')
            name = 'clip-' + secrets.token_hex(6) + '.mp4'
            STATE['status'] = 'Exportando clip…'
            captions = None
            if subtitles_enabled(payload):
                captions = lambda output, folder: transcribe_clip(output, folder, end-start, job)
            composition = (source, probe, [(start, end)], follow, title) if follow or title else None
            publish_clip(MediaStore(DATA), name, {'start': start, 'end': end, 'watermark': enabled,
                                                  'automatic': False, 'format': format_name,
                                                  'title': title['text'] if title else None},
                         lambda output, **style: export_args(tool('ffmpeg'), source, output, start, end, probe,
                                                    ROOT / 'web/logo-julio.jpg', enabled, opacity,
                                                    format_name=format_name, **style), captions,
                         cancel=job, job=job, composition=composition, burn_subtitles=burn_subtitles_enabled(payload),
                         subtitle_style=subtitle_settings(payload))
        elif action == 'edit':
            store = MediaStore(DATA)
            original = store.active_clip(payload['name'])
            clean_base = store.caption_base(original['name'])
            has_clean_base = original.get('editable_captions') and clean_base.is_file()
            source = clean_base if has_clean_base else store.path(original['name'])
            probe = inspect_media(source)
            format_name, _ = layout_settings(payload)
            follow, title = styling(payload, format_name)
            ranges = kept_ranges(payload, float(probe['format']['duration']))
            duration = sum(end-start for start, end in ranges)
            captions = None
            if subtitles_enabled(payload) or (original.get('burned_subtitles') and not has_clean_base):
                if original.get('captions'):
                    revised = corrected(original['captions'], payload.get('caption_edits'))
                    captions = lambda _output, _folder: retime_cues(revised, ranges)
                elif not original.get('burned_subtitles'):
                    captions = lambda output, folder: transcribe_clip(output, folder, duration)
            name = 'clip-' + secrets.token_hex(6) + '.mp4'
            STATE['status'] = 'Guardando copia editada…'
            composition = (source, probe, ranges, follow, title) if follow or title else None
            publish_clip(store, name, {'start': 0, 'end': duration, 'watermark': original.get('watermark', False),
                                       'automatic': False, 'edited': True,
                                       'captions_edited': payload.get('caption_edits') is not None,
                                       'format': original.get('format', 'original') if format_name == 'original' else format_name,
                                       'burned_subtitles': bool(original.get('burned_subtitles') and not has_clean_base),
                                       'title': title['text'] if title else original.get('title')},
                         lambda output, **style: trim_args(tool('ffmpeg'), source, output, probe, ranges,
                                                          format_name=format_name, **style),
                         captions, composition=composition,
                         burn_subtitles=burn_subtitles_enabled(payload) and (has_clean_base or not original.get('burned_subtitles')),
                         subtitle_style=subtitle_settings(payload))
            edit_result(payload['id'], name=name)
        elif action in ('trash', 'restore'):
            MediaStore(DATA).move(payload['name'], action == 'trash')
        elif action == 'empty-trash':
            MediaStore(DATA).empty_trash(payload.get('confirmed'))
        elif action == 'storage':
            MediaStore(DATA).configure(payload['quota_gb'], payload['max_clips'])
        elif action == 'clear-source':
            # Solo elimina archivos temporales generados/importados por esta app.
            for p in DATA.iterdir():
                if p.is_file() and (p.name == 'imported.video' or p.name.startswith('source.') or p.name in ('audio.wav', 'transcript.json')):
                    p.unlink()
            STATE.update(source=None, source_platform=None, source_duration=None, suggestions=[])
        elif action == 'clear-queue':
            if live().snapshot()['running'] or payload.get('confirmed') is not True:
                raise ValueError('Detén la captura y confirma antes de descartar los bloques pendientes.')
            queue = DATA / 'live'
            if queue.is_dir() and queue.resolve().parent == DATA.resolve():
                shutil.rmtree(queue)
        elif action == 'prepare-mac':
            STATE['status'] = 'Preparando herramientas para Mac…'
            log_path = DATA / 'preparacion-mac.log'
            with log_path.open('w', encoding='utf-8') as log:
                preparation = subprocess.Popen([sys.executable, '-I', str(ROOT/'prepare_mac.py')],
                                               stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                try:
                    while preparation.poll() is None:
                        if SHUTDOWN.wait(0.4):
                            raise ValueError('Preparación detenida.')
                finally:
                    if preparation.poll() is None:
                        preparation.terminate()
                        preparation.wait(timeout=10)
            if preparation.returncode:
                raise ValueError('No se completó la preparación. Consulta ' + str(log_path))
            STATE['status'] = 'Herramientas preparadas. Pulsa Volver a comprobar herramientas.'
            return
        STATE['status'] = 'Operación terminada'
        successful = True
    except Exception as e:
        if job and job.is_set():
            STATE['status'] = 'Operación cancelada.'
        else:
            STATE['status'] = 'Error: ' + (str(e) if isinstance(e, ValueError) else 'No se pudo completar la operación; revisa el tutorial.')
        if action == 'edit':
            edit_result(payload['id'], error=STATE['status'])
    finally:
        if job:
            job.end(successful)
        STATE['busy'] = False
        LOCK.release()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, mime='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-src https://www.youtube.com; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get('Host') == '127.0.0.1:' + str(self.server.server_port)

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {'error': 'Host no permitido'})
        path = urlparse(self.path).path
        if path == '/api/state':
            try:
                state = dict(STATE, source=bool(STATE['source']))
                state.update(MediaStore(DATA).view())
                state['live'] = live().snapshot()
                state['capabilities'] = {'kick': not PUBLIC, 'formats': not PUBLIC, 'profiles': not PUBLIC,
                                         'face_tracking': not PUBLIC and vision() is not None,
                                         'titles': not PUBLIC and FONT.is_file()}
                state['published_job'] = PUBLISHED_JOB.snapshot() if PUBLISHED_JOB else None
                if LICENSE:
                    state['license'] = LICENSE.status()
                    if state['license']['state'] != 'active':
                        state.update(clips=[], trash=[], suggestions=[], source=False, edits={})
                        state['live']['video_id'] = None
                return self.send(200, state)
            except ValueError as e:
                return self.send(500, {'error': str(e)})
        if path == '/api/session':
            return self.send(200, {'token': TOKEN, 'requirements': requirements(), 'platform': os.name,
                                   'desktop': DESKTOP, 'public': PUBLIC,
                                   'prepare_mac': DESKTOP and sys.platform == 'darwin' and not PUBLIC})
        if path == '/api/diagnostics':
            return self.send(200, {'requirements': requirements(), 'platform': os.name})
        if path.startswith(('/clips/', '/thumbs/', '/subtitulos/')) and LICENSE and not LICENSE.allowed():
            return self.send(403, {'error': LICENSE_REQUIRED})
        if path.startswith('/clips/'):
            name = path.split('/')[-1]
            if re.fullmatch(r'clip-[0-9a-f]{12}\.mp4', name) and any(x['name'] == name for x in MediaStore(DATA).view()['clips']):
                try:
                    return self.send(200, (DATA / name).read_bytes(), 'video/mp4')
                except FileNotFoundError:
                    pass
            return self.send(404, {'error': 'Clip no encontrado'})
        if path.startswith(('/thumbs/', '/subtitulos/')):
            name = path.rsplit('/', 1)[-1]
            store = MediaStore(DATA)
            try:
                clip = store.active_clip(name)
                if path.startswith('/thumbs/'):
                    return self.send(200, ensure_thumbnail(store, name).read_bytes(), 'image/jpeg')
                if clip.get('captions'):
                    return self.send(200, srt_text(clip['captions']).encode('utf-8'), 'application/x-subrip')
            except (ValueError, OSError):
                pass
            return self.send(404, {'error': 'Recurso no disponible para este clip.'})
        files = {
            '/': ('index.html', 'text/html; charset=utf-8'),
            '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
            '/style.css': ('style.css', 'text/css; charset=utf-8'),
            '/title-font.ttf': ('title-font.ttf', 'font/ttf'),
            '/logo.svg': ('logo.svg', 'image/svg+xml'),
            '/logo-julio.jpg': ('logo-julio.jpg', 'image/jpeg'),
            '/poster.svg': ('poster.svg', 'image/svg+xml'),
        }
        if path in files:
            name, mime = files[path]
            return self.send(200, (ROOT / 'web' / name).read_bytes(), mime)
        if not DESKTOP and path in ('/bridge.html', '/bridge.js'):
            return self.send(200, (ROOT / 'web' / path[1:]).read_bytes(), 'text/html; charset=utf-8' if path.endswith('.html') else 'text/javascript; charset=utf-8')
        self.send(404, {'error': 'No encontrado'})

    def do_POST(self):
        global PUBLISHED_JOB
        self.connection.settimeout(30)
        origin = 'http://127.0.0.1:' + str(self.server.server_port)
        if not self.valid_host() or self.headers.get('Origin') != origin or not secrets.compare_digest(self.headers.get('X-Julio-Token', ''), TOKEN):
            return self.send(403, {'error': 'Sesión local no autorizada'})
        if self.path == '/api/license/activate' and LICENSE:
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 2 <= size <= 512:
                    raise ValueError('Solicitud de activación inválida.')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError('Solicitud de activación inválida.')
                return self.send(200, LICENSE.activate(payload.get('code')))
            except (ValueError, UnicodeError) as e:
                return self.send(400, {'error': str(e)})
        if (LICENSE and self.path not in ('/api/live-stop', '/api/published-cancel')
                and not LICENSE.allowed()):
            return self.send(403, {'error': LICENSE_REQUIRED})
        if PUBLIC and self.path not in ('/api/live-start', '/api/live-stop', '/api/live-finish'):
            return self.send(403, {'error': 'Operación disponible en la edición privada.'})
        if self.path in ('/api/live-start', '/api/live-stop', '/api/live-finish', '/api/clip-info',
                         '/api/trash', '/api/restore', '/api/published-cancel', '/api/kick-preview'):
            try:
                size = int(self.headers.get('Content-Length', 0))
                if size < 2 or size > 4096:
                    raise ValueError('Solicitud inválida')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError('Solicitud inválida')
                if self.path == '/api/kick-preview':
                    return self.send(200, kick_preview(payload['url']), 'image/jpeg')
                if self.path == '/api/clip-info':
                    clip = MediaStore(DATA).active_clip(payload['name'])
                    return self.send(200, {'captions': clip.get('captions', [])})
                if self.path in ('/api/trash', '/api/restore'):
                    trash = self.path == '/api/trash'
                    MediaStore(DATA).move(payload['name'], trash)
                    return self.send(200, {'message': 'Clip enviado a la papelera.' if trash else 'Clip restaurado.'})
                if self.path == '/api/published-cancel':
                    job = PUBLISHED_JOB
                    if not job or payload.get('id') != job.id or not job.request_cancel():
                        return self.send(409, {'error': 'Esa operación ya terminó.'})
                    return self.send(200, {'message': 'Cancelación solicitada…'})
                if self.path == '/api/live-start':
                    start_live(payload)
                elif self.path == '/api/live-finish':
                    live().finish()
                else:
                    live().stop()
                return self.send(200, {'ok': True})
            except (ValueError, KeyError, TypeError) as e:
                return self.send(400, {'error': str(e)})
            except OSError:
                return self.send(409, {'error': 'No se pudo mover el archivo. Si está abierto en otro programa, ciérralo y vuelve a intentar.'})
        if not LOCK.acquire(False):
            return self.send(409, {'error': 'Espera a que termine la operación actual'})
        owns_lock = True
        upload_temp = None
        job = None
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if self.path == '/api/upload':
                if size <= 0 or size > MAX_SOURCE_BYTES:
                    raise ValueError('Elige un video de hasta 2 GB.')
                MediaStore(DATA).check_space(size)
                PUBLISHED_JOB = job = PublishedJob('upload')
                STATE.update(busy=True, status='Copiando el video…')
                job.progress.reset('Copiando el video desde el navegador…')
                dest = DATA / 'imported.video'
                upload_temp = DATA / ('upload-'+job.id+'.part')
                self.connection.settimeout(120)
                with upload_temp.open('wb') as f:
                    left = size
                    while left:
                        job.check()
                        chunk = self.rfile.read1(min(left, 1024*1024))
                        if not chunk:
                            raise ValueError('La carga quedó incompleta.')
                        f.write(chunk)
                        left -= len(chunk)
                        job.progress.report(1-left/size)
                with job.commit():
                    upload_temp.replace(dest)
                    STATE.update(source=str(dest), source_platform=None, source_duration=None,
                                 suggestions=[], status='Video importado', busy=False)
                LOCK.release()
                owns_lock = False
                return self.send(200, {'ok': True})
            action = self.path.replace('/api/', '')
            actions = ('youtube', 'analyze', 'export', 'edit', 'empty-trash', 'storage', 'clear-source', 'clear-queue')
            if DESKTOP and sys.platform == 'darwin':
                actions += ('prepare-mac',)
            if action not in actions or size > (65536 if action == 'edit' else 4096) or size < 2:
                raise ValueError('Solicitud inválida')
            payload = json.loads(self.rfile.read(size))
            if action == 'youtube':
                published_platform(payload['url'])
            if action == 'export':
                bounds(payload['start'], payload['end'])
                watermark_settings(payload)
                subtitles_enabled(payload)
                burn_subtitles_enabled(payload)
                subtitle_settings(payload)
                format_name, _ = layout_settings(payload)
                styling(payload, format_name)
            if action == 'edit':
                MediaStore(DATA).path(payload['name'])
                subtitles_enabled(payload)
                burn_subtitles_enabled(payload)
                subtitle_settings(payload)
                format_name, _ = layout_settings(payload)
                styling(payload, format_name)
                if not re.fullmatch(r'[0-9a-f]{24}', payload['id']):
                    raise ValueError('Solicitud de edición inválida.')
                edit_result(payload['id'])
            STATE['busy'] = True
            if action in PUBLISHED_ACTIONS:
                PUBLISHED_JOB = job = PublishedJob(action)
            threading.Thread(target=process, args=(action, payload, job), daemon=True).start()
            owns_lock = False
            self.send(202, {'ok': True})
        except Exception as e:
            if owns_lock:
                if job:
                    job.end(False)
                    STATE.update(busy=False, status='Operación cancelada.' if job.is_set() else 'No se completó la operación.')
                LOCK.release()
            if upload_temp and upload_temp.is_file():
                upload_temp.unlink()
            self.send(400, {'error': str(e) if isinstance(e, ValueError) else 'Solicitud inválida'})

def stop_engine():
    SHUTDOWN.set()
    if LIVE:
        LIVE.stop()
        if LIVE.thread:
            LIVE.thread.join(timeout=20)
        LIVE._terminate()
    if LOCK.acquire(timeout=10):
        LOCK.release()


def main():
    global LICENSE
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if REQUIRES_SUBSCRIPTION and not LICENSE_CONFIG.is_file():
        raise ValueError('Falta la configuración de licencias. Extrae nuevamente el ZIP de Julio Clip Público.')
    DATA.mkdir(parents=True, exist_ok=True)
    if LICENSE_CONFIG.is_file():
        LICENSE = LicenseGate(json.loads(LICENSE_CONFIG.read_text(encoding='utf-8')), DATA)
        threading.Thread(target=monitor_license, daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    url = 'http://127.0.0.1:%s' % server.server_port
    print('Julio Clip: ' + url, flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_engine()
        server.server_close()

if __name__ == '__main__':
    main()
