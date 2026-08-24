"""外殼共用的自繪工具列圖示。

自繪而非用 QStyle 的內建圖示，理由見 docs/spec/ui-shell.md 的 SHL-11 與 SHL-12：
Qt 不會放大來源 pixmap，而且 Windows 系統圖示的立體光澤風格與這裡的實心填色
語彙搭不起來。

原本這些函式散在三個地方——widgets.py 一個、file_manager.initUI 裡兩個閉包、
再一個閉包在工具列那段。集中在這裡才看得出它們共用同一套調色盤，也才有地方
放「新圖示要長什麼樣」這件事。

更新檢查器與作者面板各有自己的圖示模組：那些是該功能域的視覺資產，不共用。
"""

import math

from PyQt5.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import (QColor, QIcon, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPixmap)


def _as_qsize(size):
    """接受 int 或 QSize，一律回 QSize。呼叫端兩種都有。"""
    return size if isinstance(size, QSize) else QSize(size, size)


# ── 調色盤 ────────────────────────────────────────────────────────────────
# 語彙是實心填色 ＋ 深色描邊 ＋ 高光（docs/spec/ui-shell.md 的 SHL-12a）。
# 這些值原本硬寫在各個繪圖函式裡，抽出來才看得出哪幾顆該是同一族。

INK = QColor('#4a4a4a')            # 通用深色描邊
PAPER = QColor('#fbfbfb')

FOLDER_LIGHT = QColor('#fff1a8')   # 資料夾上蓋
FOLDER = QColor('#f2c23f')         # 資料夾正面
FOLDER_SIDE = QColor('#d89613')    # 資料夾側面（立體感）
FOLDER_EDGE = QColor('#8f5c00')
FOLDER_GLOSS = QColor('#ffe08a')

GREEN = QColor('#2fb24a')          # 導覽箭頭與「新增」徽章
GREEN_DARK = QColor('#1d7a33')
GREEN_LIGHT = QColor('#8be28d')

METAL = QColor('#c9ccd1')          # 金屬：垃圾桶、剪刀刀身、鉛筆金屬環
METAL_DARK = QColor('#8a8f96')
METAL_LIGHT = QColor('#eceef1')

BLUE = QColor('#7aa8dc')           # 紙板、夾板
BLUE_DARK = QColor('#37567a')
BLUE_ACCENT = QColor('#2f66d0')


def _canvas(size):
    """回傳 (pixmap, painter, 相對 64px 的縮放係數)。"""
    size = _as_qsize(size)
    pix = QPixmap(size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    return pix, painter, size.width() / 64.0


def make_up_folder_icon(size=64):
    """回到上一層目錄：黃色立體資料夾加綠色上箭頭。"""
    size = _as_qsize(size)
    pix = QPixmap(size)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    width = size.width()
    height = size.height()

    # Draw a custom angled folder matching the new-folder icon perspective, without the plus mark.
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#fff1a8"))
    p.drawPolygon(
        QPoint(int(width * 0.18), int(height * 0.16)),
        QPoint(int(width * 0.44), int(height * 0.16)),
        QPoint(int(width * 0.54), int(height * 0.06)),
        QPoint(int(width * 0.80), int(height * 0.06)),
        QPoint(int(width * 0.70), int(height * 0.28)),
        QPoint(int(width * 0.08), int(height * 0.28)),
    )

    p.setBrush(QColor("#f2c23f"))
    p.drawPolygon(
        QPoint(int(width * 0.08), int(height * 0.28)),
        QPoint(int(width * 0.70), int(height * 0.28)),
        QPoint(int(width * 0.62), int(height * 0.88)),
        QPoint(int(width * 0.08), int(height * 0.88)),
    )

    p.setBrush(QColor("#d89613"))
    p.drawPolygon(
        QPoint(int(width * 0.70), int(height * 0.28)),
        QPoint(int(width * 0.86), int(height * 0.16)),
        QPoint(int(width * 0.78), int(height * 0.78)),
        QPoint(int(width * 0.62), int(height * 0.88)),
    )

    p.setPen(QPen(QColor("#8f5c00"), 1.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(int(width * 0.18), int(height * 0.16), int(width * 0.44), int(height * 0.16))
    p.drawLine(int(width * 0.44), int(height * 0.16), int(width * 0.54), int(height * 0.06))
    p.drawLine(int(width * 0.54), int(height * 0.06), int(width * 0.80), int(height * 0.06))
    p.drawLine(int(width * 0.80), int(height * 0.06), int(width * 0.70), int(height * 0.28))
    p.drawLine(int(width * 0.70), int(height * 0.28), int(width * 0.62), int(height * 0.88))
    p.drawLine(int(width * 0.62), int(height * 0.88), int(width * 0.08), int(height * 0.88))
    p.drawLine(int(width * 0.08), int(height * 0.88), int(width * 0.08), int(height * 0.28))
    p.drawLine(int(width * 0.08), int(height * 0.28), int(width * 0.18), int(height * 0.16))
    p.drawLine(int(width * 0.70), int(height * 0.28), int(width * 0.86), int(height * 0.16))
    p.drawLine(int(width * 0.86), int(height * 0.16), int(width * 0.78), int(height * 0.78))
    p.drawLine(int(width * 0.78), int(height * 0.78), int(width * 0.62), int(height * 0.88))

    p.setPen(QPen(QColor("#ffe08a"), 1.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(int(width * 0.14), int(height * 0.32), int(width * 0.64), int(height * 0.32))
    p.drawLine(int(width * 0.14), int(height * 0.38), int(width * 0.62), int(height * 0.38))

    # Green up arrow, centered and larger
    arrow_center_x = width // 2 + 1
    arrow_top_y = max(8, height // 5)
    arrow_mid_y = height // 2
    arrow_bottom_y = height - 7
    arrow_head_half_width = max(6, width // 7)

    arrow_pen = QPen(QColor("#2fb24a"), 4.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(arrow_pen)
    p.drawLine(arrow_center_x, arrow_bottom_y, arrow_center_x, arrow_top_y)
    p.drawLine(arrow_center_x, arrow_top_y, arrow_center_x - arrow_head_half_width, arrow_mid_y)
    p.drawLine(arrow_center_x, arrow_top_y, arrow_center_x + arrow_head_half_width, arrow_mid_y)

    # Arrow highlight
    p.setPen(QPen(QColor("#8be28d"), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(arrow_center_x, arrow_bottom_y - 1, arrow_center_x, arrow_top_y + 1)

    p.end()
    return QIcon(pix)


def make_layout_icon(orientation, active=False, size=64):
    """右側面板的左右／上下排列切換鈕。active 決定強調色。"""
    size = _as_qsize(size)
    pix = QPixmap(size)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    width = size.width()
    height = size.height()

    shadow_color = QColor(0, 0, 0, 28)
    edge_dark = QColor("#6b6b6b")
    edge_mid = QColor("#9a9a9a")
    edge_light = QColor("#f8f8f8")
    fill_top = QColor("#fbfbfb")
    fill_bottom = QColor("#d8d8d8")
    divider_dark = QColor("#5d5d5d")
    divider_light = QColor("#ffffff")
    accent = QColor("#2f66d0") if active else QColor("#808080")

    def draw_pane(rect):
        shadow_rect = rect.translated(1, 2)
        p.setPen(Qt.NoPen)
        p.setBrush(shadow_color)
        p.drawRect(shadow_rect)

        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0.0, fill_top)
        grad.setColorAt(1.0, fill_bottom)
        p.setBrush(grad)
        p.setPen(Qt.NoPen)
        p.drawRect(rect)

        p.setPen(QPen(edge_light, 1.0))
        p.drawLine(rect.left(), rect.bottom(), rect.left(), rect.top())
        p.drawLine(rect.left(), rect.top(), rect.right(), rect.top())
        p.setPen(QPen(edge_dark, 1.0))
        p.drawLine(rect.right(), rect.top() + 1, rect.right(), rect.bottom())
        p.drawLine(rect.left() + 1, rect.bottom(), rect.right(), rect.bottom())
        p.setPen(QPen(edge_mid, 1.0))
        p.drawLine(rect.left() + 1, rect.bottom() - 1, rect.left() + 1, rect.top() + 1)
        p.drawLine(rect.left() + 1, rect.top() + 1, rect.right() - 1, rect.top() + 1)

        inset = rect.adjusted(3, 3, -3, -3)
        p.setPen(QPen(QColor(255, 255, 255, 120), 1.0))
        p.drawLine(inset.left(), inset.top(), inset.right(), inset.top())
        p.setPen(QPen(QColor(160, 160, 160, 140), 1.0))
        p.drawLine(inset.left(), inset.bottom(), inset.right(), inset.bottom())

    content_rect = pix.rect().adjusted(7, 8, -7, -8)
    pane_gap = max(5, width // 12)

    if orientation == Qt.Orientation.Horizontal:
        pane_width = max(10, (content_rect.width() - pane_gap) // 2)
        left_rect = content_rect.adjusted(0, 0, -(content_rect.width() - pane_width), 0)
        right_rect = content_rect.adjusted(content_rect.width() - pane_width, 0, 0, 0)
        draw_pane(left_rect)
        draw_pane(right_rect)
        split_x = left_rect.right() + pane_gap // 2 + 1
        p.setPen(QPen(divider_light, 1.0))
        p.drawLine(split_x - 1, content_rect.top() + 4, split_x - 1, content_rect.bottom() - 4)
        p.setPen(QPen(divider_dark, 1.4))
        p.drawLine(split_x, content_rect.top() + 3, split_x, content_rect.bottom() - 3)
    else:
        pane_height = max(10, (content_rect.height() - pane_gap) // 2)
        top_rect = content_rect.adjusted(0, 0, 0, -(content_rect.height() - pane_height))
        bottom_rect = content_rect.adjusted(0, content_rect.height() - pane_height, 0, 0)
        draw_pane(top_rect)
        draw_pane(bottom_rect)
        split_y = top_rect.bottom() + pane_gap // 2 + 1
        p.setPen(QPen(divider_light, 1.0))
        p.drawLine(content_rect.left() + 4, split_y - 1, content_rect.right() - 4, split_y - 1)
        p.setPen(QPen(divider_dark, 1.4))
        p.drawLine(content_rect.left() + 3, split_y, content_rect.right() - 3, split_y)

    accent_pen = QPen(accent, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(accent_pen)
    if orientation == Qt.Orientation.Horizontal:
        p.drawLine(content_rect.left() + 3, content_rect.bottom() - 2, content_rect.right() - 3, content_rect.bottom() - 2)
    else:
        p.drawLine(content_rect.right() - 2, content_rect.top() + 3, content_rect.right() - 2, content_rect.bottom() - 3)

    p.end()
    return QIcon(pix)


def make_file_action_icon(kind, size=64):
    """檔案面板的操作圖示：cut／copy／paste／rename。

    畫法定義在檔案下方的 _FILE_ACTION_PAINTERS；這裡只負責備好畫布。
    """
    painter_fn = _FILE_ACTION_PAINTERS.get(kind)
    if painter_fn is None:
        raise ValueError(f'未知的檔案操作圖示：{kind!r}')
    pix, p, s = _canvas(size)
    painter_fn(p, s)
    p.end()
    return QIcon(pix)


def make_refresh_icon(size=64):
    """自行繪製「重新整理」圖示。

    不能沿用 QStyle 的 SP_BrowserReload：它只提供 24×24 與 32×32 兩種尺寸，
    在 64px 的工具列裡 Qt 不會放大，只會把 32px 置中，看起來只有其他圖示的
    一半大。
    """
    size = _as_qsize(size).width()   # 這支以純量計算，呼叫端兩種都有
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    # 綠色沿用「回到上一層」資料夾圖示的箭頭綠，兩條工具列色調一致
    green = QColor("#2fb24a")
    green_dark = QColor("#1d7a33")
    green_light = QColor("#8be28d")

    centre = size / 2.0
    mid_r = size * 0.315          # 環的中心線半徑
    band = size * 0.052           # 環的半寬
    arrow_half = band * 1.7       # 箭頭底邊半寬（比環寬才看得出是箭頭）
    start_deg = 62                # 箭頭所在角度
    span_deg = 296                # 環由此逆時針延伸的角度
    tip_deg = 40                  # 箭尖沿圓弧再前進的角度（順時針）

    def polar(r, deg):
        rad = math.radians(deg)
        return QPointF(centre + r * math.cos(rad), centre - r * math.sin(rad))

    def square(r):
        return QRectF(centre - r, centre - r, r * 2, r * 2)

    # 環與箭頭畫成同一條封閉路徑，兩者之間才不會有接縫或錯位；
    # 箭尖落在環的中心線上，因此整個箭頭都在圓弧範圍內，不會往外突出。
    outer_r, inner_r = mid_r + band, mid_r - band
    end_deg = start_deg + span_deg
    path = QPainterPath()
    path.moveTo(polar(mid_r - arrow_half, start_deg))      # 箭頭內角
    path.lineTo(polar(mid_r, start_deg - tip_deg))         # 箭尖
    path.lineTo(polar(mid_r + arrow_half, start_deg))      # 箭頭外角
    path.arcTo(square(outer_r), start_deg, span_deg)       # 外緣
    path.lineTo(polar(inner_r, end_deg))                   # 尾端切平
    path.arcTo(square(inner_r), end_deg, -span_deg)        # 內緣繞回
    path.closeSubpath()

    p.setPen(QPen(green_dark, max(1.0, size * 0.030), Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin))
    p.setBrush(green)
    p.drawPath(path)

    # 內側高光，做出與資料夾圖示相同的厚度感
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(green_light, band * 0.55, Qt.SolidLine, Qt.FlatCap))
    p.drawArc(square(mid_r - band * 0.35).toRect(), (start_deg + 120) * 16, 95 * 16)

    p.end()
    return QIcon(pix)


# ── 取代 Qt 系統圖示的自繪版本 ────────────────────────────────────────────
# 這四顆原本用 QStyle 的 SP_ArrowBack／SP_ArrowForward／SP_FileDialogNewFolder／
# SP_TrashIcon。它們的尺寸沒問題（都有 128×128），問題在外觀：Windows 的立體
# 光澤風格與這裡的實心填色語彙擺在同一條工具列上，一眼就看得出是兩套東西。

def _arrow_polygon(s, pointing_right):
    """粗箭頭：箭身加箭頭，單一多邊形，接合處才不會有縫。"""
    shaft_top, shaft_bottom = 26.0, 38.0
    head_top, head_bottom = 14.0, 50.0
    tip, head_base, tail = 54.0, 34.0, 12.0
    xs = [tip, head_base, head_base, tail, tail, head_base, head_base]
    ys = [32.0, head_top, shaft_top, shaft_top, shaft_bottom, shaft_bottom, head_bottom]
    if not pointing_right:
        xs = [64.0 - x for x in xs]
    return QPointF(xs[0] * s, ys[0] * s), [QPointF(x * s, y * s) for x, y in zip(xs, ys)]


def _draw_arrow(p, s, pointing_right):
    _, points = _arrow_polygon(s, pointing_right)
    path = QPainterPath()
    path.moveTo(points[0])
    for point in points[1:]:
        path.lineTo(point)
    path.closeSubpath()

    p.setPen(QPen(GREEN_DARK, 2.4 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(GREEN)
    p.drawPath(path)

    # 箭身上緣的高光，與資料夾圖示同一種厚度感
    p.setPen(QPen(GREEN_LIGHT, 2.0 * s, Qt.SolidLine, Qt.RoundCap))
    x0, x1 = (16.0, 32.0) if pointing_right else (32.0, 48.0)
    p.drawLine(int(x0 * s), int(29 * s), int(x1 * s), int(29 * s))


def make_back_icon(size=64):
    """前一頁：綠色左箭頭，與「回到上一層」的綠色同一族。"""
    pix, p, s = _canvas(size)
    _draw_arrow(p, s, pointing_right=False)
    p.end()
    return QIcon(pix)


def make_forward_icon(size=64):
    """後一頁：綠色右箭頭。"""
    pix, p, s = _canvas(size)
    _draw_arrow(p, s, pointing_right=True)
    p.end()
    return QIcon(pix)


def _draw_folder(p, s):
    """黃色立體資料夾本體，座標與 make_up_folder_icon 一致。"""
    p.setPen(Qt.NoPen)
    p.setBrush(FOLDER_LIGHT)
    p.drawPolygon(QPoint(int(11 * s), int(10 * s)), QPoint(int(28 * s), int(10 * s)),
                  QPoint(int(35 * s), int(4 * s)), QPoint(int(51 * s), int(4 * s)),
                  QPoint(int(45 * s), int(18 * s)), QPoint(int(5 * s), int(18 * s)))
    p.setBrush(FOLDER)
    p.drawPolygon(QPoint(int(5 * s), int(18 * s)), QPoint(int(45 * s), int(18 * s)),
                  QPoint(int(40 * s), int(56 * s)), QPoint(int(5 * s), int(56 * s)))
    p.setBrush(FOLDER_SIDE)
    p.drawPolygon(QPoint(int(45 * s), int(18 * s)), QPoint(int(55 * s), int(10 * s)),
                  QPoint(int(50 * s), int(50 * s)), QPoint(int(40 * s), int(56 * s)))

    p.setPen(QPen(FOLDER_EDGE, 1.6 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    for a, b in (((11, 10), (28, 10)), ((28, 10), (35, 4)), ((35, 4), (51, 4)),
                 ((51, 4), (45, 18)), ((45, 18), (40, 56)), ((40, 56), (5, 56)),
                 ((5, 56), (5, 18)), ((5, 18), (11, 10)),
                 ((45, 18), (55, 10)), ((55, 10), (50, 50)), ((50, 50), (40, 56))):
        p.drawLine(int(a[0] * s), int(a[1] * s), int(b[0] * s), int(b[1] * s))

    p.setPen(QPen(FOLDER_GLOSS, 1.3 * s, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(int(9 * s), int(21 * s), int(41 * s), int(21 * s))
    p.drawLine(int(9 * s), int(25 * s), int(40 * s), int(25 * s))


def _draw_plus_badge(p, s, cx, cy, radius):
    """綠色加號徽章，與作者面板的「新增」徽章同一種。"""
    p.setPen(QPen(GREEN_DARK, 2.0 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(GREEN)
    p.drawEllipse(int((cx - radius) * s), int((cy - radius) * s),
                  int(radius * 2 * s), int(radius * 2 * s))
    p.setPen(QPen(PAPER, 2.8 * s, Qt.SolidLine, Qt.RoundCap))
    arm = radius * 0.52
    p.drawLine(int((cx - arm) * s), int(cy * s), int((cx + arm) * s), int(cy * s))
    p.drawLine(int(cx * s), int((cy - arm) * s), int(cx * s), int((cy + arm) * s))


def make_new_folder_icon(size=64):
    """新增資料夾：資料夾加綠色加號徽章。"""
    pix, p, s = _canvas(size)
    _draw_folder(p, s)
    _draw_plus_badge(p, s, cx=46.0, cy=45.0, radius=15.0)
    p.end()
    return QIcon(pix)


def make_trash_icon(size=64):
    """刪除：金屬垃圾桶。檔案面板與作者面板共用同一顆。"""
    pix, p, s = _canvas(size)

    # 桶身（上寬下窄的梯形，四角略圓）
    p.setPen(QPen(INK, 2.4 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(METAL)
    body = QPainterPath()
    body.moveTo(14 * s, 22 * s)
    body.lineTo(50 * s, 22 * s)
    body.lineTo(45 * s, 56 * s)
    body.lineTo(19 * s, 56 * s)
    body.closeSubpath()
    p.drawPath(body)

    # 桶身直紋
    p.setPen(QPen(METAL_DARK, 1.8 * s, Qt.SolidLine, Qt.RoundCap))
    for x_top, x_bottom in ((24, 26), (32, 32), (40, 38)):
        p.drawLine(int(x_top * s), int(28 * s), int(x_bottom * s), int(50 * s))

    # 桶蓋與提把
    p.setPen(QPen(INK, 2.4 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(METAL_LIGHT)
    p.drawRoundedRect(int(10 * s), int(15 * s), int(44 * s), int(8 * s), 3 * s, 3 * s)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(int(26 * s), int(8 * s), int(12 * s), int(7 * s), 2 * s, 2 * s)
    p.end()
    return QIcon(pix)


# ── 檔案操作圖示 ──────────────────────────────────────────────────────────
# 這四顆原本是無填色的線稿，與同一條工具列上的資料夾、箭頭、垃圾桶不是同一套
# 語彙。改成實心填色＋深色描邊＋高光。

def _make_copy_icon(p, s):
    """兩張疊起來的紙。後面那張只露出左上角，前後關係才看得出來。"""
    p.setPen(QPen(INK, 2.2 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(METAL_LIGHT)
    p.drawRoundedRect(int(12 * s), int(9 * s), int(28 * s), int(36 * s), 3 * s, 3 * s)
    p.setBrush(PAPER)
    p.drawRoundedRect(int(24 * s), int(19 * s), int(28 * s), int(36 * s), 3 * s, 3 * s)
    p.setPen(QPen(BLUE, 2.0 * s, Qt.SolidLine, Qt.RoundCap))
    for i in range(3):
        y = int((28 + i * 8) * s)
        p.drawLine(int(30 * s), y, int(46 * s), y)


def _make_cut_icon(p, s):
    """剪刀：金屬刀身加藍色握環。"""
    # 刀身描粗一點並用 INK：METAL_DARK 擺在飽和的鄰居旁邊會顯得褪色
    p.setPen(QPen(INK, 5.6 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(int(20 * s), int(10 * s), int(42 * s), int(40 * s))
    p.drawLine(int(44 * s), int(10 * s), int(22 * s), int(40 * s))
    p.setPen(QPen(METAL, 2.6 * s, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(int(21 * s), int(12 * s), int(41 * s), int(39 * s))
    p.drawLine(int(43 * s), int(12 * s), int(23 * s), int(39 * s))

    p.setPen(QPen(BLUE_DARK, 2.4 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(BLUE)
    ring = 15.0
    p.drawEllipse(int(11 * s), int(40 * s), int(ring * s), int(ring * s))
    p.drawEllipse(int(38 * s), int(40 * s), int(ring * s), int(ring * s))
    p.setBrush(Qt.transparent)
    p.setPen(QPen(PAPER, 2.6 * s, Qt.SolidLine, Qt.RoundCap))
    p.drawEllipse(int(15 * s), int(44 * s), int(7 * s), int(7 * s))
    p.drawEllipse(int(42 * s), int(44 * s), int(7 * s), int(7 * s))


def _make_paste_icon(p, s):
    """夾板夾著一張紙。夾板用藍色，與複製的白紙分得開。"""
    p.setPen(QPen(BLUE_DARK, 2.4 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(BLUE)
    p.drawRoundedRect(int(11 * s), int(12 * s), int(42 * s), int(44 * s), 4 * s, 4 * s)
    p.setBrush(PAPER)
    p.drawRoundedRect(int(17 * s), int(22 * s), int(30 * s), int(30 * s), 2 * s, 2 * s)

    # 上方的金屬夾
    p.setPen(QPen(INK, 2.2 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(METAL)
    p.drawRoundedRect(int(24 * s), int(6 * s), int(16 * s), int(11 * s), 2.5 * s, 2.5 * s)

    p.setPen(QPen(BLUE, 2.0 * s, Qt.SolidLine, Qt.RoundCap))
    for i in range(3):
        y = int((30 + i * 7) * s)
        p.drawLine(int(22 * s), y, int(42 * s), y)


def _make_rename_icon(p, s):
    """鉛筆加底線：木身、金屬環、深色筆尖，與作者面板的「編輯」同一種鉛筆。"""
    p.setPen(QPen(FOLDER_EDGE, 2.0 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(FOLDER)
    p.drawPolygon(QPoint(int(24 * s), int(38 * s)), QPoint(int(44 * s), int(12 * s)),
                  QPoint(int(52 * s), int(18 * s)), QPoint(int(32 * s), int(44 * s)))
    p.setPen(QPen(FOLDER_GLOSS, 1.6 * s, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(int(29 * s), int(38 * s), int(47 * s), int(15 * s))

    # 筆尖
    p.setPen(QPen(INK, 1.8 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(INK)
    p.drawPolygon(QPoint(int(24 * s), int(38 * s)), QPoint(int(32 * s), int(44 * s)),
                  QPoint(int(20 * s), int(48 * s)))

    # 金屬環
    p.setPen(QPen(METAL_DARK, 1.8 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(METAL)
    p.drawPolygon(QPoint(int(39 * s), int(18 * s)), QPoint(int(45 * s), int(11 * s)),
                  QPoint(int(53 * s), int(17 * s)), QPoint(int(47 * s), int(24 * s)))

    # 底線：這顆是「重新命名」不是「編輯」，底線代表在改名字
    p.setPen(QPen(BLUE_ACCENT, 3.0 * s, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(int(12 * s), int(56 * s), int(52 * s), int(56 * s))


_FILE_ACTION_PAINTERS = {
    'copy': _make_copy_icon,
    'cut': _make_cut_icon,
    'paste': _make_paste_icon,
    'rename': _make_rename_icon,
}
