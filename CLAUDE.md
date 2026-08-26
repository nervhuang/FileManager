# FileManager 開發規則

Windows 桌面檔案管理程式（PyQt5 + Everything 索引）。

這份文件寫的是**規則**，不是說明。行為規格在 [docs/spec/](docs/spec/)，
歷史在 [CHANGELOG.md](CHANGELOG.md)。

---

## 為什麼有這些規則

功能加得比防護快，`app/file_manager.py` 長到 2808 行、一個 `initUI` 佔 548 行，
所有功能混在同一個神類別裡。結果是原有功能默默消失也沒人發現：字型放大漏掉整個
作者面板、崩潰防護測試腐化兩個月沒人知道、新工具列圖示用了半尺寸的系統圖示。

每一次都不是誰疏忽，是「順手加在最方便的地方」的累積。下面的規則就是不讓那個
「最方便的地方」存在。

---

## 架構

**功能域拆包。** 每個域一個套件。多數域分兩層：**不依賴 Qt 的服務層**
（資料、純函式、原生 API）與依賴 Qt 的 UI 層。分層不是潔癖——MCP server 與
CLI 是沒有 `QApplication` 的獨立進程，它們要用得到服務層。

因此**各域的 `__init__.py` 一律不做 re-export**：一旦在那裡 import UI 層，
沒有 Qt 的進程連服務層都匯入不了。

| 域 | 套件 | 規格 |
|---|---|---|
| 設定 | `app/settings/` | [settings.md](docs/spec/settings.md) |
| 搜尋 | `app/search/` | [search.md](docs/spec/search.md) |
| 檔案操作 | `app/fileops/` | [fileops.md](docs/spec/fileops.md) |
| 分頁與導覽 | `app/tabs/` | [tabs.md](docs/spec/tabs.md) |
| 作者／團體 | `app/authors/` | [authors.md](docs/spec/authors.md) |
| 更新檢查器 | `app/checker/` | [checker.md](docs/spec/checker.md) |
| 對外整合 | `hermes_mcp.py`、`cli.py`、`gui_bridge.py` | [integration.md](docs/spec/integration.md) |
| 外殼 | `app/file_manager.py` | [ui-shell.md](docs/spec/ui-shell.md) |

橫切關注點另放：`app/icons.py`（工具列圖示）、`app/font_scaling.py`（字型縮放）、
`app/columns.py`（表頭欄位）、`app/paths.py`（執行期路徑）。

六個域都已建立，但外殼裡還有屬於它們的編排程式碼。各域規格的「尚未完成的部分」
記著還欠什麼。

### 硬規則

1. **新功能必須落在某個功能域套件裡。** 不確定是哪個域，先問，不要先寫。
2. **不得再往 `app/file_manager.py` 加方法。** 它是外殼，只准做三件事：
   建立面板、把訊號接到槽、管理版面。任何牽涉某個域商業規則的 `if`
   都代表那段程式碼放錯地方。
3. **域與域不得互相 import 對方的 UI。** 面板之間的互動一律走 Qt 訊號，
   由外殼接線。既有正確範例：`AuthorsPanel.search_requested`、
   `CheckerPanel.detail_requested`。
   不依賴 Qt 的**服務層**可以被別的域直接呼叫（更新檢查器的掃描器用
   `search.query.run_search` 找本機藏書），但方向必須無環，而且只能往
   服務層呼叫，不能反過來。掃描器跑在背景執行緒、沒有 Qt 事件圈，
   硬要它走訊號只會把簡單的事弄複雜。
4. **每個域只讀寫屬於自己的設定鍵。**
5. **單檔上限 600 行。** 目前只剩 `app/file_manager.py` 超標，記在
   `.line-limit-baseline.json`，只准變短。拆小之後跑
   `python scripts/check_line_limits.py --update`。

   **棘輪擋下你的修改時，它多半是對的。** 已經發生五次：每次的第一反應都是
   「往外殼再加幾行」，每次照它的意思先把更多東西搬出去之後，落點都更正確。
   要往外殼加東西，就得先從外殼拿走更多。

### 橫切關注點不准寫成手寫清單

`_apply_font_size` 是一份逐一列舉全 app widget 的白名單，每加一個面板都得記得
回來登記。作者面板漏過一次、更新檢查器是第二次補登記。這種形態一律改成遞迴或
自動註冊，並補一支遍歷測試把關。

---

## 改動流程

**規格、程式碼、測試三者同步。** 只改其中一邊視為錯誤。

- 改行為 → 改 `docs/spec/` 對應條文 → 改測試 → 改程式碼
- 加行為 → 先在規格加一條編號條文，再寫測試，再寫程式碼
- 條文編號（`SET-3`、`SRCH-14`…）是測試檔名的依據：
  `tests/search/test_srch_14_folder_first_sort.py`

### commit 粒度

- **重構 commit 行為零變更**，測試結果前後一致
- **修 bug 另開 commit，且先寫一支會失敗的測試**
- 兩者不得混在同一個 commit —— 混了就沒辦法用 `git bisect` 分辨是重構弄壞的
  還是修復弄壞的
- 直接在 main 上小步走，每個 commit 都保持可執行、測試綠燈、隨時可發版

### CHANGELOG

`feat:` 與 `fix:` 必須同步更新 [CHANGELOG.md](CHANGELOG.md)，寫**為什麼**，
不只是寫改了什麼。CHANGELOG 用英文（沿用該檔既有書寫），`docs/spec/` 用中文。

---

## 測試

```powershell
.venv\Scripts\python -m pytest            # 全部
.venv\Scripts\python -m pytest -m logic   # 純邏輯，秒級
```

- `logic`：不需要 `QApplication`。pre-commit hook 只跑這一類。
- `gui`：需要 `QApplication`，以 offscreen 執行。
- `manual`：預設不收集，只用來標記無法自動驗證的行為。

### offscreen 量得到什麼、量不到什麼

量得到：widget 尺寸、字型級數、選取模式、model/proxy 排序、訊號、
`icon.actualSize()`。

**量不到：長相。** offscreen 不會真的畫出文字。圖示好不好看、顏色對不對、
版面有沒有歪，一律標 **[手動]**，不要試圖用 offscreen 判定。
要看實際渲染就把圖示畫進 PNG 再開來看。

### CI 上不存在的東西

Everything、FileManager 主程式、exhentai、真實 shell。這些必須是可注入的介面，
測試餵假物件。這條界線也決定了「哪些邏輯應該是純函式」——愈多愈好。

### 任何會印中文的 Python 進入點都要固定 UTF-8

```python
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except Exception:
        pass
```

主控台預設用系統 codepage：開發機的繁中 Windows 是 cp950，GitHub Actions 的
windows runner 是 cp1252。兩者都印不出這個專案的中文訊息，會直接拋
`UnicodeEncodeError`。

這個 bug 已經出現過三次（`app/cli.py`、測試腳本、`scripts/check_line_limits.py`），
每一次的症狀都一樣難認：**工作本身其實成功了，死在印結果那一行**，
看起來卻像檢查失敗。

### 測試不得依賴開發者的個人設定

`tests/conftest.py` 已把 `FILEMANAGER_HOME` 指向空的暫存目錄。
這台開發機的 `config.ini` 排除了整個 `C:\`，沒隔離的話測試資料會被正確地濾光，
看起來像測試壞了。

---

## 把關

- **pre-commit**（`git config core.hooksPath .githooks`）：行數上限 + 純邏輯測試
- **CI**（`.github/workflows/test.yml`，windows-latest）：行數上限 + 全部測試

`--no-verify` 只是延後，CI 仍然會擋。

---

## 環境

- 執行期資料目錄（`config.ini`、`authors.db`）由 `app/paths.py` 決定，
  可用 `FILEMANAGER_HOME` 覆寫。GUI、MCP server、CLI 三個進程必須指向同一份。
- 這些**不依賴 Qt**，因為 MCP server 與 CLI 沒有 `QApplication`：
  `app/paths.py`、`app/settings/`、`app/search/query.py`、`app/search/everything.py`、
  `app/search/results.py`、`app/authors/db.py`、`app/authors/names.py`、
  `app/fileops/shell.py`、`app/checker/` 的資料層。保持這樣。
  改完可以這樣驗：匯入它們之後 `'PyQt5' in sys.modules` 必須是 False。
