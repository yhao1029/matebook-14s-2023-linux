import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import json

ROOT = Path(__file__).resolve().parents[1]
def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class EnrollmentTests(unittest.TestCase):
    def test_available_methods(self):
        manage = module('manage')
        for face, finger, expected in ((False, True, 'fingerprint'), (True, False, 'face'),
                                       (True, True, 'face,fingerprint'), (False, False, None)):
            with self.subTest(face=face, finger=finger), tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / 'config'
                result = subprocess.CompletedProcess([], 0,
                    'Using device\n - #0: right-index-finger\n' if finger else 'No devices', '')
                with patch.object(manage, 'CONFIG', config), \
                     patch.object(manage, 'registered_faces', return_value=[Path('synthetic.jpg')] if face else []), \
                     patch.object(manage.subprocess, 'run', return_value=result):
                    if expected is None:
                        with self.assertRaises(RuntimeError):
                            manage.configure_available_methods()
                    else:
                        self.assertEqual(manage.configure_available_methods(), expected)
                        data = json.loads((config/'config.yaml').read_text())
                        self.assertEqual(data['methods']['face']['enable'], face)
                        self.assertEqual(data['methods']['fingerprint']['enable'], finger)

    def test_confirmed_sample_exclusive(self):
        preview = module('face_preview')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'synthetic.jpg'
            preview.save_confirmed(target, b'synthetic sample')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                preview.save_confirmed(target, b'replacement')
            self.assertEqual(target.read_bytes(), b'synthetic sample')

    def test_reenable_preserves_original_backup(self):
        text = (ROOT/'scripts/enable-system.sh').read_text()
        self.assertIn('if ! $reenable; then cp -p', text)
        self.assertIn('tests+=(', text)


if __name__ == '__main__':
    unittest.main()
