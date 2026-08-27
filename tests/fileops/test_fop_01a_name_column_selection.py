"""FOP-1a、FOP-1b：左鍵只在「檔名」欄選取，其餘欄位視同空白處。

這個功能在 2026-08-13 上線當天就被回退（commit 1e64fcc），原因是 FOP-4a 那個
過期框選錨點的缺陷。修掉之後重新上線，所以這裡連「拖走整批之後選取還在不在」
一起驗——那正是當初垮掉的地方。

框選（rubber band）本身完全交給 Qt 原生流程，這裡驗的是「有沒有走進去」：
壓在非檔名欄之後往下拖，選取要真的擴到多列。
"""
import pytest
from PyQt5.QtCore import QEvent, QItemSelection, QItemSelectionModel, QPoint, Qt
from PyQt5.QtGui import QMouseEvent, QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import QAbstractItemView, QApplication

from app.views import FileListView, SearchListView

pytestmark = pytest.mark.gui

COLUMNS = ['檔名', '目錄', '大小', '時間', '類型']
NAME_COLUMN = 0
SIZE_COLUMN = 2


@pytest.fixture(params=[SearchListView, FileListView], ids=['search', 'file'])
def view(request, qapp):
    widget = request.param()
    model = QStandardItemModel()
    model.setHorizontalHeaderLabels(COLUMNS)
    for row in range(10):
        model.appendRow([QStandardItem(f'{col}-{row}') for col in COLUMNS])
    widget.setModel(model)
    widget.setSelectionBehavior(QAbstractItemView.SelectRows)
    widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
    widget.setDragEnabled(True)
    widget.resize(700, 400)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


def _centre(view, row, column):
    return view.visualRect(view.model().index(row, column)).center()


def _send(view, kind, pos, button=Qt.LeftButton, buttons=Qt.NoButton,
          modifiers=Qt.NoModifier):
    QApplication.sendEvent(
        view.viewport(), QMouseEvent(kind, pos, button, buttons, modifiers))
    QApplication.processEvents()


def _rows(view):
    return sorted(index.row() for index in view.selectionModel().selectedRows(0))


def _select_rows(view, first, last):
    model = view.model()
    view.selectionModel().select(
        QItemSelection(model.index(first, 0),
                       model.index(last, model.columnCount() - 1)),
        QItemSelectionModel.ClearAndSelect)


# ── FOP-1a：非檔名欄＝空白處 ──────────────────────────────────────────

def test_fop_1a_clicking_the_name_column_still_selects(view):
    pos = _centre(view, 3, NAME_COLUMN)
    _send(view, QEvent.MouseButtonPress, pos)
    _send(view, QEvent.MouseButtonRelease, pos)

    assert _rows(view) == [3]


def test_fop_1a_clicking_another_column_selects_nothing(view):
    pos = _centre(view, 3, SIZE_COLUMN)
    _send(view, QEvent.MouseButtonPress, pos)
    _send(view, QEvent.MouseButtonRelease, pos)

    assert _rows(view) == []


def test_fop_1a_clicking_another_column_clears_an_existing_selection(view):
    _select_rows(view, 1, 2)
    pos = _centre(view, 7, SIZE_COLUMN)

    _send(view, QEvent.MouseButtonPress, pos)
    _send(view, QEvent.MouseButtonRelease, pos)

    assert _rows(view) == []


def test_fop_1a_dragging_from_another_column_rubber_bands(view):
    """整個功能的目的：只用滑鼠就要拖得出多選。"""
    _send(view, QEvent.MouseButtonPress, _centre(view, 1, SIZE_COLUMN))
    for row in (2, 3, 4):
        _send(view, QEvent.MouseMove, _centre(view, row, SIZE_COLUMN),
              Qt.NoButton, Qt.LeftButton)
    _send(view, QEvent.MouseButtonRelease, _centre(view, 4, SIZE_COLUMN))

    assert _rows(view) == [1, 2, 3, 4]


@pytest.mark.parametrize("modifier", [Qt.ShiftModifier, Qt.ControlModifier],
                         ids=['shift', 'ctrl'])
def test_fop_1a_modifiers_do_not_rescue_a_non_name_column(view, modifier):
    """Shift／Ctrl 一併視同空白處——規則單一才好預測。"""
    _select_rows(view, 0, 0)
    pos = _centre(view, 5, SIZE_COLUMN)

    _send(view, QEvent.MouseButtonPress, pos, modifiers=modifier)
    _send(view, QEvent.MouseButtonRelease, pos, modifiers=modifier)

    assert _rows(view) == []


def test_fop_1a_right_click_still_selects_any_column(view):
    """右鍵要照常選取該列並開選單，不受空白處語意影響。"""
    pos = _centre(view, 6, SIZE_COLUMN)
    _send(view, QEvent.MouseButtonPress, pos, Qt.RightButton)

    assert _rows(view) == [6]


# ── FOP-1b：壓在「多選之一」的非檔名欄上 ──────────────────────────────

def test_fop_1b_pressing_a_selected_row_keeps_the_batch(view):
    _select_rows(view, 2, 5)

    _send(view, QEvent.MouseButtonPress, _centre(view, 3, SIZE_COLUMN))

    assert _rows(view) == [2, 3, 4, 5]


def test_fop_1b_dragging_takes_the_whole_batch(view, monkeypatch):
    """少了這條，框選好一批之後就再也拖不動它們。"""
    drags = []
    monkeypatch.setattr(type(view), 'startDrag',
                        lambda self, actions: drags.append(actions))
    _select_rows(view, 2, 5)

    press = _centre(view, 3, SIZE_COLUMN)
    _send(view, QEvent.MouseButtonPress, press)
    _send(view, QEvent.MouseMove, press + QPoint(60, 0), Qt.NoButton, Qt.LeftButton)

    assert drags, '超過拖曳門檻卻沒啟動拖曳'
    assert _rows(view) == [2, 3, 4, 5]


def test_fop_1b_the_batch_survives_moves_after_the_drag(view, monkeypatch):
    """2026-08-13 垮在這裡：拖完滑鼠還在動，選取被過期錨點改成另一段（FOP-4a）。"""
    monkeypatch.setattr(type(view), 'startDrag', lambda self, actions: None)
    _select_rows(view, 2, 5)

    press = _centre(view, 3, SIZE_COLUMN)
    _send(view, QEvent.MouseButtonPress, press)
    _send(view, QEvent.MouseMove, press + QPoint(60, 0), Qt.NoButton, Qt.LeftButton)
    _send(view, QEvent.MouseMove, _centre(view, 9, SIZE_COLUMN), Qt.NoButton, Qt.LeftButton)
    _send(view, QEvent.MouseMove, _centre(view, 0, SIZE_COLUMN), Qt.NoButton, Qt.LeftButton)

    assert _rows(view) == [2, 3, 4, 5]


def test_fop_1b_press_and_release_without_dragging_clears(view):
    """沒拖就放開＝在空白處點了一下。"""
    _select_rows(view, 2, 5)
    pos = _centre(view, 3, SIZE_COLUMN)

    _send(view, QEvent.MouseButtonPress, pos)
    _send(view, QEvent.MouseButtonRelease, pos)

    assert _rows(view) == []


def test_fop_1b_a_single_selected_row_is_not_an_exception(view):
    """例外只給「多選」。只選了一列時照空白處處理，框選才起得來。"""
    _select_rows(view, 3, 3)
    pos = _centre(view, 3, SIZE_COLUMN)

    _send(view, QEvent.MouseButtonPress, pos)

    assert _rows(view) == []


def test_fop_1a_the_rule_follows_the_name_column_when_columns_are_reordered(view):
    """欄序可以拖動並會被持久化（SET-8）。判斷用的是邏輯欄位，不是螢幕位置，
    所以檔名欄被搬到中間之後，會選取的仍然是它。"""
    view.header().moveSection(0, 2)          # 檔名欄搬到第三個位置
    QApplication.processEvents()

    _send(view, QEvent.MouseButtonPress, _centre(view, 4, NAME_COLUMN))
    _send(view, QEvent.MouseButtonRelease, _centre(view, 4, NAME_COLUMN))
    assert _rows(view) == [4], '檔名欄換位置之後就選不動了'

    pos = _centre(view, 6, SIZE_COLUMN)
    _send(view, QEvent.MouseButtonPress, pos)
    _send(view, QEvent.MouseButtonRelease, pos)
    assert _rows(view) == [], '非檔名欄換位置之後變成可以選了'
