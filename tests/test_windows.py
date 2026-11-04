import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

from mirrormate.backup import restore_snapshot
from mirrormate.cli import main
from mirrormate.errors import MirrorMateError, PermissionDeniedError
from mirrormate.models import Mirror
from mirrormate.platform import UserContext, available_categories, invoking_user, require_root, user_config_path
from mirrormate.service import MirrorService


class WindowsSupportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        for patch in (mock.patch('mirrormate.platform.sys.platform', 'win32'),
                      mock.patch.dict(os.environ, {'USERPROFILE': str(self.home), 'USERNAME': 'tester',
                                                   'APPDATA': str(self.home / 'roaming')}, clear=True)):
            patch.start()
            self.addCleanup(patch.stop)
        self.user = UserContext('tester', None, None, self.home)
        self.service = MirrorService(catalog=[], user=self.user, root=self.home / 'root')

    def test_windows_user_does_not_require_posix_accounts(self):
        self.assertEqual(invoking_user(), self.user)
        self.assertEqual(available_categories(), ('python', 'npm', 'go'))

    def test_windows_paths_apply_and_restore_without_chown(self):
        expected = {'python': self.home / 'roaming/pip/pip.ini',
                    'go': self.home / 'roaming/go/env', 'npm': self.home / '.npmrc'}
        with mock.patch('os.chown', side_effect=AssertionError('POSIX ownership call'), create=True):
            for category, path in expected.items():
                with self.subTest(category=category):
                    self.assertEqual(user_config_path(category, self.user), path)
                    mirror = Mirror('new', category, 'New', url='https://mirror.example')
                    preview = self.service.apply(category, mirror, dry_run=True)
                    self.assertTrue(preview['diff'])
                    self.assertFalse(path.exists())
                    result = self.service.apply(category, mirror, backup=True)
                    self.assertEqual(self.service.status(category)['url'], mirror.url)
                    self.service.restore(result['backup_id'])
                    self.assertFalse(path.exists())

    def test_restore_preserves_existing_windows_config(self):
        path = user_config_path('python', self.user)
        path.parent.mkdir(parents=True)
        original = '[global]\ntimeout=45\nindex-url=https://old.example\n'
        path.write_text(original)
        result = self.service.apply('python', Mirror('new', 'python', 'New', url='https://new.example'), backup=True)
        self.assertIn('timeout = 45', path.read_text())
        self.service.restore(result['backup_id'])
        self.assertEqual(path.read_text(), original)

    def test_windows_backup_ids_reject_windows_path_syntax(self):
        for identifier in ('..\\escape', 'C:escape', 'folder\\file', '../escape'):
            with self.assertRaisesRegex(MirrorMateError, 'Invalid backup id'):
                restore_snapshot(identifier, user=self.user)

    def test_cli_default_status_and_unsupported_services(self):
        with mock.patch('mirrormate.cli.invoking_user', return_value=self.user):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(['status', '--json']), 0)
            self.assertEqual([row['type'] for row in json.loads(output.getvalue())], ['python', 'npm', 'go'])
            for category in ('apt', 'docker', 'homebrew'):
                error = io.StringIO()
                with redirect_stderr(error):
                    self.assertEqual(main(['set', category, '--url', 'https://mirror.example']), 2)
                self.assertIn('Windows', error.getvalue())

    def test_windows_admin_error_is_actionable(self):
        with mock.patch('mirrormate.platform.is_admin', return_value=False):
            with self.assertRaisesRegex(PermissionDeniedError, 'PowerShell as Administrator'):
                require_root('Installing')
