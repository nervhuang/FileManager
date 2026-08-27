"""FOP-4a：自行啟動拖曳之後，過期的框選錨點不得改寫選取。

這支測試是 2026-08-13 那次回退（commit 1e64fcc）缺的那一步。當時的結論是
「合成事件重現不出，問題在 drag.exec_() 的 modal loop」——不對。這裡完全不進
modal loop（startDrag 換成空函式，等同「拖曳已結束、控制權回到 mouseMoveEvent
之後」），照樣重現得出來。缺的只是**拖曳結束之後再送一次滑鼠移動**。

前置狀態刻意用「一次真實的壓下放開」＋「直接設定選取」組出來，不靠 Qt 自己的
框選編排：在啟用拖曳的 view 上，壓在項目上再移動走的是 DnD 而不是框選，
拿它當鋪陳只會讓測試在驗別的東西。
"""
import inspect

import pytest
from PyQt5.QtCore import QEvent, QItemSelection, QItemSelectionModel, QPoint, Qt
from PyQt5.QtGui import QMouseEvent, QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import QAbstractItemView, QApplication

from app.fileops.selection import ManualDragGuardMixin
from app.views import FileListView, SearchListView

COLUMNS = ['檔名', '目錄', '大小', '時間', '類型']
SIZE_COLUMN = 2


# ── 護欄本身（純邏輯，不需要 QApplication）─────────────────────────────

class _Probe(ManualDragGuardMixin):
    pass


class _FakeMove:
    def __init__(self, buttons):
        self._buttons = buttons

    def buttons(self):
        return self._buttons


@pytest.mark.logic
def test_fop_4a_guard_is_off_until_a_manual_drag_happens():
    assert _Probe()._swallow_move_after_manual_drag(_FakeMove(Qt.LeftButton)) is False


@pytest.mark.logic
def test_fop_4a_guard_swallows_moves_while_a_button_is_still_down():
    probe = _Probe()
    probe._note_manual_drag_finished()
    assert probe._swallow_move_after_manual_drag(_FakeMove(Qt.LeftButton)) is True
    assert probe._swallow_move_after_manual_drag(_FakeMove(Qt.RightButton)) is True


@pytest.mark.logic
def test_fop_4a_guard_lifts_once_every_button_is_up():
    """不解除的話，下一次框選就再也起不來了。"""
    probe = _Probe()
    probe._note_manual_drag_finished()

    assert probe._swallow_move_after_manual_drag(_FakeMove(Qt.NoButton)) is False
    assert probe._swallow_move_after_manual_drag(_FakeMove(Qt.LeftButton)) is False


@pytest.mark.logic
def test_fop_4a_guard_is_cleared_on_press_and_release():
    probe = _Probe()
    probe._note_manual_drag_finished()
    probe._clear_manual_drag_guard()
    assert probe._swallow_move_after_manual_drag(_FakeMove(Qt.LeftButton)) is False


# ── 每一處自行啟動的拖曳都要立旗標 ────────────────────────────────────

@pytest.mark.logic
@pytest.mark.parametrize("view_class", [SearchListView, FileListView])
def test_fop_4a_every_manual_drag_site_notes_it(view_class):
    """旗標漏立就等於沒有護欄，而漏立不會有任何症狀——直到使用者拖了一批檔案。"""
    lines = inspect.getsource(view_class.mouseMoveEvent).splitlines()
    # 註解裡也寫著 drag.exec_()，照字面數會多算一處
    source = chr(10).join(l for l in lines if not l.strip().startswith('#'))
    manual_sites = source.count('drag.exec_(') + source.count('self.startDrag(')
    assert manual_sites > 0, '這支 mouseMoveEvent 沒有自行啟動的拖曳？規格對不上了'
    assert source.count('_note_manual_drag_finished()') == manual_sites


@pytest.mark.logic
@pytest.mark.parametrize("view_class", [SearchListView, FileListView])
def test_fop_4a_both_panels_carry_the_guard(view_class):
    assert issubclass(view_class, ManualDragGuardMixin)


# ── 端對端：2026-08-13 的原始情境 ─────────────────────────────────────

@pytest.fixture
def view(qapp):
    widget = SearchListView()
    model = QStandardItemModel()
    model.setHorizontalHeaderLabels(COLUMNS)
    for row in range(10):
        model.appendRow([QStandardItem(f'{col}-{row}') for col in COLUMNS])
    widget.setModel(model)
    widget.setSelectionBehavior(QAbstractItemView.SelectRows)
    widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
    widget.setDragEnabled(True)
    widget.resize(600, 400)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


def _centre(view, row, column):
    return view.visualRect(view.model().index(row, column)).center()


def _send(view, kind, pos, button=Qt.LeftButton, buttons=Qt.NoButton):
    QApplication.sendEvent(
        view.viewport(), QMouseEvent(kind, pos, button, buttons, Qt.NoModifier))
    QApplication.processEvents()


def _selected_rows(view):
    return sorted(index.row() for index in view.selectionModel().selectedRows(0))


def _select_rows(view, first, last):
    model = view.model()
    view.selectionModel().select(
        QItemSelection(model.index(first, 0),
                       model.index(last, model.columnCount() - 1)),
        QItemSelectionModel.ClearAndSelect)


@pytest.mark.gui
def test_fop_4a_selection_survives_moves_after_a_manual_drag(view, monkeypatch):
    """錨點停在第 0 列、選取是 0–5、從第 3 列的大小欄拖走整批，拖完滑鼠還在動。"""
    drags = []
    monkeypatch.setattr(SearchListView, 'startDrag',
                        lambda self, actions: drags.append(actions))

    # Qt 的框選錨點留在第 0 列
    anchor = _centre(view, 0, 0)
    _send(view, QEvent.MouseButtonPress, anchor)
    _send(view, QEvent.MouseButtonRelease, anchor)
    _select_rows(view, 0, 5)
    assert _selected_rows(view) == [0, 1, 2, 3, 4, 5]

    press = _centre(view, 3, SIZE_COLUMN)
    _send(view, QEvent.MouseButtonPress, press)
    _send(view, QEvent.MouseMove, press + QPoint(40, 0), Qt.NoButton, Qt.LeftButton)
    assert drags, '前置條件：移動超過門檻要啟動拖曳'
    assert _selected_rows(view) == [0, 1, 2, 3, 4, 5], '拖曳當下整批就該還在'

    # 拖曳已經結束，但使用者的手還在動——這幾個事件不得改寫選取
    _send(view, QEvent.MouseMove, press + QPoint(60, 0), Qt.NoButton, Qt.LeftButton)
    _send(view, QEvent.MouseMove, _centre(view, 2, SIZE_COLUMN), Qt.NoButton, Qt.LeftButton)
    _send(view, QEvent.MouseMove, _centre(view, 8, SIZE_COLUMN), Qt.NoButton, Qt.LeftButton)

    assert _selected_rows(view) == [0, 1, 2, 3, 4, 5]
