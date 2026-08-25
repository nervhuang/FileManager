"""型別化的設定讀取，任何解析失敗都退回預設值。

`configparser` 的 `fallback=` 只在**鍵不存在**時生效。鍵存在但值的型別不對
——手改壞、寫到一半斷電——`getint` / `getboolean` 會直接拋例外，讀設定的流程
就此中斷。設定檔壞掉的代價應該是使用者失去設定，不是失去整個程式
（docs/spec/settings.md 的 SET-13）。
"""


def cfg_int(cfg, section, option, fallback):
    """讀整數；鍵不存在或值不是整數時回 fallback。"""
    try:
        return cfg.getint(section, option, fallback=fallback)
    except (ValueError, TypeError):
        return fallback


def cfg_bool(cfg, section, option, fallback):
    """讀布林；鍵不存在或值不是布林時回 fallback。"""
    try:
        return cfg.getboolean(section, option, fallback=fallback)
    except (ValueError, TypeError, AttributeError):
        return fallback


def cfg_int_list(raw):
    """把 "1,2,3" 解成 [1, 2, 3]；有任何一項不是整數就回空清單。

    整組回空而不是逐項略過：這些值是分割器尺寸與欄寬，少一項的清單套下去
    會讓版面錯位，不如當作沒有設定、改用預設。
    """
    try:
        return [int(x) for x in str(raw).split(',') if str(x).strip()]
    except (ValueError, TypeError):
        return []
