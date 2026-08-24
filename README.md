# FileManager

Windows 桌面檔案管理程式（PyQt5），搜尋透過 [Everything](https://www.voidtools.com/) 索引。

## 文件

### 行為規格（現在應該是什麼）

- [docs/spec/](docs/spec/) — 一個功能域一份規格，與 `app/` 套件、`tests/` 目錄三方 1:1
  - [settings](docs/spec/settings.md) ｜ [search](docs/spec/search.md) ｜
    [fileops](docs/spec/fileops.md) ｜ [tabs](docs/spec/tabs.md)
  - [authors](docs/spec/authors.md) ｜ [checker](docs/spec/checker.md) ｜
    [integration](docs/spec/integration.md) ｜ [ui-shell](docs/spec/ui-shell.md)

### 使用指南（給外部呼叫者）

- [HERMES.md](HERMES.md) — 與 Hermes agent 的 MCP 整合：工具一覽、授權機制、設定方式
- [CLI.md](CLI.md) — 給 Hermes 以外的程式呼叫的命令列介面，功能與 MCP 相同
- [BUILD.md](BUILD.md) — 編譯與打包（PyInstaller / Nuitka，含防毒誤判對策）

### 歷史（何時為何改）

- [CHANGELOG.md](CHANGELOG.md) — 變更紀錄

## 測試

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest            # 全部
.venv\Scripts\python -m pytest -m logic   # 只跑純邏輯（秒級，pre-commit 用這個）
```

測試檔名對應 [docs/spec/](docs/spec/) 的條文編號，例如
`tests/search/test_srch_14_folder_first_sort.py` 對應 `search.md` 的 SRCH-14。
改行為時規格與測試一起改，只改其中一邊視為錯誤。

Qt 測試以 offscreen 平台執行：量得到 widget 的尺寸、字型與選取狀態，
量不到「看起來對不對」。外觀一律人工驗收，見規格裡的 **[手動]** 標記。
