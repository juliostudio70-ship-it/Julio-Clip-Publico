import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as app

class Tests(unittest.TestCase):
    def test_cancelled_tool_is_terminated(self):
        import time
        event=threading.Event()
        event.set()
        start=time.monotonic()
        with self.assertRaisesRegex(ValueError,'detenida'):
            app.run([sys.executable,'-c','import time; time.sleep(20)'],cancel=event)
        self.assertLess(time.monotonic()-start,5)

    def test_progress_is_received_before_a_cancelled_tool_exits(self):
        event = threading.Event()
        seen = []
        def progress(line):
            seen.append(line.strip())
            event.set()
        with self.assertRaisesRegex(ValueError, 'detenida'):
            app.run([sys.executable, '-c', 'import sys,time; print("progress = 25%", file=sys.stderr, flush=True); time.sleep(30)'],
                    timeout=8, cancel=event, on_line=progress)
        self.assertEqual(seen, [b'progress = 25%'])
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        app.DATA = Path(cls.tmp.name)
        cls.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.port = cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def request(self, path, method='GET', body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port)
        c.request(method, path, body, headers or {})
        r = c.getresponse()
        result = (r.status, r.read(), dict(r.getheaders()))
        c.close()
        return result

    def auth(self):
        return {'Origin': 'http://127.0.0.1:%s' % self.port, 'X-Julio-Token': app.TOKEN}

    def test_static_assets(self):
        for name in ('/', '/app.js', '/style.css', '/logo-julio.jpg', '/poster.svg', '/bridge.html', '/bridge.js'):
            status, body, headers = self.request(name)
            self.assertEqual(status, 200)
            self.assertTrue(body)
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])

    def test_dns_rebinding_blocked(self):
        self.assertEqual(self.request('/api/session', headers={'Host': 'attacker.example'})[0], 403)

    def test_cross_origin_blocked(self):
        h = self.auth()
        h['Origin'] = 'https://example.netlify.app'
        self.assertEqual(self.request('/api/upload', 'POST', b'abc', h)[0], 403)

    def test_token_required(self):
        self.assertEqual(self.request('/api/analyze', 'POST', b'{}')[0], 403)

    def test_traversal_blocked(self):
        self.assertEqual(self.request('/../server.py')[0], 404)
        self.assertEqual(self.request('/clips/../../server.py')[0], 404)

    def test_upload_and_state(self):
        with patch.object(app,'inspect_media',return_value={'format':{'duration':'12'},'streams':[{'codec_type':'video'}]}):
            self.assertEqual(self.request('/api/upload', 'POST', b'test-video', self.auth())[0], 200)
        self.assertEqual((app.DATA / 'imported.video').read_bytes(), b'test-video')
        state = json.loads(self.request('/api/state')[1])
        self.assertIs(state['source'], True)
        self.assertNotIn(str(app.DATA), json.dumps(state))

    def test_busy_rejects_upload(self):
        app.LOCK.acquire()
        try:
            self.assertEqual(self.request('/api/upload', 'POST', b'abc', self.auth())[0], 409)
        finally:
            app.LOCK.release()

    def test_old_clip_can_move_to_trash_and_restore_while_processing(self):
        name = 'clip-123456789abc.mp4'
        with tempfile.TemporaryDirectory() as root, patch.object(app, 'DATA', Path(root)):
            store = app.MediaStore(app.DATA)
            store.path(name).write_bytes(b'video')
            store.add({'name': name, 'start': 0, 'end': 20})
            with app.LOCK:
                self.assertEqual(self.request('/api/trash', 'POST', json.dumps({'name':name}), self.auth())[0], 200)
                self.assertEqual(store.view()['clips'], [])
                self.assertEqual(store.view()['trash'][0]['name'], name)
                self.assertEqual(self.request('/api/restore', 'POST', json.dumps({'name':name}), self.auth())[0], 200)
                self.assertEqual(store.path(name).read_bytes(), b'video')

    def test_published_cancel_targets_current_job_without_stopping_live(self):
        job = app.PublishedJob('export')
        with patch.object(app, 'PUBLISHED_JOB', job), patch.object(app, 'live') as live:
            self.assertEqual(self.request('/api/published-cancel', 'POST', '{"id":"old"}', self.auth())[0], 409)
            with app.LOCK:
                self.assertEqual(self.request('/api/published-cancel', 'POST', json.dumps({'id':job.id}), self.auth())[0], 200)
            self.assertTrue(job.cancel.is_set())
            self.assertEqual(job.snapshot()['status'], 'cancelling')
            live.assert_not_called()

    def test_invalid_bounds(self):
        self.assertEqual(app.bounds(15, 75), (15, 75))
        for a, b in ((-1, 2), (2, 1), (0, 180.1), ('nan', 2), (0, 'inf')):
            with self.assertRaises(ValueError):
                app.bounds(a, b)

    def test_youtube_domains(self):
        for url in ('http://youtube.com/a', 'https://youtube.com.evil.org', 'https://localhost', 'https://user@youtube.com/a'):
            with self.assertRaises(ValueError):
                app.youtube_url(url)
        self.assertEqual(app.youtube_url('https://youtu.be/abc'), 'https://youtu.be/abc')

    def test_published_links_restrict_platforms_and_individual_videos(self):
        youtube = ('https://www.youtube.com/watch?v=abc&list=playlist', 'https://youtu.be/abc',
                   'https://www.youtube.com/shorts/abc', 'https://www.youtube.com/live/abc')
        tiktok = ('https://www.tiktok.com/@video.user/video/12345', 'https://www.tiktok.com/t/Z123/',
                  'https://vm.tiktok.com/Z123/', 'https://vt.tiktok.com/Z123/')
        for expected, links in (('YouTube', youtube), ('TikTok', tiktok)):
            for link in links:
                self.assertEqual(app.published_platform(link), expected)
        for link in ('https://www.tiktok.com/@video.user/live', 'https://www.tiktok.com/@video.user',
                     'https://www.youtube.com/playlist?list=abc', 'https://www.youtube.com/watch?list=abc',
                     'https://vm.tiktok.com.evil.test/Z123', 'https://user@vm.tiktok.com/Z123',
                     'https://vm.tiktok.com:443/Z123', 'http://vt.tiktok.com/Z123',
                     'https://127.0.0.1/video.mp4'):
            with self.subTest(link=link):
                self.assertEqual(self.request('/api/youtube', 'POST', json.dumps({'url': link}), self.auth())[0], 400)
        self.assertEqual(self.request('/api/live-start', 'POST', json.dumps({'url': tiktok[0]}), self.auth())[0], 400)

    def test_failed_published_import_preserves_previous_source(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            previous = data/'imported.video'
            previous.write_bytes(b'video anterior')
            (data/'source.mp4').write_bytes(b'descarga antigua')
            state = dict(source=str(previous), source_duration=3, source_platform='YouTube')
            with patch.object(app, 'DATA', data), patch.object(app, 'STATE', state), patch.object(app, 'run'):
                with self.assertRaisesRegex(ValueError, 'No se descargó'):
                    app.import_published('https://www.tiktok.com/@cuenta/video/12345')
                self.assertEqual(state['source_platform'], 'YouTube')
                self.assertEqual(previous.read_bytes(), b'video anterior')
                self.assertFalse(list(data.glob('importando-*')))

    def test_suggested_range_fits_short_video(self):
        transcript = {'transcription': [{'offsets': {'from': 1000, 'to': 2500}, 'text': '¡Un momento!'}]}
        [pick] = app.propose(transcript, duration=3)
        self.assertEqual((pick['start'], pick['end']), (0, 3))

    def test_suggestions_nonoverlap(self):
        data = {'transcription': [{'offsets': {'from': i*30000, 'to': i*30000+10000}, 'text': 'Importante: cómo hacerlo'} for i in range(10)]}
        picks = app.propose(data)
        self.assertLessEqual(len(picks), 6)
        self.assertTrue(all(x['end'] <= y['start'] for x, y in zip(picks, picks[1:])))

    def test_live_settings_reach_controller(self):
        url = 'https://youtu.be/abc'
        with patch.object(app, 'live') as live:
            for settings in ({'clip_seconds': 40, 'clips_per_block': 10, 'fast_mode': True,
                              'profile': 'sports'}, {}):
                payload = {'url': url, **settings}
                self.assertEqual(self.request('/api/live-start', 'POST', json.dumps(payload), self.auth())[0], 200)
                live.return_value.start.assert_called_with(url, {
                    'url': url, 'clip_seconds': 30, 'clips_per_block': 2, **settings,
                })
            invalid = json.dumps({'url': url, 'profile': 'invalid'})
            self.assertEqual(self.request('/api/live-start', 'POST', invalid, self.auth())[0], 400)

    def test_split_is_kick_only_and_crops_are_checked_before_capture(self):
        split = {'camera': [72, 68, 28, 32], 'game': [0, 0, 72, 100]}
        options = {'url': 'https://www.kick.com/TuCanal/?utm_source=prueba', 'format': 'vertical', 'split': split}
        with patch.object(app, 'live') as live:
            response = self.request('/api/live-start', 'POST', json.dumps(options), self.auth())
            self.assertEqual(response[0], 200, response[1])
            url, payload = live.return_value.start.call_args.args
            self.assertEqual(url, 'https://kick.com/tucanal')
            self.assertEqual(payload['platform'], 'Kick')
            self.assertEqual(payload['split'], split)
            live.reset_mock()
            for invalid in (dict(options, url='https://youtu.be/abc'), dict(options, format='square'),
                            dict(options, split=dict(split, camera=[99, 0, 5, 5])),
                            dict(options, url='https://kick.com/tucanal/videos')):
                response = self.request('/api/live-start', 'POST', json.dumps(invalid), self.auth())
                self.assertEqual(response[0], 400, response[1])
            live.assert_not_called()
            response = self.request('/api/export', 'POST', json.dumps(dict(options, start=0, end=20)), self.auth())
            self.assertEqual(response[0], 400)

    def test_kick_preview_is_authenticated_and_returns_image(self):
        with patch.object(app, 'kick_preview', return_value=b'\xff\xd8fixture') as preview:
            body = json.dumps({'url': 'https://kick.com/canal'})
            self.assertEqual(self.request('/api/kick-preview', 'POST', body)[0], 403)
            code, jpeg, headers = self.request('/api/kick-preview', 'POST', body, self.auth())
            self.assertEqual((code, jpeg, headers['Content-Type']), (200, b'\xff\xd8fixture', 'image/jpeg'))
            self.assertIn("img-src 'self' data: blob:", headers['Content-Security-Policy'])
            preview.assert_called_once_with('https://kick.com/canal')

    def test_public_routes_reject_private_operations(self):
        with patch.object(app, 'PUBLIC', True):
            for action in ('upload', 'youtube', 'analyze', 'export', 'edit', 'clip-info'):
                response = self.request('/api/' + action, 'POST', '{}', self.auth())
                self.assertEqual(response[0], 403, action)

    def test_bad_live_settings_never_start_capture(self):
        with patch.object(app, 'live') as live:
            for settings in ({'clip_seconds': 21}, {'clip_seconds': '20'}, {'clip_seconds': 60.0},
                             {'clips_per_block': 51}, {'clips_per_block': 0}, {'clips_per_block': True},
                             {'clips_per_block': None}):
                payload = {'url': 'https://youtu.be/abc', **settings}
                with self.subTest(settings=settings):
                    status, body, _ = self.request('/api/live-start', 'POST', json.dumps(payload), self.auth())
                    self.assertEqual(status, 400)
                    self.assertIn('Elige', json.loads(body)['error'])
            live.assert_not_called()

    def test_auto_picks_highest_scores_first_without_overlaps(self):
        starts = (10, 32, 54, 76, 98, 120, 142, 164, 186, 208, 230, 252, 296)
        data = {'transcription': [
            {'offsets': {'from': start*1000, 'to': (start+1)*1000}, 'text': 'Momento' + '!'*i}
            for i, start in enumerate(starts)
        ]}
        for seconds in (20, 30, 40, 50, 60):
            with self.subTest(seconds=seconds):
                picks = app.propose(data, duration=300, seconds=seconds, limit=10)
                self.assertLessEqual(len(picks), min(10, 300//seconds))
                if seconds == 20:
                    self.assertEqual(len(picks), 10)
                self.assertEqual(picks[0]['end'], 300)
                self.assertEqual(picks[0]['score'], len(starts)-1)
                self.assertEqual(app.propose(data, duration=300, seconds=seconds, limit=1), picks[:1])
                self.assertTrue(all(p['end']-p['start'] == seconds for p in picks))
                ordered = sorted(picks, key=lambda p: p['start'])
                self.assertTrue(all(x['end'] <= y['start'] for x, y in zip(ordered, ordered[1:])))

    def test_short_or_silent_live_block_can_produce_no_clips(self):
        data = {'transcription': [{'offsets': {'from': 0, 'to': 10000}, 'text': '¡Hola!'}]}
        self.assertEqual(app.propose(data, duration=19, seconds=20, limit=10), [])
        self.assertEqual(app.propose({}, duration=300, seconds=30, limit=10), [])

    def test_legacy_queue_keeps_clip_order_under_new_duration_limit(self):
        data = {'transcription': [
            {'offsets': {'from': 10000, 'to': 60000}, 'text': '¡Importante!'},
            {'offsets': {'from': 71000, 'to': 76000}, 'text': 'Otro momento'},
            {'offsets': {'from': 98000, 'to': 103000}, 'text': 'Un cierre'},
        ]}
        picks = app.propose(data)
        self.assertEqual([(p['start'], p['end']) for p in picks], [(8, 80), (96, 123)])

if __name__ == '__main__':
    unittest.main(verbosity=2)
