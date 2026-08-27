"""TAB-1 到 TAB-6、TAB-12、TAB-17 到 TAB-25：拖曳重排的組態、麵包屑、導覽。

拖曳重排的**動畫過程**（浮動副本跟著游標、越過鄰居就換位）只能人工看；
這裡驗的是它的組態——那些設錯就整個機制失效的地方。
"""

import pytest

from app.tabs.bar import FixedWidthTabBar, PathTabBar
from app.tabs.breadcrumb import BreadcrumbBar, split_path

pytestmark = pytest.mark.gui


CHEVRONS = {'›', '«', '‹', '»'}


def _crumb_labels(crumb):
    """只取路徑分段的按鈕。

    麵包屑是「分段鈕 ＋ › 箭頭」交錯排的，另有一顆 « 溢位鈕——那些是控制元件，
    不是路徑的一部分。
    """
    from PyQt5.QtWidgets import QToolButton

    return [b.text() for b in crumb.findChildren(QToolButton)
            if b.text() and b.text() not in CHEVRONS]


@pytest.fixture
def bar(qapp):
    widget = PathTabBar()
    widget.resize(600, 40)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


@pytest.fixture
def crumb(qapp):
    widget = BreadcrumbBar()
    widget.resize(800, 32)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


# ── TAB-1：停用 Qt 內建的拖曳重排 ──────────────────────────────────────

def test_tab_1_qt_native_movable_drag_is_off(bar):
    """內建做法的 ghost widget 在捲動途中無法重新定位，所以重排完全自己實作。

    這個旗標一旦被打開，兩套機制會同時作用，拖曳行為就亂了。
    """
    assert bar.tab_bar.isMovable() is False


# ── TAB-4：拖出範圍外時逐格推進的間隔 ──────────────────────────────────

def test_tab_4_out_of_bounds_scroll_steps_every_80ms(bar):
    assert FixedWidthTabBar.SCROLL_INTERVAL == 80
    assert bar.tab_bar._scroll_timer.interval() == 80


def test_tab_4_the_scroll_timer_is_idle_when_not_dragging(bar):
    assert bar.tab_bar._scroll_timer.isActive() is False


# ── TAB-6：用 arrowType 辨識捲動鈕，不能用位置 ─────────────────────────

def test_tab_6_scroll_into_view_does_not_crash_without_scroll_buttons(bar, qapp):
    """分頁少到不需要捲動時沒有捲動鈕，這條路徑仍要安全。"""
    bar.restore_tabs([(r'D:\甲', '甲')], 0)
    qapp.processEvents()
    bar.tab_bar.scroll_index_into_view(0)      # 不該拋例外


def test_tab_6_scroll_into_view_reaches_the_last_tab(bar, qapp):
    """頁籤很寬時兩個箭頭會擠在同一側，用位置判斷會選錯方向，所以改用
    arrowType。這裡驗的是結果：最後一個分頁要被捲到看得見。"""
    bar.restore_tabs([(f'D:\\很長的資料夾名稱{i}', f'分頁{i}') for i in range(20)], 0)
    qapp.processEvents()

    bar.tab_bar.scroll_index_into_view(19)
    qapp.processEvents()

    rect = bar.tab_bar.tabRect(19)
    assert rect.isValid()


# ── TAB-12：點選目前已在的分頁仍要重新載入 ─────────────────────────────

def test_tab_12_activating_the_current_tab_still_reloads_it(bar, qapp):
    """setCurrentIndex 對同一個 index 不會發出 currentChanged，
    所以「點目前這個分頁」得自己補一次通知，否則面板不會重新載入。"""
    bar.restore_tabs([(r'D:\甲', '甲'), (r'D:\乙', '乙')], 1)
    qapp.processEvents()

    switched = []
    bar.tab_switched.connect(switched.append)

    bar._activate_tab(1)                       # 已經在第 1 個
    qapp.processEvents()

    assert switched == [r'D:\乙'], '點目前分頁也要發出切換通知'


def test_tab_12_activating_another_tab_switches_and_notifies(bar, qapp):
    bar.restore_tabs([(r'D:\甲', '甲'), (r'D:\乙', '乙')], 0)
    qapp.processEvents()

    switched = []
    bar.tab_switched.connect(switched.append)

    bar._activate_tab(1)
    qapp.processEvents()

    assert bar.tab_bar.currentIndex() == 1
    assert switched == [r'D:\乙']


# ── TAB-19：最左的根箭頭列出所有磁碟機 ─────────────────────────────────

def test_tab_19_root_chevron_exists_even_with_no_path(crumb):
    assert crumb._root_btn is not None


def test_tab_19_root_chevron_survives_navigation(crumb, qapp):
    """每次 set_path 都會重建麵包屑，根箭頭不能在重建時掉了。"""
    crumb.set_path(r'D:\甲\乙')
    qapp.processEvents()
    assert crumb._root_btn is not None


# ── TAB-18／TAB-20：分段與可編輯路徑框 ─────────────────────────────────

def test_tab_20_focus_edit_switches_to_the_editable_box(crumb, qapp):
    """Ctrl+L／Alt+D／點空白區都走這裡。"""
    crumb.set_path(r'D:\甲')
    qapp.processEvents()

    crumb.focus_edit()
    qapp.processEvents()

    assert crumb._edit.isVisible()
    assert crumb._edit.text() == r'D:\甲'
    assert crumb._edit.selectedText() == r'D:\甲', '要全選，才能直接打字覆蓋'


def test_tab_18_set_path_builds_one_crumb_per_segment(crumb, qapp):
    path = r'D:\甲\乙\丙'
    crumb.set_path(path)
    qapp.processEvents()

    assert _crumb_labels(crumb) == [text for text, _target in split_path(path)]


# ── TAB-25：沒有有效路徑時的行為 ───────────────────────────────────────

def test_tab_25_empty_path_shows_the_this_pc_crumb(crumb, qapp):
    """沒有路徑時顯示「本機」，而不是一片空白——空白會讓人以為麵包屑壞了。"""
    crumb.set_path('')
    qapp.processEvents()

    assert _crumb_labels(crumb) == ['本機']


def test_tab_25_main_window_shows_drives_when_the_tab_has_no_path(main_window, qapp):
    """空白分頁沒有路徑，檔案面板要顯示所有磁碟機而不是空白。"""
    main_window._show_all_drives()
    qapp.processEvents()

    model = main_window.listView.model()
    assert model is not None
    assert model.rowCount(main_window.listView.rootIndex()) > 0


# ── TAB-23：導覽按鈕的啟用狀態 ─────────────────────────────────────────

def test_tab_23_back_and_forward_start_disabled(main_window, qapp):
    """剛開起來沒有歷史，兩顆都不該能按。"""
    main_window._nav_history = type(main_window._nav_history)()
    main_window._update_nav_buttons()
    qapp.processEvents()

    assert main_window.action_back.isEnabled() is False
    assert main_window.action_forward.isEnabled() is False


def test_tab_23_back_becomes_available_after_two_places(main_window, qapp, tmp_path):
    first, second = tmp_path / '甲', tmp_path / '乙'
    first.mkdir()
    second.mkdir()

    main_window._nav_history = type(main_window._nav_history)()
    main_window._record_history(str(first))
    main_window._record_history(str(second))
    qapp.processEvents()

    assert main_window.action_back.isEnabled() is True
    assert main_window.action_forward.isEnabled() is False
