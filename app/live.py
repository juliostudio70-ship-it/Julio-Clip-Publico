"""Captura y cola persistente. No expone redes entrantes ni ejecuta una shell."""
import csv
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlparse
from library import MediaStore
from media_relay import MediaRelay, is_youtube_media
from monitor import LiveMonitor
from runtime_support import CA_BUNDLE, child_options

# Preferir un solo flujo HLS. YouTube también publica video y audio HLS por separado.
LIVE_FORMAT = ('best[protocol^=m3u8]'
               '/(bestvideo[protocol^=m3u8]+bestaudio[protocol^=m3u8])'
               '/best')
NORMAL_BLOCK_SECONDS = 300
FAST_BLOCK_SECONDS = 60
YOUTUBE_VIDEO_ID = re.compile(r'[A-Za-z0-9_-]{11}')

class NotLiveError(ValueError):
    pass


def youtube_video_id(url):
    parsed = urlparse(url)
    parts = parsed.path.strip('/').split('/')
    if parsed.hostname == 'youtu.be' and len(parts) == 1:
        candidate = parts[0]
    elif parsed.hostname in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
        if parts == ['watch']:
            candidate = parse_qs(parsed.query).get('v', [''])[0]
        elif len(parts) == 2 and parts[0] in ('live', 'shorts', 'embed'):
            candidate = parts[1]
        else:
            return None
    else:
        return None
    return candidate if YOUTUBE_VIDEO_ID.fullmatch(candidate) else None

def kick_channel(url):
    parsed = urlparse(url)
    slug = parsed.path.strip('/')
    if (parsed.scheme != 'https' or parsed.netloc.lower() not in ('kick.com', 'www.kick.com')
            or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', slug)
            or parsed.path not in ('/'+slug, '/'+slug+'/')
            or slug.lower() in ('video', 'videos', 'categories', 'search', 'auth', 'clips')
            or 'clip' in parse_qs(parsed.query)):
        raise ValueError('Pega el enlace HTTPS a un canal de Kick, por ejemplo https://kick.com/tu-canal.')
    return 'https://kick.com/' + slug.lower()


def twitch_channel(url):
    parsed=urlparse(url)
    channel=parsed.path.strip('/')
    if (parsed.scheme!='https' or parsed.netloc.lower() not in ('www.twitch.tv','twitch.tv')
            or not re.fullmatch(r'[a-zA-Z0-9_]{1,25}',channel)
            or channel.lower() in ('videos','directory','downloads','settings','subscriptions','search')):
        raise ValueError('Pega el enlace HTTPS de un canal de Twitch.')
    return 'https://www.twitch.tv/'+channel.lower()


def twitch_media(url):
    try:
        p=urlparse(url);host=p.hostname or ''
        return p.scheme=='https' and p.port in (None,443) and p.username is None and any(
            host==d or host.endswith('.'+d) for d in ('ttvnw.net','twitch.tv','twitchcdn.net'))
    except ValueError:return False


def kick_media(url):
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ''
        return (parsed.scheme == 'https' and parsed.port in (None, 443)
                and parsed.username is None and parsed.password is None
                and any(host == domain or host.endswith('.'+domain)
                        for domain in ('live-video.net', 'kick.com', 'kickcdn.com')))
    except ValueError:
        return False


def capture_input(media, kick=False):
    args = ['-rw_timeout', '15000000']
    if urlparse(media).scheme == 'https':
        args += ['-tls_verify', '1']
        if kick:
            args += ['-protocol_whitelist', 'https,tls,tcp,crypto']
            if CA_BUNDLE.is_file():
                args += ['-ca_file', str(CA_BUNDLE)]
    return args + ['-i', media]


def youtube_runtime_args(tool):
    if tool('qjs'):
        return ['--js-runtimes','quickjs:'+tool('qjs')]
    if tool('node'):
        return ['--js-runtimes','node:'+tool('node')]
    return []

class LiveController:
    def __init__(self, root, tool, consume, block_seconds=NORMAL_BLOCK_SECONDS, retry_seconds=5):
        self.root = Path(root)
        self.tool = tool
        self.consume = consume
        self.block_seconds = block_seconds
        self.retry_seconds = retry_seconds
        self.stop_event = threading.Event()
        self.capture_stop = threading.Event()
        self.capture_done = threading.Event()
        self.monitor = LiveMonitor()
        self.guard = threading.Lock()
        self.process = None
        self.resolver = None
        self.thread = None
        self.state = {'running': False, 'finishing': False, 'status': 'Captura automática detenida', 'processed': 0, 'backlog': 0,
                      'clip_seconds': None, 'clips_per_block': None, 'subtitles': False,
                      'fast_mode': False, 'block_seconds': block_seconds, 'profile': 'auto', 'video_id': None}

    def start(self, url, options):
        with self.guard:
            if self.thread and self.thread.is_alive():
                raise ValueError('La captura ya está iniciada o terminando.')
            fast_mode = options.get('fast_mode', False)
            if not isinstance(fast_mode, bool):
                raise ValueError('Activa o desactiva el modo rápido.')
            block_seconds = FAST_BLOCK_SECONDS if fast_mode else self.block_seconds
            if 'clip_seconds' in options:
                block_seconds=max(block_seconds,options['clip_seconds']+5)
            for name in ('ffmpeg', 'ffprobe', 'whisper-cli', 'yt-dlp'):
                if not self.tool(name):
                    raise ValueError('Falta %s. Prepara las dependencias antes de capturar.' % name)
            platform = options.get('platform', 'YouTube')
            if platform == 'YouTube' and not youtube_runtime_args(self.tool):
                raise ValueError('Falta el runtime JavaScript para YouTube. Ejecuta el asistente de preparación.')
            MediaStore(self.root).check_space()
            self.stop_event.clear()
            self.capture_stop.clear()
            self.capture_done.clear()
            self.monitor.reset()
            self.state.update(running=True, finishing=False, status='Preparando captura…', processed=0, backlog=0,
                              platform=platform, format=options.get('format', 'original'),
                              profile=options.get('profile', 'auto'),
                              clip_seconds=options.get('clip_seconds'), clips_per_block=options.get('clips_per_block'),
                              subtitles=options.get('subtitles', False), fast_mode=fast_mode,
                              block_seconds=block_seconds, video_id=youtube_video_id(url) if platform == 'YouTube' else None)
            self.thread = threading.Thread(target=self._run, args=(url, dict(options), block_seconds), daemon=True)
            self.thread.start()

    def stop(self):
        with self.guard:
            self.stop_event.set()
            self.capture_stop.set()
            self.state['status'] = 'Deteniendo captura; la tarea en curso puede tardar…'

    def finish(self):
        with self.guard:
            if not self.state['running'] or self.stop_event.is_set():
                raise ValueError('No hay una captura que terminar.')
            self.state.update(finishing=True, status='Cerrando la grabación para generar clips…')
            self.capture_stop.set()

    def _drain(self, message, completed, consumer):
        with self.guard:
            if self.stop_event.is_set():
                return
            self.state.update(finishing=True, status=message)
            self.capture_done.set()
        consumer.join()
        with self.guard:
            if not self.stop_event.is_set():
                self.state['status'] = completed

    def snapshot(self):
        return dict(self.state, monitor=self.monitor.snapshot())

    def _resolve(self, url, timeout=90):
        kick = urlparse(url).hostname in ('kick.com', 'www.kick.com')
        twitch=urlparse(url).hostname in ('twitch.tv','www.twitch.tv')
        platform = 'Kick' if kick else 'Twitch' if twitch else 'YouTube'
        extractors = 'kick:live$' if kick else 'twitch:stream$' if twitch else 'youtube$,youtube:tab$'
        args = [self.tool('yt-dlp'), '--ignore-config', '--no-plugin-dirs', '--use-extractors',
                extractors, '--no-playlist', '--no-warnings',
                '--skip-download', '--dump-single-json', '--ignore-no-formats-error', '-f', LIVE_FORMAT]
        if not kick and not twitch:
            args += youtube_runtime_args(self.tool)
        args += ['--', url]
        self.resolver = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, **child_options())
        deadline = time.monotonic()+timeout
        try:
            while True:
                if self.capture_stop.is_set() or time.monotonic()>=deadline:
                    raise ValueError('Resolución de la emisión detenida o agotada.')
                try:
                    stdout, stderr = self.resolver.communicate(timeout=.5)
                    break
                except subprocess.TimeoutExpired:
                    continue
            code=self.resolver.returncode
        finally:
            if self.resolver.poll() is None:
                self.resolver.terminate()
                try:
                    self.resolver.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    self.resolver.kill()
                    self.resolver.communicate()
            self.resolver=None
        if code:
            detail = stderr.lower()
            if (kick or twitch) and any(s in detail for s in (b'not currently live',b'not live',b'is offline')):
                raise NotLiveError(f'El canal de {platform} no está emitiendo ahora.')
            if twitch and any(s in detail for s in (b'403',b'429',b'subscriber',b'login')):
                raise ValueError('Twitch restringió el acceso. Usa un directo público permitido o importa tu archivo; no se eluden restricciones.')
            if b'requested format is not available' in detail:
                raise ValueError(f'{platform} no ofreció pistas compatibles de audio y video.')
            if b'winerror 10013' in detail:
                raise ValueError(f'Windows impidió que el programa se conectara a {platform}.')
            if kick and (b'403' in detail or b'429' in detail):
                raise ValueError('Kick rechazó la consulta del canal. Comprueba que emita en público y vuelve a intentar.')
            raise ValueError(f'No se pudo consultar la emisión en {platform}.')
        try:
            info = json.loads(stdout)
        except ValueError:
            raise ValueError(f'{platform} devolvió una respuesta que Julio Clip no pudo leer.') from None
        if not info.get('is_live') and info.get('live_status')!='is_live':
            raise NotLiveError('El enlace no está emitiendo ahora. Usa Importar para videos publicados, o reinicia cuando comience el directo.')
        tracks = info.get('requested_formats') or [info]
        inputs = tuple(track.get('url', '') for track in tracks)
        if len(inputs) not in (1, 2) or any(urlparse(media).scheme not in ('https', 'http') for media in inputs):
            raise ValueError(f'{platform} no ofreció pistas compatibles de audio y video.')
        if twitch and not all(twitch_media(media) for media in inputs):
            raise ValueError('Twitch no ofreció un servidor HTTPS de video reconocido.')
        if kick and not all(kick_media(media) for media in inputs):
            raise ValueError('Kick no ofreció un servidor HTTPS de video reconocido.')
        video_id = info.get('id')
        if not kick and not twitch and isinstance(video_id, str) and YOUTUBE_VIDEO_ID.fullmatch(video_id):
            self.state['video_id'] = video_id
        return inputs

    def _entries(self, url):
        pending = []
        key = hashlib.sha256(url.encode()).hexdigest()[:16]
        for folder in sorted((self.root / 'live' / key).glob('*')):
            if not folder.is_dir():
                continue
            try:
                options = json.loads((folder / 'opciones.json').read_text(encoding='utf-8'))
                with (folder / 'segmentos.csv').open(newline='', encoding='utf-8') as f:
                    rows = list(csv.reader(f))
                existing = {p.name for p in folder.glob('bloque-*.mkv')}
                for row in rows:
                    if len(row) < 3:
                        continue
                    name = Path(row[0]).name
                    if name not in existing or not name.startswith('bloque-') or not name.endswith('.mkv'):
                        continue
                    path = folder / name
                    if path.is_file() and not path.with_suffix('.hecho').exists():
                        pending.append((path, options))
            except (OSError, ValueError, csv.Error):
                continue
        return pending

    def _consumer(self, url):
        while not self.stop_event.is_set():
            pending = self._entries(url)
            self.state['backlog'] = len(pending)
            if not pending:
                if self.capture_done.is_set():
                    pending = self._entries(url)
                    if not pending:
                        return
                    self.state['backlog'] = len(pending)
                else:
                    self.stop_event.wait(1)
                    continue
            path, options = pending[0]
            try:
                consumed=self.consume(path, options, self.stop_event)
                if consumed is False:
                    # Límite de sesión: el bloque y su plan permanecen para reanudar.
                    self.capture_stop.set()
                    break
                if self.stop_event.is_set():
                    break
                path.with_suffix('.hecho').write_text('procesado\n', encoding='utf-8')
                path.unlink()
                path.with_suffix('.hecho').unlink()
                self.state['processed'] += 1
                self.monitor.stage('idle')
            except Exception as e:
                self.state['status'] = str(e) if isinstance(e, ValueError) else 'Falló el análisis. El bloque se conserva para reintentar.'
                self.stop_event.set()
                self.capture_stop.set()

    def _terminate(self, graceful=False):
        if self.process and self.process.poll() is None:
            if graceful:
                try:
                    self.process.stdin.write(b'q\n')
                    self.process.stdin.flush()
                    return self.process.wait(timeout=18) == 0
                except (OSError, subprocess.TimeoutExpired):
                    pass
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            return False
        return True

    def _read_progress(self, pipe):
        with pipe:
            for line in pipe:
                key, _, value = line.strip().partition(b'=')
                if key == b'out_time_us':
                    try:
                        self.monitor.progress(int(value) / 1_000_000)
                    except ValueError:
                        pass

    def _run(self, url, options, block_seconds):
        consumer = threading.Thread(target=self._consumer, args=(url,), daemon=True)
        consumer.start()
        retries = 0
        relay = None
        partial_closed = True
        platform = options.get('platform', 'YouTube')
        try:
            while not self.capture_stop.is_set():
                MediaStore(self.root).check_space()
                self.state['status'] = f'Conectando con {platform}…'
                try:
                    inputs = self._resolve(url)
                except NotLiveError as error:
                    if self.capture_stop.is_set():
                        break
                    if self.monitor.snapshot()['recorded_seconds'] or self._entries(url):
                        self._drain('La emisión terminó. Terminando los bloques pendientes…',
                                    'Emisión terminada. Cola procesada.', consumer)
                        return
                    raise error
                except (ValueError, OSError, subprocess.TimeoutExpired) as error:
                    if self.capture_stop.is_set():
                        break
                    retries += 1
                    reason = str(error) if isinstance(error, ValueError) else f'Falló la consulta a {platform}.'
                    self.state['status'] = '%s Reintento %s…' % (reason, retries)
                    self.capture_stop.wait(min(60, self.retry_seconds*retries))
                    continue
                if self.capture_stop.is_set():
                    break
                if any(is_youtube_media(media) for media in inputs):
                    if relay is None:
                        relay = MediaRelay()
                    inputs = tuple(relay.local_url(media) if is_youtube_media(media) else media for media in inputs)
                key = hashlib.sha256(url.encode()).hexdigest()[:16]
                folder = self.root / 'live' / key / ('%013d-' % int(time.time()*1000) + secrets.token_hex(3))
                folder.mkdir(parents=True)
                identity = self.state.get('video_id') if platform == 'YouTube' else url
                capture_key = hashlib.sha256(f'{platform}:{identity or url}'.encode()).hexdigest()[:16]
                (folder / 'opciones.json').write_text(json.dumps(dict(options, capture_key=capture_key)), encoding='utf-8')
                args = [self.tool('ffmpeg'), '-stdin', '-y', '-progress', 'pipe:1', '-nostats']
                for media in inputs:
                    args += capture_input(media, platform == 'Kick')
                args += ['-map', '0:v:0', '-map', '%s:a:0' % (len(inputs) - 1), '-c', 'copy',
                        '-f', 'segment', '-segment_format', 'matroska',
                        '-segment_time', str(block_seconds), '-reset_timestamps', '1', '-segment_list_type', 'csv',
                        '-segment_list', str(folder / 'segmentos.csv'), str(folder / 'bloque-%08d.mkv')]
                self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL, **child_options())
                progress = threading.Thread(target=self._read_progress, args=(self.process.stdout,), daemon=True)
                progress.start()
                capture_started=time.monotonic()
                self.state['status'] = 'Abriendo pistas de la emisión…'
                try:
                    while self.process.poll() is None and not self.capture_stop.wait(1):
                        MediaStore(self.root).check_space()
                        if self.state['status'] == 'Abriendo pistas de la emisión…' and self.monitor.snapshot()['recording']:
                            self.state['status'] = 'Grabando el directo'
                finally:
                    graceful = self.capture_stop.is_set() and not self.stop_event.is_set()
                    closed = self._terminate(graceful=graceful)
                    if graceful:
                        partial_closed = closed
                    try:
                        self.process.stdin.close()
                    except OSError:
                        pass
                    progress.join()
                    self.monitor.end_capture()
                if not self.capture_stop.is_set():
                    retries = 0 if time.monotonic()-capture_started>=block_seconds else retries+1
                    self.state['status'] = 'Se perdió la señal o falló la captura. Reconectando…'
                    self.capture_stop.wait(min(60,self.retry_seconds*max(1,retries)))
            if self.capture_stop.is_set() and not self.stop_event.is_set():
                self._drain('Grabación cerrada. Procesando el material disponible…',
                            'Grabación terminada. Revisa los clips y los descartes.' if partial_closed else
                            'Se procesaron los bloques completos. El último fragmento no pudo cerrarse.', consumer)
        except Exception as e:
            self.state['status'] = str(e) if isinstance(e, ValueError) else 'Captura detenida por error de herramienta. Los bloques completos se conservan.'
        finally:
            self.stop_event.set()
            self._terminate()
            if relay is not None:
                relay.close()
            consumer.join()
            self.monitor.finish()
            self.state.update(running=False, finishing=False)
            if self.state['status'].startswith('Deteniendo'):
                self.state['status'] = 'Captura detenida. Se conservan los bloques completos pendientes.'
