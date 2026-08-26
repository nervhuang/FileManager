# 搜尋域

[`app/search/`](../../app/search/)，分兩層。

| 檔案 | 依賴 Qt | 職責 |
|---|---|---|
| `query.py` | 否 | 關鍵字解析、查詢組裝、比對、排除、`extract_keywords` |
| `everything.py` | 否 | Everything 的 IPC 介面 |
| `models.py` | 是 | 結果模型、排序 proxy、把結果做成列並批次填入 |
| `results.py` | 否 | 結果呈現（`format_size`）|

不依賴 Qt 的那兩個是**服務層**：GUI、Hermes MCP server、CLI 是三個獨立進程，
其中兩個沒有 QApplication，三者搜出來的結果必須一致。更新檢查器的掃描器也走
這一層找本機藏書。

搜尋面板的 UI 編排（`execute_search_command`、`update_search_results`、
結果重新整理）仍在 [`app/file_manager.py`](../../app/file_manager.py)，尚未搬。

**關鍵約束**：搜尋邏輯必須是純函式、不依賴 Qt。GUI、MCP server、CLI 是三個獨立進程，
其中兩個沒有 QApplication，三者搜出來的結果必須完全一致。
`file_manager.py` 端只保留同名薄包裝方法。

---

## 關鍵字解析

**SRCH-1** 多個關鍵字以 `|` 分隔。含空白的詞組會自動加上雙引號，避免被 Everything 拆散。

**SRCH-2** 文字正規化採 NFKC ＋ casefold。全形 `－``．` 因此被正規化為半形 `-``.`。

**SRCH-3** **連字號與點不視為分隔符**。`A-10`、`ver.2`、`a.b.c` 必須整體保留。

**SRCH-4** 只剩連字號或點的孤立 token（如 `tsf - saeki` 中間的 `-`）要濾掉，不得污染查詢。

**SRCH-5** 全形／CJK 括號與連字號在檔名中通常只是標註，使用者真正要搜的是**符號之間的文字**。
查詢組裝因此以「去符號後的 tokens」為準：

- 單一詞 → 直接查該詞
- 多個詞 → 以空白分隔交給 Everything 原生 AND（不加引號、不需 regex 旗標、不要求詞序），
  另保留 regex 依序串接作為輔助

> 曾經的缺陷：只把含符號的原字串交給 Everything，檔名不含那些符號時就查無結果 ——
> 搜「（重要）」找不到「重要.txt」，搜「【tsf-saeki】」找不到「tsf-saeki」。

**SRCH-6** 比對過濾採 **token 子集**（各詞皆需出現在檔名），不要求整個正規化字串為連續子字串。
否則括號造成的空白差異會誤判 —— 關鍵字「重要（報告）」對不上檔名「重要報告」。

**SRCH-7** 含 `:` `<` `>` `!` `*` `?` 時視為 Everything 原生語法，整串原樣送出
（例如 `ext:zip path:D:\NAS`）。

**SRCH-8** `extract_keywords`（點檔名自動搜尋）辨識的括號含 ASCII `([{`、
全形 `（）［］｛｝`、CJK `【】〔〕「」『』〈〉《》`。

---

## 排除設定

**SRCH-9** `[Exclude]` 啟用時，落在被排除目錄**及其任何子路徑**下的結果一律濾掉。

**SRCH-10** 同一份排除規則同時套用於 GUI、MCP、CLI。

---

## 分頁與截斷

**SRCH-11** 搜尋結果回報四個彼此獨立的欄位：

| 欄位 | 意義 |
|---|---|
| `total` | 符合的總筆數，不受 `limit`/`offset` 影響 |
| `offset` | 本頁起始位置 |
| `has_more` | **本次分頁**沒給完 |
| `capped` | **Everything 索引端**撈滿了索取上限，代表 `total` 本身仍可能低估 |

**SRCH-12** `has_more` 與 `capped` 是不同的兩件事，不得合併成單一 `truncated` 旗標。

> 舊版只回一個 `truncated` 且只反映呼叫端的 `limit`，
> 被內部每次查詢上限砍掉的搜尋會謊稱自己是完整的。
> `truncated` 一詞在搜尋域已廢除；更新檢查器域另有自己的 `truncated`，語意不同。

**SRCH-13** `match='all'` 且關鍵字多於一個時，逐詞搜完取交集
（`|` 在搜尋管線裡是 OR，要 AND 只能自己算）。交集結果依路徑排序後再切分頁。

---

## 結果模型與排序

**SRCH-14** **資料夾恆排於所有檔案之上**，任一欄位、升冪降冪皆然。
測試涵蓋 6 種排序組合，見 `tests/search/test_srch_14_folder_first_sort.py`。

**SRCH-15** 結果中繼資料（大小、時間、是否為目錄）由 Everything 查詢直接回傳，
**不得逐筆 `os.stat`**。

**SRCH-16** `update_search_results` 接收 `everything_sdk.SearchResult` 的清單
（可解包為 `(filepath, is_dir, size, mtime)`），不接受字串清單。

> 這條規則曾經失守：`scripts/test_search_click_realapp.py` 自 2026-06-13 起仍傳
> `list[str]`，測試無法執行而沒人發現，「重建結果模型導致 proxy 對應表損毀 →
> 點擊時原生崩潰」這條防線空了兩個月。已修復並收編為
> `tests/search/test_srch_16_18_result_model_rebuild.py`。

**SRCH-17** 重建結果模型期間必須關閉排序 proxy 的 dynamic sorting。
每次 `appendRow` 都重排在 2000 列時是 O(n²)，會造成 2–3 秒 UI 凍結。

**SRCH-18** 重建結果模型不得損毀 proxy 的索引對應：舊作法在列數變少時重建會越界。
見 `tests/search/test_srch_16_18_result_model_rebuild.py`。
注意損毀只在完整主視窗路徑（真正的 `update_search_results`、啟用排序的 view、
真正的 `selectionModel`）下重現，最小化的 model/proxy 環境重現不出來。

---

## 重新整理策略

**SRCH-19** 只有**可能增加符合項**的操作（貼上／移動／拖放）才重跑完整 Everything 查詢。
刪除、重新命名、外部變更一律只做輕量的「該列是否還存在」對帳。

**SRCH-20** 拖放觸發的同步重新整理必須去重，不得重複執行。

**SRCH-21** 不得用 `setRootPath("")` 破壞式重載檔案面板；
交給 `QFileSystemModel` 內建 watcher 增量更新。

---

## 尚未完成的部分

- 搜尋面板的 UI 編排還在外殼裡：`execute_search_command`（頁籤資料與 MRU 歷史）、
  `_do_search`（Everything 不可用時的退路）、結果重新整理與存在性對帳。
  `update_search_results` 已經只剩排除過濾與一次委派。
- `everything` **每執行緒各自持有實例**，否則視窗類別名稱會衝突（INT-19）。
  這條約束目前只有註解，沒有測試。
- Everything 本體在 CI 上不存在。搜尋引擎必須是可注入的介面，
  單元測試餵假引擎；真實 Everything 的行為列為 **[手動]**。
