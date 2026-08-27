"""清單面板的滑鼠選取手勢。

中間檔案面板與右側搜尋面板共用。放在這個域裡，是因為選取的規格
（`docs/spec/fileops.md` 的 FOP-1 到 FOP-4a）本來就寫在這個域底下。
"""

from PyQt5.QtCore import (QItemSelectionModel, QPersistentModelIndex, Qt)
from PyQt5.QtWidgets import QApplication, QTreeView


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


class NameColumnSelectionMixin(ManualDragGuardMixin):
    """左鍵只在「檔名」欄選取項目；壓在其他欄位一律視同壓在空白處（FOP-1a）。

    欄位總寬超過畫面時，清單裡沒有任何空白區可供起始框選——每一個像素都落在某一
    列上，而那一列一按就進入拖放。把檔名以外的欄位變成「空白區」之後，在那裡按住
    左鍵拖曳就能框選多列。

    作法：壓下時暫時讓 `selectionCommand()` 回傳 `Clear`，其餘完全走
    `QAbstractItemView` 原本的流程——它照常記下 `pressedPosition`（框選的錨點），
    但不選中任何項目。選取被清空後 `selectedDraggableIndexes()` 為空，滑鼠移動時
    Qt 便不會進入 `DraggingState` 去啟動拖曳，而是進入 `DragSelectingState`
    開始框選。自動捲動與選取範圍都沿用 Qt 原生的框選，不另外實作。

    唯一的例外是「壓在多選之一的非檔名欄上」（FOP-1b）：那幾乎都是要把整批選取
    拖走，照樣清空的話，使用者就再也拖不動剛框選好的檔案。

    繼承 `ManualDragGuardMixin` 不是為了共用程式碼，是因為這裡自行啟動拖曳，
    非有那道護欄不可（FOP-4a）——少了它，拖完之後 Qt 會從過期錨點重新框選，
    這整個功能就是 2026-08-13 因此被回退的。
    """

    NAME_COLUMN = 0
    _hold_press = None
    _suppress_press_selection = False
    _anchor = None      # Shift 區間選取的錨點；只有 SearchListView 用得到

    def _handle_blank_zone_press(self, event):
        """左鍵壓下時的欄位分流。回傳 True 表示本次事件已由本混入處理完畢。"""
        if event.button() != Qt.LeftButton:
            return False
        index = self.indexAt(event.pos())
        if not index.isValid() or index.column() == self.NAME_COLUMN:
            return False

        sel = self.selectionModel()
        if sel is not None and sel.isSelected(index) and len(sel.selectedRows(0)) > 1:
            # 壓在「多選之一」的非檔名欄上：先什麼都不動，等移動或放開再決定。
            self._hold_press = QPersistentModelIndex(index)
            return True

        self._press_as_blank(event)
        return True

    def _handle_blank_zone_move(self, event):
        """壓住多選之後的移動門檻判定。回傳 True 表示事件已處理完畢。"""
        if self._hold_press is None:
            return False
        if (self._press_pos is None
                or (event.pos() - self._press_pos).manhattanLength()
                < QApplication.startDragDistance()):
            # 還沒到門檻：維持選取不變，也不讓 Qt 把這段移動當成框選
            return True
        self._hold_press = None
        self.startDrag(Qt.CopyAction | Qt.MoveAction | Qt.LinkAction)
        self._note_manual_drag_finished()
        self._press_pos = None
        self._press_button = Qt.NoButton
        return True

    def _handle_blank_zone_release(self, event):
        """壓住多選卻沒拖曳就放開：回歸空白處語意，清空選取。"""
        if self._hold_press is None:
            return False
        self._hold_press = None
        self._press_pos = None
        self._press_button = Qt.NoButton
        sel = self.selectionModel()
        if sel is not None:
            sel.clear()
        self._anchor = None
        return True

    def _press_as_blank(self, event):
        """以「不選取任何項目」的方式跑完 Qt 原本的 mousePressEvent。"""
        self._anchor = None
        self._suppress_press_selection = True
        try:
            QTreeView.mousePressEvent(self, event)
        finally:
            self._suppress_press_selection = False

    def selectionCommand(self, index, event=None):
        if self._suppress_press_selection:
            return QItemSelectionModel.Clear
        return super().selectionCommand(index, event)
