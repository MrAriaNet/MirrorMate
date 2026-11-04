from __future__ import annotations

import os
import platform as std_platform
try:
    import pwd
except ImportError:  # Windows has no POSIX account database.
    pwd = None
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import PermissionDeniedError, UsageError
from .models import DISTROS, MIRROR_TYPES, DistroInfo


SUPPORTED_RELEASES = {
    "ubuntu": {"22.04", "24.04", "26.04"},
    "debian": {"12", "13"},
}


@dataclass(frozen=True, slots=True)
class UserContext:
    name: str
    uid: int | None
    gid: int | None
    home: Path


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return sys.platform == "win32"


def current_uid() -> int | None:
    return getattr(os, "getuid", lambda: None)()


def current_gid() -> int | None:
    return getattr(os, "getgid", lambda: None)()


def is_root() -> bool:
    return not is_windows() and getattr(os, "geteuid", lambda: -1)() == 0


def is_admin() -> bool:
    if is_windows():
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    return is_root()


def windows_appdata(user: UserContext) -> Path:
    return Path(os.environ.get("APPDATA") or user.home / "AppData/Roaming")


def available_categories() -> tuple[str, ...]:
    if is_windows():
        return ("python", "npm", "go")
    return ("python", "npm", "go", "homebrew") if is_macos() else tuple(
        category for category in MIRROR_TYPES if category != "homebrew"
    )


def ensure_category_supported(category: str) -> None:
    if is_windows() and category in {"apt", "docker", "homebrew"}:
        detail = " Configure Docker Desktop in Settings > Docker Engine." if category == "docker" else ""
        raise UsageError(f"{category.upper()} configuration is unavailable on Windows.{detail}")
    if category == "homebrew" and not is_macos():
        raise UsageError("Homebrew mirror configuration is currently supported on macOS only")
    if is_macos() and category == "apt":
        raise UsageError("APT configuration is unavailable on macOS; it requires Ubuntu or Debian")
    if is_macos() and category == "docker":
        raise UsageError(
            "Docker configuration is unavailable on macOS; configure registry-mirrors "
            "in Docker Desktop Settings > Docker Engine, then Apply & restart"
        )


def user_config_path(category: str, user: UserContext) -> Path:
    """Resolve per-user tool configuration, shared by adapters and restore checks."""
    if category == "homebrew":
        base = os.environ.get("XDG_CONFIG_HOME") or os.environ.get("HOMEBREW_XDG_CONFIG_HOME")
        return Path(base) / "homebrew/brew.env" if base else user.home / ".homebrew/brew.env"
    if category == "python":
        if is_windows():
            return windows_appdata(user) / "pip/pip.ini"
        if is_macos():
            data_home = os.environ.get("XDG_DATA_HOME")
            base = Path(data_home) if data_home else user.home / "Library/Application Support"
            if (base / "pip").is_dir():
                return base / "pip/pip.conf"
        else:
            config_home = os.environ.get("XDG_CONFIG_HOME")
            if config_home:
                return Path(config_home) / "pip/pip.conf"
        return user.home / ".config/pip/pip.conf"
    if category == "npm":
        override = os.environ.get("NPM_CONFIG_USERCONFIG") or os.environ.get("npm_config_userconfig")
        return Path(override) if override else user.home / ".npmrc"
    if category == "go":
        override = os.environ.get("GOENV")
        if override == "off":
            raise UsageError("Go configuration is disabled by GOENV=off; unset it before using MirrorMate")
        if override:
            return Path(override)
        if is_windows():
            return windows_appdata(user) / "go/env"
        if is_macos():
            return user.home / "Library/Application Support/go/env"
        return Path(os.environ.get("XDG_CONFIG_HOME") or user.home / ".config") / "go/env"
    raise UsageError(f"Unsupported user configuration type: {category}")


def _parse_os_release(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise UsageError(f"Cannot read {path}: {exc}") from exc
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def normalize_architecture(machine: str) -> str:
    aliases = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "i386": "i386",
        "i686": "i386",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "armhf",
        "ppc64le": "ppc64el",
    }
    return aliases.get(machine.lower(), machine.lower())


def detect_distro(root: Path = Path("/"), architecture: str | None = None) -> DistroInfo:
    values = _parse_os_release(root / "etc/os-release")
    distro_id = values.get("ID", "").lower()
    codename = values.get("VERSION_CODENAME") or values.get("UBUNTU_CODENAME", "")
    version_id = values.get("VERSION_ID", "")
    if distro_id not in DISTROS:
        raise UsageError(f"Unsupported distribution: {distro_id or 'unknown'}")
    if not codename:
        raise UsageError("VERSION_CODENAME is missing from /etc/os-release")
    arch = normalize_architecture(architecture or std_platform.machine())
    return DistroInfo(distro_id, version_id, codename, arch)


def ensure_supported(distro: DistroInfo) -> None:
    supported = SUPPORTED_RELEASES.get(distro.id, set())
    if distro.version_id not in supported:
        versions = ", ".join(sorted(supported))
        raise UsageError(
            f"{distro.id} {distro.version_id or 'unknown'} is not supported; "
            f"supported versions: {versions}"
        )


def invoking_user(environ: dict[str, str] | None = None) -> UserContext:
    env = environ if environ is not None else os.environ
    if is_windows():
        home = Path(env.get("USERPROFILE") or Path.home())
        return UserContext(env.get("USERNAME") or home.name, None, None, home)
    uid = getattr(os, "geteuid", lambda: -1)()
    if uid == 0 and env.get("SUDO_UID", "").isdigit():
        uid = int(env["SUDO_UID"])
    try:
        if pwd is None:
            raise UsageError("POSIX user information is unavailable")
        record = pwd.getpwuid(uid)
    except KeyError as exc:
        raise UsageError(f"Cannot resolve user for uid {uid}") from exc
    return UserContext(record.pw_name, record.pw_uid, record.pw_gid, Path(record.pw_dir))


def require_root(action: str) -> None:
    if not is_admin():
        instruction = "run PowerShell as Administrator" if is_windows() else "rerun the command with sudo"
        raise PermissionDeniedError(f"{action} requires administrator/root privileges; {instruction}")


def rooted(root: Path, absolute_path: Path) -> Path:
    if not absolute_path.is_absolute():
        raise ValueError(f"Expected an absolute path: {absolute_path}")
    return root / absolute_path.relative_to("/")
