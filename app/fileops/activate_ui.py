"""把 `activate.plan_activation` 的判定做出來：導覽、開檔、該問的先問。

判定在 `activate.py`（不依賴 Qt、CI 測得到），這裡只剩「做」與「呈現」。
雙擊與 Enter 走同一支函式，兩者的行為因此不可能再分頭演化。

規格見 docs/spec/fileops.md 的 FOP-25 到 FOP-27。
"""

import os

from PyQt5.QtWidgets import QMessageBox

from . import activate


def activate_paths(paths, navigate, parent=None, open_file=None):
    """開啟這批路徑。回傳 True 代表已處理（呼叫端可以吃掉事件）。

    `navigate` 收單一目錄路徑，由呼叫端決定要導覽哪個面板。
    `open_file` 只為了測試可注入；預設是 `os.startfile`（要在呼叫時才取，
    monkeypatch 才蓋得到）。
    """
    open_file = open_file or os.startfile
    plan = activate.plan_activation(paths)

    if plan.directory:
        navigate(plan.directory)
        return True
    if not plan.files:
        return False

    if activate.needs_confirmation(plan):
        answer = QMessageBox.question(
            parent, "開啟多個檔案",
            f"要一次開啟 {len(plan.files)} 個檔案嗎？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return True

    for path in plan.files:
        try:
            open_file(path)
        except Exception as ex:
            # 第一個開不起來就停手：整批都開不起來時，逐一跳十幾個對話框
            # 比問題本身還難收拾。
            QMessageBox.warning(parent, "錯誤", f"無法開啟檔案: {ex}")
            return True
    return True
