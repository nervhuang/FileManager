"""面板工具列的按鈕與容器工廠。

兩種按鈕：**導覽鈕**只有圖示（上一頁、新增資料夾…），**操作鈕**圖示上文字下
（剪下、複製…）。兩者都不搶焦點——`_focused_file_view()` 靠焦點判斷該對哪個
面板動作，工具列按鈕一搶就失準。

原本是 `initUI` 裡的三個巢狀函式。它們是通用工廠，與外殼的組裝流程無關。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QToolBar, QToolButton

# 按鈕文字比內文大兩級，否則加大圖示之後會頭大身小。
# 這個偏移是刻意的，字型縮放會保留它（docs/spec/ui-shell.md 的 SHL-2a）。
BUTTON_POINT_SIZE = 14

SEPARATOR = None    # 放進 specs 代表一條群組分隔線


def make_nav_button(parent, icon, tooltip, handler, icon_size):
    """只有圖示的導覽鈕。"""
    button = QToolButton(parent)
    button.setIcon(icon)
    button.setIconSize(icon_size)
    button.setToolTip(tooltip)
    button.setAutoRaise(True)
    button.setFocusPolicy(Qt.NoFocus)
    button.clicked.connect(handler)
    return button


def make_action_button(parent, icon, text, handler, icon_size):
    """圖示上、文字下的操作鈕，與左側作者面板工具列同一種排法與高度。"""
    button = QToolButton(parent)
    button.setIcon(icon)
    button.setIconSize(icon_size)
    button.setText(text)
    button.setToolTip(text)
    button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
    button.setAutoRaise(True)
    button.setFocusPolicy(Qt.NoFocus)
    font = button.font()
    font.setPointSize(BUTTON_POINT_SIZE)
    button.setFont(font)
    button.clicked.connect(handler)
    return button


def build(parent, icon_size, specs):
    """建立面板工具列，回傳 (工具列, 按鈕清單)。

    `specs` 的每一項是 `(icon, tooltip, handler)`，或 `SEPARATOR` 代表分隔線。

    用 `QToolBar` 而非固定的 `QHBoxLayout`：後者的最小寬度等於所有按鈕寬度總和
    （加大圖示與文字後高達 1500px），會把中間面板的最小寬度一起撐到那麼寬，
    導致左側作者面板的分隔線在一般視窗寬度下根本拖不動。QToolBar 在寬度不足時
    會把排不下的按鈕收進溢位選單，最小寬度僅一顆按鈕（SHL-13）。
    """
    bar = QToolBar(parent)
    bar.setFloatable(False)
    bar.setMovable(False)
    bar.setFocusPolicy(Qt.NoFocus)
    bar.setIconSize(icon_size)
    bar.setContentsMargins(2, 2, 2, 2)
    bar.setStyleSheet('QToolBar { spacing: 6px; }')   # 加大圖示後放寬按鈕間距

    buttons = []
    for spec in specs:
        if spec is SEPARATOR:
            bar.addSeparator()
            continue
        icon, tooltip, handler = spec
        button = make_nav_button(parent, icon, tooltip, handler, icon_size)
        bar.addWidget(button)
        buttons.append(button)
    return bar, buttons
