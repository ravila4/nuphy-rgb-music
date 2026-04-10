#!/usr/bin/env bash
# Build "NuPhy RGB.app" with embedded NuPhyDaemon binary
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

# SPM target is "NuPhyRGBMenu" but the .app is named "NuPhy RGB"
BINARY=".build/debug/NuPhyRGBMenu"
APP_DIR=".build/debug/NuPhy RGB.app"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"

echo "==> Wrapping in .app bundle..."
mkdir -p "$MACOS"
mkdir -p "$CONTENTS/Resources"
cp "$BINARY" "$MACOS/NuPhyRGBMenu"
cp Info.plist "$CONTENTS/Info.plist"
cp AppIcon.icns "$CONTENTS/Resources/AppIcon.icns"

# --- Step 3: Embed daemon binary ---
echo "==> Embedding NuPhyDaemon..."
cp "$DAEMON_BIN" "$MACOS/NuPhyDaemon"

# --- Step 4: Codesign ---
# Order matters: sign the daemon FIRST (with entitlements for PyInstaller runtime),
# then sign the .app bundle to seal the daemon's final signature in CodeResources.
# Reversing this order breaks the bundle seal and causes TCC permission failures.
codesign --force \
    --entitlements "$PROJECT_ROOT/entitlements.plist" \
    -s - "$MACOS/NuPhyDaemon" 2>&1
codesign --force -s - "$APP_DIR" 2>&1

# --- Step 5: Package DMG ---
if [ "${1:-}" = "--dmg" ]; then
    VERSION=$(cd "$PROJECT_ROOT" && python3 -c "
import tomllib, pathlib
p = tomllib.loads(pathlib.Path('pyproject.toml').read_text())
print(p['project']['version'])
")
    DMG_NAME="NuPhyRGB-v${VERSION}.dmg"
    STAGING="$SCRIPT_DIR/.build/dmg-staging"

    echo "==> Packaging $DMG_NAME..."
    rm -rf "$STAGING" "$SCRIPT_DIR/.build/$DMG_NAME"
    mkdir -p "$STAGING"
    cp -R "$APP_DIR" "$STAGING/"
    ln -s /Applications "$STAGING/Applications"

    hdiutil create -volname "NuPhy RGB" \
        -srcfolder "$STAGING" \
        -ov -format UDZO \
        "$SCRIPT_DIR/.build/$DMG_NAME" 2>&1

    rm -rf "$STAGING"
    echo "==> DMG: .build/$DMG_NAME ($(du -h "$SCRIPT_DIR/.build/$DMG_NAME" | cut -f1))"
else
    echo "==> Done: $APP_DIR"
    echo "    Run with: open \"$APP_DIR\""
    echo "    Build DMG: bash build.sh --dmg"
fi
