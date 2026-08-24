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
