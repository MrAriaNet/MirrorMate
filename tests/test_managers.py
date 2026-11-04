import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipIf(sys.platform == 'win32', 'POSIX manager tests require /bin/sh')
class ManagerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'log'
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.defpath,
                        TEST_LOG=str(self.log), TEST_UID='0', TEST_OS='Linux')
        self.script('id', 'printf "%s\\n" "$TEST_UID"')
        self.script('uname', 'printf "%s\\n" "$TEST_OS"')

    def script(self, name, content):
        path = self.bin / name
        path.write_text('#!/bin/sh\nset -eu\n' + content + '\n')
        path.chmod(0o755)
        return path

    def run_script(self, name, *args):
        return subprocess.run(['/bin/sh', name, *args], env=self.env, text=True, capture_output=True)

    def test_all_unix_entrypoints_require_root_before_other_commands(self):
        self.env['TEST_UID'] = '1000'
        for name in ('install.sh', 'manager-mac.sh', 'manager-linux.sh'):
            with self.subTest(script=name):
                result = self.run_script(name)
                self.assertEqual(result.returncode, 77)
                self.assertIn('sudo', result.stderr)
                self.assertFalse(self.log.exists())

    def test_installer_dispatches_platform_and_forwards_action(self):
        self.script('curl', '''
while [ "$#" -gt 0 ]; do
    case "$1" in
        --output) destination=$2; shift 2 ;;
        https:*) url=$1; shift ;;
        *) shift ;;
    esac
done
printf '%s\\n' "$url" >> "$TEST_LOG"
printf '#!/bin/sh\\nprintf "action=%%s\\\\n" "$1" >> "$TEST_LOG"\\n' > "$destination"
''')
        for system, manager in (('Darwin', 'manager-mac.sh'), ('Linux', 'manager-linux.sh')):
            self.env['TEST_OS'] = system
            result = self.run_script('install.sh', 'update')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('/' + manager, self.log.read_text())
            self.assertIn('action=update', self.log.read_text())

    def test_failed_download_does_not_execute_manager(self):
        self.script('curl', 'exit 22')
        result = self.run_script('install.sh')
        self.assertEqual(result.returncode, 22)
        self.assertFalse(self.log.exists())

    def test_linux_checksum_and_lifecycle_commands(self):
        checksum = hashlib.sha256(b'package').hexdigest()
        self.env['TEST_CHECKSUM'] = checksum
        self.script('apt-get', 'printf "apt %s\\n" "$*" >> "$TEST_LOG"')
        self.script('dpkg-query', 'printf "dpkg %s\\n" "$*" >> "$TEST_LOG"')
        self.script('sha256sum', f'printf "{checksum}  %s\\n" "$1"')
        self.script('curl', '''
while [ "$#" -gt 0 ]; do
    case "$1" in
        --output) destination=$2; shift 2 ;;
        *) shift ;;
    esac
done
case "$destination" in
    *.sha256) printf '%s  mirrormate_all.deb\\n' "$TEST_CHECKSUM" > "$destination" ;;
    *) printf package > "$destination" ;;
esac
''')
        self.assertEqual(self.run_script('manager-linux.sh', 'install').returncode, 0)
        self.assertIn('apt install -y', self.log.read_text())
        self.log.unlink()
        self.env['TEST_CHECKSUM'] = 'invalid'
        rejected = self.run_script('manager-linux.sh', 'update')
        self.assertEqual(rejected.returncode, 1)
        self.assertIn('checksum', rejected.stderr)
        self.assertFalse(self.log.exists())
        self.assertEqual(self.run_script('manager-linux.sh', 'uninstall').returncode, 0)
        self.assertIn('apt remove -y mirrormate', self.log.read_text())
        self.assertEqual(self.run_script('manager-linux.sh', 'status').returncode, 0)
        self.assertIn('dpkg -W mirrormate', self.log.read_text())

    def test_mac_install_update_status_uninstall_in_sandbox(self):
        self.env['TEST_OS'] = 'Darwin'
        install = self.root / 'application'
        link = self.root / 'mirrormate'
        # Exercise the real script with its two system destinations sandboxed.
        source = Path('manager-mac.sh').read_text().replace(
            "INSTALL_DIR='/Library/Application Support/MirrorMate'", f"INSTALL_DIR='{install}'"
        ).replace("LINK='/usr/local/bin/mirrormate'", f"LINK='{link}'").replace(
            'mkdir -p "$INSTALL_DIR" /usr/local/bin', 'mkdir -p "$INSTALL_DIR"'
        )
        manager = self.root / 'manager-mac.sh'
        manager.write_text(source)
        python = self.script('fake-python', '''
if [ "$1" = '-c' ]; then exit 0; fi
if [ "$1" = '-m' ] && [ "$2" = venv ]; then
    mkdir -p "$3/bin"
    printf '#!/bin/sh\\nprintf "pip %%s\\\\n" "$*" >> "$TEST_LOG"\\n' > "$3/bin/python"
    printf '#!/bin/sh\\nprintf "MirrorMate test\\\\n"\\n' > "$3/bin/mirrormate"
    chmod +x "$3/bin/python" "$3/bin/mirrormate"
fi
''')
        self.env['MIRRORMATE_PYTHON'] = str(python)
        for action in ('install', 'update', 'status'):
            result = self.run_script(str(manager), action)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(link.is_symlink())
        self.assertIn('pip -m pip install --upgrade', self.log.read_text())
        self.assertEqual(self.run_script(str(manager), 'uninstall').returncode, 0)
        self.assertFalse(install.exists())
        self.assertFalse(link.exists())
        install.mkdir()
        refused = self.run_script(str(manager), 'uninstall')
        self.assertNotEqual(refused.returncode, 0)
        self.assertTrue(install.exists())
