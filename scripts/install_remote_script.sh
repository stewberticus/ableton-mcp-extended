#!/usr/bin/env bash
# Copy the AbletonMCP Remote Script into Ableton's User Library.
#
# Usage:
#   scripts/install_remote_script.sh            # default User Library location
#   scripts/install_remote_script.sh --dest DIR # a different "Remote Scripts" folder
#   scripts/install_remote_script.sh --check    # only report whether the installed copy is current
#
# No sudo needed: this writes to your User Library, not into the Live app bundle.
# After installing, restart Live (or re-select AbletonMCP as a Control Surface)
# so it loads the new script.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$REPO_ROOT/AbletonMCP_Remote_Script/__init__.py"
DEST_ROOT=""
CHECK_ONLY=0

while [ $# -gt 0 ]; do
    case "$1" in
        --dest) DEST_ROOT="${2:?--dest needs a directory}"; shift 2 ;;
        --check) CHECK_ONLY=1; shift ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

if [ -z "$DEST_ROOT" ]; then
    case "$(uname -s)" in
        Darwin) DEST_ROOT="$HOME/Music/Ableton/User Library/Remote Scripts" ;;
        MINGW*|MSYS*|CYGWIN*) DEST_ROOT="${USERPROFILE:-$HOME}/Documents/Ableton/User Library/Remote Scripts" ;;
        *) echo "Unsupported OS; pass --dest \"<your User Library>/Remote Scripts\"" >&2; exit 2 ;;
    esac
fi

TARGET_DIR="$DEST_ROOT/AbletonMCP"
TARGET="$TARGET_DIR/__init__.py"

if [ ! -f "$SOURCE" ]; then
    echo "Source script not found: $SOURCE" >&2
    exit 1
fi

if [ -f "$TARGET" ] && cmp -s "$SOURCE" "$TARGET"; then
    echo "Up to date: $TARGET"
    exit 0
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
    if [ -f "$TARGET" ]; then
        echo "Out of date: $TARGET differs from the repo copy. Run without --check to update."
    else
        echo "Not installed: $TARGET does not exist."
    fi
    exit 1
fi

if [ ! -d "$DEST_ROOT" ]; then
    echo "Remote Scripts folder not found: $DEST_ROOT" >&2
    echo "Open Live once so it creates its User Library, or pass --dest." >&2
    exit 1
fi

mkdir -p "$TARGET_DIR"
if [ -f "$TARGET" ]; then
    BACKUP="$TARGET.bak-$(date +%Y%m%d-%H%M%S)"
    cp "$TARGET" "$BACKUP"
    echo "Backed up previous version to $BACKUP"
fi
cp "$SOURCE" "$TARGET"
# Live caches compiled bytecode next to the script; drop it so the new code loads.
rm -rf "$TARGET_DIR/__pycache__" "$TARGET_DIR"/*.pyc 2>/dev/null || true

echo "Installed: $TARGET"
echo "Restart Ableton Live (or re-select AbletonMCP under Settings > Link, Tempo & MIDI) to load it."
