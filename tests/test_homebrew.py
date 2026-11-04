import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

from mirrormate.backup import create_snapshot
from mirrormate.benchmark import benchmark_mirrors, probe_urls
from mirrormate.catalog import normalize_entry, mutate_custom_catalog, load_catalogs
from mirrormate.cli import main
from mirrormate.errors import CatalogError, MirrorMateError, UsageError
from mirrormate.models import Mirror
from mirrormate.platform import current_uid, current_gid, UserContext, user_config_path, available_categories
from mirrormate.service import MirrorService


class HomebrewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.user = UserContext('tester', current_uid(), current_gid(), self.home)
        for patch in (mock.patch('mirrormate.platform.sys.platform', 'darwin'),
                      mock.patch.dict(os.environ, {}, clear=True)):
            patch.start()
            self.addCleanup(patch.stop)
        self.service = MirrorService(catalog=[], user=self.user, root=self.home / 'root')
        self.mirror = Mirror('brew-new', 'homebrew', 'New', url='https://bottles.example',
                             api_url='https://api.example/api')
        self.path = self.home / '.homebrew/brew.env'

    def test_apply_preserves_unrelated_lines_and_restore_original(self):
        self.path.parent.mkdir()
        original = ('# My settings\nHOMEBREW_NO_ANALYTICS=1\n'
                    'HOMEBREW_BOTTLE_DOMAIN=https://old.example\n'
                    'HOMEBREW_BOTTLE_DOMAIN=https://duplicate.example\n'
                    'HOMEBREW_API_DOMAIN=https://old-api.example\n')
        self.path.write_text(original)
        result = self.service.apply('homebrew', self.mirror, backup=True)
        content = self.path.read_text()
        self.assertIn('# My settings\nHOMEBREW_NO_ANALYTICS=1', content)
        self.assertEqual(content.count('HOMEBREW_BOTTLE_DOMAIN='), 1)
        self.assertIn('HOMEBREW_BOTTLE_DOMAIN=https://bottles.example\n', content)
        self.assertIn('HOMEBREW_API_DOMAIN=https://api.example/api\n', content)
        self.assertEqual(self.service.status('homebrew')['api_url'], self.mirror.api_url)
        self.service.restore(result['backup_id'])
        self.assertEqual(self.path.read_text(), original)

    def test_dry_run_then_apply_and_restore_absent_file(self):
        preview = self.service.apply('homebrew', self.mirror, dry_run=True)
        self.assertIn('HOMEBREW_BOTTLE_DOMAIN=', preview['diff'])
        self.assertFalse(self.path.exists())
        result = self.service.apply('homebrew', self.mirror, backup=True)
        self.assertTrue(self.path.exists())
        self.service.restore(result['backup_id'])
        self.assertFalse(self.path.exists())

    def test_bottle_only_keeps_existing_api_mirror(self):
        self.path.parent.mkdir()
        self.path.write_text('HOMEBREW_API_DOMAIN=https://old-api.example\n')
        self.service.apply('homebrew', Mirror('bottle', 'homebrew', 'Bottle', url='https://new.example'))
        self.assertIn('HOMEBREW_API_DOMAIN=https://old-api.example\n', self.path.read_text())

    def test_xdg_paths_and_backup_allowlist(self):
        for variable in ('XDG_CONFIG_HOME', 'HOMEBREW_XDG_CONFIG_HOME'):
            with mock.patch.dict(os.environ, {variable: str(self.home / variable)}):
                path = user_config_path('homebrew', self.user)
                self.assertEqual(path, self.home / variable / 'homebrew/brew.env')
                result = self.service.apply('homebrew', self.mirror, backup=True)
                self.service.restore(result['backup_id'])
                self.assertFalse(path.exists())
        unrelated = self.home / '.zshrc'
        unrelated.write_text('original')
        identifier = create_snapshot('homebrew', [unrelated], user=self.user)
        unrelated.write_text('current')
        with self.assertRaisesRegex(MirrorMateError, 'outside the allowed area'):
            self.service.restore(identifier)
        self.assertEqual(unrelated.read_text(), 'current')

    def test_catalog_roundtrip_and_api_field_validation(self):
        entry = self.mirror.to_dict()
        entry.pop('source')
        mirror = normalize_entry(entry)
        mutate_custom_catalog([mirror], user=self.user)
        self.assertEqual(next(item for item in load_catalogs(self.user) if item.id == mirror.id).api_url,
                         mirror.api_url)
        for invalid in (dict(entry, api_url='file:///tmp/foo'), dict(entry, type='npm')):
            with self.assertRaises(CatalogError):
                normalize_entry(invalid)

    def test_cli_apply_official_reset_and_invalid_api_option(self):
        with mock.patch('mirrormate.cli.invoking_user', return_value=self.user):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main(['set', 'homebrew', '--url', self.mirror.url,
                             '--api-url', self.mirror.api_url, '--backup'])
                self.assertEqual(code, 0)
                self.assertEqual(main(['set', 'homebrew', '--mirror', 'homebrew-official']), 0)
            self.assertIn('HOMEBREW_BOTTLE_DOMAIN=https://ghcr.io/v2/homebrew/core', self.path.read_text())
            self.assertIn('HOMEBREW_API_DOMAIN=https://formulae.brew.sh/api', self.path.read_text())
            for args in (['set', 'npm', '--url', 'https://npm.example', '--api-url', 'https://api.example'],
                         ['set', 'homebrew', '--mirror', 'homebrew-official', '--api-url', 'https://api.example']):
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(main(args), 2)

    def test_linux_hides_homebrew_and_rejects_apply(self):
        with mock.patch('mirrormate.platform.sys.platform', 'linux'):
            self.assertNotIn('homebrew', available_categories())
            with self.assertRaisesRegex(UsageError, 'macOS only'):
                self.service.apply('homebrew', self.mirror)
        self.assertFalse(self.path.exists())

    def test_benchmark_requires_bottle_probe_and_tests_api_too(self):
        result = benchmark_mirrors([self.mirror], attempts=1)[0]
        self.assertFalse(result.healthy)
        self.assertIn('probe_url', result.error)
        mirror = Mirror('brew', 'homebrew', 'Brew', url=self.mirror.url,
                        api_url=self.mirror.api_url, probe_url='https://bottles.example/test-bottle')
        urls = probe_urls(mirror)
        self.assertEqual(urls, ['https://bottles.example/test-bottle', 'https://api.example/api/formula/zlib.json'])
        def probe(url, timeout, category):
            if 'api.example' in url:
                raise OSError('API unavailable')
            return 10
        self.assertFalse(benchmark_mirrors([mirror], attempts=1, probe=probe)[0].healthy)


if __name__ == '__main__':
    unittest.main()
