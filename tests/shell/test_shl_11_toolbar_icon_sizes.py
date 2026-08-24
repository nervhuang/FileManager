"""SHL-10、SHL-11：工具列圖示一律 64×64。

判定用 `icon.actualSize(QSize(64, 64))`，不是 `availableSizes()`——後者回的是
來源 pixmap 的尺寸，系統圖示會回報 [16, 32, 128] 之類的清單，看不出它在 64px
工具列裡實際畫多大。

Qt 不會把來源 pixmap 放大。只出到 32×32 的系統圖示（SP_BrowserReload、
SP_MediaStop）擺進 64px 工具列，就是把 32px 置中，看起來只有鄰居的一半大。
"""
import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QAbstractButton, QToolBar

pytestmark = pytest.mark.gui

ICON_SIZE = QSize(64, 64)

# QToolBar 自己的溢位鈕，不是我們放的圖示。
QT_INTERNAL_BUTTONS = {'qt_toolbar_ext_button'}


def _toolbar_icon_buttons(toolbar):
    return [b for b in toolbar.findChildren(QAbstractButton)
            if b.objectName() not in QT_INTERNAL_BUTTONS and not b.icon().isNull()]


def _describe(button):
    """按鈕沒有文字時（圖示模式）用 tooltip 指認，錯誤訊息才看得出是哪一顆。"""
    return button.text() or button.toolTip() or '<無標示>'


def test_shl_10_every_toolbar_uses_64px_icons(main_window):
    toolbars = main_window.findChildren(QToolBar)
    assert toolbars, "主視窗應該有工具列"
    for toolbar in toolbars:
        assert toolbar.iconSize() == ICON_SIZE


def test_shl_10_toolbars_share_one_height(main_window):
    """兩條工具列並排時形狀必須一致，不得因 sizeHint 差異而漂移。"""
    heights = {tb.height() for tb in main_window.findChildren(QToolBar)}
    assert len(heights) == 1, f"工具列高度不一致：{sorted(heights)}"


def test_shl_11_every_toolbar_icon_actually_renders_at_64px(main_window):
    undersized = []
    total = 0
    for toolbar in main_window.findChildren(QToolBar):
        for button in _toolbar_icon_buttons(toolbar):
            total += 1
            actual = button.icon().actualSize(ICON_SIZE)
            if actual != ICON_SIZE:
                undersized.append(
                    f'{_describe(button)}：{actual.width()}x{actual.height()}')

    assert total > 0, "沒有找到任何工具列圖示按鈕，測試本身可能失效了"
    assert not undersized, (
        "以下圖示在 64px 工具列裡畫不到 64×64（Qt 不會放大來源 pixmap，"
        "改用自繪圖示，見 widgets.make_refresh_icon）：\n  "
        + '\n  '.join(undersized))
