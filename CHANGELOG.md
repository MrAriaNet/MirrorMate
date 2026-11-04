# Changelog

All notable changes to MirrorMate are documented here.

## [2.1.0] - 2026-11-04

### Added

- macOS CLI and TUI support for Python/PyPI, NPM, Go, and Homebrew.
- Windows CLI and TUI support for Python/PyPI, NPM, and Go, with a conditional `windows-curses` dependency.
- Homebrew bottle mirrors and optional API mirrors through per-user `brew.env`, including custom catalog entries, dry runs, backups, restore, and an official-source option.
- `manager-mac.sh`, `manager-linux.sh`, and `manager.ps1` with install, update, uninstall, and status actions.
- One-line installers, explicit root/Administrator checks, and machine-wide isolated Python environments on macOS and Windows.
- Windows and macOS CI jobs, platform-specific configuration tests, manager lifecycle tests, and PowerShell validation.
- Python wheel and source distribution release assets, checksums, and downloadable manager scripts.

### Changed

- Resolve pip and Go configuration paths for each platform and honor supported environment overrides.
- Show available services in the default CLI list, status output, and TUI dashboard for each platform.
- Share configuration path resolution with backup restore validation; reject Windows path syntax in snapshot identifiers and stored paths.
- Avoid POSIX account and ownership APIs on Windows.
- Route `install.sh` to the appropriate Unix manager; installation now requires elevation and exits with code 77 when privileges are missing.
- Run the cross-platform test suite before publishing a release.
- Align README and package license metadata with the existing GPL v3 `LICENSE` file; license contents are unchanged.

### Scope

- APT and Docker daemon configuration remain Linux-only. Docker Desktop settings are managed through Docker Desktop on macOS and Windows.
- Homebrew mirror configuration is currently available on macOS only. Git remotes, taps, and artifact proxy configuration are managed separately.
- Linux managers install the latest Debian release package. Mac and Windows managers install the current `main` source archive and require Python 3.10+ to be installed separately.

## [2.0.0]

- Introduced a shared Python core, non-interactive CLI, and curses TUI for Ubuntu and Debian.
- Added HTTP mirror benchmarks, five themes, persistent TUI settings, and custom catalogs.
- Added APT `.list` and deb822 support, Docker daemon configuration merging, atomic writes, rollback, and optional persistent backups.
- Added Debian packaging, release checksums, and a Linux CI matrix.

[2.1.0]: https://github.com/free-programmers/MirrorMate/compare/v2...v2.1.0
[2.0.0]: https://github.com/free-programmers/MirrorMate/releases/tag/v2
