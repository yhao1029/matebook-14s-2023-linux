import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('windows_volume',
    Path(__file__).resolve().parents[1] / 'scripts/windows_volume.py')
volume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(volume)


class WindowsVolumeTests(unittest.TestCase):
    def make_windows(self, root, name):
        for relative in (f'{name}/SYSTEM32/CONFIG/system',
                         f'{name}/SYSTEM32/CONFIG/security',
                         'PROGRAMDATA/GOODIX/goodix_cache.BIN'):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic-not-a-secret')

    def test_windows_variants_and_all_components(self):
        for name in ('Windows', 'WINDOWS', 'windows'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_windows(root, name)
                self.assertEqual(len(volume.required_files(root)), 3)
                self.assertEqual(volume.resolve_path(root, 'Windows').name, name)

    def test_case_collision_and_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Windows').mkdir()
            (root / 'WINDOWS').mkdir()
            with self.assertRaises(ValueError):
                volume.resolve_path(root, 'windows')
            (root / 'outside').symlink_to(root.parent, target_is_directory=True)
            with self.assertRaises(ValueError):
                volume.resolve_path(root, 'outside')

    def test_default_candidate_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_windows(root, 'WINDOWS')
            rows = [dict(source='/dev/mock1', target=str(root), score=3, options='ro')]
            with patch.object(volume, 'mounted_volumes', return_value=rows), \
                 patch.object(volume.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')), \
                 patch('builtins.input', side_effect=['', 'YES']), \
                 patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(volume.choose_volume(), root.resolve())
            with patch.object(volume, 'mounted_volumes', return_value=rows), \
                 patch.object(volume.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')), \
                 patch('builtins.input', side_effect=['1', 'NO']), \
                 patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(ValueError):
                    volume.choose_volume()


if __name__ == '__main__':
    unittest.main()
