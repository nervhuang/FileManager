from PyQt5.QtWidgets import QTabBar, QWidget, QHBoxLayout, QToolButton, QStyle, QStyleOptionTab, QStylePainter, QComboBox, QApplication
from PyQt5.QtCore import Qt, pyqtSignal


class FixedWidthTabBar(QTabBar):
    """每個頁籤寬度固定為 10 個字元大小（依字型度量計算），文字靠左對齊。"""
    CHAR_COUNT = 10
    LEFT_PAD = 4  # 文字距左邊距 px

    def tabSizeHint(self, index):
        hint = super().tabSizeHint(index)
        fm = self.fontMetrics()
        char_w = max(fm.averageCharWidth(), fm.height())
        hint.setWidth(char_w * self.CHAR_COUNT)
        return hint

    def minimumTabSizeHint(self, index):
        return self.tabSizeHint(index)

    def paintEvent(self, event):
        # 取得關閉按鈕的像素寬度（含右側 padding），用來保留空間
        close_btn_w = self.style().pixelMetric(QStyle.PM_TabCloseIndicatorWidth, None, self) + 6
        painter = QStylePainter(self)
        for i in range(self.count()):
            opt = QStyleOptionTab()
            self.initStyleOption(opt, i)
            # 移除文字，先畫頁籤底色/邊框
            text = opt.text
            opt.text = ""
            painter.drawControl(QStyle.CE_TabBarTab, opt)
            # 手動繪製靠左文字，右側保留關閉按鈕空間
            tab_rect = self.tabRect(i)
            text_rect = tab_rect.adjusted(self.LEFT_PAD, 0, -close_btn_w, 0)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)


class TreeComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._skip_hide_once = False

    def showPopup(self):
        super().showPopup()
        view = self.view()
        if view is None:
            return
        popup = view.window()
        if popup is None:
            return
        screen = QApplication.screenAt(self.mapToGlobal(self.rect().bottomLeft()))
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        popup_geom = popup.geometry()
        max_height = max(320, available.bottom() - popup_geom.top() - 8)
        target_height = min(max_height, max(popup_geom.height(), int(available.height() * 0.8)))
        popup.resize(popup_geom.width(), target_height)

    def keep_popup_open_once(self):
        self._skip_hide_once = True

    def hidePopup(self):
        if self._skip_hide_once:
            self._skip_hide_once = False
            view = self.view()
            if view is not None:
                view.setFocus()
            return
        super().hidePopup()


class PathTabBar(QWidget):
    """多頁籤列，追蹤路徑（左/中面板）或搜尋關鍵字（右面板）。
    tab_switched 訊號在使用者切換頁籤時發出，帶出該頁籤儲存的資料。"""
    tab_switched = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tab_bar = FixedWidthTabBar(self)
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.setMovable(True)
        self.tab_bar.setExpanding(False)
        self.tab_bar.tabCloseRequested.connect(self._on_close_tab)
        self.tab_bar.currentChanged.connect(self._on_current_changed)
        self.tab_bar.tabMoved.connect(self._on_tab_moved)

        self._add_btn = QToolButton(self)
        self._add_btn.setText("+")
        self._add_btn.setToolTip("新增頁籤")
        self._add_btn.setFixedSize(22, 22)
        self._add_btn.clicked.connect(lambda: self.add_tab(""))

        layout.addWidget(self.tab_bar, 1)
        layout.addWidget(self._add_btn, 0)
        self.setLayout(layout)

        self._tab_data = []   # 每個頁籤儲存的資料（路徑或關鍵字）
        self._emit_on_change = True

        # 初始頁籤
        self._internal_add("", "新頁籤")
        self.sync_height()

    def sync_height(self, target_height=None):
        bar_height = max(target_height if target_height is not None else self.tab_bar.sizeHint().height(), 22)
        self.tab_bar.setFixedHeight(bar_height)
        self._add_btn.setFixedSize(bar_height, bar_height)
        self.setFixedHeight(bar_height)

    def _internal_add(self, data, label):
        prev = self._emit_on_change
        self._emit_on_change = False
        idx = self.tab_bar.addTab(label)
        self._tab_data.append(data)
        self._emit_on_change = prev
        return idx

    def add_tab(self, data="", label=""):
        """新增頁籤並切換至該頁籤。label 預設由 data 衍生。"""
        display = label or (data if data else "新頁籤")
        self._internal_add(data, display)
        self._emit_on_change = True
        self.tab_bar.setCurrentIndex(self.tab_bar.count() - 1)
        return self.tab_bar.count() - 1

    def set_current_data(self, data, label=""):
        """更新目前頁籤儲存的資料與標籤文字。"""
        idx = self.tab_bar.currentIndex()
        if 0 <= idx < len(self._tab_data):
            self._tab_data[idx] = data
            display = label or (data if data else "新頁籤")
            self.tab_bar.setTabText(idx, display)

    def current_data(self):
        idx = self.tab_bar.currentIndex()
        if 0 <= idx < len(self._tab_data):
            return self._tab_data[idx]
        return ""

    def _on_close_tab(self, index):
        if self.tab_bar.count() > 1:
            prev = self._emit_on_change
            self._emit_on_change = False
            self.tab_bar.removeTab(index)
            self._tab_data.pop(index)
            self._emit_on_change = prev

    def _on_tab_moved(self, from_index, to_index):
        """頁籤拖動時同步 _tab_data 的順序。"""
        self._tab_data.insert(to_index, self._tab_data.pop(from_index))

    def _on_current_changed(self, index):
        if self._emit_on_change and 0 <= index < len(self._tab_data):
            self.tab_switched.emit(self._tab_data[index])

    def get_all_tabs(self):
        """回傳 [(data, label), ...] 串列及目前頁籤索引。"""
        tabs = []
        for i in range(self.tab_bar.count()):
            data = self._tab_data[i] if i < len(self._tab_data) else ""
            label = self.tab_bar.tabText(i)
            tabs.append((data, label))
        return tabs, self.tab_bar.currentIndex()

    def restore_tabs(self, tabs, current_index):
        """以給定的 [(data, label), ...] 重建整個頁籤列。"""
        prev = self._emit_on_change
        self._emit_on_change = False
        while self.tab_bar.count() > 0:
            self.tab_bar.removeTab(0)
        self._tab_data.clear()
        for data, label in tabs:
            self.tab_bar.addTab(label)
            self._tab_data.append(data)
        if not tabs:
            self.tab_bar.addTab("新頁籤")
            self._tab_data.append("")
        safe_idx = current_index if 0 <= current_index < self.tab_bar.count() else 0
        self.tab_bar.setCurrentIndex(safe_idx)
        self._emit_on_change = prev
        self.sync_height()
