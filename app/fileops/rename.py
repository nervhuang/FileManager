"""重新命名的判定。不依賴 Qt。

只回答「這次改名該不該做、目標是什麼、不行的話為什麼」。實際的 `os.rename`
與訊息呈現留給呼叫端——搜尋面板改完要就地更新那一列，檔案面板不用。

規格見 docs/spec/fileops.md 的 FOP-10 到 FOP-12。
"""

import os
from collections import namedtuple

# Windows 檔名不接受的字元。
INVALID_CHARS = '\\/:*?"<>|'

# new_path 為 None 代表不執行；error 為 None 代表不是錯誤，只是沒有要改。
Plan = namedtuple('Plan', ('new_path', 'error'))

NOTHING_TO_DO = Plan(None, None)


def plan_rename(old_path, new_name):
    """判斷是否要把 old_path 改名為 new_name。

    三種結果：
      Plan(新路徑, None)   可以做
      Plan(None, 訊息)     不能做，訊息給使用者看
      Plan(None, None)     沒有要改（空白、或名稱沒變），呼叫端把顯示還原即可
    """
    new_name = (new_name or '').strip()
    old_name = os.path.basename(old_path)
    if not new_name or new_name == old_name:
        return NOTHING_TO_DO

    if any(ch in new_name for ch in INVALID_CHARS):
        return Plan(None, '檔名包含無效字元。')

    new_path = os.path.join(os.path.dirname(old_path), new_name)

    # Windows 的 os.path.exists 不分大小寫，會把「同一個檔案只改大小寫」
    # （Report.txt → report.txt）誤判成目標已存在而擋下來。改名為自己不算衝突，
    # 交給 os.rename 處理；只有指向**不同**檔案時才算已存在（FOP-12）。
    same_file = (os.path.normcase(os.path.normpath(new_path)) ==
                 os.path.normcase(os.path.normpath(old_path)))
    if not same_file and os.path.exists(new_path):
        return Plan(None, '目標名稱已存在。')

    return Plan(new_path, None)
