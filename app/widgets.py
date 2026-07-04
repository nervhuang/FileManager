from PyQt5.QtWidgets import (QTabBar, QWidget, QHBoxLayout, QToolButton, QStyle,
                             QStyleOptionTab, QStylePainter, QComboBox, QApplication,
                             QProxyStyle)
from PyQt5.QtCore import Qt, QRect, QTimer, pyqtSignal


class _LeftAlignTabStyle(QProxyStyle):
    """攔截 CE_TabBarTabLabel，將頁籤文字改為靠左對齊。
    其餘所有繪製（背景、邊框、close 按鈕、drag 動畫）全部委派給原生樣式，
    避免自訂 paintEvent 對 clip region 與 painter state 造成的副作用。"""
    LEFT_PAD = 4

    def drawControl(self, element, opt, painter, widget=None):
        if (element == QStyle.CE_TabBarTabLabel
                and isinstance(opt, QStyleOptionTab)
                and opt.text):
            fm = widget.fontMetrics() if widget else painter.fontMetrics()
            tr = self.subElementRect(QStyle.SE_TabBarTabText, opt, widget)
            if tr.isValid():
                tr = tr.adjusted(self.LEFT_PAD, 0, 0, 0)
                elided = fm.elidedText(opt.text, Qt.ElideRight, tr.width())
                painter.drawText(tr, Qt.AlignLeft | Qt.AlignVCenter, elided)
                return
        super().drawControl(element, opt, painter, widget)


class FixedWidthTabBar(QTabBar):
    """每個頁籤寬度固定為 10 個字元大小（依字型度量計算），文字靠左對齊。

    拖曳重排完全自行實作（停用 Qt 原生 movable）：被拖曳的頁籤以一個浮動副本緊跟
    游標繪製，游標在邊界內時隨即就近重排；游標超出左右邊界時，由 timer 逐格推進，
    被拖曳的頁籤越過相鄰頁籤一格、並捲動讓原本隱藏的頁籤現身，一格接一格越過去。

    之所以不用 Qt 原生拖曳：原生拖曳的錨點在按下時就固定，一旦在拖曳途中捲動，
    它畫的浮動頁籤位置便與游標脫節且無法從外部修正。自行繪製可完全掌控位置。"""
    CHAR_COUNT = 10
    SCROLL_INTERVAL = 80  # 逐格推進的間隔（毫秒）

    drag_released = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setElideMode(Qt.ElideRight)
        self.setStyle(_LeftAlignTabStyle())
        self.setMovable(False)   # 改由本類別自行處理拖曳重排與浮動繪製
        self._drag_idx = -1      # 正在拖曳的頁籤索引，-1 表示未拖曳
        self._grab_dx = 0        # 按下點與該頁籤左緣的距離，浮動副本據此貼齊游標
        self._press_x = 0
        self._dragging = False   # 是否已超過啟動拖曳的位移門檻
        self._float_left = 0     # 浮動副本目前的左緣（widget 座標）
        self._scroll_dir = 0     # -1 往左、+1 往右、0 不推進
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(self.SCROLL_INTERVAL)
        self._scroll_timer.timeout.connect(self._advance_dragged_tab)

    def tabSizeHint(self, index):
        hint = super().tabSizeHint(index)
        fm = self.fontMetrics()
        char_w = max(fm.averageCharWidth(), fm.height())
        hint.setWidth(char_w * self.CHAR_COUNT)
        return hint

    def minimumTabSizeHint(self, index):
        return self.tabSizeHint(index)

    # ---- 拖曳：按下／移動／放開 ----------------------------------------

    def mousePressEvent(self, event):
        super().mousePressEvent(event)   # 維持原生的選取行為
        if event.button() == Qt.LeftButton:
            idx = self.tabAt(event.pos())
            if idx >= 0:
                self._drag_idx = idx
                self._grab_dx = event.x() - self.tabRect(idx).left()
                self._press_x = event.x()
                self._dragging = False

    def mouseMoveEvent(self, event):
        if self._drag_idx < 0 or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if not self._dragging:
            if abs(event.x() - self._press_x) < QApplication.startDragDistance():
                return
            self._begin_drag()
        self._float_left = event.x() - self._grab_dx
        if event.x() >= self.width():
            self._set_scroll_dir(1)        # 超出右界：交給 timer 逐格推進
        elif event.x() < 0:
            self._set_scroll_dir(-1)       # 超出左界
        else:
            self._set_scroll_dir(0)        # 邊界內：就近重排
            self._reorder_to_float()
        self.update()

    def mouseReleaseEvent(self, event):
        self._end_drag()
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.drag_released.emit()

    def _begin_drag(self):
        self._dragging = True
        # 隱藏被拖曳頁籤原位的關閉鈕，原位只留空檔，頁籤改以浮動副本呈現
        self._set_close_button_visible(self._drag_idx, False)

    def _end_drag(self):
        self._set_scroll_dir(0)
        if self._drag_idx >= 0:
            self._set_close_button_visible(self._drag_idx, True)
        self._drag_idx = -1
        self._dragging = False
        self.update()

    def _set_close_button_visible(self, index, visible):
        if not (0 <= index < self.count()):
            return
        for side in (QTabBar.RightSide, QTabBar.LeftSide):
            btn = self.tabButton(index, side)
            if btn is not None:
                btn.setVisible(visible)

    # ---- 重排與捲動 ----------------------------------------------------

    def _reorder_to_float(self):
        """邊界內：當浮動副本的中心越過相鄰頁籤的中心，就與之對調，使順序就近跟著游標。"""
        i = self._drag_idx
        center = self._float_left + self.tabRect(i).width() / 2
        while i < self.count() - 1 and center > self.tabRect(i + 1).center().x():
            self.moveTab(i, i + 1)
            i += 1
        while i > 0 and center < self.tabRect(i - 1).center().x():
            self.moveTab(i, i - 1)
            i -= 1
        self._drag_idx = i

    def _set_scroll_dir(self, direction):
        if direction == self._scroll_dir:
            return
        self._scroll_dir = direction
        if direction != 0:
            self._scroll_timer.start()
        else:
            self._scroll_timer.stop()

    def _advance_dragged_tab(self):
        """游標停在邊界外時，由 timer 週期呼叫：被拖曳的頁籤越過相鄰頁籤一格並捲動現身。"""
        direction = self._scroll_dir
        if direction == 0 or self._drag_idx < 0:
            self._scroll_timer.stop()
            return
        target = self._drag_idx + direction
        if not (0 <= target < self.count()):
            self._scroll_timer.stop()   # 已到最前／最後一個頁籤，無法再越過
            return
        self.moveTab(self._drag_idx, target)
        self._drag_idx = target
        self.scroll_index_into_view(target)
        self.update()

    def scroll_index_into_view(self, index):
        """點擊原生捲動箭頭，直到第 index 個頁籤完整顯示。"""
        if not (0 <= index < self.count()):
            return
        # 依頁籤目前是被切到左側還是右側，決定要點左箭頭或右箭頭。以箭頭方向
        # （arrowType）辨識而非位置：頁籤很寬時兩個箭頭會擠在同一側，用位置會選錯方向。
        for _ in range(self.count() + 1):
            rect = self.tabRect(index)
            if rect.left() >= 0 and rect.right() <= self.width():
                return
            want = Qt.LeftArrow if rect.left() < 0 else Qt.RightArrow
            btn = next((b for b in self.findChildren(QToolButton)
                        if b.parent() is self and b.isVisible() and b.isEnabled()
                        and b.arrowType() == want), None)
            if btn is None:
                return  # 該方向已無可用箭頭（捲到底）
            btn.click()

    # ---- 繪製：原位留空，被拖曳頁籤以浮動副本緊跟游標 ------------------

    def paintEvent(self, event):
        # 非拖曳狀態完全交給原生繪製，外觀與行為與未改動前一致，零回歸風險。
        if not self._dragging or self._drag_idx < 0:
            super().paintEvent(event)
            return
        # 拖曳中：被拖曳頁籤的原位留空，改以一個平移到游標處的浮動副本呈現。
        painter = QStylePainter(self)
        cur = self.currentIndex()
        drag = self._drag_idx
        # 先畫其餘頁籤，選取的頁籤畫在上層以正確覆蓋邊框；被拖曳的原位略過（留空檔）
        for i in range(self.count()):
            if i == cur or i == drag:
                continue
            opt = QStyleOptionTab()
            self.initStyleOption(opt, i)
            painter.drawControl(QStyle.CE_TabBarTab, opt)
        if cur >= 0 and cur != drag:
            opt = QStyleOptionTab()
            self.initStyleOption(opt, cur)
            painter.drawControl(QStyle.CE_TabBarTab, opt)
        # 被拖曳的頁籤畫在最上層，並平移到貼齊游標的浮動位置
        opt = QStyleOptionTab()
        self.initStyleOption(opt, drag)
        r = opt.rect
        opt.rect = QRect(int(self._float_left), r.y(), r.width(), r.height())
        painter.drawControl(QStyle.CE_TabBarTab, opt)


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
    tab_switched 訊號在使用者切換頁籤時發出，帶出該頁籤儲存的資料。
    拖曳移動期間抑制 tab_switched，待滑鼠放開後補發一次，避免面板異常刷新。"""
    tab_switched = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tab_bar = FixedWidthTabBar(self)
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.setExpanding(False)
        self.tab_bar.tabCloseRequested.connect(self._on_close_tab)
        self.tab_bar.currentChanged.connect(self._on_current_changed)
        self.tab_bar.tabMoved.connect(self._on_tab_moved)
        self.tab_bar.drag_released.connect(self._on_drag_released)

        self._add_btn = QToolButton(self)
        self._add_btn.setText("+")
        self._add_btn.setToolTip("新增頁籤")
        self._add_btn.setFixedSize(22, 22)
        self._add_btn.clicked.connect(lambda: self.add_tab(""))

        layout.addWidget(self.tab_bar, 1)
        layout.addWidget(self._add_btn, 0)
        self.setLayout(layout)

        self._tab_data = []
        self._emit_on_change = True
        self._tab_moved_during_drag = False

        self._internal_add("", "新頁籤")
        self.sync_height()

    def sync_height(self, target_height=None):
        bar_height = max(target_height if target_height is not None else self.tab_bar.sizeHint().height(), 22)
        self.tab_bar.setFixedHeight(bar_height)
        self._add_btn.setFixedSize(bar_height, bar_height)
        self.setFixedHeight(bar_height)

    def _internal_add(self, data, label, index=None):
        prev = self._emit_on_change
        self._emit_on_change = False
        if index is None:
            idx = self.tab_bar.addTab(label)
            self._tab_data.append(data)
        else:
            idx = self.tab_bar.insertTab(index, label)
            self._tab_data.insert(index, data)
        self._emit_on_change = prev
        return idx

    def add_tab(self, data="", label="", index=None):
        display = label or (data if data else "新頁籤")
        idx = self._internal_add(data, display, index)
        self._emit_on_change = True
        self.tab_bar.setCurrentIndex(idx)
        return idx

    def set_current_data(self, data, label=""):
        idx = self.tab_bar.currentIndex()
        if 0 <= idx < len(self._tab_data):
            self._tab_data[idx] = data
            display = label or (data if data else "新頁籤")
            self.tab_bar.setTabText(idx, display)
            QTimer.singleShot(0, lambda i=idx: self.tab_bar.scroll_index_into_view(i))

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
        self._tab_data.insert(to_index, self._tab_data.pop(from_index))
        self._tab_moved_during_drag = True

    def _on_current_changed(self, index):
        if self._tab_moved_during_drag:
            return
        if self._emit_on_change and 0 <= index < len(self._tab_data):
            self.tab_switched.emit(self._tab_data[index])

    def _on_drag_released(self):
        was_moved = self._tab_moved_during_drag
        self._tab_moved_during_drag = False
        if was_moved and self._emit_on_change:
            idx = self.tab_bar.currentIndex()
            if 0 <= idx < len(self._tab_data):
                self.tab_switched.emit(self._tab_data[idx])

    def get_all_tabs(self):
        tabs = []
        for i in range(self.tab_bar.count()):
            data = self._tab_data[i] if i < len(self._tab_data) else ""
            label = self.tab_bar.tabText(i)
            tabs.append((data, label))
        return tabs, self.tab_bar.currentIndex()

    def restore_tabs(self, tabs, current_index):
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
