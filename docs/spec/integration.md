# 對外整合：MCP、CLI、GUI 橋接

現況 [`app/hermes_mcp.py`](../../app/hermes_mcp.py)（MCP stdio server）、
[`app/cli.py`](../../app/cli.py)（命令列）、
[`app/gui_bridge.py`](../../app/gui_bridge.py)（`QLocalServer` 命名管道）。

使用指南在 [HERMES.md](../../HERMES.md) 與 [CLI.md](../../CLI.md)（給外部使用者看），
本文是**行為規格**（給實作與測試看）。

---

## 授權閘門

**INT-1** 九個工具在 FileManager 主程式未執行時一律回
`{"ok": false, "reason": "gui_not_running"}`。

**INT-2** 閘門**套用在每一個工具**，不只是會掃硬碟的那幾個。
只擋一部分，模型改叫另一個工具就繞過去了。

> 這是一條安全條文，不是便利性設計。任何新增的工具都必須加上閘門。
> `tests/integration/test_int_01_05_gui_gate.py` 以**掃模組**的方式遍歷全部
> `fm_` 工具逐一驗證，不是對著一份寫死的清單——寫死的清單正是這條規則會被
> 繞過的方式。實測過它抓得到：拿掉任一個工具的閘門，測試立刻指名那一個。

**INT-3** `fm_open_search_tab` **不得**有 `launch_if_needed` 之類的參數。
能啟動主程式的工具，等於可以自己授予這道閘門本來要擋下的存取權。

**INT-4** 判定方式為本機命名管道是否存在，不建立連線、無連線成本。

---

## 工具清單

九個工具，CLI 有一一對應的子指令：

| 工具 | CLI 子指令 | 用途 |
|---|---|---|
| `fm_search` | `search` | 搜尋本機檔案 |
| `fm_search_all` | `search-all` | 分頁取回完整結果 |
| `fm_open_search_tab` | `open-search-tab` | 在 GUI 開搜尋分頁 |
| `fm_authors_list` | `authors-list` | 列出作者／團體 |
| `fm_authors_upsert` | `authors-upsert` | 新增或更新 |
| `fm_authors_link` | `authors-link` | 建立／解除關聯 |
| `fm_authors_delete` | `authors-delete` | 軟刪除 |
| `fm_match_author` | `match-author` | 找出屬於某作者的本機檔案 |
| `fm_authors_stats` | `authors-stats` | 統計各作者的本機檔案數 |

**INT-5** MCP 與 CLI 功能等價。新增工具時兩邊一起加，測試須驗證兩份清單一致。

---

## 搜尋工具語意

**INT-6** `fm_search` 預設 `limit=200`，`match` 為 `any`（任一命中）或 `all`（全部命中）。

**INT-7** `fm_search_all` 欄位與 `fm_search` 完全相同，另有分頁語意：
`limit` 預設 200、**上限 2000**（每筆約 0.28KB，2000 筆約 560KB）。

**INT-8** `fm_search_all` 向 Everything 索取的筆數放大 100 倍（`limit_scale=100`），
**只影響它自己的呼叫**，GUI 的搜尋上限不受影響。

> 曾經的缺陷：`fm_search` 看不到 Everything 被索取的每次查詢上限之外的東西，
> 一個命中 6989 個檔案的關鍵字回報 2000。

**INT-9** `total` / `offset` / `has_more` / `capped` 四欄語意見
[search.md](search.md) 的 SRCH-11、SRCH-12。

**INT-10** 排除設定與 GUI 共用，見 [search.md](search.md) 的 SRCH-10。

---

## 關聯維護

**INT-11** `fm_authors_link` 能單獨建立或解除一組作者⇄團體關聯，
任一邊不存在時自動建立。

> 沒有它的時候，只為了加一個關聯就得用 `fm_authors_upsert` 重送整筆記錄。

**INT-12** `fm_authors_upsert` 的說明必須明確寫出「已知的作者／團體配對必須用
`linked_names` 一併送出」，否則模型會建出兩筆互不相關的資料。

**INT-13** `linked_names` 為新增合併語意，見 [authors.md](authors.md) 的 AUT-7。

**INT-13a** 這幾處接受 `english_name`，可用英文名反查對應的日文／中文實體：
`fm_match_author`、`fm_authors_link(unlink=true)`（兩者都走 `_resolve_entity`），
以及 `fm_authors_list` 的 keyword 過濾與回傳實體。

**INT-13b** **[未驗]** `fm_authors_link` 的**建立**方向**不**認英文名。
它走 `authors_db.link` → `_ensure_entity`，只比對名稱，找不到就建新的。
於是 `fm_authors_link('Kou', '某團體')` 會安靜地多出一筆叫 `Kou` 的作者，
而不是接到既有的「甲作者」——正是 INT-12 警告的「建出兩筆互不相關的資料」。

> 建立與解除的行為不對稱。現況已由
> `tests/integration/test_int_10_18_authors_and_bridge.py` 鎖住，
> **但這比較像缺陷而非設計**。要改成一致的話先改這條規格與那支測試。
> 原本的 INT-13a 把兩個方向寫成一樣，是鑑定時從 commit 訊息推的，不精確。

---

## GUI 橋接

**INT-14** GUI 與 MCP server 之間走本機命名管道（`QLocalServer`）。

**INT-15** Hermes 對清單的寫入會推送到 GUI，GUI 立即重新整理作者面板。

**INT-16** GUI **先回應管道、再執行搜尋**。否則慢查詢在呼叫端看起來像逾時。

---

## 資料目錄一致性

**INT-17** MCP server 以專案 venv 的 python 執行（未凍結），
預設解析到專案目錄；使用者實際在跑的是打包後的 exe（解析到 exe 所在資料夾）。
不設 `FILEMANAGER_HOME` 時兩個進程各讀寫一份 `authors.db` 與 `config.ini`，
Hermes 寫進去的資料在程式裡完全看不到。

**INT-18** MCP server 啟動時必須在自己的 instructions 裡標明**實際解析到的資料目錄**，
兩端對不上時一眼就看得出來，而不是靜默不一致。

---

## 執行緒

**INT-19** `EverythingSDK` **每執行緒各自持有實例**，否則視窗類別名稱會衝突。

---

## 測試注意

- Everything 與 GUI 主程式在 CI 上都不存在。閘門測試餵假的管道探測，
  搜尋測試餵假的搜尋引擎。
- INT-2 的遍歷測試是本域最重要的一支：它是安全條文，而且新增工具時最容易漏。
