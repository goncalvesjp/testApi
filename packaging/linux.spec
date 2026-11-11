# -*- mode: python ; coding: utf-8 -*-
import os

PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

# jsonpath-ng genere ses tables de parsing (ply) via des imports internes que
# l'analyse statique de PyInstaller ne detecte pas toujours ; on les force.
HIDDEN_IMPORTS = [
    'jsonpath_ng.ext',
    'jsonpath_ng.ext.parser',
    'jsonpath_ng.ext.filter',
    'jsonpath_ng.parser',
    'lxml.etree',
    'lxml._elementpath',
]

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'main.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        (os.path.join(PROJECT_ROOT, 'assets', 'icon.png'), 'assets'),
        (os.path.join(PROJECT_ROOT, 'VERSION'), '.'),
        (os.path.join(PROJECT_ROOT, 'LICENSE'), '.'),
    ],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='soapui-tester',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
