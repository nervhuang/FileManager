# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('config.ini', '.'), ('icon.ico', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# onedir 模式：exclude_binaries=True 讓二進位/資料留給 COLLECT 放進資料夾，
# 而非塞進單一 exe。配合下方 COLLECT 產生 dist/FileManager/ 資料夾發佈版。
#
# 防毒誤判對策：
#   1. upx=False —— 不加殼。UPX 加殼是防毒啟發式的頭號紅旗。
#   2. onedir（非 onefile）—— 避免執行時自我解壓到暫存目錄，
#      這種「自解壓+執行」行為最易被當成釋放 payload 的惡意程式。
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FileManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='FileManager',
)
