"""SHL-15a：兩個側邊面板的工具列入口。

只靠選單與快捷鍵叫得出來的面板等於藏起來了。這支測試把關的是三件事：
按鈕在、順序對（新增資料夾 → 作者／團體 → 更新檢查器）、按下去真的會切換。

圖示尺寸不在這裡驗——SHL-11 那支測試會遍歷全部工具列按鈕，新加的按鈕自動被涵蓋。
長相同樣不在這裡驗（offscreen 不會真的畫出東西）。
"""
import pytest
from PyQt5.QtWidgets import QToolButton

pytestmark = pytest.mark.gui


def _ordered_buttons(bar):
    """依工具列上的實際排列順序回傳按鈕。

    不能用 findChildren：那是建立順序，不是版面順序，而這條規格管的正是順序。
    """
    buttons = []
    for action in bar.actions():
        widget = bar.widgetForAction(action)
        if isinstance(widget, QToolButton):
            buttons.append(widget)
    return buttons


def _index_of(buttons, keyword):
    for i, button in enumerate(buttons):
        if keyword in button.toolTip():
            return i
    raise AssertionError(f'工具列上找不到工具提示含「{keyword}」的按鈕：'
                         f'{[b.toolTip() for b in buttons]}')


def test_shl_15a_both_side_panels_have_a_toolbar_entry(main_window):
    buttons = _ordered_buttons(main_window.mid_panel_toolbar)
    _index_of(buttons, '作者')
    _index_of(buttons, '更新檢查器')


def test_shl_15a_the_two_toggles_sit_after_new_folder_in_order(main_window):
    """作者／團體排在更新檢查器前面，兩者都排在「新增資料夾」之後。"""
    buttons = _ordered_buttons(main_window.mid_panel_toolbar)
    new_folder = _index_of(buttons, '新增資料夾')
    authors = _index_of(buttons, '作者')
    checker = _index_of(buttons, '更新檢查器')

    assert new_folder < authors < checker


def test_shl_15a_the_two_toggles_are_adjacent(main_window):
    """並列成一組，中間不夾別的按鈕。"""
    buttons = _ordered_buttons(main_window.mid_panel_toolbar)
    assert _index_of(buttons, '更新檢查器') - _index_of(buttons, '作者') == 1


def test_shl_15a_the_authors_button_toggles_the_panel(main_window, qapp):
    button = main_window.authors_toolbar_button
    assert main_window.authors_panel.isVisible()

    button.click()
    qapp.processEvents()
    assert not main_window.authors_panel.isVisible()
    assert main_window._authors_panel_visible is False

    button.click()
    qapp.processEvents()
    assert main_window.authors_panel.isVisible()
    assert main_window._authors_panel_visible is True


def test_shl_15a_the_authors_button_keeps_the_menu_item_in_sync(main_window, qapp):
    """按鈕、選單項目與快捷鍵是同一個動作的三個入口，勾選狀態不能各說各話。"""
    main_window.authors_toolbar_button.click()
    qapp.processEvents()

    assert main_window.action_authors_panel.isChecked() is False


def test_shl_15a_neither_toggle_is_checkable(main_window):
    """狀態回饋來自面板在不在畫面上；多一條同步路徑就多一個會腐化的地方。"""
    assert main_window.authors_toolbar_button.isCheckable() is False
    assert main_window.checker_toolbar_button.isCheckable() is False
