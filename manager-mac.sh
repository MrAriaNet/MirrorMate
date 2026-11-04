#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    printf '%s\n' 'Root privileges required. Run this manager with sudo (sudo bash manager-mac.sh).' >&2
    exit 77
fi
if [ "$(uname -s)" != Darwin ]; then
    printf '%s\n' 'This manager requires macOS.' >&2
    exit 2
fi
ACTION=${1:-install}
INSTALL_DIR='/Library/Application Support/MirrorMate'
LINK='/usr/local/bin/mirrormate'
case "$ACTION" in
    status)
        if [ ! -f "$INSTALL_DIR/.managed" ]; then
            printf '%s\n' 'MirrorMate is not installed by this manager.' >&2
            exit 1
        fi
        exec "$INSTALL_DIR/venv/bin/mirrormate" --version ;;
    uninstall)
        if [ ! -f "$INSTALL_DIR/.managed" ]; then
            printf '%s\n' 'No managed installation found; nothing removed.' >&2
            exit 1
        fi
        if [ -L "$LINK" ] && [ "$(readlink "$LINK")" = "$INSTALL_DIR/venv/bin/mirrormate" ]; then
            rm -- "$LINK"
        fi
        rm -rf -- "$INSTALL_DIR"
        printf '%s\n' 'MirrorMate uninstalled. User configuration and backups were preserved.'
        exit 0 ;;
    install|update) ;;
    *) printf '%s\n' 'Usage: manager-mac.sh [install|update|uninstall|status]' >&2; exit 2 ;;
esac
if [ -e "$INSTALL_DIR" ] && [ ! -f "$INSTALL_DIR/.managed" ]; then
    printf '%s\n' "Refusing to overwrite an unmanaged directory: $INSTALL_DIR" >&2
    exit 1
fi
if [ -e "$LINK" ] || [ -L "$LINK" ]; then
    if [ ! -L "$LINK" ] || [ "$(readlink "$LINK")" != "$INSTALL_DIR/venv/bin/mirrormate" ]; then
        printf '%s\n' "Refusing to overwrite an existing command: $LINK" >&2
        exit 1
    fi
fi
PYTHON=${MIRRORMATE_PYTHON:-python3}
if ! command -v "$PYTHON" >/dev/null 2>&1 || ! "$PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    printf '%s\n' 'Python 3.10+ with venv and pip is required. Install Python first.' >&2
    exit 1
fi
mkdir -p "$INSTALL_DIR" /usr/local/bin
touch "$INSTALL_DIR/.managed"
"$PYTHON" -m venv "$INSTALL_DIR/venv"
REPOSITORY=${MIRRORMATE_REPOSITORY:-free-programmers/MirrorMate}
"$INSTALL_DIR/venv/bin/python" -m pip install --upgrade --force-reinstall --no-cache-dir "https://github.com/$REPOSITORY/archive/refs/heads/main.zip"
ln -sfn "$INSTALL_DIR/venv/bin/mirrormate" "$LINK"
printf '%s\n' 'MirrorMate installed. Run mirrormate as your normal user.'
