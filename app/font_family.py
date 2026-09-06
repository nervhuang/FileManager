"""應用程式字型種類的設定。不依賴 Qt。

只有兩件事：檔案裡寫了什麼、拿不到時該用什麼（docs/spec/settings.md 的 SET-16）。
挑字型的對話框在 `app/font_dialog.py`，套用在 `app/font_scaling.py`。

自己讀寫、不經過主視窗的 `save_config`：字型是在對話框裡改、要立刻落地的設定，
掛在主視窗上就得等到關程式才寫進檔案。`ConfigStore.save()` 保留不認得的鍵，
兩邊因此不會互相覆蓋（與更新檢查筆數同一套作法，SET-15）。
"""

from . import settings

SECTION = 'General'
KEY = 'font_family'
SYSTEM_DEFAULT = ''      # 空字串＝不指定，交給 Qt 用系統預設字型


def load(store=None):
    """回目前設定的字型種類；沒設過回空字串（＝系統預設）。"""
    if store is None:
        store = settings.ConfigStore.load()
    return store.get_str(SECTION, KEY, SYSTEM_DEFAULT).strip()


def save(family, store=None):
    """寫回設定檔，回傳實際寫進去的值。

    不檢查這個字型在不在系統上：設定檔跟著使用者跑，換一台機器就可能沒有這套
    字型，而 Qt 對不認得的 family 本來就會自己替代。擋在這裡只會讓設定憑空消失。
    """
    if store is None:
        store = settings.ConfigStore.load()
    family = (family or SYSTEM_DEFAULT).strip()
    store.set(SECTION, KEY, family)
    store.save()
    return family
