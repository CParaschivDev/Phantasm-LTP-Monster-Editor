# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['gui_pyside.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'mu_monster_editor\\assets'), ('C:\\Users\\Paras\\AppData\\Local\\Programs\\Python\\Python311\\Lib\\site-packages\\PySide6\\plugins\\platforms', 'PySide6\\plugins\\platforms'), ('C:\\Users\\Paras\\AppData\\Local\\Programs\\Python\\Python311\\Lib\\site-packages\\PySide6\\plugins\\imageformats', 'PySide6\\plugins\\imageformats')],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='PhantasmLTP_MonsterEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PhantasmLTP_MonsterEditor',
)
