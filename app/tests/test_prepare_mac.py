from pathlib import Path
import ssl
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_mac import SecureDownloadRedirect, download, mac_target, safe_zip
from runtime_support import CA_BUNDLE, child_options, verified_tls_context

def macho(version):
    # Cabecera Intel 64 y LC_VERSION_MIN_MACOSX mínima, sin código ejecutable.
    header=struct.pack('<8I',0xfeedfacf,0x01000007,3,2,1,16,0,0)
    cmd=struct.pack('<4I',0x24,16,(version[0]<<16)|(version[1]<<8)|version[2],0)
    return header+cmd

class PrepareTests(unittest.TestCase):
    def test_certificate_bundle_works_without_system_roots(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.assertEqual(context.cert_store_stats()['x509_ca'], 0)
        with patch('runtime_support.ssl.create_default_context', return_value=context):
            self.assertIs(verified_tls_context(), context)
        self.assertGreater(context.cert_store_stats()['x509_ca'], 100)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_mac_child_gets_bundle_without_overriding_explicit_ca(self):
        with patch('runtime_support.os.name', 'posix'), patch('runtime_support.sys.platform', 'darwin'):
            with patch.dict('runtime_support.os.environ', {}, clear=True):
                self.assertEqual(child_options()['env']['SSL_CERT_FILE'], str(CA_BUNDLE))
            with patch.dict('runtime_support.os.environ', {'SSL_CERT_FILE': '/mi-ca.pem'}, clear=True):
                self.assertNotIn('env', child_options())

    def test_download_explains_certificate_failure_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp, patch('prepare_mac.build_opener') as opener:
            path = Path(tmp)/'ffmpeg.zip'
            path.write_bytes(b'anterior')
            opener.return_value.open.side_effect = URLError(ssl.SSLCertVerificationError('certificado no confiable'))
            with self.assertRaisesRegex(ValueError, 'certificado de evermeet.cx'):
                download('https://evermeet.cx/ffmpeg.zip', path)
            self.assertEqual(path.read_bytes(), b'anterior')
            self.assertFalse(path.with_suffix('.zip.part').exists())

    def test_download_rejects_downgrade_to_http(self):
        source = Request('https://example.com/ffmpeg.zip')
        with self.assertRaisesRegex(URLError, 'fuera de HTTPS'):
            SecureDownloadRedirect().redirect_request(source, None, 302, '', {}, 'http://example.com/ffmpeg.zip')

    def test_minimum_target_is_inspected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'binary'
            p.write_bytes(macho((10,9,0)))
            self.assertEqual(mac_target(p),(10,9,0))
            p.write_bytes(macho((10,13,6)))
            self.assertEqual(mac_target(p),(10,13,6))

    def test_new_macos_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'binary'
            p.write_bytes(macho((10,15,0)))
            with self.assertRaisesRegex(ValueError,'más nuevo'):
                mac_target(p)

    def test_exe_is_not_mistaken_for_mac_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'binary'
            p.write_bytes(b'MZ'+b'0'*40)
            with self.assertRaises(ValueError):
                mac_target(p)

    def test_unsafe_zip_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            zpath=root/'unsafe.zip'
            with zipfile.ZipFile(zpath,'w') as z:
                z.writestr('../escape.txt','bad')
            with self.assertRaises(ValueError):
                safe_zip(zpath,root/'destination')
            self.assertFalse((root/'escape.txt').exists())

if __name__=='__main__':
    unittest.main(verbosity=2)
