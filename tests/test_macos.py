import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

from mirrormate.backup import create_snapshot, restore_snapshot
from mirrormate.cli import main
from mirrormate.errors import MirrorMateError, UsageError
from mirrormate.models import Mirror
from mirrormate.platform import current_uid, current_gid, UserContext, available_categories, user_config_path
from mirrormate.service import MirrorService
from mirrormate.tui import Tui


class MacOSSupportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.user = UserContext("tester", current_uid(), current_gid(), self.home)
        platform_patch = mock.patch("mirrormate.platform.sys.platform", "darwin")
        platform_patch.start()
        self.addCleanup(platform_patch.stop)
        environment = mock.patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.service = MirrorService(catalog=[], user=self.user, root=self.home / "root")

    def test_pip_follows_directory_selection_and_preserves_settings(self):
        fallback = self.home / ".config/pip/pip.conf"
        self.assertEqual(user_config_path("python", self.user), fallback)
        native = self.home / "Library/Application Support/pip/pip.conf"
        native.parent.mkdir(parents=True)
        native.write_text("[global]\ntimeout = 45\nindex-url = https://old.example/simple\n")
        mirror = Mirror("new", "python", "New", url="https://new.example/simple")
        result = self.service.apply("python", mirror, backup=True)
        self.assertIn("timeout = 45", native.read_text())
        self.assertIn(mirror.url, native.read_text())
        self.assertFalse(fallback.exists())
        self.service.restore(result["backup_id"])
        self.assertIn("https://old.example/simple", native.read_text())

    def test_go_and_npm_apply_backup_and_restore_without_root(self):
        for category, relative, assignment in (
            ("go", "Library/Application Support/go/env", "GOPROXY"),
            ("npm", ".npmrc", "registry"),
        ):
            with self.subTest(category=category):
                path = self.home / relative
                mirror = Mirror("new", category, "New", url="https://new.example")
                with mock.patch("os.geteuid", return_value=self.user.uid, create=True):
                    result = self.service.apply(category, mirror, backup=True)
                    self.assertIn(f"{assignment}={mirror.url}", path.read_text())
                    self.assertEqual(self.service.status(category)["url"], mirror.url)
                    self.service.restore(result["backup_id"])
                self.assertFalse(path.exists())

    def test_restore_rejects_unrelated_file(self):
        unrelated = self.home / "unrelated"
        unrelated.write_text("original")
        identifier = create_snapshot("go", [unrelated], user=self.user)
        unrelated.write_text("current")
        with self.assertRaisesRegex(MirrorMateError, "outside the allowed area"):
            self.service.restore(identifier)
        self.assertEqual(unrelated.read_text(), "current")

    def test_restore_pip_fallback_after_native_directory_appears(self):
        path = self.home / ".config/pip/pip.conf"
        mirror = Mirror("new", "python", "New", url="https://new.example/simple")
        result = self.service.apply("python", mirror, backup=True)
        (self.home / "Library/Application Support/pip").mkdir(parents=True)
        self.service.restore(result["backup_id"])
        self.assertFalse(path.exists())

    def test_environment_configuration_paths_and_go_disabled(self):
        for category, variable in (("go", "GOENV"), ("npm", "NPM_CONFIG_USERCONFIG")):
            path = self.home / f"custom-{category}"
            with mock.patch.dict(os.environ, {variable: str(path)}):
                mirror = Mirror("new", category, "New", url="https://new.example")
                result = self.service.apply(category, mirror, backup=True)
                self.assertTrue(path.exists())
                self.service.restore(result["backup_id"])
                self.assertFalse(path.exists())
        with mock.patch.dict(os.environ, {"GOENV": "off"}):
            with self.assertRaisesRegex(UsageError, "GOENV=off"):
                self.service.status("go")

    def test_pip_xdg_data_directory(self):
        data = self.home / "data"
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(data)}):
            self.assertEqual(user_config_path("python", self.user), self.home / ".config/pip/pip.conf")
            (data / "pip").mkdir(parents=True)
            self.assertEqual(user_config_path("python", self.user), data / "pip/pip.conf")

    def test_cli_list_defaults_to_mac_services_but_catalog_keeps_all(self):
        mirrors = [Mirror(category, category, category, url="https://example.test")
                   for category in ("docker", "npm", "go")]
        with mock.patch("mirrormate.cli.invoking_user", return_value=self.user), mock.patch(
            "mirrormate.cli.load_catalogs", return_value=mirrors
        ):
            for command, expected in ((["list", "--json"], ["npm", "go"]),
                                      (["catalog", "list", "--json"], ["docker", "npm", "go"])):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(command), 0)
                self.assertEqual([row["type"] for row in json.loads(output.getvalue())], expected)

    def test_linux_paths_remain_supported(self):
        with mock.patch("mirrormate.platform.sys.platform", "linux"):
            self.assertEqual(user_config_path("python", self.user), self.home / ".config/pip/pip.conf")
            self.assertEqual(user_config_path("go", self.user), self.home / ".config/go/env")
            self.assertIn("apt", available_categories())

    def test_unsupported_services_fail_before_writing(self):
        for category, detail in (("apt", "Ubuntu or Debian"), ("docker", "Docker Desktop")):
            mirror = Mirror("new", category, "New", url="https://new.example")
            with self.assertRaisesRegex(UsageError, detail):
                self.service.apply(category, mirror)
        self.assertFalse(self.service.root.exists())

    def test_cli_status_defaults_and_explicit_platform_errors(self):
        with mock.patch("mirrormate.cli.invoking_user", return_value=self.user):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["status", "--json"]), 0)
            self.assertEqual([row["type"] for row in json.loads(output.getvalue())], ["python", "npm", "go", "homebrew"])
            for category in ("apt", "docker"):
                error = io.StringIO()
                with redirect_stderr(error):
                    self.assertEqual(main(["set", category, "--url", "https://new.example"]), 2)
                self.assertIn("macOS", error.getvalue())

    def test_dashboard_only_offers_supported_services(self):
        tui = Tui.__new__(Tui)
        tui.menu = mock.Mock(return_value=None)
        self.assertEqual(tui.run(), 0)
        choices = [key for key, label in tui.menu.call_args.args[1]]
        self.assertIn("go", choices)
        self.assertIn("homebrew", choices)
        self.assertNotIn("apt", choices)
        self.assertNotIn("docker", choices)



if __name__ == "__main__":
    unittest.main()
