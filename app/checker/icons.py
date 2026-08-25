"""更新檢查器的自繪工具列圖示。

自繪而非用 QStyle 的內建圖示，有兩個理由：

1. **尺寸**。Qt 不會放大來源 pixmap。只出到 32×32 的系統圖示擺進 64px 工具列，
   就是把 32px 置中，看起來只有鄰居的一半大。
2. **視覺語彙**。三條工具列共用同一套風格：實心填色 ＋ 深色描邊 ＋ 高光，
   不是線稿。系統圖示混進來會很突兀。

沿用 `icons.make_refresh_icon()` 建立的作法。
"""

import math

from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

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


def _ring_arrow_path(cx, cy, mid_r, band, start_deg, span_deg, tip_deg):
    """回轉箭頭：環與箭頭畫成同一條封閉路徑。

    分成兩個圖形畫的話，接合處無論怎麼對齊都會留下看得見的縫。箭尖落在環的
    中心線上，整個箭頭因此都在圓弧範圍內，不會往外突出。作法沿用
    `icons.make_refresh_icon()`。
    """
    arrow_half = band * 1.7          # 箭頭底邊半寬，比環寬才看得出是箭頭
    outer_r, inner_r = mid_r + band, mid_r - band
    end_deg = start_deg + span_deg

    def polar(r, deg):
        rad = math.radians(deg)
        return QPointF(cx + r * math.cos(rad), cy - r * math.sin(rad))

    def square(r):
        return QRectF(cx - r, cy - r, r * 2, r * 2)

    path = QPainterPath()
    path.moveTo(polar(mid_r - arrow_half, start_deg))    # 箭頭內角
    path.lineTo(polar(mid_r, start_deg - tip_deg))       # 箭尖
    path.lineTo(polar(mid_r + arrow_half, start_deg))    # 箭頭外角
    path.arcTo(square(outer_r), start_deg, span_deg)     # 外緣
    path.lineTo(polar(inner_r, end_deg))                 # 尾端切平
    path.arcTo(square(inner_r), end_deg, -span_deg)      # 內緣繞回
    path.closeSubpath()
    return path


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
    同一個問題（見 icons.make_refresh_icon）。

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


def make_detail_icon(size=64):
    """開啟詳細清單（Web UI）：瀏覽器視窗裡的縮圖牆。

    畫成瀏覽器而不是單純的清單圖示，因為這顆按鈕開的是外部瀏覽器分頁，
    不是在面板裡展開——剪影上就先告訴使用者「會跳出去」。
    """
    pix, p, s = _canvas(size)

    left, top = 7 * s, 12 * s
    width, height = 50 * s, 40 * s
    bar = 10 * s

    # 視窗外框與標題列
    p.setPen(QPen(_COVER_EDGE, 2.4 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(_PAPER)
    p.drawRoundedRect(int(left), int(top), int(width), int(height), 3 * s, 3 * s)
    p.setBrush(_COVER)
    p.drawRoundedRect(int(left), int(top), int(width), int(bar), 3 * s, 3 * s)
    p.drawRect(int(left), int(top + bar - 3 * s), int(width), int(3 * s))

    # 標題列上的三顆點
    p.setPen(Qt.NoPen)
    p.setBrush(_PAPER)
    for i in range(3):
        p.drawEllipse(int(left + (5 + i * 6) * s), int(top + bar / 2 - 1.6 * s),
                      int(3.2 * s), int(3.2 * s))

    # 2×2 縮圖格
    p.setPen(QPen(_COVER_EDGE, 1.6 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(_GLASS)
    cell = 18 * s
    gap = 4 * s
    grid_left = left + (width - cell * 2 - gap) / 2
    grid_top = top + bar + gap
    for row in range(2):
        for col in range(2):
            p.drawRect(int(grid_left + col * (cell + gap)),
                       int(grid_top + row * (cell * 0.62 + gap)),
                       int(cell), int(cell * 0.62))
    p.end()
    return QIcon(pix)


def make_reset_icon(size=64):
    """重設掃描紀錄：紀錄紙上蓋一個紅色的回轉箭頭。

    紅色而非綠色：這個動作會清掉既有的比對結果，與工具列上綠色的「重新整理」
    是不同性質的事，顏色先分開才不會誤按。
    """
    pix, p, s = _canvas(size)

    # 紀錄紙偏左上，讓出右下角給徽章
    p.setPen(QPen(_INK, 2.4 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(_PAPER)
    p.drawRoundedRect(int(7 * s), int(6 * s), int(31 * s), int(40 * s), 3 * s, 3 * s)
    p.setPen(QPen(_INK, 1.8 * s, Qt.SolidLine, Qt.RoundCap))
    for i in range(3):
        y = int((15 + i * 7) * s)
        p.drawLine(int(13 * s), y, int(32 * s), y)

    # 右下角的紅色徽章。刻意畫大：64px 下徽章若只有 26px，環＋缺口＋箭頭
    # 三層細節會糊成一個白色的 C，看不出是回轉箭頭。
    cx, cy, badge_r = 42.0, 42.0, 19.0
    p.setPen(QPen(_STOP_EDGE, 2.2 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(_STOP)
    p.drawEllipse(int((cx - badge_r) * s), int((cy - badge_r) * s),
                  int(badge_r * 2 * s), int(badge_r * 2 * s))

    p.setPen(Qt.NoPen)
    p.setBrush(_PAPER)
    p.drawPath(_ring_arrow_path(cx * s, cy * s, 9.6 * s, 2.6 * s,
                                start_deg=70, span_deg=290, tip_deg=45))
    p.end()
    return QIcon(pix)
