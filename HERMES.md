# 與 Hermes 整合（MCP）

本專案內建一個 MCP stdio server（[`app/hermes_mcp.py`](app/hermes_mcp.py)），讓 [Hermes](https://github.com/) agent 能查詢本機檔案、讀寫作者／團體清單，並叫主程式開搜尋分頁。

工具在 Hermes 裡會以 `mcp_filemanager_*` 前綴出現。

---

## 授權機制：主程式沒開就什麼都查不到

**全部九個工具**在 FileManager 主程式未執行時一律回：

```json
{"ok": false, "reason": "gui_not_running"}
```

開啟主程式就是使用者授予存取權的動作。關著的時候，Hermes 讀不到硬碟內容，也讀不到作者清單。

幾個刻意的設計：

- **閘門套用在每一個工具**，不只是會掃硬碟的那幾個。只擋一部分的話，模型改叫另一個工具就繞過去了，形同虛設。
- **`fm_open_search_tab` 不會自行啟動主程式。** 能啟動主程式的工具，等於可以自己授予這道閘門本來要擋下的存取權。
- 判定方式是本機命名管道是否存在（見 [`app/gui_bridge.py`](app/gui_bridge.py)），沒有連線成本。

---

## 安裝與設定

### 1. 伺服器端套件

```powershell
.venv\Scripts\pip install mcp
```

Hermes 那邊也要有 `mcp` 套件，否則它的 MCP client 會靜默停用。

### 2. 資料目錄：`FILEMANAGER_HOME`

程式的資料目錄（`config.ini`、`authors.db`）預設是這樣決定的：

| 執行方式 | 預設資料目錄 |
|---|---|
| 打包後的 exe（凍結） | exe 所在資料夾 |
| 從原始碼執行、MCP server | 專案目錄 |

所以**不設這個變數的話，MCP server 與 exe 會各自讀寫一份 `authors.db` 與 `config.ini`**，Hermes 寫進去的資料在程式裡完全看不到。

建議設成使用者層級環境變數，一次涵蓋所有入口（exe、原始碼執行、MCP server）：

```powershell
[Environment]::SetEnvironmentVariable('FILEMANAGER_HOME', 'D:\你的安裝資料夾', 'User')
```

設定後需重新啟動終端機、編輯器與 Hermes——Windows 的環境變數只在進程啟動時繼承。

MCP server 啟動時會在自己的 instructions 裡標明實際解析到的資料目錄，兩端若對不上一眼就看得出來。

### 3. Hermes 設定檔

Windows 上的實際位置是 `%LOCALAPPDATA%\hermes\config.yaml`（不是文件寫的 `~/.hermes/config.yaml`）。

```yaml
mcp_servers:
  filemanager:
    command: 'D:\PycharmProjects\FileManager\.venv\Scripts\python.exe'
    args: ['-m', 'app.hermes_mcp']
    env:
      PYTHONPATH: 'D:\PycharmProjects\FileManager'
      FILEMANAGER_HOME: 'D:\你的安裝資料夾'
    timeout: 120
    connect_timeout: 60
```

**路徑一律用單引號。** YAML 雙引號會把 `\P`、`\f` 之類當成逸出序列，`"D:\PycharmProjects"` 會直接解析失敗，`'D:\filemanager'` 則安然無恙。

改完設定要重啟 Hermes 才會生效。

---

## 工具一覽

### 檔案搜尋

#### `fm_search` — 一般搜尋

| 參數 | 預設 | 說明 |
|---|---|---|
| `query` | 必填 | 關鍵字，以 `\|` 分隔多個。也接受 Everything 原生語法（含 `: < > ! * ?` 時整串原樣送出，例如 `ext:zip path:D:\NAS`） |
| `match` | `any` | `any` 任一關鍵字命中即列出；`all` 所有關鍵字都要命中 |
| `limit` | 200 | 最多回傳幾筆 |
| `under_dir` | — | 只回傳此目錄底下的結果 |
| `ext` | — | 只回傳此副檔名，例如 `zip` |

適合找幾個特定檔案。**看不到向 Everything 索取的每查詢上限之外的資料**，撞到時 `capped` 為 `true`。

#### `fm_search_all` — 大量搜尋（可分頁）

參數同 `fm_search`，另加 `offset`（預設 0）。回傳欄位與 `fm_search` **完全相同**，另有 `total`、`offset`、`has_more`。

把 `offset` 加上 `count` 再呼叫一次，直到 `has_more` 為 `false`，就能取得完整清單。單頁上限 2000 筆（每筆約 0.28 KB，2000 筆約 560 KB）。

適合「把符合的檔案全部列出來」。實測某關鍵字 `fm_search` 只看得到 2000 筆，這個工具能取得全部 6989 筆。

#### `fm_match_author` — 找某作者／團體的作品

| 參數 | 預設 | 說明 |
|---|---|---|
| `name` | — | 作者或團體名稱（也比對別名） |
| `type` | — | `author` / `circle`，用於消歧義 |
| `id` | 0 | 直接指定實體 id |
| `limit` | 200 | 最多回傳幾筆 |

把該實體的**名稱與所有別名**組成 OR 查詢丟進同一套搜尋管線，因此結果與使用者在程式裡點該項目看到的完全一致。

### 作者／團體清單

#### `fm_authors_list` — 查詢

| 參數 | 預設 | 說明 |
|---|---|---|
| `type` | — | `author` / `circle`，留空則兩者都列 |
| `keyword` | — | 以子字串比對名稱與別名 |
| `limit` | 500 | 最多幾筆 |

#### `fm_authors_upsert` — 新增或更新

參數 `entries`（陣列，必填）。每筆可帶：

- `name`、`type`（`author` / `circle`）——新增時必填
- `id`——要改既有項目時給
- `aliases`——字串陣列，會**整組取代**
- `linked_names`——相對類型的名稱陣列（作者填團體名、團體填作者名），對方不存在會自動建檔並雙向關聯
- `note`

以 `(type, name)` 找得到現有項目時會更新它，不會重複新增。

> **已知作者與其所屬團體時，務必用 `linked_names` 一起送**，不要送成兩筆彼此無關的 entry。少了關聯，它們在清單裡會變成兩個孤立項目，而不是團體底下掛著作者。只送一筆帶 `linked_names` 的 entry 即可：
>
> ```json
> [{"name": "南浜屋", "type": "circle", "linked_names": ["南浜よりこ"]}]
> ```

#### `fm_authors_link` — 單獨建立或解除關聯

| 參數 | 預設 | 說明 |
|---|---|---|
| `author` | 必填 | 作者名稱 |
| `circle` | 必填 | 團體名稱 |
| `unlink` | `false` | 設為 `true` 則是解除關聯（兩個項目本身都保留） |

兩者已各自存在、只是還沒關聯時用這個補，不必重送整筆資料。任一邊不存在會自動建檔；作者與團體是多對多，重複呼叫同一組不會產生重複資料。

#### `fm_authors_delete` — 刪除

給 `ids` 陣列，或給 `name` + `type` 二擇一。**軟刪除**，使用者可在程式的「最近變更」一鍵還原。

### 統計

#### `fm_authors_stats` — 每個作者／團體各有幾個檔案

參數 `type`（留空則全部）、`limit`（預設 100）。

會對每個實體各跑一次搜尋，項目多時很慢，建議搭配 `type` 或 `limit` 縮小範圍。

### GUI 操作

#### `fm_open_search_tab` — 開搜尋分頁

參數 `query`（必填）。在程式右面板開一個新分頁顯示該關鍵字的搜尋結果。

---

## 回傳欄位

搜尋類工具共通：

| 欄位 | 意義 |
|---|---|
| `count` | 本次回傳筆數，等於 `len(results)` |
| `total` | 符合的總筆數，不受 `limit` / `offset` 影響 |
| `offset` | 本頁起始位置 |
| `has_more` | **本次分頁**沒給完，調 `offset` 可繼續取 |
| `capped` | **Everything 索引端**撈滿了索取上限，代表 `total` 本身可能仍是低估 |
| `results` | 每筆含 `path`、`name`、`dir`、`is_dir`、`size`、`mtime` |

`has_more` 與 `capped` 是不同的兩件事，別混用：前者是「這一頁沒給完」，後者是「索引裡可能還有更多沒被取回」。

所有搜尋都會套用程式裡的**排除目錄設定**（`config.ini` 的 `[Exclude]`，在程式的「選項 → 排除設定」裡維護）。設定一按確定就寫回檔案，因此 MCP 端讀到的永遠是最新值。

---

## 資料存放

| 檔案 | 內容 |
|---|---|
| `<FILEMANAGER_HOME>/authors.db` | 作者／團體清單（SQLite、WAL），含別名、多對多關聯與完整變更紀錄 |
| `<FILEMANAGER_HOME>/config.ini` | 程式設定，MCP 端只讀其中的 `[Exclude]` |

清單的每一次寫入都會附帶變更前後快照寫進 `changes` 表，刪除一律為軟刪除，因此 Hermes 寫錯的任何一筆都能從程式的「最近變更」還原。

---

## 疑難排解

| 症狀 | 原因與處理 |
|---|---|
| 所有工具都回 `gui_not_running` | 主程式沒開。這是設計行為，開啟 FileManager 即可 |
| 回 `everything_unavailable` | Everything 沒在執行，或找不到它的 IPC 視窗。與 FileManager 無關 |
| Hermes 寫入的資料在程式裡看不到 | 兩邊的資料目錄不一致。檢查 `FILEMANAGER_HOME`，並比對 MCP server instructions 裡回報的資料目錄 |
| Hermes 啟動時 MCP server 沒出現 | Hermes 環境缺 `mcp` 套件（會靜默停用），或 `config.yaml` 的路徑用了雙引號導致 YAML 解析失敗 |
| 搜尋結果包含不想要的目錄 | 在程式的「選項 → 排除設定」加入該目錄，MCP 端會立即沿用 |
| 作者與團體變成兩個孤立項目 | 寫入時漏了 `linked_names`。用 `fm_authors_link` 補上關聯即可 |
