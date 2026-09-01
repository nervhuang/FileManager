# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # 不要把 config.ini 加進來。它會被放進 _internal/，而執行期讀的是 exe 同層
    # 的 config.ini（見 app/paths.py 的 runtime_root 與 bundle_root 之別），因此
    # 打包進來的那份永遠不會被讀到，只會把開發機的搜尋歷史與私人路徑一起發佈出去。
    # 首次啟動時沒有 config.ini 是正常的，程式會以內建預設值執行並在關閉時寫出。
    # 更新檢查器的 Web UI 頁面模板是資源檔，必須跟著模組走進 app/checker/：
    # 漏收的話程式照常啟動，直到按下「詳細清單」才炸。
    datas=[('icon.ico', '.'), ('app/checker/page.html', 'app/checker')],
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
