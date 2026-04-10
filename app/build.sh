#!/usr/bin/env bash
# Build NuPhyRGBMenu.app with embedded NuPhyDaemon binary
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Step 1: Build Python daemon ---
echo "==> Building NuPhyDaemon (PyInstaller)..."
cd "$PROJECT_ROOT"
uv run pyinstaller NuPhyDaemon.spec --noconfirm 2>&1

DAEMON_BIN="$PROJECT_ROOT/dist/NuPhyDaemon"
if [ ! -f "$DAEMON_BIN" ]; then
    echo "ERROR: PyInstaller build failed — $DAEMON_BIN not found"
    exit 1
fi
echo "    Daemon binary: $(du -h "$DAEMON_BIN" | cut -f1)"

# --- Step 2: Build Swift menu bar app ---
echo "==> Building NuPhyRGBMenu (Swift)..."
cd "$SCRIPT_DIR"
swift build 2>&1

BINARY=".build/debug/NuPhyRGBMenu"
APP_DIR=".build/debug/NuPhyRGBMenu.app"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"

echo "==> Wrapping in .app bundle..."
mkdir -p "$MACOS"
cp "$BINARY" "$MACOS/NuPhyRGBMenu"
cp Info.plist "$CONTENTS/Info.plist"

# --- Step 3: Embed daemon binary ---
echo "==> Embedding NuPhyDaemon..."
cp "$DAEMON_BIN" "$MACOS/NuPhyDaemon"

# --- Step 4: Codesign ---
codesign --force --options runtime \
    --entitlements "$PROJECT_ROOT/entitlements.plist" \
    -s - "$MACOS/NuPhyDaemon" 2>&1
codesign --force --deep -s - "$APP_DIR" 2>&1

echo "==> Done: $APP_DIR"
echo "    Run with: open $APP_DIR"
