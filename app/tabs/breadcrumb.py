"""麵包屑位址列：檔案總管式的路徑分段，點下去才讀該層的子目錄。

延遲載入是刻意的：預先掃描整棵樹在網路磁碟上會卡住整個 UI
（docs/spec/tabs.md 的 TAB-18 到 TAB-21）。
"""

import os

from PyQt5.QtCore import QDir, QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QFontMetrics
from PyQt5.QtWidgets import (QHBoxLayout, QLineEdit, QMenu, QSizePolicy,
                             QStackedLayout, QToolButton, QWidget)


def _list_drives():
    """回傳目前系統的磁碟機根路徑，例如 ['C:\\\\', 'D:\\\\']。"""
    roots = []
    for info in QDir.drives():
        p = os.path.normpath(info.absolutePath())
        if not p.endswith(os.sep):
            p += os.sep
        roots.append(p)
    return roots


def _list_subdirs(path):
    """單層列出 path 底下的子資料夾名稱（點下去才呼叫，不預先掃描）。"""
    try:
        with os.scandir(path) as it:
            names = [e.name for e in it if e.is_dir()]
    except OSError:
        return []
    names.sort(key=str.lower)
    return names


def split_path(path):
    """把絕對路徑拆成麵包屑分段，回傳 [(顯示文字, 完整路徑), ...]。
    例：D:\\PycharmProjects\\FileManager → [('D:', 'D:\\'), ('PycharmProjects', 'D:\\PycharmProjects'), ('FileManager', 'D:\\PycharmProjects\\FileManager')]"""
    norm = os.path.normpath(path)
    drive, tail = os.path.splitdrive(norm)
    segments = []
    if drive:
        root = drive + os.sep
        segments.append((drive, root))
        accum = root
        for part in [p for p in tail.split(os.sep) if p]:
            accum = os.path.join(accum, part)
            segments.append((part, accum))
    elif norm and norm != '.':
        segments.append((norm, norm))
    return segments


class _CrumbArea(QWidget):
    """麵包屑分段的容器；點在分段按鈕以外的空白處會發出 clicked_blank（用來切換編輯模式）。"""
    clicked_blank = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.childAt(event.pos()) is None:
            self.clicked_blank.emit()
        super().mousePressEvent(event)

    def minimumSizeHint(self):
        # 不讓分段總寬把整個視窗撐開；塞不下時交給溢位邏輯收合
        return QSize(0, super().minimumSizeHint().height())


class BreadcrumbBar(QWidget):
    """檔案總管風格的混合式路徑列。

    平常顯示可點擊的麵包屑分段；點分段=導覽到該層，點分段右側的 ›=下拉列出該層子資料夾
    （延遲載入，點下去才讀）。最左的根箭頭列出所有磁碟機。點右側空白區或按 Ctrl+L/Alt+D
    會切換成可編輯文字框，能打字/貼上完整路徑；按 Enter 導覽、失焦或 Esc 則變回麵包屑。
    路徑太長時，左側以 « 溢位選單收合前段祖先，當前資料夾永遠可見。

    導覽動作一律透過 path_selected 訊號對外發出（帶完整路徑；空字串代表「本機／所有磁碟機」）。"""
    path_selected = pyqtSignal(str)

    _CHEVRON_QSS = ("QToolButton{border:none;padding:1px 2px;}"
                    "QToolButton::menu-indicator{image:none;width:0;}"
                    "QToolButton:hover{background:rgba(127,127,127,0.20);border-radius:3px;}")
    _CRUMB_QSS = ("QToolButton{border:none;padding:2px 6px;}"
                  "QToolButton:hover{background:rgba(127,127,127,0.20);border-radius:3px;}")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 做成 Explorer 風格的位址列：淡邊框 + 微圓角 + 隨主題的底色
        self.setObjectName("breadcrumbBar")
        self.setStyleSheet(
            "#breadcrumbBar{border:1px solid rgba(127,127,127,0.45);"
            "border-radius:4px;background:palette(base);}"
        )
        self._base_height = 30
        self.setMinimumHeight(self._base_height)
        self._current_path = ""
        self._pairs = []  # [(crumb_btn, chevron_btn, label, path), ...]
        # 目前套用的字型。Qt 對設過 stylesheet 的元件會把字型視為「已明確設定」，
        # 父層字型不再往下傳，因此每個子元件都得自己設一次（含之後重建的麵包屑）。
        self._crumb_font = None

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)

        # 麵包屑頁
        self._area = _CrumbArea(self)
        self._area.clicked_blank.connect(self.focus_edit)
        area_layout = QHBoxLayout(self._area)
        area_layout.setContentsMargins(6, 0, 6, 0)
        area_layout.setSpacing(0)
        self._area_layout = area_layout

        self._root_btn = self._make_chevron(None)   # None → 列出磁碟機
        self._overflow_btn = self._make_overflow_btn()
        self._stack.addWidget(self._area)

        # 編輯頁：無邊框、透明底，讓它融入位址列外框
        self._edit = QLineEdit(self)
        self._edit.setFrame(False)
        self._edit.setStyleSheet("QLineEdit{border:none;background:transparent;padding:0 6px;}")
        self._edit.returnPressed.connect(self._commit_edit)
        self._edit.installEventFilter(self)
        self._stack.addWidget(self._edit)

        self.set_path("")

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    # ---- 對外 API ---------------------------------------------------------
    def set_path(self, path):
        """更新顯示的路徑（導覽後由外部呼叫）。不會反過來觸發 path_selected。"""
        self._current_path = path or ""
        self._rebuild()

    def apply_font(self, font):
        """套用字型到位址列的每一個子元件，並依字高調整列高。

        不能只 setFont(self)：本列與其中的按鈕、編輯框都各自設了 stylesheet，
        Qt 會把這些元件的字型視為已明確設定，父層字型無法傳下去。
        """
        self._crumb_font = QFont(font)
        self.setFont(font)
        self._area.setFont(font)
        self._edit.setFont(font)
        for btn in self.findChildren(QToolButton):
            btn.setFont(font)
        self.setMinimumHeight(max(self._base_height, QFontMetrics(font).height() + 12))
        self._rebuild()   # 重建的麵包屑要拿到新字型

    def _apply_crumb_font(self, btn):
        if self._crumb_font is not None:
            btn.setFont(self._crumb_font)
        return btn

    def focus_edit(self):
        """切換成可編輯文字框並全選（Ctrl+L / Alt+D / 點空白區）。"""
        self._edit.setText(self._current_path)
        self._stack.setCurrentWidget(self._edit)
        self._edit.setFocus()
        self._edit.selectAll()

    # ---- 內部：麵包屑建構 --------------------------------------------------
    def _make_crumb(self, label, path):
        btn = QToolButton(self._area)
        btn.setText(label)
        btn.setAutoRaise(True)
        btn.setStyleSheet(self._CRUMB_QSS)
        btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn.clicked.connect(lambda _=False, p=path: self.path_selected.emit(p))
        return self._apply_crumb_font(btn)

    def _make_chevron(self, path):
        """分段之間的下拉箭頭。path=完整路徑時列出其子資料夾；path=None 時列出磁碟機。"""
        btn = QToolButton(self._area)
        btn.setText("›")  # ›
        btn.setAutoRaise(True)
        btn.setStyleSheet(self._CHEVRON_QSS)
        btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(btn)
        menu.aboutToShow.connect(lambda m=menu, p=path: self._populate_dir_menu(m, p))
        btn.setMenu(menu)
        return self._apply_crumb_font(btn)

    def _make_overflow_btn(self):
        btn = QToolButton(self._area)
        btn.setText("«")  # «
        btn.setAutoRaise(True)
        btn.setStyleSheet(self._CHEVRON_QSS)
        btn.setPopupMode(QToolButton.InstantPopup)
        btn.setToolTip("顯示上層路徑")
        self._overflow_menu = QMenu(btn)
        btn.setMenu(self._overflow_menu)
        btn.hide()
        return self._apply_crumb_font(btn)

    def _populate_dir_menu(self, menu, path):
        menu.clear()
        if path is None:
            entries = [(os.path.splitdrive(d)[0] or d, d) for d in _list_drives()]
        else:
            entries = [(name, os.path.join(path, name)) for name in _list_subdirs(path)]
        if not entries:
            act = menu.addAction("（無子資料夾）")
            act.setEnabled(False)
            return
        for label, full in entries:
            act = menu.addAction(label)
            act.triggered.connect(lambda _=False, p=full: self.path_selected.emit(p))

    def _clear_area(self):
        while self._area_layout.count():
            item = self._area_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._pairs = []

    def _rebuild(self):
        self._clear_area()
        segments = split_path(self._current_path) if self._current_path else []

        # 根箭頭（列出磁碟機）永遠在最左
        self._root_btn = self._make_chevron(None)
        self._area_layout.addWidget(self._root_btn)
        # 溢位鈕（預設隱藏，_apply_overflow 時視需要顯示）
        self._area_layout.addWidget(self._overflow_btn)
        self._overflow_btn.hide()

        if not segments:
            crumb = self._make_crumb("本機", "")
            self._area_layout.addWidget(crumb)
            self._pairs.append((crumb, None, "本機", ""))
        else:
            for label, path in segments:
                crumb = self._make_crumb(label, path)
                chevron = self._make_chevron(path)
                self._area_layout.addWidget(crumb)
                self._area_layout.addWidget(chevron)
                self._pairs.append((crumb, chevron, label, path))

        self._area_layout.addStretch(1)
        # 版面尚未定寬時，延到事件迴圈再算溢位
        QTimer.singleShot(0, self._apply_overflow)

    def _pair_width(self, pair):
        crumb, chevron, _, _ = pair
        w = crumb.sizeHint().width()
        if chevron is not None:
            w += chevron.sizeHint().width()
        return w

    def _apply_overflow(self):
        if not self._pairs:
            return
        # 先全部顯示，重算可用寬度
        for crumb, chevron, _, _ in self._pairs:
            crumb.show()
            if chevron is not None:
                chevron.show()
        margins = self._area_layout.contentsMargins()
        avail = self._area.width() - margins.left() - margins.right() - self._root_btn.sizeHint().width()
        total = sum(self._pair_width(p) for p in self._pairs)
        if total <= avail or len(self._pairs) <= 1:
            self._overflow_btn.hide()
            return

        # 需要收合：保留溢位鈕寬度，從右往左盡量塞，最右段一定保留
        self._overflow_btn.show()
        avail -= self._overflow_btn.sizeHint().width()
        used = 0
        keep_from = len(self._pairs) - 1
        for i in range(len(self._pairs) - 1, -1, -1):
            w = self._pair_width(self._pairs[i])
            if i != len(self._pairs) - 1 and used + w > avail:
                break
            used += w
            keep_from = i

        hidden = self._pairs[:keep_from]
        for crumb, chevron, _, _ in hidden:
            crumb.hide()
            if chevron is not None:
                chevron.hide()

        self._overflow_menu.clear()
        for _, _, label, path in hidden:
            act = self._overflow_menu.addAction(label)
            act.triggered.connect(lambda _=False, p=path: self.path_selected.emit(p))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_overflow()

    # ---- 內部：編輯模式 ---------------------------------------------------
    def _show_crumbs(self):
        self._stack.setCurrentWidget(self._area)

    def _commit_edit(self):
        text = self._edit.text().strip()
        self._show_crumbs()
        if text:
            self.path_selected.emit(text)

    def eventFilter(self, obj, event):
        if obj is self._edit:
            if event.type() == QEvent.FocusOut:
                # 失焦：回到麵包屑，不導覽（規格）
                self._show_crumbs()
            elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self._show_crumbs()
                return True
        return super().eventFilter(obj, event)
