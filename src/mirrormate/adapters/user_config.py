from __future__ import annotations

import configparser
import io
import os
import re
from pathlib import Path
from typing import Any

from ..errors import UsageError
from ..io import capture_file
from ..models import ChangePlan, Mirror, PlannedFile
from ..platform import user_config_path
from .base import Adapter


class UserConfigAdapter(Adapter):
    config_path: Path

    def _planned_file(self, content: str) -> PlannedFile:
        state = capture_file(self.config_path)
        return PlannedFile(
            path=self.config_path,
            content=content.encode("utf-8"),
            mode=state.mode if state.existed else 0o600,
            uid=self.user.uid,
            gid=self.user.gid,
        )

    def _read(self) -> str:
        try:
            return self.config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except (OSError, UnicodeDecodeError) as exc:
            raise UsageError(f"Cannot read {self.config_path}: {exc}") from exc


class PythonAdapter(UserConfigAdapter):
    category = "python"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config_path = user_config_path(self.category, self.user)

    def plan(self, mirror: Mirror, **options: Any) -> ChangePlan:
        if mirror.type != self.category or not mirror.url:
            raise UsageError("A Python mirror URL is required")
        parser = configparser.RawConfigParser()
        current = self._read()
        if current:
            try:
                parser.read_string(current)
            except configparser.Error as exc:
                raise UsageError(f"Cannot parse {self.config_path}: {exc}") from exc
        if not parser.has_section("global"):
            parser.add_section("global")
        parser.set("global", "index-url", mirror.url)
        buffer = io.StringIO()
        parser.write(buffer)
        return ChangePlan(
            self.category,
            mirror,
            [self._planned_file(buffer.getvalue())],
            f"Set pip index-url to {mirror.url}",
        )

    def status(self) -> dict[str, Any]:
        value = None
        parser = configparser.RawConfigParser()
        current = self._read()
        if current:
            try:
                parser.read_string(current)
                value = parser.get("global", "index-url", fallback=None)
            except configparser.Error:
                value = None
        return {"type": self.category, "path": str(self.config_path), "url": value}


def _replace_assignment(content: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=).*$", re.MULTILINE)
    replacement = rf"\g<1>{value}"
    if pattern.search(content):
        updated = pattern.sub(replacement, content)
    else:
        separator = "" if not content or content.endswith("\n") else "\n"
        updated = f"{content}{separator}{key}={value}\n"
    return updated


def _read_assignment(content: str, key: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*$", re.MULTILINE)
    match = pattern.search(content)
    return match.group(1) if match else None


class NpmAdapter(UserConfigAdapter):
    category = "npm"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config_path = user_config_path(self.category, self.user)

    def plan(self, mirror: Mirror, **options: Any) -> ChangePlan:
        if mirror.type != self.category or not mirror.url:
            raise UsageError("An NPM mirror URL is required")
        content = _replace_assignment(self._read(), "registry", mirror.url)
        return ChangePlan(
            self.category,
            mirror,
            [self._planned_file(content)],
            f"Set NPM registry to {mirror.url}",
        )

    def status(self) -> dict[str, Any]:
        return {
            "type": self.category,
            "path": str(self.config_path),
            "url": _read_assignment(self._read(), "registry"),
        }


class GoAdapter(UserConfigAdapter):
    category = "go"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config_path = user_config_path(self.category, self.user)

    def plan(self, mirror: Mirror, **options: Any) -> ChangePlan:
        if mirror.type != self.category or not mirror.url:
            raise UsageError("A Go proxy URL is required")
        content = _replace_assignment(self._read(), "GOPROXY", mirror.url)
        return ChangePlan(
            self.category,
            mirror,
            [self._planned_file(content)],
            f"Set GOPROXY to {mirror.url}",
        )

    def status(self) -> dict[str, Any]:
        return {
            "type": self.category,
            "path": str(self.config_path),
            "url": _read_assignment(self._read(), "GOPROXY"),
        }


class HomebrewAdapter(UserConfigAdapter):
    category = "homebrew"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config_path = user_config_path(self.category, self.user)

    @staticmethod
    def _set(content: str, key: str, value: str) -> str:
        # brew.env is a literal environment file, not a shell script. Normalize
        # every matching assignment to column zero so Homebrew loads it.
        lines = content.splitlines(keepends=True)
        pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=")
        lines = [line for line in lines if not pattern.match(line)]
        current = "".join(lines)
        separator = "" if not current or current.endswith("\n") else "\n"
        return f"{current}{separator}{key}={value}\n"

    def plan(self, mirror: Mirror, **options: Any) -> ChangePlan:
        if mirror.type != self.category or not mirror.url:
            raise UsageError("A Homebrew bottle mirror URL is required")
        content = self._set(self._read(), "HOMEBREW_BOTTLE_DOMAIN", mirror.url)
        summary = f"Set Homebrew bottle mirror to {mirror.url}"
        if mirror.api_url:
            content = self._set(content, "HOMEBREW_API_DOMAIN", mirror.api_url)
            summary += f" and API mirror to {mirror.api_url}"
        return ChangePlan(self.category, mirror, [self._planned_file(content)], summary)

    def activate(self, plan: ChangePlan, **options: Any) -> list[str]:
        warnings = []
        if not self.runner.which("brew"):
            warnings.append("Homebrew was not found on PATH; settings will apply once it is installed")
        if os.environ.get("HOMEBREW_ARTIFACT_DOMAIN") or _read_assignment(
            self._read(), "HOMEBREW_ARTIFACT_DOMAIN"
        ):
            warnings.append("HOMEBREW_ARTIFACT_DOMAIN can override the bottle mirror")
        warnings.append("Settings apply to the next brew command; system policy may override user settings")
        return warnings

    def status(self) -> dict[str, Any]:
        content = self._read()
        return {
            "type": self.category,
            "path": str(self.config_path),
            "url": _read_assignment(content, "HOMEBREW_BOTTLE_DOMAIN"),
            "api_url": _read_assignment(content, "HOMEBREW_API_DOMAIN"),
        }
