"""FOP-26：Enter 等同雙擊，作用於目前有焦點的面板。

判定本身由 test_fop_25_27_activate.py 顧，這裡驗的是接線：焦點在哪個面板、
選取怎麼變成路徑、Enter 有沒有走到同一支 activate_paths。

用搜尋面板做這件事，因為它的模型是同步填的；檔案面板的 QFileSystemModel
非同步列目錄，等它列完只會讓這支測試變慢又不穩。
"""
import os

import pytest
from PyQt5.QtCore import QEvent, QItemSelection, QItemSelectionModel, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication

from app.search.everything import SearchResult

pytestmark = pytest.mark.gui


def _fill(window, paths):
    window.update_search_results(
        [SearchResult(p, os.path.isdir(p), 0, 0) for p in paths])
    QApplication.processEvents()


def _select_rows(window, rows):
    view = window.listView2
    model = view.model()
    selection = QItemSelection()
    for row in rows:
        index = model.index(row, 0)
        selection.select(index, index.sibling(row, model.columnCount() - 1))
    view.selectionModel().select(selection, QItemSelectionModel.ClearAndSelect)
    view.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()


def _press_enter(window, key=Qt.Key_Return):
    QApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    QApplication.processEvents()


@pytest.fixture
def opened(monkeypatch):
    calls = []
    monkeypatch.setattr(os, 'startfile', calls.append, raising=False)
    return calls


@pytest.fixture
def visited(monkeypatch, main_window):
    calls = []
    monkeypatch.setattr(main_window, '_navigate_to_path', calls.append)
    return calls


def test_fop_26_enter_opens_the_selected_file(main_window, opened, visited, tmp_path):
    target = tmp_path / 'a.txt'
    target.write_text('x', encoding='utf-8')
    _fill(main_window, [str(target)])
    _select_rows(main_window, [0])

    _press_enter(main_window)

    assert opened == [str(target)]
    assert visited == []


def test_fop_26_numpad_enter_counts_too(main_window, opened, visited, tmp_path):
    target = tmp_path / 'a.txt'
    target.write_text('x', encoding='utf-8')
    _fill(main_window, [str(target)])
    _select_rows(main_window, [0])

    _press_enter(main_window, Qt.Key_Enter)

    assert opened == [str(target)]


def test_fop_26_enter_on_a_folder_navigates_the_file_panel(main_window, opened,
                                                           visited, tmp_path):
    folder = tmp_path / 'sub'
    folder.mkdir()
    _fill(main_window, [str(folder)])
    _select_rows(main_window, [0])

    _press_enter(main_window)

    assert visited == [str(folder)]
    assert opened == []


def test_fop_27_enter_opens_every_selected_file(main_window, opened, visited, tmp_path):
    targets = []
    for name in ('a.txt', 'b.txt'):
        target = tmp_path / name
        target.write_text('x', encoding='utf-8')
        targets.append(str(target))
    _fill(main_window, targets)
    _select_rows(main_window, [0, 1])

    _press_enter(main_window)

    assert sorted(opened) == sorted(targets)


def test_fop_26_enter_without_a_focused_panel_opens_nothing(main_window, opened,
                                                            visited, tmp_path):
    """焦點在別處（例如搜尋輸入框）時，Enter 不該從清單的殘留選取開檔。"""
    target = tmp_path / 'a.txt'
    target.write_text('x', encoding='utf-8')
    _fill(main_window, [str(target)])
    _select_rows(main_window, [0])
    main_window.right_info_combo.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()

    _press_enter(main_window)

    assert opened == []
