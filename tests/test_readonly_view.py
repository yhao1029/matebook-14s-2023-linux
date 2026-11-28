"""Mock mount commands: never mount a real filesystem or inspect Windows."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/read-windows-key.sh'


class ReadonlyViewTests(unittest.TestCase):
    def run_view(self, *, same_namespace=False, fail_remount=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = {
                'id': 'echo 0',
                'readlink': 'echo child-ns',
                'mktemp': '/usr/bin/mktemp -d "$FIXTURE/view.XXXXXXXX"',
                'mount': 'printf "mount %s\\n" "$*" >> "$LOG"; '
                         'if [[ ${FAIL_REMOUNT:-} == yes && $1 == -o ]]; then exit 1; fi',
                'findmnt': 'echo ro,nosuid,nodev,noexec',
                'umount': 'printf "umount %s\\n" "$*" >> "$LOG"',
                'reader-python': 'printf "reader %s\\n" "$*" >> "$LOG"',
            }
            for name, body in commands.items():
                path = root / name
                path.write_text('#!/bin/bash\n' + body + '\n')
                path.chmod(0o700)
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                       FIXTURE=str(root), LOG=str(root / 'log'),
                       FAIL_REMOUNT='yes' if fail_remount else 'no')
            result = subprocess.run(['/bin/bash', str(SCRIPT),
                'child-ns' if same_namespace else 'parent-ns', '/mock/original Windows',
                str(root / 'reader-python'), '/mock/reader.py', '/mock/format.py', '/mock/out.bin'],
                env=env, text=True, capture_output=True, timeout=10)
            log = (root / 'log').read_text() if (root / 'log').exists() else ''
            return result, log

    def test_remount_only_temporary_view(self):
        result, log = self.run_view()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('mount --bind -- /mock/original Windows ', log)
        remount = next(line for line in log.splitlines() if line.startswith('mount -o'))
        self.assertIn('remount,bind,ro,nosuid,nodev,noexec', remount)
        self.assertNotIn('/mock/original Windows', remount)
        self.assertIn('reader ', log)
        self.assertIn('umount ', log)

    def test_refuses_original_namespace(self):
        result, log = self.run_view(same_namespace=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(log, '')

    def test_failed_readonly_remount_never_calls_reader(self):
        result, log = self.run_view(fail_remount=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('reader ', log)
        self.assertIn('umount ', log)


if __name__ == '__main__':
    unittest.main()
