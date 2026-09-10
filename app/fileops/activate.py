"""「開啟」的判定：雙擊或按 Enter 時，這批選取要開什麼。不依賴 Qt。

只回答「導覽到哪個目錄、開哪些檔案」。實際的 `os.startfile`、導覽與對話框
留給呼叫端——同一個判定在檔案面板與搜尋面板要做的後續不同。

規格見 docs/spec/fileops.md 的 FOP-25 到 FOP-27。
"""

import os
from collections import namedtuple

# 超過這個數量才先問一聲。與 Windows 檔案總管相同的門檻：一次開十幾個
# 程式視窗是使用者按錯 Enter 的典型後果，而且沒有復原鍵。
CONFIRM_THRESHOLD = 15

# directory 有值代表要導覽進那個目錄；files 是要交給系統預設程式的檔案。
# 兩者不會同時有值——導覽一次只能去一個地方。
Plan = namedtuple('Plan', ('directory', 'files'))

NOTHING_TO_DO = Plan(None, ())


def plan_activation(paths, isdir=os.path.isdir, exists=os.path.exists):
    """判斷這批路徑按下去要開什麼。

    三種結果：
      Plan(目錄, ())        單選一個資料夾 → 導覽進去
      Plan(None, (檔案…))   開這些檔案
      Plan(None, ())        沒有東西可開

    多選時忽略其中的資料夾（FOP-27）：導覽只能去一個地方，而使用者按 Enter
    的意圖幾乎都是「把選到的檔案開起來」。
    """
    real = [p for p in paths if p and exists(p)]
    if not real:
        return NOTHING_TO_DO
    if len(real) == 1 and isdir(real[0]):
        return Plan(real[0], ())
    return Plan(None, tuple(p for p in real if not isdir(p)))


def needs_confirmation(plan):
    """要開的檔案多到該先問一聲嗎（FOP-27）。"""
    return len(plan.files) > CONFIRM_THRESHOLD
