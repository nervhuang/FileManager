"""FOP-28：單選時再點一次已選取的檔名 → 就地改名。

節奏是 Qt 的 `SelectedClicked`：延後一個 double-click interval 才開編輯器，
所以每個「該進編輯」的斷言都得先等過那段時間，「不該進編輯」的也一樣——
等太短的話兩種情況看起來都一樣（都還沒開），測試就永遠是綠的。
"""
import time

import pytest
from PyQt5.QtCore import QEvent, QItemSelection, QItemSelectionModel, Qt
from PyQt5.QtGui import QMouseEvent, QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import QAbstractItemView, QApplication

from app.views import FileListView, SearchListView

pytestmark = pytest.mark.gui

COLUMNS = ['檔名', '目錄', '大小', '時間']
NAME_COLUMN = 0
SIZE_COLUMN = 2


@pytest.fixture(params=[SearchListView, FileListView], ids=['search', 'file'])
def view(request, qapp):
    widget = request.param()
    model = QStandardItemModel()
    model.setHorizontalHeaderLabels(COLUMNS)
    for row in range(6):
        model.appendRow([QStandardItem(f'{col}-{row}') for col in COLUMNS])
    widget.setModel(model)
    widget.setSelectionBehavior(QAbstractItemView.SelectRows)
    widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
    # 與 file_manager.initUI 給兩個面板的設定相同。
    widget.setEditTriggers(QAbstractItemView.SelectedClicked)
    widget.resize(700, 400)
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


def _click(view, row, column=NAME_COLUMN):
    pos = _centre(view, row, column)
    _send(view, QEvent.MouseButtonPress, pos, buttons=Qt.LeftButton)
    _send(view, QEvent.MouseButtonRelease, pos)


def _select_rows(view, first, last):
    model = view.model()
    view.selectionModel().select(
        QItemSelection(model.index(first, 0),
                       model.index(last, model.columnCount() - 1)),
        QItemSelectionModel.ClearAndSelect)
    QApplication.processEvents()


def _wait_past_the_double_click_interval(qapp):
    """Qt 的延遲編輯計時器跑完之前，「有進」與「沒進」長得一模一樣。"""
    loop_end = time.monotonic() + (QApplication.doubleClickInterval() + 200) / 1000.0
    while time.monotonic() < loop_end:
        qapp.processEvents()


def _is_editing(view):
    return view.state() == QAbstractItemView.EditingState


def test_fop_28_second_click_on_the_selected_name_starts_renaming(view, qapp):
    _select_rows(view, 1, 1)
    _click(view, 1)
    _wait_past_the_double_click_interval(qapp)
    assert _is_editing(view)


def test_fop_28_first_click_on_an_unselected_row_only_selects(view, qapp):
    _click(view, 1)
    _wait_past_the_double_click_interval(qapp)
    assert not _is_editing(view)
    assert [i.row() for i in view.selectionModel().selectedRows(0)] == [1]


def test_fop_28_multi_selection_collapses_instead_of_renaming(view, qapp):
    """多選時點其中一個，那一下的語意是收斂成單選（FOP-3），不是改名。"""
    _select_rows(view, 1, 3)
    _click(view, 2)
    _wait_past_the_double_click_interval(qapp)
    assert not _is_editing(view)
    assert [i.row() for i in view.selectionModel().selectedRows(0)] == [2]


def test_fop_28_double_click_cancels_the_pending_rename(view, qapp):
    """第二下補成雙擊就是「開啟」（FOP-25），編輯器不得再冒出來。"""
    _select_rows(view, 1, 1)
    _click(view, 1)
    _send(view, QEvent.MouseButtonDblClick, _centre(view, 1, NAME_COLUMN),
          buttons=Qt.LeftButton)
    _wait_past_the_double_click_interval(qapp)
    assert not _is_editing(view)


def test_fop_28_clicking_another_column_does_not_start_renaming(view, qapp):
    """檔名以外的欄位那一下先清空選取（FOP-1a），自然到不了改名。"""
    _select_rows(view, 1, 1)
    _click(view, 1, SIZE_COLUMN)
    _wait_past_the_double_click_interval(qapp)
    assert not _is_editing(view)


def test_fop_28_f2_still_opens_the_editor(view, qapp):
    """SelectedClicked 是「觸發」，不是「限制」：明確呼叫 edit() 仍要開得起來。"""
    index = view.model().index(1, NAME_COLUMN)
    view.setCurrentIndex(index)
    view.edit(index)
    qapp.processEvents()
    assert _is_editing(view)


def test_fop_28_both_panels_are_configured_for_it(main_window):
    """接線的那一半：面板的編輯觸發若被改回 NoEditTriggers，上面每一條都失效。"""
    for panel in (main_window.listView, main_window.listView2):
        assert panel.editTriggers() == QAbstractItemView.SelectedClicked
