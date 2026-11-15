import http.client
import io
from contextlib import closing
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from media_relay import MediaRelay, is_youtube_media


class MediaRelayTests(unittest.TestCase):
    def setUp(self):
        self.relay = MediaRelay()
        self.addCleanup(self.relay.close)

    def test_untrusted_hosts_and_schemes(self):
        for url in ('http://media.googlevideo.com/s.ts', 'https://media.googlevideo.com.evil/s.ts',
                    'https://127.0.0.1/s.ts', 'file:///C:/s.ts', 'https://media.googlevideo.com:444/s.ts'):
            with self.subTest(url=url):
                self.assertFalse(is_youtube_media(url))
                with self.assertRaises(ValueError):
                    self.relay.local_url(url)

    def test_playlist_rewrites_relative_media_and_rejects_external_reference(self):
        base = 'https://media.googlevideo.com/track/index.m3u8'
        rewritten = self.relay.playlist('#EXTM3U\n#EXTINF:6,\ns/001.ts\n', base).decode().splitlines()
        self.assertEqual(self.relay.source_for(urlsplit(rewritten[2]).path),
                         'https://media.googlevideo.com/track/s/001.ts')
        with self.assertRaises(ValueError):
            self.relay.playlist('#EXTM3U\n#EXT-X-MAP:URI="https://evil.example/init.mp4"\n', base)

    def test_loopback_endpoint_requires_signature_and_keeps_byte_range(self):
        url = 'https://media.googlevideo.com/track/segment.ts'
        path = urlsplit(self.relay.local_url(url)).path
        signature, encoded, filename = path.strip('/').split('/')
        other = 'a' if signature[0] != 'a' else 'b'
        altered = '/%s%s/%s/%s' % (other, signature[1:], encoded, filename)
        response = io.BytesIO(b'segment bytes')
        response.status = 206
        response.headers = {'Content-Type':'video/mp2t', 'Content-Length':'13', 'Content-Range':'bytes 0-12/30'}
        with patch.object(self.relay.opener, 'open', return_value=response) as upstream:
            with closing(http.client.HTTPConnection('127.0.0.1', self.relay.server_port, timeout=4)) as client:
                client.request('GET', altered)
                result = client.getresponse()
                self.assertEqual(result.status, 403)
                result.read()
                upstream.assert_not_called()
                client.request('GET', path, headers={'Range':'bytes=0-12'})
                result = client.getresponse()
                self.assertEqual(result.status, 206)
                self.assertEqual(result.getheader('Content-Range'), 'bytes 0-12/30')
                self.assertEqual(result.read(), b'segment bytes')
                self.assertEqual(upstream.call_args.args[0].get_header('Range'), 'bytes=0-12')
