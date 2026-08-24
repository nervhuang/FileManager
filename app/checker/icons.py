"""更新檢查器的自繪工具列圖示。

自繪而非用 QStyle 的內建圖示，有兩個理由：

1. **尺寸**。Qt 不會放大來源 pixmap。只出到 32×32 的系統圖示擺進 64px 工具列，
   就是把 32px 置中，看起來只有鄰居的一半大。
2. **視覺語彙**。三條工具列共用同一套風格：實心填色 ＋ 深色描邊 ＋ 高光，
   不是線稿。系統圖示混進來會很突兀。

沿用 `widgets.make_refresh_icon()` 建立的作法。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

_INK = QColor('#4a4a4a')
_PAPER = QColor('#fdfdfd')
_COVER = QColor('#7aa8dc')
_COVER_EDGE = QColor('#37567a')
_GLASS = QColor('#eaf3ff')
_BADGE = QColor('#e0483c')
_STOP = QColor('#e0483c')
_STOP_EDGE = QColor('#8f2119')
_STOP_LIGHT = QColor('#f2867c')


def _canvas(size):
    """回傳 (pixmap, painter, 相對 64px 的縮放係數)。"""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    return pix, painter, size / 64.0


def make_checker_icon(size=64):
    """書本加放大鏡：沿用面板工具列的實心填色＋深色描邊風格，不是線稿。"""
    pix, p, s = _canvas(size)

    # 書本
    p.setPen(QPen(_COVER_EDGE, 2.4 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(_COVER)
    p.drawRoundedRect(int(8 * s), int(10 * s), int(34 * s), int(44 * s), 3 * s, 3 * s)
    p.setBrush(_PAPER)
    p.drawRoundedRect(int(14 * s), int(16 * s), int(24 * s), int(32 * s), 2 * s, 2 * s)
    p.setPen(QPen(_INK, 1.6 * s, Qt.SolidLine, Qt.RoundCap))
    for i in range(3):
        y = int((22 + i * 7) * s)
        p.drawLine(int(18 * s), y, int(34 * s), y)

    # 放大鏡
    p.setPen(QPen(_INK, 3.2 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(_GLASS)
    p.drawEllipse(int(30 * s), int(28 * s), int(24 * s), int(24 * s))
    p.drawLine(int(50 * s), int(48 * s), int(59 * s), int(58 * s))
    p.end()
    return QIcon(pix)


def make_stop_icon(size=64):
    """停止掃描：紅色圓角方塊。

    不能用 QStyle 的 SP_MediaStop——這個樣式只提供到 32×32，擺進 64px 工具列
    只會置中顯示 32px，看起來是鄰居的一半大。這正是當初 SP_BrowserReload 的
    同一個問題（見 widgets.make_refresh_icon）。

    用方塊而非圓形：它與旁邊的「重新整理」圓環在剪影上就分得開，工具列縮成
    小圖示時仍認得出來。
    """
    pix, p, s = _canvas(size)

    side = 40 * s          # 與重新整理圓環的直徑相當，兩顆並排時份量才一致
    left = top = (size - side) / 2.0
    radius = 6 * s

    p.setPen(QPen(_STOP_EDGE, 2.6 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(_STOP)
    p.drawRoundedRect(int(left), int(top), int(side), int(side), radius, radius)

    # 左上角的短高光：與資料夾、書本圖示同一套立體語彙，不是純平面色塊。
    # 刻意只佔約四成寬——橫貫整寬會讀成一條減號，看起來像「移除」而不是「停止」。
    p.setPen(QPen(_STOP_LIGHT, 2.0 * s, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(int(left + 8 * s), int(top + 8 * s),
               int(left + side * 0.45), int(top + 8 * s))
    p.end()
    return QIcon(pix)
