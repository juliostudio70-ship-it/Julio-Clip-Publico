"""Pruebas con FFmpeg real; configurar JULIO_FFMPEG y JULIO_FFPROBE."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from watermark import export_args
from live import LiveController, NotLiveError

FFMPEG = os.environ.get('JULIO_FFMPEG')
FFPROBE = os.environ.get('JULIO_FFPROBE')

@unittest.skipUnless(FFMPEG and FFPROBE, 'Requiere ejecutables FFmpeg y ffprobe reales')
class VideoIntegration(unittest.TestCase):
    def test_sports_finds_field_action_after_black_ad_and_studio(self):
        import threading
        import wave
        from unittest.mock import patch
        import server as app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root/'partido.mkv'
            # 0–9: anuncio sobre negro. 9–25: estudio. 25–60: campo.
            # El movimiento y la reacción coinciden sólo en la jugada de control.
            video_filter = (
                '[0:v][1:v][2:v]concat=n=3:v=1:a=0[base];'
                '[base][5:v]overlay=x=mod(t*28\\,260):y=70:enable=gte(t\\,9)[moving];'
                '[moving][3:v]overlay=x=mod(t*95\\,240):y=110:enable=between(t\\,37\\,42)[picture]'
            )
            audio_filter = (
                r"aevalsrc=(0.06+0.45*between(t\,2\,6)+0.58*between(t\,38\,41))*sin(2*PI*410*t):d=60"
            )
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=black:s=320x180:r=12:d=9',
                            '-f', 'lavfi', '-i', 'color=0x604756:s=320x180:r=12:d=16',
                            '-f', 'lavfi', '-i', 'color=0x3c9138:s=320x180:r=12:d=35',
                            '-f', 'lavfi', '-i', 'color=white:s=72x46:r=12:d=60',
                            '-f', 'lavfi', '-i', audio_filter, '-f', 'lavfi', '-i', 'color=gray:s=22x24:r=12:d=60',
                            '-filter_complex', video_filter,
                            '-map', '[picture]', '-map', '4:a', '-c:v', 'libx264', '-c:a', 'aac', str(video)],
                           check=True, timeout=60)
            with patch.object(app, 'tool', side_effect={'ffmpeg': FFMPEG, 'ffprobe': FFPROBE}.get), \
                    patch.object(app, 'whisper_audio', return_value={}) as whisper:
                stop = threading.Event()
                probe = app.inspect_media(video, stop)
                picks, rejects, _ = app.review_highlights(video, probe, 20, 2, 'sports', root, stop)
                self.assertEqual(len(picks), 1, (picks, rejects))
                pick = picks[0]
                self.assertGreaterEqual(pick['start'], 25)
                self.assertLess(pick['start'], 38)
                self.assertGreater(pick['end'], 41)
                self.assertEqual(pick['end']-pick['start'], 20)
                self.assertTrue(any('negro' in reject['reason'] for reject in rejects))
                whisper.assert_called_once()
                with wave.open(str(whisper.call_args.args[0]), 'rb') as wav:
                    self.assertLess(wav.getnframes()/wav.getframerate(), 25)
                self.assertTrue(whisper.call_args.args[-1])
                # La misma selección alcanza la ruta de exportación automática real.
                with patch.object(app, 'DATA', root), patch.object(app, 'LIVE', None):
                    app.consume_live(video, {'profile': 'sports', 'clip_seconds': 20,
                                             'clips_per_block': 2, 'watermark': False}, stop)
                    clip, = app.MediaStore(root).view()['clips']
                    self.assertEqual(clip['start'], pick['start'])
                    self.assertTrue(clip['thumbnail'])
                    self.assertGreaterEqual(clip['interest'], 60)
                whisper.return_value = {'transcription': [
                    {'offsets': {'from': 10000, 'to': 14900}, 'text': '¿Por qué cambió tanto el equipo desde el primer juego?'},
                    {'offsets': {'from': 15000, 'to': 23000}, 'text': 'Resulta que el entrenador cambió la estrategia porque nadie esperaba un lanzamiento tan rápido.'},
                    {'offsets': {'from': 38000, 'to': 42100}, 'text': '¡Cuadrangular por el jardín izquierdo, increíble jugada!'},
                ]}
                combined, _, _ = app.review_highlights(video, probe, 20, 2, 'auto', root, stop)
                self.assertEqual(len(combined), 2, combined)
                self.assertTrue(any('entrenador' in item['title'] and item['start'] < 20 for item in combined))
                self.assertTrue(any('Cuadrangular' in item['title'] and item['start'] > 24 for item in combined))

    def test_entirely_black_video_skips_transcription(self):
        from unittest.mock import patch
        import server as app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root/'negro.mp4'
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'color=black:s=96x64:r=12:d=5', '-f', 'lavfi', '-i', 'sine=duration=5',
                            '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(video)], check=True, timeout=30)
            with patch.object(app, 'tool', side_effect={'ffmpeg': FFMPEG, 'ffprobe': FFPROBE}.get), \
                    patch.object(app, 'whisper_audio') as whisper:
                picks, rejects, _ = app.review_highlights(video, app.inspect_media(video), 30, 2, 'auto', root, None)
            self.assertFalse(picks)
            self.assertIn('negro', rejects[0]['reason'])
            whisper.assert_not_called()

    def test_export_formats_keep_audio_and_split_places_camera_above_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'fixture.mp4'
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'color=c=blue:s=320x180:r=10:d=2', '-f', 'lavfi', '-i', 'sine=duration=2',
                            '-vf', 'drawbox=x=0:y=0:w=160:h=180:color=red:t=fill',
                            '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(source)],
                           check=True, timeout=30)
            def probe(path):
                return json.loads(subprocess.check_output([FFPROBE, '-v', 'error', '-show_streams',
                                                           '-of', 'json', str(path)], timeout=20))
            original = probe(source)
            split = {'camera': [0,0,50,100], 'game': [50,0,50,100]}
            logo = Path(__file__).resolve().parents[1]/'web/logo-julio.jpg'
            for label, layout, expected in (('original', None, (320,180)), ('vertical', None, (720,1280)),
                                             ('square', None, (720,720)), ('vertical', split, (720,1280))):
                with self.subTest(format=label, split=bool(layout)):
                    output = root/(('split' if layout else label)+'.mp4')
                    command = export_args(FFMPEG, source, output, 0, 1.5, original, logo,
                                          bool(layout), format_name=label, split=layout)
                    subprocess.run(command[:1]+['-v','error']+command[1:], check=True, timeout=45)
                    streams = probe(output)['streams']
                    video = next(s for s in streams if s['codec_type']=='video')
                    self.assertEqual((video['width'],video['height']), expected)
                    self.assertTrue(any(s['codec_type']=='audio' for s in streams))
                    def pixel(y, x=360):
                        return subprocess.check_output([FFMPEG, '-v', 'error', '-i', str(output),
                            '-vf', f'crop=2:2:{x}:{y}', '-frames:v', '1', '-threads', '1',
                            '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'], timeout=25)[:3]
                    if label == 'vertical' and not layout:
                        self.assertGreater(max(pixel(40)), 90)
                        self.assertGreater(max(pixel(1240)), 90)
                        self.assertGreater(pixel(640, 140)[0], 190)
                        self.assertGreater(pixel(640, 580)[2], 190)
                    if layout:
                        top, bottom = pixel(220), pixel(850)
                        self.assertGreater(top[0], 190, top)
                        self.assertGreater(bottom[2], 190, bottom)

    def test_capture_discards_frozen_picture_and_replayed_conversation(self):
        import threading
        from unittest.mock import patch
        import server as app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen = root/'live/link/first/bloque-0.mkv'
            healthy = root/'live/link/first/bloque-1.mkv'
            replay = root/'live/other-link/second/bloque-0.mkv'
            frozen.parent.mkdir(parents=True)
            replay.parent.mkdir(parents=True)
            for destination, duration, extra in ((frozen, 10, ['-vf', 'tpad=stop_mode=clone:stop_duration=10']),
                                                 (healthy, 20, [])):
                subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                                f'testsrc2=s=160x90:r=12:d={duration}', '-f', 'lavfi', '-i',
                                'sine=duration=20', *extra, '-c:v', 'libx264', '-c:a', 'aac',
                                '-t', '20', str(destination)], check=True, timeout=30)
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-ss', '2', '-i', str(healthy),
                            '-c:v', 'libx264', '-crf', '21', '-c:a', 'aac', str(replay)],
                           check=True, timeout=30)
            transcript = {'transcription': [
                {'offsets': {'from': 1000, 'to': 4500}, 'text': '¿Cómo descubriste que habían cambiado la pelota?'},
                {'offsets': {'from': 4800, 'to': 9500}, 'text': 'Al principio nadie lo notó, pero entonces el árbitro revisó la marca.'},
                {'offsets': {'from': 10500, 'to': 15700}, 'text': '¡Increíble! De repente se dieron cuenta de que era la del primer juego.'},
            ]}
            options = {'clip_seconds': 20, 'clips_per_block': 2, 'format': 'vertical',
                       'watermark': False, 'capture_key': 'same-live-video'}
            with patch.object(app, 'DATA', root), patch.object(app, 'LIVE', None), \
                    patch.object(app, 'tool', side_effect={'ffmpeg': FFMPEG, 'ffprobe': FFPROBE}.get), \
                    patch.object(app, 'whisper_audio', return_value=transcript):
                stop = threading.Event()
                app.consume_live(frozen, options, stop)
                self.assertFalse(app.MediaStore(root).view()['clips'])
                self.assertTrue(any('congelada' in entry['reason']
                                    for entry in app.live().monitor.snapshot()['recent_rejections']))
                with self.assertRaises(app.FrozenExport):
                    app.publish_clip(app.MediaStore(root), 'clip-123456789abc.mp4', {'start': 0, 'end': 20},
                                     lambda output: [FFMPEG, '-v', 'error', '-y', '-i', str(frozen),
                                                     '-c', 'copy', str(output)], verify_motion=True)
                self.assertFalse((root/'clip-123456789abc.mp4').exists())
                app.consume_live(healthy, options, stop)
                clip, = app.MediaStore(root).view()['clips']
                self.assertNotIn('signature', clip)
                self.assertGreater(clip['interest'], 60)
                app.consume_live(replay, options, stop)
                self.assertEqual(app.MediaStore(root).view()['clips'], [clip])
                monitor = app.live().monitor.snapshot()
                self.assertEqual((monitor['reviewed'], monitor['generated'], monitor['pending_clips']), (3, 1, 0))
                self.assertTrue(any('Repite' in entry['reason'] for entry in monitor['recent_rejections']))

    def test_finish_gracefully_exports_the_open_segment_to_the_queue(self):
        import time
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'fixture.mp4'
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'testsrc2=s=96x64:r=10:d=12', '-f', 'lavfi', '-i', 'sine=duration=12',
                            '-c:v', 'libx264', '-g', '10', '-c:a', 'aac', '-shortest', str(source)],
                           check=True, timeout=30)
            blocks = []
            real_popen = subprocess.Popen
            def slow_capture(args, **kwargs):
                if '-segment_time' in args:
                    position = args.index('-i')
                    args = args[:position] + ['-re'] + args[position:]
                return real_popen(args, **kwargs)
            def consume(path, _, stop):
                self.assertFalse(stop.is_set())
                probe = subprocess.check_output([FFPROBE, '-v', 'error', '-show_format', '-of', 'json', str(path)])
                blocks.append(float(json.loads(probe)['format']['duration']))

            controller = LiveController(root/'data', lambda _: FFMPEG, consume, block_seconds=30)
            controller._resolve = lambda _: (str(source),)
            with patch('live.subprocess.Popen', side_effect=slow_capture):
                controller.start('https://youtu.be/finish', {})
                try:
                    deadline = time.monotonic()+10
                    while controller.snapshot()['monitor']['recorded_seconds'] < 3 and time.monotonic() < deadline:
                        time.sleep(.1)
                    self.assertFalse(blocks)
                    controller.finish()
                    controller.thread.join(25)
                    state = controller.snapshot()
                    self.assertEqual(state['processed'], 1, state)
                    self.assertTrue(2 <= blocks[0] < 12, blocks)
                    self.assertFalse(state['running'])
                    self.assertIn('Grabación terminada', state['status'])
                finally:
                    if controller.thread.is_alive():
                        controller.stop()
                        controller.thread.join(20)

    def test_natural_end_drains_all_real_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'directo.mp4'
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'testsrc2=s=96x64:r=10:d=9', '-f', 'lavfi', '-i', 'sine=duration=9',
                            '-c:v', 'libx264', '-g', '10', '-sc_threshold', '0', '-c:a', 'aac',
                            '-shortest', str(source)], check=True, timeout=30)
            blocks = []
            attempts = iter([True, False])

            def resolve(_url):
                if next(attempts):
                    return (str(source),)
                raise NotLiveError('Finalizado')

            def consume(path, options, stop):
                if not controller.capture_done.wait(8) or stop.is_set():
                    raise ValueError('El final del directo canceló el análisis.')
                blocks.append(path.name)

            controller = LiveController(root/'data', lambda _: FFMPEG, consume, block_seconds=3, retry_seconds=.02)
            controller._resolve = resolve
            controller.start('https://youtu.be/finalizado', {'watermark':False})
            controller.thread.join(12)
            try:
                self.assertFalse(controller.thread.is_alive())
                state = controller.snapshot()
                self.assertEqual(len(blocks), 3, state)
                self.assertEqual(state['processed'], 3)
                self.assertEqual(state['backlog'], 0)
                self.assertIn('Cola procesada', state['status'])
                self.assertGreater(state['monitor']['recorded_seconds'], 8)
                self.assertFalse(state['monitor']['recording'])
            finally:
                if controller.thread.is_alive():
                    controller.stop()
                    controller.thread.join(10)

    @unittest.skipUnless(os.environ.get('JULIO_WHISPER'), 'Requiere un Whisper real y el modelo')
    def test_real_whisper_exports_caption_track_and_thumbnail(self):
        from unittest.mock import patch
        import server as app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'voz.mkv'
            voice = app.ROOT/'resources/prueba-motor.wav'
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=s=96x64:r=10',
                            '-i', str(voice), '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(source)],
                           check=True, timeout=30)
            tools = {'ffmpeg': FFMPEG, 'ffprobe': FFPROBE, 'whisper-cli': os.environ['JULIO_WHISPER']}
            store = app.MediaStore(root)
            name = 'clip-123456789abc.mp4'
            with patch.object(app, 'tool', tools.get), patch.object(app, 'STATE', {}):
                probe = app.inspect_media(source)
                end = float(probe['format']['duration'])
                app.publish_clip(store, name, {'start': 0, 'end': end},
                                 lambda output: export_args(FFMPEG, source, output, 0, end, probe, None, False),
                                 lambda video, folder: app.transcribe_clip(video, folder, end))
                tracks = app.inspect_media(store.path(name))['streams']
            [caption_track] = [track for track in tracks if track['codec_type'] == 'subtitle']
            self.assertEqual(caption_track['disposition']['default'], 1)
            clip = store.active_clip(name)
            self.assertTrue(clip['captions'])
            self.assertIn('-->', app.srt_text(clip['captions']))
            self.assertTrue(clip['thumbnail'])
            self.assertEqual(store.thumbnail(name).read_bytes()[:2], b'\xff\xd8')
            store.move(name, True)
            self.assertTrue(store.thumbnail(name, True).exists())
            store.move(name, False)
            self.assertTrue(store.thumbnail(name).exists())

    def test_live_selection_avoids_real_timestamp_gap(self):
        import threading
        from unittest.mock import patch
        import server as app

        with tempfile.TemporaryDirectory() as tmp:
            block = Path(tmp) / 'salto.mkv'
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=96x64:r=10:d=65',
                            '-vf', "select='not(between(t,11,14))'", '-fps_mode', 'vfr',
                            '-c:v', 'libx264', str(block)], check=True, timeout=30)
            with patch.object(app, 'tool', lambda name: FFPROBE):
                probe = app.inspect_media(block)
                gaps = app.live_gaps(block, probe, threading.Event())
            self.assertTrue(any(start <= 11.1 and end >= 14 for start, end in gaps), gaps)
            transcript = {'transcription': [
                {'offsets': {'from': 10000, 'to': 13000}, 'text': '¡Importante! ¡Increíble!'},
                {'offsets': {'from': 34000, 'to': 38000}, 'text': 'Otra parte'}]}
            first = app.propose(transcript, duration=65, seconds=20, limit=1)[0]
            self.assertEqual(first['start'], 8)
            [safe] = app.propose(transcript, duration=65, seconds=20, limit=1, gaps=gaps)
            self.assertEqual((safe['start'], safe['end']), (32, 52))

    def test_public_engine_exports_two_contiguous_mp4_with_one_mark(self):
        import threading
        from unittest.mock import patch
        import server as app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = root/'primero.mkv'
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'testsrc2=s=96x64:r=30000/1001:d=70', '-f', 'lavfi', '-i', 'sine=duration=70',
                            '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(block)], check=True, timeout=45)
            quota = app.PublicQuota(root, lambda: 1700000000)
            transcript = {'transcription': [
                {'offsets': {'from': 1000, 'to': 2000}, 'text': '¡Importante!'},
                {'offsets': {'from': 35000, 'to': 40000}, 'text': 'Otro momento.'}]}
            tools = {'ffmpeg': FFMPEG, 'ffprobe': FFPROBE}
            with patch.object(app, 'PUBLIC', True), patch.object(app, 'DATA', root), \
                    patch.object(app, 'STATE', {}), patch.object(app, 'tool', tools.get), \
                    patch.object(app, 'PublicQuota', return_value=quota), \
                    patch.object(app, 'transcribe', return_value=transcript):
                settings = {'clip_seconds': 60, 'clips_per_block': 10, 'subtitles': True, 'watermark': True}
                app.consume_live(block, settings, threading.Event())
                clips = app.MediaStore(root).view()['clips']
                self.assertEqual(len(clips), 2)
                self.assertEqual(sum(clip['watermark'] for clip in clips), 1)
                for clip in clips:
                    probe = app.inspect_media(root/clip['name'])
                    self.assertEqual({stream['codec_type'] for stream in probe['streams']}, {'audio', 'video'})
                    self.assertLessEqual(float(probe['format']['duration']), 30.005)
                next_block = block.rename(root/'segundo.mkv')
                with self.assertRaisesRegex(ValueError, 'dos clips'):
                    app.consume_live(next_block, settings, threading.Event())
                self.assertEqual(len(app.MediaStore(root).view()['clips']), 2)

    def test_import_published_sources_and_export_a_vertical_clip(self):
        from shutil import copyfile
        from unittest.mock import patch
        import server as app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'video.mp4'
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'color=s=96x160:r=10:d=4', '-f', 'lavfi', '-i', 'sine=duration=4',
                            '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(source)], check=True, timeout=30)
            state = {}
            real_run = app.run
            downloads = []
            tools = {'ffmpeg': FFMPEG, 'ffprobe': FFPROBE, 'yt-dlp': 'simulado', 'qjs': 'simulado'}

            def run(args, **options):
                if args[0] != tools['yt-dlp']:
                    return real_run(args, **options)
                downloads.append(args)
                destination = Path(args[args.index('-o')+1].replace('%(ext)s', 'mp4'))
                copyfile(source, destination)
                return b''

            with patch.object(app, 'DATA', root/'data'), patch.object(app, 'STATE', state), \
                    patch.object(app, 'tool', tools.get), patch.object(app, 'run', side_effect=run):
                for url, platform in (('https://www.youtube.com/shorts/abc', 'YouTube'),
                                      ('https://vm.tiktok.com/Z123/', 'TikTok')):
                    app.import_published(url)
                    self.assertEqual(state['source_platform'], platform)
                    self.assertAlmostEqual(state['source_duration'], 4, places=1)
                    self.assertEqual(Path(state['source']).read_bytes(), source.read_bytes())
                    self.assertEqual(downloads[-1][-1], url)
                    self.assertIn('--no-playlist', downloads[-1])
                    self.assertIn('live_status!=?is_live & live_status!=?is_upcoming', downloads[-1])
                self.assertIn('youtube$,youtube:clip$', downloads[0])
                self.assertIn(r'TikTok$,vm\.tiktok$', downloads[1])
                self.assertIn('--js-runtimes', downloads[0])
                self.assertNotIn('--js-runtimes', downloads[1])
                self.assertTrue(app.LOCK.acquire(False))
                app.process('export', {'start': 1, 'end': 3, 'watermark': False})
                [clip] = app.MediaStore(app.DATA).view()['clips']
                probe = app.inspect_media(app.DATA / clip['name'])
                self.assertEqual({track['codec_type'] for track in probe['streams']}, {'audio', 'video'})
                video = next(track for track in probe['streams'] if track['codec_type'] == 'video')
                self.assertEqual((video['width'], video['height']), (96, 160))
                self.assertAlmostEqual(float(probe['format']['duration']), 2, places=1)

    def test_edit_removes_intervals_and_preserves_optional_caption_track(self):
        import http.client
        import threading
        import time
        from unittest.mock import patch
        import server as app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_name = 'clip-123456abcdef.mp4'
            source = root / original_name
            seed = root / 'semilla.mp4'
            # Rojo de 0 a 2 s, verde de 2 a 4 s y azul de 4 a 6 s.
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'color=c=red:s=96x64:r=10:d=6', '-f', 'lavfi', '-i',
                            'sine=duration=6', '-vf',
                            "drawbox=c=green:t=fill:enable='between(t,2,3.999)',drawbox=c=blue:t=fill:enable='gte(t,4)'",
                            '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(seed)], check=True, timeout=30)
            state = {'status': 'Listo', 'busy': False, 'source': None, 'clips': [], 'suggestions': [], 'edits': {}}
            tools = {'ffmpeg': FFMPEG, 'ffprobe': FFPROBE}
            with patch.object(app, 'DATA', root), patch.object(app, 'STATE', state), patch.object(app, 'tool', tools.get):
                store = app.MediaStore(root)
                app.publish_clip(store, original_name, {'start': 0, 'end': 6, 'watermark': True},
                                 lambda output: [FFMPEG, '-v', 'error', '-y', '-i', str(seed), '-c', 'copy', str(output)],
                                 lambda *_: [{'start': 0, 'end': 1.5, 'text': 'Inicio'},
                                             {'start': 2.2, 'end': 3.7, 'text': 'Quitar'},
                                             {'start': 4.5, 'end': 5.5, 'text': 'Último'}])
                original_bytes = source.read_bytes()
                srv = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
                threading.Thread(target=srv.serve_forever, daemon=True).start()

                def post(action, payload, authorized=True):
                    c = http.client.HTTPConnection('127.0.0.1', srv.server_port, timeout=10)
                    headers = {'Origin': 'http://127.0.0.1:%d' % srv.server_port, 'X-Julio-Token': app.TOKEN}
                    c.request('POST', '/api/' + action, json.dumps(payload), headers if authorized else {})
                    response = c.getresponse()
                    result = response.status, json.loads(response.read())
                    c.close()
                    return result

                def edit(payload, index):
                    request_id = '%024x' % index
                    code, result = post('edit', dict(payload, name=original_name, id=request_id))
                    self.assertEqual(code, 202, result)
                    deadline = time.monotonic() + 30
                    while state['busy'] and time.monotonic() < deadline:
                        time.sleep(.05)
                    self.assertFalse(state['busy'])
                    return state['edits'][request_id]

                try:
                    self.assertEqual(post('clip-info', {'name': original_name}, False)[0], 403)
                    self.assertEqual(post('clip-info', {'name': original_name})[1]['captions'][2]['text'], 'Último')
                    self.assertNotIn('captions', store.view()['clips'][0])
                    ranges = {'start': 0.5, 'end': 5.5, 'remove': [{'start': 2, 'end': 4}]}
                    broken = edit(dict(ranges, remove=[{'start': 2, 'end': 6}]), 1)
                    self.assertIn('dentro', broken['error'])
                    for i, enabled in enumerate((True, False), 2):
                        result = edit(dict(ranges, subtitles=enabled), i)
                        self.assertIn('name', result, result)
                        output = root / result['name']
                        info = app.inspect_media(output)
                        self.assertAlmostEqual(float(info['format']['duration']), 3, places=1)
                        tracks = {s['codec_type'] for s in info['streams']}
                        self.assertEqual(tracks, {'video', 'audio', 'subtitle'} if enabled else {'video', 'audio'})
                        clip = store.active_clip(result['name'])
                        self.assertTrue(clip['watermark'] and clip['edited'])
                        expected = [{'start': 0, 'end': 1, 'text': 'Inicio'},
                                    {'start': 2, 'end': 3, 'text': 'Último'}] if enabled else []
                        self.assertEqual(clip['captions'], expected)
                        if enabled:
                            subtitles = subprocess.check_output([FFMPEG, '-v', 'error', '-i', str(output), '-map',
                                                                 '0:s:0', '-f', 'srt', '-'], timeout=15).decode('utf-8')
                            self.assertIn('00:00:02,000 --> 00:00:03,000\nÚltimo', subtitles)
                            self.assertNotIn('Quitar', subtitles)
                        pixels = subprocess.check_output([FFMPEG, '-v', 'error', '-ss', '1.8', '-i', str(output),
                                                         '-frames:v', '1', '-vf', 'scale=1:1', '-pix_fmt', 'rgb24',
                                                         '-f', 'rawvideo', '-'], timeout=15)
                        self.assertGreater(pixels[2], 200, pixels)
                    self.assertEqual(source.read_bytes(), original_bytes)
                    self.assertEqual(len(store.view()['clips']), 3)
                    self.assertFalse(list(root.glob('exportando-*')))
                finally:
                    srv.shutdown()
                    srv.server_close()

    def test_one_minute_export_caps_fractional_frame_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.mkv'
            output = Path(tmp) / 'clip.mp4'
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'color=s=96x64:r=30000/1001:d=62', '-f', 'lavfi', '-i',
                            'sine=duration=62', '-c:v', 'libx264', '-c:a', 'aac', '-shortest',
                            str(source)], check=True, timeout=45)
            def probe(path):
                return json.loads(subprocess.check_output([
                    FFPROBE, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path),
                ], timeout=15))
            logo = Path(__file__).resolve().parents[1] / 'web/logo-julio.jpg'
            for end, marked in ((60.7, False), (60.7, True), (60.69, True)):
                with self.subTest(end=end, marked=marked):
                    args = export_args(FFMPEG, source, output, .7, end, probe(source), logo, marked)
                    subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=45)
                    info = probe(output)
                    duration = float(info['format']['duration'])
                    self.assertLessEqual(duration, 60)
                    self.assertGreaterEqual(duration, end-.71)
                    self.assertEqual({s['codec_type'] for s in info['streams']}, {'video', 'audio'})

    def test_http_import_export_download_and_trash(self):
        import http.client
        import threading
        import time
        from unittest.mock import patch
        import server as app
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/'source.mp4'
            subprocess.run([FFMPEG,'-v','error','-y','-f','lavfi','-i','color=s=320x180:r=10:d=3','-f','lavfi','-i','sine=duration=3','-c:v','libx264','-c:a','aac','-shortest',str(source)],check=True,timeout=30)
            data=root/'data'
            data.mkdir()
            state={'status':'Listo','busy':False,'source':None,'clips':[],'suggestions':[]}
            with patch.object(app,'DATA',data),patch.object(app,'STATE',state),patch.object(app,'tool',side_effect=lambda name:FFMPEG if name=='ffmpeg' else FFPROBE):
                srv=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
                threading.Thread(target=srv.serve_forever,daemon=True).start()
                def request(path,method='GET',body=None):
                    c=http.client.HTTPConnection('127.0.0.1',srv.server_port,timeout=10)
                    h={'Origin':'http://127.0.0.1:%s'%srv.server_port,'X-Julio-Token':app.TOKEN}
                    c.request(method,path,body,h)
                    r=c.getresponse()
                    code,payload=r.status,r.read()
                    c.close()
                    return code,payload
                def wait():
                    deadline=time.monotonic()+15
                    while time.monotonic()<deadline:
                        code,payload=request('/api/state')
                        result=json.loads(payload)
                        if not result['busy']:
                            return result
                        time.sleep(.05)
                    self.fail('La tarea no terminó a tiempo')
                try:
                    self.assertEqual(request('/api/upload','POST',source.read_bytes())[0],200)
                    self.assertEqual(request('/api/export','POST',json.dumps({'start':0,'end':2,'watermark':False}))[0],202)
                    result=wait()
                    self.assertEqual(len(result['clips']),1,result['status'])
                    name=result['clips'][0]['name']
                    code,body=request('/clips/'+name)
                    self.assertEqual(code,200)
                    self.assertGreater(len(body),1000)
                    self.assertEqual(request('/api/trash','POST',json.dumps({'name':name}))[0],200)
                    self.assertEqual(len(wait()['trash']),1)
                    self.assertEqual(request('/clips/'+name)[0],404)
                    self.assertEqual(request('/api/restore','POST',json.dumps({'name':name}))[0],200)
                    self.assertEqual(len(wait()['clips']),1)
                    self.assertEqual(request('/clips/'+name)[0],200)
                finally:
                    srv.shutdown()
                    srv.server_close()

    def test_real_segment_capture_and_parallel_queue(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'input.mp4'
            subprocess.run([FFMPEG,'-v','error','-y','-f','lavfi','-i','color=s=320x180:r=10:d=12','-f','lavfi','-i','sine=duration=12','-c:v','libx264','-g','10','-c:a','aac','-shortest',str(source)],check=True,timeout=30)
            captured=[]
            def consume(path, options, stop):
                result = subprocess.run([FFPROBE,'-v','error','-show_entries','format=duration','-of','json',str(path)],stdout=subprocess.PIPE,check=True,timeout=10)
                self.assertGreater(float(json.loads(result.stdout)['format']['duration']),0)
                captured.append(path.name)
            c=LiveController(root/'data',lambda name:FFMPEG,consume,block_seconds=3,retry_seconds=.02)
            attempts=[]
            def resolve(url):
                attempts.append(url)
                if len(attempts)==1:
                    raise ValueError('Corte de conexión provocado por la prueba')
                return (str(source),) # Solo la prueba usa un archivo; producción exige YouTube.
            c._resolve=resolve
            c.start('https://youtu.be/test',{'watermark':False})
            deadline=time.monotonic()+15
            while len(captured)<2 and c.state['running'] and time.monotonic()<deadline:
                time.sleep(.1)
            c.stop()
            c.thread.join(15)
            self.assertFalse(c.thread.is_alive())
            self.assertGreaterEqual(len(captured),2,c.snapshot())
            self.assertGreaterEqual(len(attempts),2)
            self.assertFalse(c.state['running'])

    def test_capture_segments_with_separate_hls_tracks(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video, audio = root/'video.m3u8', root/'audio.m3u8'
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'color=s=320x180:r=10:d=8', '-an', '-c:v', 'libx264', '-g', '10',
                            '-f', 'hls', '-hls_time', '1', '-hls_list_size', '0', str(video)],
                           check=True, timeout=30)
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'sine=duration=8', '-vn', '-c:a', 'aac', '-f', 'hls',
                            '-hls_time', '1', '-hls_list_size', '0', str(audio)],
                           check=True, timeout=30)
            captured = []
            def consume(path, options, stop):
                result = subprocess.check_output([FFPROBE, '-v', 'error', '-show_entries',
                    'stream=codec_type', '-of', 'json', str(path)], timeout=10)
                captured.append({stream['codec_type'] for stream in json.loads(result)['streams']})
            controller = LiveController(root/'data', lambda name: FFMPEG, consume, block_seconds=3)
            controller._resolve = lambda url: (str(video), str(audio))
            controller.start('https://youtu.be/test', {'watermark':False})
            try:
                deadline = time.monotonic() + 15
                while len(captured) < 2 and controller.snapshot()['running'] and time.monotonic() < deadline:
                    time.sleep(.1)
                self.assertGreaterEqual(len(captured), 2, controller.snapshot())
                self.assertTrue(all(tracks == {'video', 'audio'} for tracks in captured), captured)
            finally:
                controller.stop()
                controller.thread.join(15)

    def test_fast_mode_changes_real_block_length(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.mp4'
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=s=96x64:r=2:d=310',
                            '-f', 'lavfi', '-i', 'sine=sample_rate=16000:duration=310',
                            '-c:v', 'libx264', '-g', '2', '-sc_threshold', '0', '-c:a', 'aac',
                            '-shortest', str(source)], check=True, timeout=45)
            for options, expected in (({}, 300), ({'fast_mode': True}, 60)):
                with self.subTest(expected=expected):
                    captured = []

                    def consume(block, settings, stop):
                        probe = json.loads(subprocess.check_output([FFPROBE, '-v', 'error', '-show_entries',
                            'format=duration:stream=codec_type', '-of', 'json', str(block)], timeout=10))
                        captured.append((probe, settings))

                    controller = LiveController(root / str(expected), lambda name: FFMPEG, consume, retry_seconds=30)
                    controller._resolve = lambda url: (str(source),)
                    controller.start('https://youtu.be/test', dict(options, clip_seconds=20, clips_per_block=1))
                    try:
                        deadline = time.monotonic() + 15
                        while not controller.snapshot()['processed'] and time.monotonic() < deadline:
                            time.sleep(.1)
                        state = controller.snapshot()
                        self.assertEqual(state['block_seconds'], expected)
                        self.assertIs(state['fast_mode'], expected == 60)
                        self.assertTrue(captured, state)
                        probe, settings = captured[0]
                        self.assertAlmostEqual(float(probe['format']['duration']), expected, delta=.75)
                        self.assertEqual({track['codec_type'] for track in probe['streams']}, {'audio', 'video'})
                        self.assertRegex(settings['capture_key'], r'^[0-9a-f]{16}$')
                        self.assertEqual({k: v for k, v in settings.items() if k != 'capture_key'},
                                         dict(options, clip_seconds=20, clips_per_block=1))
                    finally:
                        controller.stop()
                        controller.thread.join(15)

    def test_watermark_corners_audio_and_no_watermark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'source.mp4'
            def run(args):
                r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
                self.assertEqual(r.returncode, 0, r.stderr.decode(errors='replace')[-4000:])
                return r.stdout
            run([FFMPEG,'-y','-f','lavfi','-i','color=c=0x607080:s=640x360:r=10:d=35','-f','lavfi','-i','sine=frequency=440:duration=35','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)])
            probe = json.loads(run([FFPROBE,'-v','error','-show_format','-show_streams','-of','json',str(source)]))
            logo = Path(__file__).resolve().parents[1]/'web/logo-julio.jpg'
            marked, plain = root/'marked.mp4', root/'plain.mp4'
            for target, enabled in ((marked, True),(plain, False)):
                run(export_args(FFMPEG,source,target,1,34,probe,logo,enabled,0.30))
                output = json.loads(run([FFPROBE,'-v','error','-show_format','-show_streams','-of','json',str(target)]))
                self.assertAlmostEqual(float(output['format']['duration']),33,delta=.2)
                self.assertTrue(any(s['codec_type']=='audio' for s in output['streams']))
                self.assertTrue(any(s['codec_name']=='h264' and s['width']==640 for s in output['streams']))
            boxes = [(320,0,640,180),(320,180,640,360),(0,180,320,360),(0,0,320,180)]
            for t, expected in ((1,0),(9,1),(17,2),(25,3)):
                frames=[]
                for target in (marked,plain):
                    raw=run([FFMPEG,'-v','error','-ss',str(t),'-i',str(target),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'])
                    self.assertEqual(len(raw),640*360*3)
                    frames.append(raw)
                diff=bytes(abs(a-b) for a,b in zip(*frames))
                def energy(box):
                    x1,y1,x2,y2=box
                    return sum(sum(diff[(y*640+x1)*3:(y*640+x2)*3]) for y in range(y1,y2))
                energies=[energy(box) for box in boxes]
                self.assertEqual(energies.index(max(energies)),expected,energies)
                self.assertGreater(max(energies),1000)
                # Fuera de las esquinas no hay un fondo negro rectangular.
                self.assertLess(energy((200,100,440,260)),500)

if __name__ == '__main__':
    unittest.main(verbosity=2)
