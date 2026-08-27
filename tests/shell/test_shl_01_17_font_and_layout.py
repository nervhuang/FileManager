"""SHL-1、SHL-5 到 SHL-9、SHL-13 到 SHL-17：字級範圍、麵包屑、關閉鈕、版面。

字型的**範圍**（哪些 widget 要跟上）在 test_shl_02_font_applies_to_whole_app.py，
圖示尺寸在 test_shl_11_toolbar_icon_sizes.py。這裡補其餘。
"""
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QAbstractButton, QToolBar, QToolButton

from app.tabs.bar import PathTabBar
from app.tabs.breadcrumb import BreadcrumbBar

pytestmark = pytest.mark.gui


# ── SHL-1：字級範圍 6–72，每次 1pt，狀態列顯示 ──────────────────────────

def test_shl_1_increase_and_decrease_move_one_point(main_window, qapp):
    base = main_window._current_font_size()
    main_window.on_font_increase()
    assert main_window._current_font_size() == base + 1
    main_window.on_font_decrease()
    assert main_window._current_font_size() == base


def test_shl_1_stops_at_the_upper_bound(main_window, qapp):
    main_window._apply_font_size(72)
    main_window.on_font_increase()
    assert main_window._current_font_size() == 72


def test_shl_1_stops_at_the_lower_bound(main_window, qapp):
    main_window._apply_font_size(6)
    main_window.on_font_decrease()
    assert main_window._current_font_size() == 6


def test_shl_1_status_bar_shows_the_current_size(main_window, qapp):
    main_window._apply_font_size(15)
    main_window.update_status_bar()
    qapp.processEvents()
    assert '15' in main_window.statusBar().currentMessage()


def test_shl_1_status_bar_follows_the_shortcut_actions(main_window, qapp):
    """按 Ctrl+= 之後狀態列要跟著改，不能停在舊數字。"""
    main_window._apply_font_size(12)
    main_window.on_font_increase()
    qapp.processEvents()
    assert '13' in main_window.statusBar().currentMessage()


# ── SHL-5／SHL-6：麵包屑的字型與高度 ────────────────────────────────────

@pytest.fixture
def crumb(qapp):
    bar = BreadcrumbBar()
    bar.resize(800, 32)
    bar.show()
    qapp.processEvents()
    yield bar
    bar.close()


def test_shl_5_apply_font_reaches_the_styled_children(crumb, qapp):
    """麵包屑本體、按鈕、編輯框各自帶 stylesheet，Qt 因此不再往下傳字型。

    只設 BreadcrumbBar 自己是不夠的——這正是當初漏掉的地方。
    """
    from PyQt5.QtGui import QFont

    crumb.set_path(r'D:\甲\乙')
    qapp.processEvents()
    crumb.apply_font(QFont(crumb.font().family(), 20))
    qapp.processEvents()

    sizes = {w.font().pointSize() for w in crumb.findChildren(QToolButton)}
    assert sizes, '應該有麵包屑按鈕'
    assert sizes == {20}, f'仍有按鈕沒跟上：{sizes}'


def test_shl_6_height_grows_with_the_font(crumb, qapp):
    from PyQt5.QtGui import QFont

    crumb.apply_font(QFont(crumb.font().family(), 10))
    qapp.processEvents()
    small = crumb.height()

    crumb.apply_font(QFont(crumb.font().family(), 22))
    qapp.processEvents()
    assert crumb.height() > small, '高度應該跟著字型長高，不是卡在最小值'


def test_shl_5_crumbs_rebuilt_after_navigation_inherit_the_font(crumb, qapp):
    """導覽後重建的麵包屑也要用新字型，不能只有舊的那批。"""
    from PyQt5.QtGui import QFont

    crumb.apply_font(QFont(crumb.font().family(), 20))
    crumb.set_path(r'D:\導覽後\新的路徑')
    qapp.processEvents()

    sizes = {w.font().pointSize() for w in crumb.findChildren(QToolButton)}
    assert sizes == {20}


# ── SHL-7／SHL-8：分頁關閉鈕隨字型縮放 ──────────────────────────────────

@pytest.fixture
def bar(qapp):
    widget = PathTabBar()
    widget.resize(600, 40)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


def _close_buttons(bar):
    """分頁的關閉鈕。

    Qt 給的關閉鈕是純 QAbstractButton，分頁列兩側的捲動鈕是 QToolButton——
    兩者都沒有 objectName，只能用型別分。
    """
    return [b for b in bar.tab_bar.findChildren(QAbstractButton)
            if not isinstance(b, QToolButton)]


def test_shl_7_close_button_grows_with_the_font(bar, qapp):
    from PyQt5.QtGui import QFont

    bar.restore_tabs([(r'D:\甲', '甲'), (r'D:\乙', '乙')], 0)
    bar.tab_bar.setFont(QFont(bar.tab_bar.font().family(), 10))
    qapp.processEvents()
    small = bar.tab_bar._close_button_size()

    bar.tab_bar.setFont(QFont(bar.tab_bar.font().family(), 24))
    qapp.processEvents()
    assert bar.tab_bar._close_button_size() > small


def test_shl_7_close_button_never_shrinks_below_16px(bar, qapp):
    """再小也要點得到。"""
    from PyQt5.QtGui import QFont

    bar.tab_bar.setFont(QFont(bar.tab_bar.font().family(), 6))
    qapp.processEvents()
    assert bar.tab_bar._close_button_size() >= 16


def test_shl_8_proxy_style_is_attached_to_the_buttons_not_the_tab_bar(bar, qapp):
    """QWidget::setStyle 不會傳到子項。掛在分頁列上時，關閉鈕用的仍是應用程式
    樣式，✕ 依然是固定大小。"""
    bar.restore_tabs([(r'D:\甲', '甲')], 0)
    qapp.processEvents()

    buttons = _close_buttons(bar)
    assert buttons, '應該有關閉鈕'
    assert all(b.style() is bar.tab_bar._close_style for b in buttons)


def test_shl_8_the_proxy_style_object_is_kept_alive(bar):
    """setStyle 不接手所有權，物件被回收會在繪製時崩潰，所以必須留參考。"""
    assert bar.tab_bar._close_style is not None


# ── SHL-13／SHL-14：工具列的最小寬度與排法 ─────────────────────────────

def test_shl_13_toolbars_stay_narrow_so_the_splitter_can_move(main_window):
    """固定 QHBoxLayout 的最小寬度曾經高達 1506px，把中間面板一起撐開，
    害左側面板的分割握把在一般視窗寬度下拖不動。"""
    for toolbar in main_window.findChildren(QToolBar):
        assert toolbar.minimumSizeHint().width() < 400


def test_shl_14_action_buttons_put_text_under_the_icon(main_window):
    """指的是檔案面板的操作鈕（剪下、複製…），與左側作者面板工具列同一種排法。

    分頁列的 ＋／‹／›、麵包屑的路徑鈕、檢查器的「清除」不在此列——它們是控制
    元件不是操作鈕，本來就只放文字或只放圖示。
    """
    buttons = [main_window.act_cut, main_window.act_copy, main_window.act_paste,
               main_window.act_rename, main_window.act_delete, main_window.act_refresh]
    assert all(b.text() for b in buttons), '操作鈕都該有文字'
    assert all(b.toolButtonStyle() == Qt.ToolButtonTextUnderIcon for b in buttons)


def test_toolbar_buttons_do_not_take_focus(main_window):
    """工具列按鈕一搶焦點，_focused_file_view() 就抓不到該操作哪個面板。"""
    for toolbar in main_window.findChildren(QToolBar):
        for button in toolbar.findChildren(QToolButton):
            if button.objectName() == 'qt_toolbar_ext_button':
                continue
            assert button.focusPolicy() == Qt.NoFocus


# ── SHL-15：作者面板的快捷鍵 ────────────────────────────────────────────

def test_shl_15_authors_panel_uses_ctrl_shift_a(main_window):
    assert main_window.action_authors_panel.shortcut().toString() == 'Ctrl+Shift+A'


def test_shl_15_ctrl_l_is_left_for_the_breadcrumb(main_window):
    """Ctrl+L 已被麵包屑用來聚焦路徑框，兩個動作綁同一組合鍵會變成模糊快捷鍵。"""
    assert main_window.action_authors_panel.shortcut().toString() != 'Ctrl+L'


# ── SHL-16／SHL-17：版面切換與持久化 ────────────────────────────────────

def test_shl_16_layout_switch_changes_the_splitter_orientation(main_window, qapp):
    main_window._set_right_panel_layout(Qt.Orientation.Vertical)
    qapp.processEvents()
    assert main_window.right_splitter.orientation() == Qt.Orientation.Vertical

    main_window._set_right_panel_layout(Qt.Orientation.Horizontal)
    qapp.processEvents()
    assert main_window.right_splitter.orientation() == Qt.Orientation.Horizontal


def test_shl_17_panel_visibility_toggles(main_window, qapp):
    main_window._set_authors_panel_visible(False)
    qapp.processEvents()
    assert main_window._authors_panel_visible is False
    assert not main_window.authors_panel.isVisible()

    main_window._set_authors_panel_visible(True)
    qapp.processEvents()
    assert main_window._authors_panel_visible is True
    assert main_window.authors_panel.isVisible()


def test_shl_17_hiding_the_panel_captures_the_width_it_had_on_screen(main_window, qapp):
    """隱藏時記下的是「當下實際的寬度」，不是先前存的值——下次打開才回到同樣位置。

    隱藏之後 splitter 給的寬度是 0，所以必須在 setVisible(False) 之前就抓。
    """
    main_window._set_authors_panel_visible(True)
    qapp.processEvents()
    on_screen = main_window.main_splitter.sizes()[0]
    assert on_screen > 0, '測試前提：面板此時是看得見的'

    main_window._set_authors_panel_visible(False)
    qapp.processEvents()

    assert main_window._authors_panel_width == on_screen
    assert main_window._authors_panel_width > 0, '不可被隱藏後的 0 覆蓋'
