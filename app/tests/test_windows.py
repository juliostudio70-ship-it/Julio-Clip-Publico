import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comprobar_windows import verify_inventory
from runtime_support import default_data_dir

class WindowsTests(unittest.TestCase):
    def test_windows_storage_uses_local_appdata(self):
        self.assertEqual(default_data_dir('nt', {'LOCALAPPDATA': 'C:/Users/Julio/AppData/Local'}, 'C:/Users/Julio'),
                         Path('C:/Users/Julio/AppData/Local/Julio Clip'))

    def test_windows_storage_falls_back_without_environment(self):
        self.assertEqual(default_data_dir('nt', {}, 'C:/Users/Julio'), Path('C:/Users/Julio/AppData/Local/Julio Clip'))

    def test_mac_storage_is_preserved(self):
        self.assertEqual(default_data_dir('posix', {}, '/Users/Julio'), Path('/Users/Julio/Library/Application Support/Julio Clip'))

    def inventory(self, root):
        entries = {}
        for i in range(5):
            file = root / ('tool-%d.bin' % i)
            file.write_bytes(('tool-%d' % i).encode())
            entries[file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
        (root/'HERRAMIENTAS-SHA256.json').write_text(json.dumps(entries), encoding='utf-8')
        return entries

    def test_inventory_detects_partial_extraction_and_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.inventory(root)
            self.assertEqual(verify_inventory(root), 5)
            (root/'tool-0.bin').unlink()
            with self.assertRaisesRegex(ValueError, 'Falta tool-0'):
                verify_inventory(root)
            (root/'tool-0.bin').write_bytes(b'broken')
            with self.assertRaisesRegex(ValueError, 'incompleto o cambi'):
                verify_inventory(root)

    def test_inventory_rejects_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entries = self.inventory(root)
            entries = {'../outside.bin': 'anything', **entries}
            (root/'HERRAMIENTAS-SHA256.json').write_text(json.dumps(entries), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'fuera de'):
                verify_inventory(root)

    def test_alternative_engine_may_recover_only_optional_engine_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entries = self.inventory(root)
            entries['bin/whisper-cli.exe'] = 'missing'
            (root/'HERRAMIENTAS-SHA256.json').write_text(json.dumps(entries))
            self.assertEqual(verify_inventory(root, engine_optional=True), 6)
            with self.assertRaisesRegex(ValueError, 'Falta bin/whisper-cli'):
                verify_inventory(root)
            (root/'tool-1.bin').write_bytes(b'broken')
            with self.assertRaisesRegex(ValueError, 'incompleto o cambi'):
                verify_inventory(root, engine_optional=True)

if __name__ == '__main__':
    unittest.main(verbosity=2)
