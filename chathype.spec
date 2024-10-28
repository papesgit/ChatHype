# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import os

# Collect data files, excluding twitch-dl.pyz
datas = [
    (os.path.join('.', 'settings.json'), '.')
]

# Include twitch-dl.pyz and TwitchDownloaderCLI as binaries
binaries = [
    (os.path.join('.', 'twitch-dl.pyz'), '.'),  # Add twitch-dl.pyz as a binary
    (os.path.join('.', 'TwitchDownloaderCLI.exe'), '.')
]

a = Analysis(
    ['chathype.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=True,  # Bundle everything into one file
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ChatHypev4',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Set to True if you want a console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
