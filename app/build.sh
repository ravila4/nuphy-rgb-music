#!/usr/bin/env bash
# Build NuPhyRGBMenu and wrap in a .app bundle
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Building..."
swift build 2>&1

BINARY=".build/debug/NuPhyRGBMenu"
APP_DIR=".build/debug/NuPhyRGBMenu.app"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"

echo "==> Wrapping in .app bundle..."
mkdir -p "$MACOS"
cp "$BINARY" "$MACOS/NuPhyRGBMenu"
cp Info.plist "$CONTENTS/Info.plist"

# Ad-hoc sign so macOS trusts it
codesign --force --deep -s - "$APP_DIR" 2>&1

echo "==> Done: $APP_DIR"
echo "    Run with: open $APP_DIR"
