# 設定層

目標位置 `app/settings/`。現況散在 [`app/file_manager.py`](../../app/file_manager.py) 的
`load_config`（129 行）與 `save_config`（102 行），以及 [`app/paths.py`](../../app/paths.py)。
這是**第一個要拆的域**：每個功能域都伸手進這兩個方法讀寫自己的設定，不先拆它，
後面每個域都還是得回頭依賴主視窗。

---

## 路徑解析

**SET-1** 可寫入的執行期目錄（`config.ini`、`authors.db`）依序決定：
環境變數 `FILEMANAGER_HOME`（非空白時優先）→ 凍結時為 exe 所在目錄 → 否則為專案根目錄。

**SET-2** 打包資源目錄（`icon.ico` 等）與執行期目錄是**不同**的兩件事：
凍結時為 `sys._MEIPASS`，否則為專案根目錄。混用會導致「寫進 `_internal/` 但執行期讀不到」。

**SET-3** 路徑解析不得依賴 Qt。GUI、MCP server、CLI 三個進程共用同一份解析邏輯，
其中兩個沒有 QApplication。

**SET-4** `config.ini` 不得被打包進發佈檔。程式讀的是 exe 同層的 `config.ini`，
打包進去的那份永遠不會被載入，只會洩漏建置機器的搜尋歷史與私人路徑。

**SET-5** 首次啟動時沒有 `config.ini` 是正常狀態：以內建預設值執行，關閉時寫出檔案。

---

## 段落與鍵

設定檔分五段。**每個功能域只准讀寫屬於自己的鍵**，這是拆分後要靠測試守住的界線。

### `[General]`

| 鍵 | 型別 | 說明 |
|---|---|---|
| `font_size` | int | 應用程式字型級數，見 [ui-shell.md](ui-shell.md) |
| `search_history` | JSON 陣列 | 搜尋歷史，還原時最新的排在最上 |

### `[Layout]`

| 鍵 | 型別 | 說明 |
|---|---|---|
| `window_geometry` / `window_state` | | 主視窗幾何與狀態 |
| `authors_panel_visible` | bool | 作者面板顯隱 |
| `authors_panel_width` | int | 作者面板寬度，預設 660，下限 80 |
| `checker_panel_visible` / `checker_panel_width` | | 更新檢查器面板顯隱與寬度 |
| `checker_split_sizes` / `checker_col_widths` | | 檢查器內部分割與欄寬 |
| `right_splitter_orientation` | | 右側面板水平／垂直 |
| `right_splitter_sizes` | | 水平配置下的分割尺寸 |
| `right_splitter_vertical_sizes` | | 垂直配置下的分割尺寸 |

**SET-6** 水平與垂直兩種配置的分割尺寸**各自獨立保存**，切換配置再切回來時尺寸不變。

### `[Columns]`

鍵名格式 `{panel}_col_widths`、`{panel}_col_hidden`、`{panel}_col_order`，
`{panel}` 為 `mid`（檔案面板）或 `right`（搜尋面板）。

**SET-7** 兩面板的欄位設定彼此獨立。

**SET-8** 還原順序固定為「寬度 → 隱藏 → 欄序」。先把寬度套到所有欄位（含隨後要隱藏的），
`QHeaderView` 才會記住隱藏欄的原始寬度，使用者日後勾回來時寬度才正確。

**SET-9** 舊版設定把隱藏欄寬度存成 `0`；讀到 `0` 時改用預設欄寬，否則欄位勾回來仍是 0 寬。

**SET-10** `{panel}_col_hidden` 鍵**存在但為空字串**代表「全部顯示」，
與**鍵不存在**（採用該面板的預設隱藏欄）是不同的兩件事。

### `[Sort]`

`mid_sort_column` / `mid_sort_order` / `right_sort_column` / `right_sort_order`。

### `[Exclude]`

| 鍵 | 型別 | 說明 |
|---|---|---|
| `enabled` | bool | 是否套用排除 |
| `dirs` | | 被排除的目錄清單 |

**SET-11** 排除設定同時套用於 GUI 搜尋與 MCP／CLI 搜尋，三者結果必須一致。
見 [integration.md](integration.md)。

### `[Tabs]`

`{panel}_tabs`（JSON 的 `[[data, label], …]`）與 `{panel}_tabs_current`（int）。

**SET-12** `restore_tabs` **不觸發** `tab_switched` 訊號。因此啟動時必須額外主動執行：
檔案面板導覽至還原後的當前目錄（無有效路徑則顯示所有磁碟機），
搜尋面板則主動跑一次當前頁籤的關鍵字搜尋。少了這步，還原出來的分頁會是空的。

---

## 容錯

**SET-13** 任何一個鍵解析失敗（JSON 壞掉、型別不符）只影響該鍵，改用預設值，
不得讓整個 `load_config` 中斷或讓程式無法啟動。

**SET-14** 設定於 `closeEvent` 寫出。**[未驗]** 崩潰時的設定遺失屬已知取捨，未做即時寫出。

---

## 拆分注意

- `load_config` 目前混雜「讀設定」與「套用設定到 widget」兩件事。拆分後設定層只負責
  讀寫與型別轉換，套用交給各功能域自己的 `apply_settings()`。
- `save_config` 同理，改為各域提供 `collect_settings()`。
- 拆分 commit 必須行為零變更：以既有 `config.ini` 讀入、寫出，前後檔案內容應等價。
