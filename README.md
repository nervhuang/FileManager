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
