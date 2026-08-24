# 行為規格（SPEC）

這裡描述程式**現在應該是什麼**。歷史「何時為何改」在 [CHANGELOG.md](../../CHANGELOG.md)。

## 檔案配置

一個功能域一份規格，與 `app/` 底下的套件、與 `tests/` 底下的目錄三方 1:1。

| 規格 | 對應程式碼 | 對應測試 |
|---|---|---|
| [settings.md](settings.md) | `app/settings/` | `tests/settings/` |
| [search.md](search.md) | `app/search/` | `tests/search/` |
| [fileops.md](fileops.md) | `app/fileops/` | `tests/fileops/` |
| [tabs.md](tabs.md) | `app/tabs/` | `tests/tabs/` |
| [authors.md](authors.md) | `app/authors/` | `tests/authors/` |
| [checker.md](checker.md) | `app/checker/` | `tests/checker/` |
| [integration.md](integration.md) | `app/hermes_mcp.py`、`app/cli.py`、`app/gui_bridge.py` | `tests/integration/` |
| [ui-shell.md](ui-shell.md) | `app/file_manager.py`（外殼） | `tests/shell/` |

套件尚未拆分完成前，「對應程式碼」欄位寫的是**目標位置**，不是現況。現況見各規格內的註記。

## 條文編號

每條行為給一個 ID（`SET-3`、`SRCH-7`…）。測試以 ID 命名，例如：

```python
def test_SET_3_font_size_round_trips():
    ...
```

改行為時，SPEC 條文與測試一起改；只改其中一邊視為錯誤。

## 條文標記

| 標記 | 意義 |
|---|---|
| （無） | 已實作，且有或應有自動測試 |
| **[手動]** | 行為正確與否無法用 offscreen 測試判定（外觀、原生 shell 選單、真實網路），只能人工驗收 |
| **[待修]** | 規格是對的，程式碼目前不符。修復另開 commit，且先寫失敗測試 |
| **[未驗]** | 條文由程式碼逆向寫出，尚未經人工確認原意 |

## 來源

2026-08-24 的鑑定：把 CHANGELOG 的 107 條逐一對照程式碼，實測可測量的部分（面板最小寬、圖示尺寸、字型傳播、選取模式、排序），歧異項經人工裁決後寫成本規格。
