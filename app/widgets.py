import os

from PyQt5.QtWidgets import (QTabBar, QWidget, QHBoxLayout, QToolButton, QStyle,
                             QStyleOptionTab, QStylePainter, QApplication,
                             QProxyStyle, QLineEdit, QMenu, QStackedLayout, QSizePolicy)
from PyQt5.QtCore import Qt, QRect, QRectF, QSize, QTimer, QEvent, QDir, QPoint, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette, QPen



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


class _ScaledTabCloseStyle(QProxyStyle):
    """把頁籤關閉鈕的 X 改為隨按鈕大小縮放。

    原生樣式的 PE_IndicatorTabClose 只會在按鈕矩形中央畫一個固定尺寸的 X，
    把按鈕放大也不會跟著變，字型一放大 X 就顯得越來越小。這裡整個接手繪製，
    連帶自行處理滑過與按下的回饋（原本那份是由原生樣式一起畫的）。
    """

    def drawPrimitive(self, element, option, painter, widget=None):
        if element != QStyle.PE_IndicatorTabClose:
            super().drawPrimitive(element, option, painter, widget)
            return

        rect = option.rect
        hovered = bool(option.state & (QStyle.State_MouseOver | QStyle.State_Raised))
        pressed = bool(option.state & QStyle.State_Sunken)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if pressed or hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(196, 43, 28) if pressed else QColor(127, 127, 127, 64))
            radius = rect.width() * 0.2
            painter.drawRoundedRect(QRectF(rect), radius, radius)

        inset = max(2.0, rect.width() * 0.30)
        cross = QRectF(rect).adjusted(inset, inset, -inset, -inset)
        colour = QColor("#ffffff") if pressed else option.palette.color(QPalette.WindowText)
        painter.setPen(QPen(colour, max(1.1, rect.width() * 0.10),
                            Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(cross.topLeft(), cross.bottomRight())
        painter.drawLine(cross.topRight(), cross.bottomLeft())
        painter.restore()


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
        # 需保留參考：QWidget.setStyle 不接手所有權，物件被回收會導致繪製時崩潰
        self._close_style = _ScaledTabCloseStyle()

    def tabSizeHint(self, index):
        hint = super().tabSizeHint(index)
        fm = self.fontMetrics()
        char_w = max(fm.averageCharWidth(), fm.height())
        hint.setWidth(char_w * self.CHAR_COUNT)
        return hint

    def minimumTabSizeHint(self, index):
        return self.tabSizeHint(index)

    # ---- 關閉鈕尺寸 ----------------------------------------------------
    #
    # 頁籤本身會隨字型變大（tabSizeHint 依 fontMetrics 計算），但關閉鈕的大小
    # 來自樣式的 PM_TabCloseIndicator*，與字型無關，因此字放大後 X 會顯得越來越
    # 小。關閉鈕是 QTabBar 自建的子元件，且它取用的 style 物件與本 tab bar 的
    # proxy style 並非同一個，覆寫 pixelMetric 影響不到它，只能直接設定尺寸。

    def _close_button_size(self):
        return max(16, round(self.fontMetrics().height() * 0.78))

    def _sync_close_button_sizes(self):
        size = QSize(self._close_button_size(), self._close_button_size())
        for index in range(self.count()):
            for side in (QTabBar.RightSide, QTabBar.LeftSide):
                btn = self.tabButton(index, side)
                if btn is None:
                    continue
                # 光是放大按鈕不夠：原生樣式畫的 X 是固定尺寸，只會置中在放大後
                # 的框裡。改掛自訂 style，X 才會跟著按鈕一起長大。
                if btn.style() is not self._close_style:
                    btn.setStyle(self._close_style)
                if btn.size() != size:
                    btn.setFixedSize(size)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange:
            self._sync_close_button_sizes()

    def tabInserted(self, index):
        super().tabInserted(index)
        self._sync_close_button_sizes()

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
        # 「＋」上按右鍵＝列出所有分頁
        self._add_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self._add_btn.customContextMenuRequested.connect(
            lambda pos: self._show_tab_list_menu(self._add_btn.mapToGlobal(pos)))

        # 分頁清單鈕：頁籤只有 10 個字寬且會被截斷，分頁一多就認不出誰是誰，
        # 這顆鈕列出每個分頁的完整路徑／關鍵字，點一下直接跳過去。
        self._list_btn = QToolButton(self)
        self._list_btn.setArrowType(Qt.DownArrow)
        self._list_btn.setToolTip("所有分頁")
        self._list_btn.setFixedSize(22, 22)
        self._list_btn.clicked.connect(
            lambda: self._show_tab_list_menu(
                self._list_btn.mapToGlobal(QPoint(0, self._list_btn.height()))))

        # 頁籤列的空白處按右鍵也叫得出來；按在頁籤本身則不反應
        self.tab_bar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tab_bar.customContextMenuRequested.connect(self._on_tab_bar_context_menu)

        layout.addWidget(self.tab_bar, 1)
        layout.addWidget(self._add_btn, 0)
        layout.addWidget(self._list_btn, 0)
        self.setLayout(layout)

        self._tab_data = []
        self._emit_on_change = True
        self._tab_moved_during_drag = False

        self._internal_add("", "新頁籤")
        self.sync_height()

    def sync_height(self, target_height=None):
        bar_height = max(target_height if target_height is not None else self.tab_bar.sizeHint().height(), 22)
        self.tab_bar.setFixedHeight(bar_height)
        for btn in (self._add_btn, self._list_btn):
            btn.setFixedSize(bar_height, bar_height)
        self.setFixedHeight(bar_height)

    # ---- 所有分頁清單 --------------------------------------------------

    def _on_tab_bar_context_menu(self, pos):
        """只在頁籤列的空白處回應右鍵；按在頁籤上不動作。"""
        if self.tab_bar.tabAt(pos) < 0:
            self._show_tab_list_menu(self.tab_bar.mapToGlobal(pos))

    def _tab_list_label(self, index):
        """清單上要顯示的文字：優先用完整資料，沒有資料才退回頁籤標籤。"""
        data = self._tab_data[index] if index < len(self._tab_data) else ""
        return data or self.tab_bar.tabText(index)

    def _show_tab_list_menu(self, global_pos):
        menu = self.build_tab_list_menu()
        if menu is None:
            return
        menu.exec_(global_pos)
        menu.deleteLater()   # 否則每開一次就多留一個 QMenu 掛在本元件底下

    def build_tab_list_menu(self):
        """建立「所有分頁」選單（不顯示）。分開建構與顯示以便測試。"""
        if self.tab_bar.count() == 0:
            return None
        menu = QMenu(self)
        # QMenu 不會從父層繼承已放大的字型，必須明確指定，否則字型放大後清單仍是預設大小
        menu.setFont(self.tab_bar.font())
        menu.setToolTipsVisible(True)

        metrics = QFontMetrics(menu.font())
        max_width = metrics.averageCharWidth() * 48   # 超過此寬度才省略，約 48 個字
        current = self.tab_bar.currentIndex()
        bold = QFont(menu.font())
        bold.setBold(True)

        for index in range(self.tab_bar.count()):
            full = self._tab_list_label(index)
            # 中間省略：路徑的磁碟機與最後一層資料夾都是辨識關鍵，頭尾都要保留
            action = menu.addAction(metrics.elidedText(full, Qt.ElideMiddle, max_width))
            action.setToolTip(full)
            if index == current:
                action.setCheckable(True)
                action.setChecked(True)
                action.setFont(bold)
            action.triggered.connect(lambda _=False, i=index: self._activate_tab(i))

        return menu

    def _activate_tab(self, index):
        """切換到指定分頁並讓面板顯示它的內容。

        一般情況下 setCurrentIndex 會觸發既有的 _on_current_changed 發出
        tab_switched；但點到的若已經是目前分頁，setCurrentIndex 不會發出
        currentChanged，面板就不會更新。面板內容本來就可能與分頁存的資料不同步
        （例如面板已導覽到別的目錄、分頁資料卻還是舊的），使用者從清單點選時的
        期待是「顯示這個分頁的內容」，因此這種情況補發一次。
        """
        if not (0 <= index < self.tab_bar.count()):
            return
        if index == self.tab_bar.currentIndex():
            if self._emit_on_change and index < len(self._tab_data):
                self.tab_switched.emit(self._tab_data[index])
        else:
            self.tab_bar.setCurrentIndex(index)
        self.tab_bar.scroll_index_into_view(index)

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

    def close_current_tab(self):
        """關閉目前分頁（至少保留一個），關閉後切換至相鄰分頁並發出 tab_switched，
        讓面板內容更新為新目前分頁的資料。供 Ctrl+W 熱鍵使用。"""
        if self.tab_bar.count() <= 1:
            return
        self._on_close_tab(self.tab_bar.currentIndex())
        new_idx = self.tab_bar.currentIndex()
        if self._emit_on_change and 0 <= new_idx < len(self._tab_data):
            self.tab_switched.emit(self._tab_data[new_idx])

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


def _split_path(path):
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
        segments = _split_path(self._current_path) if self._current_path else []

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


class KeepOpenMenu(QMenu):
    """勾選 checkable 項目後不關閉的選單，可一次連續切換多個選項。

    QMenu 預設觸發任何動作即關閉。此處攔截滑鼠放開與 Enter/Space：若當前項目是
    啟用中的 checkable 動作，就自行 trigger() 並吞掉事件，選單保持開啟；其餘情形
    （點在分隔線、停用項目或選單外）一律交回原生處理，Esc 與點外面仍可關閉。"""

    def _toggle_active(self):
        action = self.activeAction()
        if action is not None and action.isEnabled() and action.isCheckable():
            action.trigger()
            return True
        return False

    def mouseReleaseEvent(self, event):
        if self._toggle_active():
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self._toggle_active():
            event.accept()
            return
        super().keyPressEvent(event)


def build_column_visibility_menu(view, locked_columns=(), on_toggled=None, parent=None):
    """建立「欄位顯示」切換選單：每個欄位一個 checkbox，勾選狀態即該欄目前是否顯示。

    項目依表頭的視覺順序排列，與畫面上看到的欄位順序一致。locked_columns 內的欄位
    以已勾選但停用的樣子呈現（恆顯示、點不動）。實際的顯示/隱藏動作交由 on_toggled
    (column, visible) 執行，讓呼叫端得以一併處理欄寬記憶。"""
    menu = KeepOpenMenu(parent if parent is not None else view)
    model = view.model()
    header = view.header()
    if model is None or header is None:
        return menu

    for visual in range(header.count()):
        logical = header.logicalIndex(visual)
        label = model.headerData(logical, Qt.Horizontal, Qt.DisplayRole)
        action = menu.addAction(str(label) if label else str(logical))
        action.setCheckable(True)
        action.setChecked(not view.isColumnHidden(logical))
        if logical in locked_columns:
            action.setEnabled(False)
        elif on_toggled is not None:
            action.toggled.connect(
                lambda checked, col=logical: on_toggled(col, checked))
    return menu
