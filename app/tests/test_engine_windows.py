import hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine_windows import Engines,category,version

class EngineTests(unittest.TestCase):
    def fixture(self,root):
        for name in ('bin/whisper-cli.exe','bin/whisper-respaldo/whisper-cli.exe','bin/whisper-respaldo/whisper.dll'):
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'verified-test-engine')
        (root/'VERSION.txt').write_text('2026.11.17.1')
        manifest={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'bin').rglob('*') if p.is_file()}
        (root/'HERRAMIENTAS-SHA256.json').write_text(json.dumps(manifest))
    def test_fallback_after_exact_missing_dll_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root);selector=Engines()
            def run(args,**kw):
                self.assertEqual(kw['timeout'],60)
                self.assertEqual(Path(args[0]).parent,kw['cwd'])
                return subprocess.CompletedProcess(args,0 if 'whisper-respaldo' in args[0] else -1073741515,b'',b'')
            with patch('engine_windows.subprocess.run',side_effect=run) as execute:
                self.assertIn('whisper-respaldo',selector.select(root))
                self.assertIn('whisper-respaldo',selector.select(root));self.assertEqual(execute.call_count,2)
            report=selector.report(root)
            self.assertEqual(report['checks'][0]['exit_code'],'0xC0000135')
            self.assertEqual(report['checks'][0]['reason'],'library')
            self.assertEqual(report['selected'],'respaldo')
            self.assertNotIn(str(root),json.dumps(report))
    def test_absent_primary_and_unmodified_alternative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root);(root/'bin/whisper-cli.exe').unlink()
            with patch('engine_windows.subprocess.run',return_value=subprocess.CompletedProcess([],0)) as run:
                selector=Engines();self.assertIn('whisper-respaldo',selector.select(root));self.assertEqual(run.call_count,1)
            self.assertEqual(selector.report(root)['checks'][0]['reason'],'missing')
    def test_tampered_motor_is_never_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root);(root/'bin/whisper-cli.exe').write_bytes(b'changed')
            (root/'bin/whisper-respaldo/whisper.dll').write_bytes(b'changed')
            with patch('engine_windows.subprocess.run') as run:
                selector=Engines();self.assertIsNone(selector.select(root));run.assert_not_called()
            self.assertTrue(all(r['reason']=='integrity' for r in selector.report(root)['checks']))
    def test_classifier_keeps_security_cpu_architecture_separate(self):
        for code,expected in [(577,'security'),(225,'security'),(0xc000001d,'cpu'),(193,'architecture'),(0xc0000142,'library'),(0xc0000017,'memory')]:
            self.assertEqual(category(code),expected)
    def test_both_fail_keep_the_actual_codes_and_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root);selector=Engines()
            with patch('engine_windows.subprocess.run',side_effect=OSError(193,'private path must not be shared')):
                self.assertIsNone(selector.select(root))
            report=selector.report(root);self.assertEqual(len(report['checks']),2)
            self.assertNotIn('private path',json.dumps(report))
    def test_timeout_tries_the_other_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root);selector=Engines()
            with patch('engine_windows.subprocess.run',side_effect=[subprocess.TimeoutExpired([],60),subprocess.CompletedProcess([],0)]):
                self.assertIn('whisper-respaldo',selector.select(root))
            self.assertEqual(selector.report(root)['checks'][0]['reason'],'timeout')
    def test_primary_is_preferred_when_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            with patch('engine_windows.subprocess.run',return_value=subprocess.CompletedProcess([],0)) as run:
                selector=Engines();self.assertEqual(selector.select(root),str((root/'bin/whisper-cli.exe').resolve()));self.assertEqual(run.call_count,1)
            self.assertEqual(version(root),'2026.11.17.1')

if __name__=='__main__':unittest.main()
