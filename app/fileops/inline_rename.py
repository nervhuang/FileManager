"""再點一次已選取的檔名 → 就地改名（FOP-28）。

節奏本身用 Qt 的 `SelectedClicked` 編輯觸發：它延後一個 double-click interval
才開編輯器，期間補上第二下就取消，因此不會與「雙擊開檔」搶同一個手勢。

缺的只有「多選時不要進編輯」——Qt 只看被點的那一項是不是已選取，不看總共
選了幾項。於是在多選狀態下點其中一個（那一下的語意是把選取收斂成單選，
FOP-3）也會進編輯，與檔案總管不同。
"""

from PyQt5.QtWidgets import QAbstractItemView


class SecondClickRenameMixin:
    """給清單面板用：只有單選時，再點一次已選取的項目才進入改名。"""

    def edit(self, index, trigger=None, event=None):
        if (trigger == QAbstractItemView.SelectedClicked
                and not self._single_row_selected()):
            return False
        # F2 與新建資料夾走的是單參數的 public slot，它會自己再繞回這個
        # 虛擬函式一次（trigger=AllEditTriggers），不會遞迴。
        if trigger is None:
            return super().edit(index)
        return super().edit(index, trigger, event)

    def _single_row_selected(self):
        selection_model = self.selectionModel()
        return (selection_model is not None
                and len(selection_model.selectedRows(0)) == 1)
