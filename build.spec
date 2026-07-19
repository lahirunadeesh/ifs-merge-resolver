# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for IFS Merge Conflict Resolver.
Build:
  pip install pyinstaller
  pyinstaller build.spec
Output: dist/IFSMergeResolver (folder) or dist/IFSMergeResolver.app (Mac)
"""

import os
block_cipher = None

a = Analysis(
    ['server/app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('ui/templates',   'ui/templates'),
        ('ui/static',      'ui/static'),
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'fastapi',
        'jinja2',
        'starlette',
        'anyio',
        'anyio._backends._asyncio',
        'multipart',
        'tkinter',
        'tkinter.filedialog',
        'pystray',
        'pystray._win32',
        'pystray._darwin',
        'pystray._xorg',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='IFSMergeResolver',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # no console window — errors now logged to ~/ifs_merge_resolver.log
    icon='ui/static/icon.ico',  # Windows .ico / Mac falls back to icns below
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='IFSMergeResolver',
)

# macOS .app bundle
app = BUNDLE(
    coll,
    name='IFSMergeResolver.app',
    icon='ui/static/icon.icns',
    bundle_identifier='com.lahirunadeesh.ifsmerge',
    info_plist={
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': '2.5.0',
        'CFBundleName': 'IFS Merge Resolver',
    },
)
