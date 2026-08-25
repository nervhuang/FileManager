"""設定層：config.ini 的讀寫與型別轉換。

不依賴 Qt——設定檔的格式、預設值與容錯是純資料問題，而 MCP server 與 CLI
也讀同一份檔案（見 docs/spec/settings.md 的 SET-3）。

套用設定到 widget 不屬於這一層。這裡只回答「檔案裡寫了什麼、拿不到時該用什麼」。
"""

from .config import cfg_bool, cfg_int, cfg_int_list

__all__ = ['cfg_bool', 'cfg_int', 'cfg_int_list']
