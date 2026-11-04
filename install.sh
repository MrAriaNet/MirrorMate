#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    printf '%s\n' 'Root privileges required. Run: curl -fsSL https://raw.githubusercontent.com/free-programmers/MirrorMate/main/install.sh | sudo bash' >&2
    exit 77
fi
case "$(uname -s)" in
    Darwin) MANAGER=manager-mac.sh ;;
    Linux) MANAGER=manager-linux.sh ;;
    *) printf '%s\n' 'Use manager.ps1 in Administrator PowerShell on Windows.' >&2; exit 2 ;;
esac
REPOSITORY=${MIRRORMATE_REPOSITORY:-free-programmers/MirrorMate}
TEMP_DIR=$(mktemp -d)
trap 'rm -rf -- "$TEMP_DIR"' EXIT INT TERM
URL="https://raw.githubusercontent.com/$REPOSITORY/main/$MANAGER"
if command -v curl >/dev/null 2>&1; then
    curl --fail --location --silent --show-error "$URL" --output "$TEMP_DIR/$MANAGER"
elif command -v wget >/dev/null 2>&1; then
    wget --quiet --output-document="$TEMP_DIR/$MANAGER" "$URL"
else
    printf '%s\n' 'curl or wget is required.' >&2
    exit 1
fi
sh "$TEMP_DIR/$MANAGER" "$@"
