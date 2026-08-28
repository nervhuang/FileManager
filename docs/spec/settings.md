# 設定層

[`app/settings/`](../../app/settings/)，不依賴 Qt。

| 檔案 | 職責 |
|---|---|
| `config.py` | 型別化讀取的容錯（`cfg_int` / `cfg_bool` / `cfg_int_list`）|
| `store.py` | `ConfigStore`：一份 `config.ini` 的讀寫、段落與舊鍵管理 |
| [`app/paths.py`](../../app/paths.py) | 檔案位置解析（先於本套件存在，維持原位）|

設定層只回答兩件事：**檔案裡寫了什麼**，以及**拿不到時該用什麼**。
把值套到 widget 上不屬於這裡。`FileManager.load_config` / `save_config`
現在只做編排，面板內部的版面由面板自己的 `restore_layout` / `layout_state` 負責。

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

設定檔分六段。**每個功能域只准讀寫屬於自己的鍵**，這是拆分後要靠測試守住的界線。

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

### `[Checker]`

| 鍵 | 型別 | 說明 |
|---|---|---|
| `first_run_limit` | int | 首次掃描每位作者取幾筆建立基準（預設 25）|
| `max_items` | int | 之後每輪最多回溯幾筆（預設 50）|

**SET-15** 更新檢查器的兩個筆數上限由 `app/checker/limits.py` **自己讀寫**，
不經過 `FileManager.load_config` / `save_config`。它讀出一份 `ConfigStore`、只改
這兩個鍵、立刻存回；`ConfigStore` 保留不認得的鍵，因此主視窗稍後寫出自己那批鍵時
兩邊不會互相覆蓋。範圍夾在 25–500，超出或值壞掉都退回預設——設定檔手改是預期用法，
壞值的代價該是失去這個設定，不是掃描炸掉。

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

## 尚未完成的部分

- 各功能域還沒有自己的 `apply_settings()` / `collect_settings()`。`load_config` 仍然
  知道每一個鍵屬於誰；等域拆出來之後，這裡應該只剩「問每個域要它的設定」。
- 欄位的還原與寫出已移到 [`app/columns.py`](../../app/columns.py)。它們依賴
  `QHeaderView`，不能放進這個不依賴 Qt 的套件；等檔案面板域拆出來時再隨它搬。
