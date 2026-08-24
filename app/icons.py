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
    """檔案面板的操作圖示：cut／copy／paste／rename。"""
    size = _as_qsize(size)
    pix = QPixmap(size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    w, h = size.width(), size.height()
    ink = QColor("#4a4a4a")
    p.setPen(QPen(ink, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)

    def pt(fx, fy):
        return QPoint(int(w * fx), int(h * fy))

    if kind == "copy":
        p.drawRect(int(w * 0.22), int(h * 0.18), int(w * 0.38), int(h * 0.44))
        p.setBrush(QColor("#ffffff"))
        p.drawRect(int(w * 0.38), int(h * 0.34), int(w * 0.38), int(h * 0.44))
    elif kind == "cut":
        p.drawLine(pt(0.30, 0.28), pt(0.74, 0.62))
        p.drawLine(pt(0.74, 0.30), pt(0.30, 0.64))
        r = int(w * 0.13)
        p.drawEllipse(int(w * 0.20), int(h * 0.60), r, r)
        p.drawEllipse(int(w * 0.66), int(h * 0.60), r, r)
    elif kind == "paste":
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(int(w * 0.24), int(h * 0.22), int(w * 0.50), int(h * 0.58), 4, 4)
        p.setBrush(ink)
        p.drawRoundedRect(int(w * 0.40), int(h * 0.13), int(w * 0.20), int(h * 0.13), 2, 2)
        p.setPen(QPen(ink, 1.6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pt(0.33, 0.44), pt(0.65, 0.44))
        p.drawLine(pt(0.33, 0.56), pt(0.65, 0.56))
        p.drawLine(pt(0.33, 0.68), pt(0.55, 0.68))
    elif kind == "rename":
        p.drawLine(pt(0.24, 0.76), pt(0.68, 0.32))
        p.setBrush(ink)
        p.drawPolygon(pt(0.18, 0.82), pt(0.30, 0.78), pt(0.24, 0.70))
        p.setBrush(Qt.NoBrush)
        p.drawLine(pt(0.60, 0.24), pt(0.76, 0.40))
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
