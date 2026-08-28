"""每輪要抓「最新幾筆」的設定。不依賴 Qt。

原本兩個數字寫死在 `scanner.py`：首次掃描取 25 筆建立基準、之後最多回溯 50 筆。
兩者都是估的——作者發書快慢差很多，藏書斷了半年再開的人，50 筆根本追不回來，
只會每位都標上「可能有遺漏」。所以交給使用者調。

放在這一層而不是 `scanner.py` 裡，是因為掃描跑在沒有 Qt 事件圈的背景執行緒，
而對話框在主執行緒——中間得有一個兩邊都能呼叫的地方，而它不能依賴 Qt。
"""

from collections import namedtuple

from .. import settings

SECTION = 'Checker'
FIRST_RUN_KEY = 'first_run_limit'
MAX_ITEMS_KEY = 'max_items'

FIRST_RUN_DEFAULT = 25          # tag 頁一次回 25 筆，取滿一頁不多花任何一次請求
MAX_ITEMS_DEFAULT = 50          # 2 頁
MINIMUM = 25                    # 少於一頁沒有意義：那一頁本來就整頁回來了
MAXIMUM = 500                   # 20 頁。再多就不是「檢查更新」，是重建整份清單

Limits = namedtuple('Limits', 'first_run max_items')

DEFAULTS = Limits(FIRST_RUN_DEFAULT, MAX_ITEMS_DEFAULT)


def clamp(value, fallback):
    """夾在 MINIMUM～MAXIMUM 之間；不是整數就回 fallback。

    設定檔不是只有這個程式會寫（手改是預期用法），值壞掉的代價應該是
    退回預設，不是掃描炸掉。
    """
    try:
        value = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(MINIMUM, min(MAXIMUM, value))


def load(store=None):
    """讀出目前設定；讀不到或值壞掉都退回預設。"""
    if store is None:
        store = settings.ConfigStore.load()
    return Limits(
        clamp(store.get_str(SECTION, FIRST_RUN_KEY), FIRST_RUN_DEFAULT),
        clamp(store.get_str(SECTION, MAX_ITEMS_KEY), MAX_ITEMS_DEFAULT),
    )


def save(limits, store=None):
    """寫回設定檔，回傳實際寫進去的（已夾範圍的）值。

    自己載入、自己存檔，不經過主視窗：`ConfigStore.save()` 會保留不認得的鍵，
    主視窗稍後存自己那批鍵時不會把這裡寫的洗掉。
    """
    if store is None:
        store = settings.ConfigStore.load()
    limits = Limits(clamp(limits[0], FIRST_RUN_DEFAULT),
                    clamp(limits[1], MAX_ITEMS_DEFAULT))
    store.set(SECTION, FIRST_RUN_KEY, limits.first_run)
    store.set(SECTION, MAX_ITEMS_KEY, limits.max_items)
    store.save()
    return limits
