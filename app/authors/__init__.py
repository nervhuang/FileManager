"""作者／團體域：清單資料庫、面板與其對話框。

分兩層：

* `db`／`names` **不依賴 Qt**。`authors.db` 是作者與團體的單一真實來源，
  Hermes MCP server 與 CLI 兩個進程也讀寫它（docs/spec/authors.md 的 AUT-1）。
* `panel`／`icons` 依賴 Qt。

本檔案刻意不做 re-export：一旦在這裡 import panel，沒有 Qt 的那兩個進程就
連 db 都匯入不了。
"""
