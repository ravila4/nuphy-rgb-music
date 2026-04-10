# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the NuPhy RGB daemon (onefile mode).
# Build with: uv run pyinstaller NuPhyDaemon.spec --noconfirm

import os
import _sounddevice_data

sd_dir = os.path.dirname(_sounddevice_data.__file__)
portaudio = os.path.join(sd_dir, "portaudio-binaries", "libportaudio.dylib")

a = Analysis(
    ["src/nuphy_rgb/main.py"],
    pathex=[],
    binaries=[(portaudio, "_sounddevice_data/portaudio-binaries")],
    datas=[],
    hiddenimports=[
        "_sounddevice_data",
        "objc",
        "CoreAudio",
        # Dynamically imported by user plugins in ~/.config/nuphy-rgb/
        "nuphy_rgb.plugin_api",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PIL", "scipy"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NuPhyDaemon",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file="entitlements.plist",
)
