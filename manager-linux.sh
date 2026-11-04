#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    printf '%s\n' 'Root privileges required. Run this manager with sudo (sudo bash manager-linux.sh).' >&2
    exit 77
fi
if [ "$(uname -s)" != Linux ] || ! command -v apt-get >/dev/null 2>&1; then
    printf '%s\n' 'This manager requires Ubuntu or Debian with APT.' >&2
    exit 2
fi
ACTION=${1:-install}
case "$ACTION" in
    status) exec dpkg-query -W mirrormate ;;
    uninstall) exec apt-get remove -y mirrormate ;;
    install|update) ;;
    *) printf '%s\n' 'Usage: manager-linux.sh [install|update|uninstall|status]' >&2; exit 2 ;;
esac
REPOSITORY=${MIRRORMATE_REPOSITORY:-free-programmers/MirrorMate}
BASE_URL=${MIRRORMATE_RELEASE_URL:-https://github.com/$REPOSITORY/releases/latest/download}
TEMP_DIR=$(mktemp -d)
trap 'rm -rf -- "$TEMP_DIR"' EXIT INT TERM
PACKAGE="$TEMP_DIR/mirrormate_all.deb"
CHECKSUM="$TEMP_DIR/mirrormate_all.deb.sha256"
download() {
    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --silent --show-error "$1" --output "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget --quiet --output-document="$2" "$1"
    else
        printf '%s\n' 'curl or wget is required.' >&2
        exit 1
    fi
}
download "$BASE_URL/mirrormate_all.deb" "$PACKAGE"
download "$BASE_URL/mirrormate_all.deb.sha256" "$CHECKSUM"
expected=$(awk 'NR == 1 { print $1 }' "$CHECKSUM")
actual=$(sha256sum "$PACKAGE" | awk '{ print $1 }')
if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
    printf '%s\n' 'MirrorMate package checksum verification failed.' >&2
    exit 1
fi
apt-get install -y "$PACKAGE"
printf '%s\n' 'MirrorMate installed. Run mirrormate as your normal user.'
