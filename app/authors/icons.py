"""作者面板工具列的自繪圖示。

與檔案面板工具列共用同一套視覺語彙——實心填色 ＋ 深色描邊 ＋ 高光
（docs/spec/ui-shell.md 的 SHL-12a）。色盤與 `app/icons.py` 對齊，
不共用是因為這幾顆（人形、時鐘）只有這個域用得到。
"""

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap


# 與中間檔案面板工具列共用的色盤：實心填色 + 深色描邊 + 高光，
# 而非單純的線稿，這樣兩條工具列擺在一起才是同一種視覺語彙。
_INK = QColor("#4a4a4a")
_BODY = QColor("#7aa8dc")          # 人形主體
_BODY_DARK = QColor("#4d7cb0")
_BODY_BACK = QColor("#b8cfe8")     # 後排人形（較淡，製造前後層次）
_EDGE = QColor("#37567a")          # 人形描邊
_SKIN = QColor("#f5cfa4")
_SKIN_EDGE = QColor("#b3844f")
_GREEN = QColor("#2fb24a")         # 新增徽章
_GREEN_DARK = QColor("#1d7a33")
_WOOD_LIGHT = QColor("#fff1a8")    # 鉛筆木身，沿用資料夾圖示的黃
_WOOD = QColor("#f2c23f")
_WOOD_EDGE = QColor("#8f5c00")
_METAL = QColor("#c9ccd1")
_FACE = QColor("#fbfbfb")          # 時鐘面
_RIM = QColor("#6b6b6b")
_ACCENT = QColor("#2f66d0")


def make_glyph_icon(kind):
    """畫出工具列圖示（64×64 畫布，由 QToolButton 縮到實際大小）。

    風格對齊中間檔案面板的 make_up_folder_icon／make_glyph_icon：實心填色、
    深色描邊、局部高光，不是純線稿。
    """
    canvas = 64
    pix = QPixmap(canvas, canvas)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    def pt(fx, fy):
        return QPoint(int(canvas * fx), int(canvas * fy))

    def px(f):
        return int(canvas * f)

    def filled(brush, edge, width=1.6):
        p.setBrush(brush)
        p.setPen(QPen(edge, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def person(cx, cy_head, scale, body, edge, skin=_SKIN, skin_edge=_SKIN_EDGE):
        """一個人形：頭 + 肩胸。cx 為中心、scale 控制大小。"""
        head_r = 0.115 * scale
        filled(skin, skin_edge)
        p.drawEllipse(px(cx - head_r), px(cy_head - head_r),
                      px(head_r * 2), px(head_r * 2))
        # 肩胸：上緣為半圓，下緣切平
        grad = QLinearGradient(pt(cx, cy_head + head_r), pt(cx, cy_head + 0.46 * scale))
        grad.setColorAt(0.0, body.lighter(112))
        grad.setColorAt(1.0, body)
        filled(grad, edge)
        left, right = cx - 0.20 * scale, cx + 0.20 * scale
        top, bottom = cy_head + head_r * 1.15, cy_head + 0.44 * scale
        p.drawChord(px(left), px(top), px(right - left), px((bottom - top) * 2), 0, 180 * 16)
        p.setPen(QPen(body.lighter(150), 1.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pt(cx - 0.10 * scale, top + 0.05 * scale),
                   pt(cx - 0.13 * scale, bottom - 0.02 * scale))

    def plus_badge(cx, cy, r=0.19):
        filled(_GREEN, _GREEN_DARK, 1.8)
        p.drawEllipse(px(cx - r), px(cy - r), px(r * 2), px(r * 2))
        p.setPen(QPen(QColor("#ffffff"), 3.4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pt(cx - r * 0.52, cy), pt(cx + r * 0.52, cy))
        p.drawLine(pt(cx, cy - r * 0.52), pt(cx, cy + r * 0.52))

    if kind == 'add_author':
        person(0.42, 0.32, 1.15, _BODY, _EDGE)
        plus_badge(0.76, 0.76)

    elif kind == 'add_circle':
        person(0.30, 0.30, 0.88, _BODY_BACK, _EDGE.lighter(135))
        person(0.58, 0.28, 0.88, _BODY_BACK, _EDGE.lighter(135))
        person(0.44, 0.42, 1.00, _BODY, _EDGE)
        plus_badge(0.78, 0.78, 0.17)

    elif kind == 'group':
        # 中間檔案面板工具列的「作者／團體清單」入口（SHL-15a）。
        # 與 add_circle 同一組人形，去掉新增徽章——那顆鈕是「建一筆」，
        # 這顆是「開面板」，徽章正是兩者唯一該有的差別。
        person(0.28, 0.28, 0.92, _BODY_BACK, _EDGE.lighter(135))
        person(0.62, 0.28, 0.92, _BODY_BACK, _EDGE.lighter(135))
        person(0.45, 0.45, 1.16, _BODY, _EDGE)

    elif kind == 'edit':
        # 鉛筆：木身 + 金屬套環 + 筆尖，斜置由左下指向右上
        body_pts = [pt(0.30, 0.86), pt(0.22, 0.70), pt(0.66, 0.26), pt(0.78, 0.40)]
        grad = QLinearGradient(pt(0.22, 0.70), pt(0.40, 0.90))
        grad.setColorAt(0.0, _WOOD_LIGHT)
        grad.setColorAt(1.0, _WOOD)
        filled(grad, _WOOD_EDGE)
        p.drawPolygon(*body_pts)
        filled(_METAL, _WOOD_EDGE, 1.3)
        p.drawPolygon(pt(0.62, 0.22), pt(0.74, 0.36), pt(0.80, 0.30), pt(0.68, 0.16))
        # 筆尖與石墨
        filled(_WOOD_LIGHT, _WOOD_EDGE, 1.3)
        p.drawPolygon(pt(0.14, 0.92), pt(0.22, 0.70), pt(0.30, 0.86))
        filled(_INK, _INK, 1.0)
        p.drawPolygon(pt(0.14, 0.92), pt(0.185, 0.80), pt(0.235, 0.865))
        p.setPen(QPen(QColor("#ffffff"), 1.4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pt(0.29, 0.68), pt(0.68, 0.30))

    elif kind == 'history':
        # 時鐘 + 逆時針箭頭（還原的意象）
        margin = 0.20
        filled(_FACE, _RIM, 3.0)
        p.drawEllipse(px(margin), px(margin), px(1 - margin * 2), px(1 - margin * 2))
        p.setPen(QPen(_INK, 3.0, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pt(0.50, 0.50), pt(0.50, 0.32))
        p.drawLine(pt(0.50, 0.50), pt(0.65, 0.57))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_ACCENT, 3.4, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(px(0.07), px(0.07), px(0.52), px(0.52), 30 * 16, 200 * 16)
        filled(_ACCENT, _ACCENT, 1.0)
        p.drawPolygon(pt(0.04, 0.26), pt(0.22, 0.24), pt(0.11, 0.40))

    p.end()
    return QIcon(pix)
