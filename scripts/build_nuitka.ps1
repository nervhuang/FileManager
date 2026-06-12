# 用 Nuitka 把 FileManager 編譯成原生機器碼，降低防毒誤判。
#
# 與 PyInstaller 的差異：Nuitka 將 Python 編譯成 C 再編成機器碼，沒有 PyInstaller
# 那個被各家防毒指紋化的 bootloader，誤判率大幅下降。
#
# 首次執行會自動下載 MinGW64 工具鏈（--assume-yes-for-downloads），不需先裝 MSVC。
#
# 用法（在專案根目錄）：
#   powershell -ExecutionPolicy Bypass -File scripts\build_nuitka.ps1
#
# 產出： build_nuitka\main.dist\FileManager.exe （standalone 資料夾發佈版）

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "==> 確認 Nuitka 已安裝..."
python -c "import nuitka" 2>$null
if (-not $?) {
    Write-Host "    未安裝，正在安裝 nuitka..."
    python -m pip install nuitka
}

Write-Host "==> 開始 Nuitka 編譯（首次會下載 MinGW64，請耐心等候）..."
python -m nuitka `
    --standalone `
    --enable-plugin=pyqt5 `
    --windows-console-mode=disable `
    --windows-icon-from-ico=icon.ico `
    --include-data-file=config.ini=config.ini `
    --include-data-dir=resources/icons=resources/icons `
    --output-dir=build_nuitka `
    --output-filename=FileManager.exe `
    --company-name="FileManager" `
    --product-name="FileManager" `
    --file-version=1.0.0 `
    --product-version=1.0.0 `
    --assume-yes-for-downloads `
    --remove-output `
    main.py

if ($?) {
    Write-Host ""
    Write-Host "==> 完成！產出位置： build_nuitka\main.dist\FileManager.exe"
    Write-Host "    發佈時請整個 main.dist 資料夾一起帶（standalone 模式）。"
} else {
    Write-Host "==> 編譯失敗，請檢查上方錯誤訊息。"
    exit 1
}
