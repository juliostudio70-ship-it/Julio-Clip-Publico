import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from library import MediaStore
from live import LiveController, NotLiveError, youtube_runtime_args
from watermark import settings, display_size, export_args

class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = MediaStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, i):
        name = 'clip-%012x.mp4' % i
        self.store.path(name).write_bytes(b'video')
        self.store.add({'name': name, 'start': 0, 'end': 5})
        return name

    def test_trash_restore_and_persistence(self):
        name = self.add(1)
        self.store.move(name, True)
        view = MediaStore(self.root).view()
        self.assertFalse(view['clips'])
        self.assertEqual(len(view['trash']), 1)
        self.store.move(name, False)
        self.assertEqual(self.store.view()['clips'][0]['name'], name)

    def test_trash_counts_toward_usage(self):
        name = self.add(1)
        self.store.move(name, True)
        self.assertGreaterEqual(self.store.usage(), 5)

    def test_block_removed_during_storage_count(self):
        missing=Mock()
        missing.is_file.return_value=True
        missing.is_symlink.return_value=False
        missing.stat.side_effect=FileNotFoundError()
        with patch.object(Path,'rglob',return_value=iter([missing])):
            self.assertEqual(self.store.usage(),0)

    def test_empty_requires_explicit_confirmation(self):
        name = self.add(2)
        self.store.move(name, True)
        for value in (False, None, 'true', 1):
            with self.assertRaises(ValueError):
                self.store.empty_trash(value)
        self.assertTrue(self.store.path(name, True).exists())
        self.store.empty_trash(True)
        self.assertFalse(self.store.path(name, True).exists())

    def test_oldest_retained_in_trash(self):
        self.store.configure(10, 1)
        first = self.add(1)
        self.add(2)
        self.assertEqual(len(self.store.view()['clips']), 1)
        self.assertEqual(self.store.view()['trash'][0]['name'], first)

    def test_outside_path_never_touched(self):
        for name in ('../original.mp4', '/tmp/test.mp4', 'clip-xyz.mp4'):
            with self.assertRaises(ValueError):
                self.store.path(name)

    def test_corrupt_index_is_not_silently_overwritten(self):
        self.store.index.write_text('{broken', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'dañada'):
            self.store.view()
        self.assertEqual(self.store.index.read_text(), '{broken')

    def test_disk_and_quota_failure(self):
        with patch.object(self.store, 'usage', return_value=11*1024**3):
            with self.assertRaisesRegex(ValueError, 'Límite'):
                self.store.check_space()
        with patch('library.shutil.disk_usage') as space:
            space.return_value.free = 1024**3
            with self.assertRaisesRegex(ValueError, 'reserva'):
                self.store.check_space()

    def test_invalid_config(self):
        for quota, count in ((0, 1), ('nan', 50), (10, 0), (10, 501)):
            with self.assertRaises(ValueError):
                self.store.configure(quota, count)

class WatermarkTests(unittest.TestCase):
    def test_settings_reject_untrusted_values(self):
        for p in ({'watermark': 'false'}, {'watermark_opacity': 'nan'}, {'watermark_opacity': 1}, {'watermark_opacity': 0}):
            with self.assertRaises(ValueError):
                settings(p)
        self.assertEqual(settings({'watermark': False})[0], False)

    def test_rotation_dimensions(self):
        self.assertEqual(display_size({'streams': [{'codec_type': 'video', 'width': 1920, 'height': 1080, 'side_data_list': [{'rotation': -90}]}]}), (1080, 1920))

    def test_no_logo_needed_when_disabled(self):
        args = export_args('ffmpeg', 'original.mp4', 'clip.mp4', 0, 5, {}, 'missing.jpg', False)
        self.assertNotIn('-filter_complex', args)
        self.assertNotIn('missing.jpg', args)

class LiveTests(unittest.TestCase):
    def test_quickjs_is_selected_before_node(self):
        self.assertEqual(youtube_runtime_args(lambda name:'/tools/'+name),['--js-runtimes','quickjs:/tools/qjs'])

    def test_node_fallback_is_explicit(self):
        self.assertEqual(youtube_runtime_args(lambda name:'/tools/node' if name=='node' else None),['--js-runtimes','node:/tools/node'])

    def test_no_js_runtime_is_reported(self):
        self.assertEqual(youtube_runtime_args(lambda name:None),[])
    def test_recorded_video_is_not_recaptured_forever(self):
        with tempfile.TemporaryDirectory() as root:
            c=LiveController(root,lambda name:'yt-dlp',lambda *args:None)
            with patch('live.subprocess.Popen') as proc:
                proc.return_value.returncode=0
                proc.return_value.communicate.return_value=(json.dumps({'is_live':False,'url':'https://media.example/video'}).encode(),b'')
                with self.assertRaises(NotLiveError):
                    c._resolve('https://youtu.be/abc')

    def test_live_metadata_resolves_single_stream(self):
        with tempfile.TemporaryDirectory() as root:
            c=LiveController(root,lambda name:'yt-dlp',lambda *args:None)
            with patch('live.subprocess.Popen') as proc:
                proc.return_value.returncode=0
                proc.return_value.communicate.return_value=(json.dumps({'is_live':True,'url':'https://media.example/live.m3u8'}).encode(),b'')
                self.assertEqual(c._resolve('https://youtu.be/abc'), ('https://media.example/live.m3u8',))

    def test_live_metadata_resolves_separate_hls_tracks(self):
        with tempfile.TemporaryDirectory() as root:
            c = LiveController(root, lambda name: 'yt-dlp', lambda *args: None)
            video = 'https://media.example/video.m3u8'
            audio = 'https://media.example/audio.m3u8'
            with patch('live.subprocess.Popen') as proc:
                proc.return_value.returncode = 0
                proc.return_value.communicate.return_value = (json.dumps({
                    'is_live': True, 'requested_formats': [{'url': video}, {'url': audio}],
                }).encode(), b'')
                self.assertEqual(c._resolve('https://youtu.be/abc'), (video, audio))
                args = proc.call_args.args[0]
                self.assertIn('bestvideo[protocol^=m3u8]+bestaudio[protocol^=m3u8]', args[args.index('-f') + 1])

    def test_missing_tool_does_not_start(self):
        with tempfile.TemporaryDirectory() as root:
            c = LiveController(root, lambda name: None, lambda *args: None)
            with self.assertRaisesRegex(ValueError, 'Falta'):
                c.start('https://youtu.be/abc', {})
            self.assertFalse(c.state['running'])

    def test_invalid_fast_mode_does_not_start(self):
        with tempfile.TemporaryDirectory() as root:
            c = LiveController(root, lambda name: 'tool', lambda *args: None)
            with self.assertRaisesRegex(ValueError, 'modo rápido'):
                c.start('https://youtu.be/abc', {'fast_mode': 'true'})
            self.assertFalse(c.snapshot()['running'])

    def test_completed_csv_only_and_resume(self):
        import hashlib
        with tempfile.TemporaryDirectory() as root:
            url = 'https://youtu.be/abc'
            folder = Path(root)/'live'/hashlib.sha256(url.encode()).hexdigest()[:16]/'job'
            folder.mkdir(parents=True)
            (folder/'opciones.json').write_text('{}')
            (folder/'segmentos.csv').write_text('bloque-00000000.mkv,0,5\n')
            (folder/'bloque-00000000.mkv').write_bytes(b'completed')
            (folder/'bloque-00000001.mkv').write_bytes(b'active, never in csv yet')
            received = []
            c = LiveController(root, lambda name: 'tool', lambda path, options, stop: received.append(path.name))
            self.assertEqual(len(c._entries(url)), 1)
            thread = threading.Thread(target=c._consumer, args=(url,), daemon=True)
            thread.start()
            for _ in range(100):
                if c.state['processed']:
                    break
                c.stop_event.wait(0.01)
            c.stop_event.set()
            thread.join(2)
            self.assertEqual(received, ['bloque-00000000.mkv'])
            self.assertEqual(c._entries(url), [])
            self.assertTrue((folder/'bloque-00000001.mkv').exists())

    def test_analysis_failure_preserves_block(self):
        import hashlib
        with tempfile.TemporaryDirectory() as root:
            url = 'https://youtu.be/abc'
            folder = Path(root)/'live'/hashlib.sha256(url.encode()).hexdigest()[:16]/'job'
            folder.mkdir(parents=True)
            (folder/'opciones.json').write_text('{}')
            (folder/'segmentos.csv').write_text('bloque-00000000.mkv,0,5\n')
            block = folder/'bloque-00000000.mkv'
            block.write_bytes(b'completed')
            def fail(*args):
                raise ValueError('Herramienta ausente')
            c = LiveController(root, lambda name: 'tool', fail)
            c._consumer(url)
            self.assertTrue(block.exists())
            self.assertTrue(c.stop_event.is_set())
            self.assertIn('ausente', c.state['status'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
