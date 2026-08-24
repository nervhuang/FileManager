"""把字級套用到整棵 widget 樹，保留刻意的相對差距。

這個模組取代原本寫在 `FileManager._apply_font_size` 裡的手寫白名單。白名單的
問題不是它會出錯，而是它**必須有人記得維護**：新增一個面板就要回去登記一次。
作者面板漏過一次（整個面板完全不隨 Ctrl+= 縮放），更新檢查器是第二次補登記。
橫切關注點不該用逐一列舉的方式實作。

保留相對差距，是因為有些差距是刻意的：更新檢查器的計數列比內文大一級、
執行紀錄用等寬且小一級。做法是算出每個 widget 相對於舊基準的偏移，
套用新基準時原樣帶過去。
"""

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QWIDGETSIZE_MAX, QToolBar, QWidget

# 與 FileManager.on_font_decrease 的下限一致。
MIN_POINT_SIZE = 6


def apply(root, old_base, new_base):
    """把 `root` 及其所有子 widget 的字級從 `old_base` 換算到 `new_base`。

    回傳實際被改動的 widget 數量，供測試與除錯用。

    以 point 為單位。用 pixel 指定字型的 widget（`pointSize()` 回 -1）跳過：
    那是另一套單位，硬換算只會把它弄壞。
    """
    delta = new_base - old_base

    # 刻意不動 QApplication.setFont：那是全域可變狀態，會讓這個函式變成不可
    # 重入、且順序相依（同一個進程裡開第二個視窗時基準就錯了）。對話框本來
    # 就得自己套用字型——Qt 在頂層視窗邊界停止字型傳播，繼承不到父 widget，
    # 見 docs/spec/authors.md 的 AUT-14。

    # 先量完再套用，兩段不能合成一段。setFont 會往下傳播到還沒明確設過字型的
    # 子 widget，邊走邊改的話，往下每一層讀到的都已經是新值，delta 會一層層
    # 疊上去——12pt 的三層樹，最底層會被砍到下限。
    snapshot = []
    for widget in [root] + root.findChildren(QWidget):
        font = widget.font()
        size = font.pointSize()
        if size > 0:
            snapshot.append((widget, font, size))

    for widget, font, size in snapshot:
        widget.setFont(_resized(font, size + delta))
    return len(snapshot)


def _resized(font, point_size):
    new_font = QFont(font)
    new_font.setPointSize(max(MIN_POINT_SIZE, point_size))
    return new_font


def sync_toolbar_heights(root):
    """把 `root` 底下所有工具列釘成同一個高度，依目前字型重算。回傳該高度。

    工具列高度必須釘死：三條工具列左右並排，高度差一階就會看得出來，
    而各自的 `sizeHint` 本來就不同（按鈕數量、有無文字標籤）。

    但釘死的值必須跟著字型重算。原本它在建構時算一次就固定，那個年代工具列
    文字不隨字型縮放，所以不會出事；文字開始跟著長大之後（SHL-2），釘死的
    高度就會把文字裁掉——實測 18pt 時檔案面板與作者面板的工具列各需要
    107 與 111px，卻都還釘在 102px。

    先解除釘死再讀 `sizeHint`：釘死狀態下讀到的是被限制後的值，不是內容需求。
    """
    toolbars = root.findChildren(QToolBar)
    if not toolbars:
        return 0

    for bar in toolbars:
        bar.setMinimumHeight(0)
        bar.setMaximumHeight(QWIDGETSIZE_MAX)

    height = max(bar.sizeHint().height() for bar in toolbars)
    for bar in toolbars:
        bar.setFixedHeight(height)
    return height
