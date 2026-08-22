# CLI（給 Hermes 以外的程式呼叫）

[`app/cli.py`](app/cli.py) 提供跟 [HERMES.md](HERMES.md) 講的 MCP server 完全相同的九個工具，差別只是介面換成一般的命令列，不需要跑 MCP 協定。任何語言的程式只要能執行外部指令、讀 stdout，就能用。

實作上直接呼叫 `app/hermes_mcp.py` 裡的工具函式（`@server.tool()` 只是註冊用的裝飾器，回傳原函式不變），所以行為與 MCP 端保證一致，包含下面這條授權規則。

---

## 授權機制：跟 MCP 一樣，主程式沒開就什麼都查不到

所有指令在 FileManager 主程式未執行時一律回：

```json
{"ok": false, "reason": "gui_not_running"}
```

此時 exit code 為 `1`。開啟主程式就是使用者授予存取權的動作，詳見 [HERMES.md](HERMES.md#授權機制主程式沒開就什麼都查不到) 的說明——CLI 與 MCP 共用同一個閘門，不是各自實作一份。

---

## 用法

跟 Hermes 的 MCP server 走同一支直譯器、同一份資料目錄：

```powershell
.venv\Scripts\python.exe -m app.cli <command> [options]
```

資料目錄（`FILEMANAGER_HOME`）的設定方式與 MCP server 完全相同，見 [HERMES.md 的「資料目錄」一節](HERMES.md#2-資料目錄filemanager_home)。

每個指令輸出**一行 JSON 到 stdout**；`ok` 為 `false` 時 exit code 為 `1`，方便 shell／其他程式判斷成敗。輸出固定用 UTF-8（不看主控台的系統 codepage），作者名稱常是日文，靠這個才不會印一半就炸掉。

---

## 指令一覽

參數與回傳欄位都對應 MCP 工具，詳細語意見 [HERMES.md 的「工具一覽」](HERMES.md#工具一覽)。

| 指令 | 對應 MCP 工具 | 參數 |
|---|---|---|
| `search` | `fm_search` | `query`（位置參數）、`--match`、`--limit`、`--under-dir`、`--ext` |
| `search-all` | `fm_search_all` | 同 `search`，另加 `--offset` |
| `open-search-tab` | `fm_open_search_tab` | `query`（位置參數） |
| `authors-list` | `fm_authors_list` | `--type`、`--keyword`、`--limit` |
| `authors-upsert` | `fm_authors_upsert` | `--json`（entries 的 JSON 陣列字串）；不給就從 stdin 讀 |
| `authors-link` | `fm_authors_link` | `author` `circle`（位置參數）、`--unlink` |
| `authors-delete` | `fm_authors_delete` | `--ids`（可多個）、`--name`、`--type` |
| `match-author` | `fm_match_author` | `--name`、`--type`、`--id`、`--limit` |
| `authors-stats` | `fm_authors_stats` | `--type`、`--limit` |

`--help` 可加在任何指令後面看完整說明。

### 範例

```powershell
# 搜尋
.venv\Scripts\python.exe -m app.cli search "zero戦" --limit 20

# 列出團體
.venv\Scripts\python.exe -m app.cli authors-list --type circle

# 新增／更新（entries 用 stdin 餵，避免跟殼層引號搏鬥）
'[{"name":"サイクロン","type":"circle","linked_names":["和泉","冷泉"],"english_name":"Cyclone"}]' | `
    .venv\Scripts\python.exe -m app.cli authors-upsert

# 建立關聯
.venv\Scripts\python.exe -m app.cli authors-link "和泉" "サイクロン"

# 用英文名稱反查回本機清單裡對應哪個實體
.venv\Scripts\python.exe -m app.cli authors-list --keyword "Cyclone"
.venv\Scripts\python.exe -m app.cli match-author --name "Cyclone"
```

`english_name` 是網站查詢用的英文名稱，單一字串（一對一，不是清單），不會影響本機檔案搜尋結果；但 `authors-list --keyword` 與 `match-author --name` 都能用它反查回對應的日文/中文實體。
