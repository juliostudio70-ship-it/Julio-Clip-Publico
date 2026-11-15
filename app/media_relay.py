"""Entrega medios de YouTube a FFmpeg mediante HTTP local y HTTPS verificado."""
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import secrets
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener
from runtime_support import verified_tls_context


def is_youtube_media(url):
    try:
        parts = urlsplit(url)
        host = parts.hostname or ''
        return (parts.scheme == 'https' and parts.port in (None, 443)
                and parts.username is None and parts.password is None
                and (host == 'googlevideo.com' or host.endswith('.googlevideo.com')))
    except ValueError:
        return False


class MediaRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_youtube_media(newurl):
            raise URLError('Redirección fuera del servidor de medios de YouTube.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class MediaHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.headers.get('Host') != self.server.host:
            self.send_error(403)
            return
        url = self.server.source_for(self.path)
        if url is None:
            self.send_error(403)
            return
        headers = {'Accept-Encoding': 'identity'}
        byte_range = self.headers.get('Range', '')
        if re.fullmatch(r'bytes=\d+-\d*', byte_range):
            headers['Range'] = byte_range
        try:
            source = self.server.opener.open(Request(url, headers=headers), timeout=15)
        except HTTPError as error:
            with error:
                self.send_error(error.code)
            return
        except (OSError, ValueError):
            self.send_error(502)
            return

        with source:
            try:
                prefix = source.read(8)
                if prefix.startswith(b'#EXTM3U') or 'mpegurl' in source.headers.get('Content-Type', '').lower():
                    limit = 16 * 1024 * 1024
                    playlist = prefix + source.read(limit)
                    if len(playlist) >= limit:
                        raise ValueError('Lista de reproducción demasiado grande.')
                    body = self.server.playlist(playlist.decode('utf-8-sig'), source.url)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
            except ValueError:
                self.send_error(502)
                return
            except OSError:
                return

            try:
                self.send_response(source.status)
                for name in ('Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges'):
                    if name in source.headers:
                        self.send_header(name, source.headers[name])
                self.end_headers()
                self.wfile.write(prefix)
                while True:
                    chunk = source.read(128 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            except OSError:
                # FFmpeg puede cerrar una lectura al detener la captura.
                pass


class MediaRelay(ThreadingHTTPServer):
    def __init__(self):
        self.key = secrets.token_bytes(32)
        self.opener = build_opener(MediaRedirect(), HTTPSHandler(context=verified_tls_context()))
        super().__init__(('127.0.0.1', 0), MediaHandler)
        self.host = '127.0.0.1:%d' % self.server_port
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def local_url(self, source, fallback='.mp4'):
        if not is_youtube_media(source):
            raise ValueError('La lista de reproducción apunta fuera del servidor de medios de YouTube.')
        encoded = base64.urlsafe_b64encode(source.encode()).decode()
        signature = hmac.new(self.key, encoded.encode(), hashlib.sha256).hexdigest()
        suffix = re.search(r'\.(m3u8|m4s|mp4|m4a|ts|aac|webm|vtt|key)$', urlsplit(source).path, re.I)
        return 'http://%s/%s/%s/medio%s' % (self.host, signature, encoded, suffix.group(0) if suffix else fallback)

    def source_for(self, path):
        match = re.fullmatch(r'/([a-f0-9]{64})/([A-Za-z0-9_=\-]+)/medio\.[A-Za-z0-9]+', urlsplit(path).path)
        if not match:
            return None
        signature, encoded = match.groups()
        expected = hmac.new(self.key, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            source = base64.urlsafe_b64decode(encoded).decode()
        except ValueError:
            return None
        return source if is_youtube_media(source) else None

    def playlist(self, text, base):
        lines = []
        segment_extension = '.m4s' if '#EXT-X-MAP:' in text else '.ts'
        next_is_playlist = False
        for line in text.splitlines():
            if line.startswith('#'):
                if line.startswith('#EXT-X-STREAM-INF:'):
                    next_is_playlist = True
                extension = segment_extension
                if line.startswith(('#EXT-X-MEDIA:', '#EXT-X-I-FRAME-STREAM-INF:', '#EXT-X-RENDITION-REPORT:')):
                    extension = '.m3u8'
                if line.startswith('#EXT-X-MAP:'):
                    extension = '.mp4'
                line = re.sub(r'([,:]URI=")([^"]+)(")',
                              lambda match: match[1] + self.local_url(urljoin(base, match[2]), extension) + match[3],
                              line)
            elif line.strip():
                line = self.local_url(urljoin(base, line.strip()), '.m3u8' if next_is_playlist else segment_extension)
                next_is_playlist = False
            lines.append(line)
        return ('\n'.join(lines) + '\n').encode()

    def close(self):
        self.shutdown()
        self.server_close()
        self.thread.join()
