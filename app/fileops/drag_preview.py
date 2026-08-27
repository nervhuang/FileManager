"""拖曳時跟著游標的預覽圖。

純繪圖：吃檔名、圖示與項目數，回傳 QPixmap。原本是 `SearchListView` 的方法，
但它一個 view 狀態都沒讀——把它留在 views.py 只是讓那支檔案為了畫一張圖而長大。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap


def build(name, icon, count):
    """畫出拖曳預覽：深色圓角底 ＋ 圖示 ＋ 檔名（過長從尾端省略）。

    `count` 大於 1 時多一行「N 個項目」，卡片也跟著加高——拖走一整批時，
    使用者要在放手之前就看得出來拖的不只一個。
    """
    secondary = f"{count} 個項目" if count > 1 else ""
    w = 260
    h = 52 if secondary else 40
    pix = QPixmap(w, h)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(32, 32, 32, 215))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, w - 1, h - 1, 8, 8)

    x = 10
    if isinstance(icon, QIcon):
        pm = icon.pixmap(20, 20)
        if not pm.isNull():
            p.drawPixmap(x, (h - 20) // 2, pm)
            x += 26

    p.setPen(QColor("white"))
    fm = p.fontMetrics()
    text_w = w - x - 10
    title = fm.elidedText(name, Qt.ElideRight, text_w)
    if secondary:
        p.drawText(x, 20, title)
        p.setPen(QColor(210, 210, 210))
        p.drawText(x, 38, secondary)
    else:
        p.drawText(x, 26, title)
    p.end()
    return pix
