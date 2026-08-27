"""清單面板的滑鼠選取手勢。

中間檔案面板與右側搜尋面板共用。放在這個域裡，是因為選取的規格
（`docs/spec/fileops.md` 的 FOP-1 到 FOP-4a）本來就寫在這個域底下。
"""

from PyQt5.QtCore import Qt


class ManualDragGuardMixin:
    """自行啟動拖曳之後的移動事件護欄（FOP-4a）。

    為了保住整組選取，壓在已選取項目上時不能呼叫 `QTreeView.mousePressEvent`
    （FOP-2），於是 Qt 內部的 `pressedPosition`——它的框選錨點——停留在**上一次
    真正壓下**的位置。`drag.exec_()` 回來之後若讓後續的移動落到
    `super().mouseMoveEvent()`，Qt 會進入 `DragSelectingState`，從那個過期錨點
    重新框選，把剛拖走的那批選取改成另一段。

    護欄在所有按鍵放開之後自動解除——不解除的話，下一次框選就起不來了。
    """

    _manual_drag_done = False

    def _note_manual_drag_finished(self):
        """緊接在自行呼叫的 startDrag／drag.exec_() 之後呼叫。"""
        self._manual_drag_done = True

    def _swallow_move_after_manual_drag(self, event):
        """回傳 True 代表這個移動事件要吃掉，不得往下傳給 Qt。"""
        if not self._manual_drag_done:
            return False
        if event.buttons() == Qt.NoButton:
            self._manual_drag_done = False
            return False
        return True

    def _clear_manual_drag_guard(self):
        self._manual_drag_done = False
