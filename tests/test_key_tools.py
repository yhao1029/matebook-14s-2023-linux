"""Synthetic tests: no real Windows volume or sensor access."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class KeyFlowTests(unittest.TestCase):
    def run_flow(self, answers, output):
        return subprocess.run(['bash', str(ROOT / 'scripts/acquire-key.sh'),
                               '/nonexistent/source', str(output)], input=answers,
                              text=True, capture_output=True, timeout=10)

    def test_manual_valid_and_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / 'synthetic key.bin'
            output = root / 'out.bin'
            key.write_bytes(bytes(range(32)))
            result = self.run_flow(f'n\n{key}\n', output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_bytes(), key.read_bytes())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            key.write_bytes(b'wrong length')
            self.assertNotEqual(self.run_flow(f'n\n{key}\n', root / 'invalid').returncode, 0)
            self.assertFalse((root / 'invalid').exists())

    def test_windows_consent_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out.bin'
            result = self.run_flow('y\ny\n1\nNO\n', output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('未获授权', result.stderr)
            self.assertFalse(output.exists())

    def test_windows_export_exclusive_write(self):
        spec = importlib.util.spec_from_file_location('exporter', ROOT / 'scripts/export-windows-key.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'existing.bin'
            path.write_bytes(b'keep')
            with self.assertRaises(FileExistsError):
                module.write_all(str(path), b'replacement')
            self.assertEqual(path.read_bytes(), b'keep')

    def test_installer_has_no_provisioning(self):
        text = (ROOT / 'scripts/matebook-biometrics.sh').read_text()
        self.assertNotIn('--upload-bb010002', text)
        self.assertNotIn('--build-bb010002', text)


if __name__ == '__main__':
    unittest.main()
