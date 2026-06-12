# 編譯與打包

本專案為 PyQt5 桌面程式。提供兩種編譯方式，**皆已針對防毒誤判最佳化**。

## 為什麼會被防毒誤判？

PyInstaller 容易被誤判的三大原因：

1. **UPX 加殼**（`upx=True`）— 加殼器是惡意軟體常用手法，啟發式偵測的頭號紅旗。
2. **單檔模式（onefile）**— 執行時自我解壓到暫存目錄再執行，這種「自解壓+執行」行為極易被當成釋放 payload 的惡意程式。
3. **PyInstaller bootloader 指紋**— 官方預編 bootloader 的特徵碼被各家防毒收錄。

本專案的設定已避開 1、2。若仍被誤判，建議改用 Nuitka（避開 3），或加上程式碼簽章（根治）。

---

## 方式 A：PyInstaller（onedir、無 UPX）

設定檔 [`FileManager.spec`](FileManager.spec) 已調整為 `upx=False` + onedir。

```powershell
python -m PyInstaller FileManager.spec --noconfirm --clean
```

產出： `dist\FileManager\FileManager.exe`（連同 `_internal\` 依賴資料夾一起發佈）。

---

## 方式 B：Nuitka（編譯成原生機器碼，誤判最低）

Nuitka 把 Python 編成 C 再編成機器碼，沒有被指紋化的 bootloader，誤判率最低。
首次執行會自動下載 MinGW64 工具鏈，不需先裝 MSVC。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_nuitka.ps1
```

或直接呼叫（不經 PowerShell 腳本）：

```powershell
python -m nuitka --standalone --enable-plugin=pyqt5 `
  --windows-console-mode=disable --windows-icon-from-ico=icon.ico `
  --include-data-file=config.ini=config.ini `
  --include-data-dir=resources/icons=resources/icons `
  --output-dir=build_nuitka --output-filename=FileManager.exe `
  --assume-yes-for-downloads --remove-output main.py
```

產出： `build_nuitka\main.dist\FileManager.exe`（連同整個 `main.dist\` 資料夾發佈）。

---

## 根治：程式碼簽章（Authenticode）

不論用哪種工具，被簽章的執行檔誤判率最低：

- **EV 憑證**：可立即取得 Windows SmartScreen 信譽。
- **OV 憑證**：較便宜，但需累積下載量才建立信譽。

簽章指令（需安裝 Windows SDK 的 `signtool`）：

```powershell
signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /a dist\FileManager\FileManager.exe
```

## 若仍被特定防毒誤判

1. 上傳到 VirusTotal 看是哪幾家引擎誤判。
2. 向該防毒廠商提交誤判（false positive）申訴，通常數日內加入白名單。
