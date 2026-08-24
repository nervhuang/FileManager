"""更新檢查器：比對 exhentai 最新發布與本機藏書，找出還沒收的書。

規格與設計決策見 docs/spec/checker.md。

本套件分兩層：

* 純函式層（`titles`／`matcher`）不依賴 Qt、不碰網路，可獨立測試，
  也方便日後若要搬回獨立專案時整包帶走。
* I/O 層（`fetcher`／`scanner`）負責網路與編排，錯誤一律在此收斂，
  不讓例外冒進 Qt 事件圈拖垮主程式。
* UI 層（`panel`／`icons`／`webui`）。

本檔案刻意不做任何 re-export：純函式層要能在沒有 Qt 的環境（MCP server、
CLI、純邏輯測試）被匯入，這裡一旦 import panel 就會把 Qt 一起拖進來。
"""
