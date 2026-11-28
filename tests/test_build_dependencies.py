import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HELPER = Path(__file__).resolve().parents[1] / 'scripts/build-dependencies.sh'


class BuildDependenciesTests(unittest.TestCase):
    def run_preflight(self, answer, missing=True, broken_pc=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bodies = {
                'dpkg-query': 'if [[ $MISSING == yes && ${*: -1} == libgudev-1.0-dev ]]; then exit 1; fi; printf installed',
                'sudo': 'printf "%s\\n" "$*" >> "$LOG"',
                # Model Noble: normal .pc dependencies exist, doctest.pc does not.
                'pkg-config': '[[ $BROKEN_PC != yes && $* != *doctest* ]]',
            }
            for name, body in bodies.items():
                path = root / name
                path.write_text('#!/bin/bash\n' + body + '\n')
                path.chmod(0o700)
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                       LOG=str(root / 'log'), MISSING='yes' if missing else 'no',
                       BROKEN_PC='yes' if broken_pc else 'no')
            result = subprocess.run(['bash', '-c',
                'source "$1"; ensure_build_dependencies libglib2.0-dev libgudev-1.0-dev doctest-dev',
                'test', str(HELPER)], input=answer, text=True, capture_output=True, env=env, timeout=10)
            log = (root / 'log').read_text() if (root / 'log').exists() else ''
            return result, log

    def test_missing_gudev_installed_on_confirmation(self):
        result, log = self.run_preflight('YES\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('apt-get install --no-remove libgudev-1.0-dev', log)
        self.assertNotIn('libglib2.0-dev', log)

    def test_decline_never_runs_apt(self):
        result, log = self.run_preflight('NO\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(log, '')

    def test_installed_but_broken_pkgconfig_stops(self):
        result, log = self.run_preflight('', missing=False, broken_pc=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pkg-config', result.stderr)
        self.assertEqual(log, '')

    def test_ready_environment_no_apt(self):
        result, log = self.run_preflight('', missing=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log, '')

    def test_cmake_only_doctest_does_not_block_preflight(self):
        result, log = self.run_preflight('', missing=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Meson/CMake', result.stdout)
        self.assertEqual(log, '')


if __name__ == '__main__':
    unittest.main()
