"""搜尋域：關鍵字解析、Everything 查詢、結果模型與排序。

分兩層：

* 純函式與 I/O 層（`query`／`everything`）**不依賴 Qt**。GUI、Hermes MCP server
  與 CLI 是三個獨立進程，其中兩個沒有 QApplication，三者搜出來的結果必須一致
  （docs/spec/search.md）。更新檢查器的掃描器也走這一層找本機藏書。
* UI 層（`models`／`results`）依賴 Qt。

本檔案刻意不做 re-export：一旦在這裡 import models，沒有 Qt 的那兩個進程就
連 query 都匯入不了。要什麼就明確地從子模組拿。
"""
