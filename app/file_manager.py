import sys
import subprocess
import os
import ctypes
import ctypes.wintypes as wt
import base64
import configparser
import json
import re
import traceback
import unicodedata
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTreeView, QFileSystemModel, QWidget,
    QHBoxLayout, QVBoxLayout, QAction, QMessageBox, QStyle,
    QToolButton, QSplitter, QSizePolicy, QFileIconProvider,
    QAbstractItemView, QMenu, QComboBox,
    QDialog, QCheckBox, QListWidget, QFileDialog, QDialogButtonBox,
    QPushButton, QLabel,
)
from PyQt5.QtCore import QDir, Qt, QSize, QFileInfo, QEvent, QTimer, QFileSystemWatcher, QPoint, QItemSelectionModel, QMimeData, QUrl
from PyQt5.QtGui import QKeySequence, QIcon, QFont, QPixmap, QPainter, QColor, QPalette, QStandardItem, QPen, QLinearGradient

# Optional SVG renderer (may not be present in minimal PyQt installs)
try:
    from PyQt5.QtSvg import QSvgRenderer
    HAVE_SVG_RENDERER = True
except Exception:
    QSvgRenderer = None
    HAVE_SVG_RENDERER = False

from .everything_sdk import EverythingSDK
from .file_index import FileMetadataCache
from .models import DrivesSortProxyModel, SearchSortProxyModel, SearchResultsModel, FileSystemSortProxyModel
from .views import CustomTreeView, SearchListView, FileListView
from .widgets import PathTabBar, TreeComboBox

ref_s = 0
ref_e = 1
global_keywords = []


def _bundle_root():
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def _runtime_root():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class ExcludeSettingsDialog(QDialog):
    """排除設定對話框：勾選是否啟用排除清單，並維護「不列出的目錄」清單。

    被排除的目錄（及其子路徑）不會在中間檔案面板與右側搜尋結果中列出。"""

    def __init__(self, enabled, dirs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("排除設定")
        self.resize(560, 420)

        layout = QVBoxLayout(self)

        self.enable_checkbox = QCheckBox("啟用排除清單", self)
        self.enable_checkbox.setChecked(bool(enabled))
        layout.addWidget(self.enable_checkbox)

        layout.addWidget(QLabel("排除的目錄（這些目錄及其內容不會列出）：", self))

        body = QHBoxLayout()
        self.dir_list = QListWidget(self)
        self.dir_list.addItems(list(dirs))
        body.addWidget(self.dir_list, 1)

        button_col = QVBoxLayout()
        self.add_button = QPushButton("新增資料夾...", self)
        self.remove_button = QPushButton("移除", self)
        self.add_button.clicked.connect(self._on_add_folder)
        self.remove_button.clicked.connect(self._on_remove)
        button_col.addWidget(self.add_button)
        button_col.addWidget(self.remove_button)
        button_col.addStretch(1)
        body.addLayout(button_col)
        layout.addLayout(body)

        self.dir_list.currentRowChanged.connect(self._update_buttons)
        self._update_buttons()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_buttons(self, *args):
        self.remove_button.setEnabled(self.dir_list.currentRow() >= 0)

    def _on_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "選擇要排除的資料夾")
        if not folder:
            return
        folder = os.path.normpath(folder)
        existing = {os.path.normcase(self.dir_list.item(i).text())
                    for i in range(self.dir_list.count())}
        if os.path.normcase(folder) not in existing:
            self.dir_list.addItem(folder)

    def _on_remove(self):
        row = self.dir_list.currentRow()
        if row >= 0:
            self.dir_list.takeItem(row)

    def result_values(self):
        dirs = [self.dir_list.item(i).text() for i in range(self.dir_list.count())]
        return self.enable_checkbox.isChecked(), dirs


class FileManager(QMainWindow):
    def __init__(self):
        super().__init__()

        self.everything = EverythingSDK()
        # 開啟時於背景預載固定磁碟的檔案中繼資料，加速搜尋結果渲染。
        # 索引會存到磁碟，下次開啟直接載入（秒級），不必每次重掃幾分鐘。
        self.file_index = FileMetadataCache(
            cache_path=os.path.join(_runtime_root(), 'file_index_cache.dat')
        )
        self.search_model = None
        self.sdk_warned = False
        # 排除目錄設定：被排除的目錄（及其子路徑）不在中間面板與搜尋結果中列出。
        # _exclude_dirs 保存使用者原始路徑（供顯示），_exclude_norm 為比對用正規化路徑。
        self._exclude_enabled = False
        self._exclude_dirs = []
        self._exclude_norm = ()
        self._search_drag_button = Qt.NoButton
        self._toolbar_icon_size = QSize(48, 48)
        self._nav_history = []
        self._nav_history_index = -1
        self._ignore_tree_selection = False
        self._search_model_updating = False
        self._search_item_rename_in_progress = False
        self._search_icon_provider = QFileIconProvider()
        self._search_icon_cache = {}
        self._clipboard_file_op = "copy"
        self._clipboard_paths = ()
        self._pending_new_folder_path = ""
        self._combo_auto_search_timer = QTimer(self)
        self._combo_auto_search_timer.setSingleShot(True)
        self._combo_auto_search_timer.timeout.connect(self._trigger_combo_auto_search)
        # 防抖動：多個來源同時排程刷新時合併為單次執行，避免 SearchSortProxyModel 索引損毀
        self._panel_refresh_timer = QTimer(self)
        self._panel_refresh_timer.setSingleShot(True)
        self._panel_refresh_timer.timeout.connect(self._do_scheduled_panel_refresh)
        # 排程刷新時是否需要重跑整個 Everything 查詢。僅「可能新增符合搜尋結果」的
        # 操作（貼上/移動/新增）才需要；刪除/改名/單純瀏覽或外部異動只需輕量的
        # 逐列存在性檢查，避免每次檔案異動都在 GUI 執行緒上同步重查造成卡頓。
        self._pending_full_search = False
        self._right_splitter_sizes_by_orientation = {
            Qt.Orientation.Horizontal: [600, 600],
            Qt.Orientation.Vertical: [600, 600],
        }
        # 監控中間面板目前目錄，任何外部檔案異動皆可即時刷新
        self._mid_fs_watcher = QFileSystemWatcher(self)
        self._mid_fs_watcher.directoryChanged.connect(self._on_mid_dir_changed)
        # 監控本次檔案操作涉及的來源/目標目錄，等異動真正落地後再刷新
        self._op_fs_watcher = QFileSystemWatcher(self)
        self._op_fs_watcher.directoryChanged.connect(self._on_operation_dir_changed)
        self.initUI()
        # 背景開始掃描磁碟建立中繼資料快取（daemon 執行緒，不阻塞 UI）
        self.file_index.start()

    def initUI(self):
        self.setWindowTitle("文件管理器")
        self.setGeometry(100, 100, 800, 600)

        # 创建左侧的目录树视图
        self.treeView = CustomTreeView(self)
        self.treeView.setHeaderHidden(True)

        # 设置左侧目录树的根目录为计算机的顶级目录
        root_path = ""
        self.model = QFileSystemModel()
        self.model.setReadOnly(False)
        self.model.setRootPath(root_path)

        # 只显示目录和磁盘驱动器，不显示目录属性
        self.model.setFilter(QDir.Dirs | QDir.Drives | QDir.NoDotAndDotDot)

        # 以 proxy model 讓磁碟機依字母排序
        self.tree_proxy = DrivesSortProxyModel(self)
        self.tree_proxy.setSourceModel(self.model)
        self.tree_proxy.setSortCaseSensitivity(Qt.CaseInsensitive)
        self.tree_proxy.sort(0, Qt.AscendingOrder)

        self.treeView.setModel(self.tree_proxy)
        root_idx = self.tree_proxy.mapFromSource(self.model.index(root_path))
        self.treeView.setRootIndex(root_idx)
        # 尝试展开根节点并确保可以看到内容
        try:
            if root_idx.isValid():
                self.treeView.expand(root_idx)
                self.treeView.scrollTo(root_idx)
        except Exception:
            pass
        self.treeView.hideColumn(1)
        self.treeView.hideColumn(2)
        self.treeView.hideColumn(3)

        # 保留快捷鍵 action，供 Ctrl +/- 與其他輸入路徑重用
        action_new = QAction("字型放大", self)
        action_new.setShortcuts([
            QKeySequence("Ctrl++"),
            QKeySequence("Ctrl+="),
            QKeySequence("Ctrl+Num++"),
        ])
        action_new.setToolTip("放大字型 (Ctrl +)")
        action_new.triggered.connect(self.on_font_increase)

        action_open = QAction("字型縮小", self)
        action_open.setShortcuts([
            QKeySequence("Ctrl+-"),
            QKeySequence("Ctrl+Num+-"),
        ])
        action_open.setToolTip("縮小字型 (Ctrl -)")
        action_open.triggered.connect(self.on_font_decrease)
        self.addAction(action_new)
        self.addAction(action_open)

        # 嘗試從 resources/icons 載入自訂圖示；若不存在或無法載入 SVG，會 fallback 或動態繪製一個文字圖示
        icons_dir = os.path.join(_bundle_root(), "resources", "icons")
        def make_text_icon(ch, font_size=14, color="#222"):
            size = self._toolbar_icon_size
            pix = QPixmap(size)
            pix.fill(QColor("transparent"))
            p = QPainter(pix)
            p.setPen(QColor(color))
            f = QFont("Arial", font_size)
            f.setBold(True)
            p.setFont(f)
            rect = pix.rect()
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, ch)
            p.end()
            return QIcon(pix)

        def make_bg_text_icon(ch, font_size=14, fg="#222", bg="#fff"):
            size = self._toolbar_icon_size
            pix = QPixmap(size)
            pix.fill(QColor(bg))
            p = QPainter(pix)
            p.setPen(QColor(fg))
            f = QFont("Arial", font_size)
            f.setBold(True)
            p.setFont(f)
            rect = pix.rect()
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, ch)
            p.end()
            return QIcon(pix)

        def load_icon(name, fallback_sp):
            # For A icons prefer generated icons that match current theme (no SVG dependency)
            palette = QApplication.palette()
            fg_col = palette.color(QPalette.Text).name()
            bg_col = palette.color(QPalette.Window).name()
            if name == 'A_large':
                return make_bg_text_icon('A', font_size=16, fg=fg_col, bg=bg_col)
            if name == 'A_small':
                return make_bg_text_icon('a', font_size=12, fg=fg_col, bg=bg_col)

            path = os.path.join(icons_dir, f"{name}.svg")
            style = QApplication.style()

            # Try loading vendor SVG or fallback to system icon
            try:
                if os.path.exists(path):
                    icon = QIcon(path)
                    if not icon.isNull():
                        pm = icon.pixmap(self._toolbar_icon_size)
                        if pm and not pm.isNull():
                            return icon
                    pix = QPixmap(path)
                    if not pix.isNull():
                        pm = pix.scaled(
                            self._toolbar_icon_size,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        return QIcon(pm)
                    if HAVE_SVG_RENDERER and QSvgRenderer is not None:
                        renderer = QSvgRenderer(path)
                        size = self._toolbar_icon_size
                        pixmap = QPixmap(size)
                        pixmap.fill(QColor("transparent"))
                        painter = QPainter(pixmap)
                        renderer.render(painter)
                        painter.end()
                        if not pixmap.isNull():
                            return QIcon(pixmap)
            except Exception:
                pass

            if style is not None:
                return style.standardIcon(fallback_sp)
            return QIcon()

        def make_up_folder_icon():
            size = self._toolbar_icon_size
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

        def make_layout_icon(orientation, active=False):
            size = self._toolbar_icon_size
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

        self._make_layout_icon = make_layout_icon
        up_folder_icon = make_up_folder_icon()
        horizontal_layout_icon = self._make_layout_icon(Qt.Orientation.Horizontal, active=True)
        vertical_layout_icon = self._make_layout_icon(Qt.Orientation.Vertical)

        def make_panel_nav_button(icon, tooltip, handler):
            button = QToolButton(self)
            if isinstance(icon, QIcon):
                button.setIcon(icon)
            else:
                button.setIcon(QApplication.style().standardIcon(icon))
            button.setIconSize(self._toolbar_icon_size)
            button.setToolTip(tooltip)
            button.setAutoRaise(True)
            button.clicked.connect(handler)
            return button

        def build_panel_toolbar(button_specs):
            bar = QWidget(self)
            layout = QHBoxLayout()
            layout.setContentsMargins(2, 2, 2, 2)
            layout.setSpacing(2)
            buttons = []
            for icon, tooltip, handler in button_specs:
                btn = make_panel_nav_button(icon, tooltip, handler)
                layout.addWidget(btn)
                buttons.append(btn)
            bar.setLayout(layout)
            return bar, buttons

        # 使用 QToolButton 並將其明確命名（以便後續啟用/停用）
        # 创建右侧的文件列表视图
        self.listView = FileListView(self)
        self.listView.setSortingEnabled(True)
        self.listView.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.listView.setContextMenuPolicy(Qt.CustomContextMenu)
        self.listView.customContextMenuRequested.connect(self._show_file_context_menu)
        self.listView2 = SearchListView(self)
        self.listView2.setSortingEnabled(True)
        self.listView2.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.listView2.setContextMenuPolicy(Qt.CustomContextMenu)
        self.listView2.customContextMenuRequested.connect(self._show_search_context_menu)

        # 中間面板：加入多重頁籤列
        self.mid_panel_toolbar, self.mid_nav_buttons = build_panel_toolbar([
            (QStyle.StandardPixmap.SP_ArrowBack, "前一頁", self._navigate_back),
            (QStyle.StandardPixmap.SP_ArrowForward, "後一頁", self._navigate_forward),
            (up_folder_icon, "回到上一層目錄", self._navigate_up),
            (QStyle.StandardPixmap.SP_FileDialogNewFolder, "新增資料夾", self._create_folder_in_current_dir),
        ])
        toolbar_layout = self.mid_panel_toolbar.layout()
        layout_gap = max(8, self._toolbar_icon_size.width() // 2)
        toolbar_layout.addSpacing(layout_gap)
        self.layout_horizontal_button = make_panel_nav_button(horizontal_layout_icon, "左右排列", lambda: self._set_right_panel_layout(Qt.Orientation.Horizontal))
        toolbar_layout.addWidget(self.layout_horizontal_button)
        self.layout_vertical_button = make_panel_nav_button(vertical_layout_icon, "上下排列", lambda: self._set_right_panel_layout(Qt.Orientation.Vertical))
        toolbar_layout.addWidget(self.layout_vertical_button)
        toolbar_layout.addSpacing(layout_gap)

        # 下拉式功能表（漢堡選單）：目前提供「選項…」開啟排除設定。
        self.menu_button = QToolButton(self)
        self.menu_button.setIcon(self._make_menu_icon())
        self.menu_button.setIconSize(self._toolbar_icon_size)
        self.menu_button.setToolTip("功能表")
        self.menu_button.setAutoRaise(True)
        self.menu_button.setPopupMode(QToolButton.InstantPopup)
        self.main_menu = QMenu(self.menu_button)
        option_action = self.main_menu.addAction("選項…")
        option_action.triggered.connect(self._open_exclude_dialog)
        self.menu_button.setMenu(self.main_menu)
        toolbar_layout.addWidget(self.menu_button)
        toolbar_layout.addSpacing(layout_gap)

        self.left_drive_combo = TreeComboBox(self)
        self.left_drive_combo.setEditable(True)
        self.left_drive_combo.setInsertPolicy(QComboBox.NoInsert)
        self.left_drive_combo.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.left_drive_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.left_drive_combo.setMinimumWidth(0)
        self.left_drive_combo_view = QTreeView(self.left_drive_combo)
        self.left_drive_combo_view.setHeaderHidden(True)
        self.left_drive_combo_view.setItemsExpandable(True)
        self.left_drive_combo_view.setRootIsDecorated(True)
        self.left_drive_combo_view.setUniformRowHeights(True)
        self.left_drive_combo_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.left_drive_combo_view.setModel(self.tree_proxy)
        self.left_drive_combo_view.hideColumn(1)
        self.left_drive_combo_view.hideColumn(2)
        self.left_drive_combo_view.hideColumn(3)
        self.left_drive_combo.setModel(self.tree_proxy)
        self.left_drive_combo.setModelColumn(0)
        self.left_drive_combo.setView(self.left_drive_combo_view)
        self.left_drive_combo.setRootModelIndex(root_idx)
        self.left_drive_combo_view.viewport().installEventFilter(self)
        self.left_drive_combo.lineEdit().returnPressed.connect(self._on_left_drive_entered)
        toolbar_layout.addWidget(self.left_drive_combo, 1)
        toolbar_layout.setStretch(toolbar_layout.indexOf(self.left_drive_combo), 1)
        self.mid_tab_bar = PathTabBar(self)
        self.mid_info_combo = QComboBox()
        self.mid_info_combo.setEditable(True)
        self.mid_info_combo.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.mid_info_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.mid_container = QWidget()
        mid_vbox = QVBoxLayout()
        mid_vbox.setContentsMargins(0, 0, 0, 0)
        mid_vbox.setSpacing(0)
        mid_vbox.addWidget(self.mid_panel_toolbar)
        mid_vbox.addWidget(self.mid_tab_bar)
        mid_vbox.addWidget(self.mid_info_combo)
        mid_vbox.addWidget(self.listView, 1)
        self.mid_container.setLayout(mid_vbox)

        # 右側面板：加入多重頁籤列並包裝
        self.right_tab_bar = PathTabBar(self)
        self.right_header_spacer = QWidget(self)
        self.right_info_combo = QComboBox()
        self.right_info_combo.setEditable(True)
        self.right_info_combo.setInsertPolicy(QComboBox.NoInsert)
        self.right_info_combo.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.right_info_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 儲存使用者輸入的文字，供 Enter 與自動搜尋共用。
        self._combo_typed_text = ""
        self.right_info_combo.lineEdit().textEdited.connect(self._on_combo_text_edited)
        self.right_info_combo.lineEdit().editingFinished.connect(self._on_combo_editing_finished)
        self.right_info_combo.lineEdit().returnPressed.connect(self._on_combo_return_pressed)
        right_frame = QWidget()
        right_frame_vbox = QVBoxLayout()
        right_frame_vbox.setContentsMargins(0, 0, 0, 0)
        right_frame_vbox.setSpacing(0)
        right_frame_vbox.addWidget(self.right_header_spacer)
        right_frame_vbox.addWidget(self.right_tab_bar)
        right_frame_vbox.addWidget(self.right_info_combo)
        right_frame_vbox.addWidget(self.listView2, 1)
        right_frame.setLayout(right_frame_vbox)

        self.right_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.right_splitter.addWidget(self.mid_container)
        self.right_splitter.addWidget(right_frame)
        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 1)
        self.right_splitter.setSizes([600, 600])
        self._set_right_panel_layout(Qt.Orientation.Horizontal)

        right_container = QWidget()
        right_vbox = QVBoxLayout()
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.addWidget(self.right_splitter)
        right_container.setLayout(right_vbox)

        # 左側面板：加入多重頁籤列並包裝
        self.left_panel_toolbar, self.left_nav_buttons = build_panel_toolbar([
            (QStyle.StandardPixmap.SP_ArrowBack, "前一頁", self._navigate_back),
            (QStyle.StandardPixmap.SP_ArrowForward, "後一頁", self._navigate_forward),
            (up_folder_icon, "回到上一層目錄", self._navigate_up),
            (QStyle.StandardPixmap.SP_FileDialogNewFolder, "新增資料夾", self._create_folder_in_current_dir),
        ])
        self.left_tab_bar = PathTabBar(self)
        self.left_info_combo = QComboBox()
        self.left_info_combo.setEditable(True)
        self.left_info_combo.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.left_info_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.left_frame = QWidget(self)
        left_vbox = QVBoxLayout()
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(0)
        left_vbox.addWidget(self.left_panel_toolbar)
        left_vbox.addWidget(self.left_tab_bar)
        left_vbox.addWidget(self.left_info_combo)
        left_vbox.addWidget(self.treeView, 1)
        self.left_frame.setLayout(left_vbox)
        self.left_frame.hide()

        # 左側面板已從主畫面移除，中央視圖直接使用中/右對稱分割
        self.splitter = None
        self.setCentralWidget(right_container)

        # 初始化狀態列並顯示目前字型大小
        status = self.statusBar()
        if status is not None:
            status.showMessage("")

        # 设置右侧文件列表的模型
        self.fileListModel = QFileSystemModel()
        self.fileListModel.setReadOnly(False)
        self.fileListModel.fileRenamed.connect(self._on_file_list_item_renamed)
        # 以 proxy model 讓資料夾恆排於檔案之上（與搜尋面板一致）。
        self.file_proxy = FileSystemSortProxyModel(self.listView)
        self.file_proxy.setSourceModel(self.fileListModel)
        self.file_proxy.setSortCaseSensitivity(Qt.CaseInsensitive)
        self.listView.setModel(self.file_proxy)
        # 中間檔案面板允許多選（與搜尋面板一致），以便一次拖曳/操作多個檔案。
        self.listView.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.listView.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.search_model = SearchResultsModel(self.listView2)
        self.search_model.setHorizontalHeaderLabels(["檔名", "目錄", "日期", "大小"])
        self.search_model.itemChanged.connect(self._on_search_result_name_changed)
        self.search_proxy = SearchSortProxyModel(self.listView2)
        self.search_proxy.setSourceModel(self.search_model)
        self.listView2.setModel(self.search_proxy)
        self.listView2.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.listView2.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.listView2.setDragEnabled(True)
        self.listView2.setDragDropMode(QAbstractItemView.DragDrop)
        self.listView2.setAcceptDrops(True)
        self.listView2.setDropIndicatorShown(True)
        self.listView2.setDefaultDropAction(Qt.IgnoreAction)

        # 中間面板接受從右側搜尋結果拖曳進來的檔案
        self.listView.setDragEnabled(True)
        self.listView.setDragDropMode(QAbstractItemView.DragDrop)
        self.listView.setAcceptDrops(True)
        self.listView.setDropIndicatorShown(True)

        header = self.listView.header()
        if header is not None:
            header.moveSection(3, 1)
        self.listView.hideColumn(2)

        header2 = self.listView2.header()
        if header2 is not None:
            header2.setStretchLastSection(True)
        # 顯示初始字型資訊
        self.update_status_bar()
        # 根據選取啟用/停用刪除與屬性按鈕
        try:
            self.listView.doubleClicked.connect(self.on_listView_doubleClicked)
            self.listView.clicked.connect(self.on_listView_clicked)  # 添加單擊事件
            self.listView2.doubleClicked.connect(self.on_listView2_doubleClicked)
        except Exception:
            pass
        # 用 eventFilter 追蹤各面板 viewport 事件：滑鼠按下、拖放與 Ctrl+滾輪縮放
        self._listview_mouse_pressed = False
        self.treeView.viewport().installEventFilter(self)
        self.listView.viewport().installEventFilter(self)
        self.listView2.viewport().installEventFilter(self)

        # 设置默认排序为日期排序
        self.listView.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self.listView2.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        # 连接目录树的项选择事件到显示文件列表的函数
        tree_selection = self.treeView.selectionModel()
        if tree_selection is not None:
            tree_selection.selectionChanged.connect(self.on_treeView_selectionChanged)
        # 頁籤列切換訊號
        self.left_tab_bar.tab_switched.connect(self._on_left_tab_switched)
        self.mid_tab_bar.tab_switched.connect(self._on_mid_tab_switched)
        self.right_tab_bar.tab_switched.connect(self._on_right_tab_switched)
        # 下拉清單點擊搜尋
        self.right_info_combo.view().pressed.connect(self._on_right_info_combo_list_pressed)
        self._sync_right_header_spacing()
        self._sync_tab_bar_heights()
        # 載入 config.ini 並還原上次狀態
        self.load_config()
        self._sync_right_header_spacing()
        self._sync_tab_bar_heights()
        self._update_nav_buttons()

    def on_treeView_selectionChanged(self, selected, deselected):
        # 当左侧目录树中的项被选择时，更新右侧文件列表
        if self._ignore_tree_selection:
            return
        if selected.indexes():
            path = self.model.filePath(self.tree_proxy.mapToSource(selected.indexes()[0]))
            self._navigate_to_path(path)

    def on_listView_clicked(self, index):
        """处理中央视窗文件单击事件"""
        # 只有在 listView viewport 上確實發生過滑鼠按下時才觸發搜尋
        if not self._listview_mouse_pressed:
            return
        self._listview_mouse_pressed = False
        global ref_s, ref_e, global_keywords

        if not self.file_proxy.isDir(index):
            file_name = self.file_proxy.fileName(index)
            keywords = self.extract_keywords(file_name)
            global_keywords = keywords

            if keywords:
                ref_s = 0
                ref_e = len(keywords)
                search_command = '|'.join(keywords)
                self.execute_search_command(search_command)


    def on_listView_doubleClicked(self, index):
        path = self.file_proxy.filePath(index)
        if self.file_proxy.isDir(index):
            self._navigate_to_path(path)
        else:
            try:
                os.startfile(path)
            except Exception as e:
                QMessageBox.warning(self, "錯誤", f"無法開啟檔案: {e}")

    def keyPressEvent(self, e):
        global ref_s, ref_e, global_keywords

        if e.modifiers() & Qt.ControlModifier:
            if e.key() == Qt.Key.Key_C:
                if self._copy_selected_paths_from_focused_view():
                    e.accept()
                    return
            if e.key() == Qt.Key.Key_X:
                if self._cut_selected_paths_from_focused_view():
                    e.accept()
                    return
            if e.key() == Qt.Key.Key_V:
                if self._paste_into_current_dir_from_clipboard():
                    e.accept()
                    return
            if e.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                self.on_font_increase()
                e.accept()
                return
            if e.key() in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
                self.on_font_decrease()
                e.accept()
                return

        if e.key() == Qt.Key.Key_Backspace:
            if self._focused_shortcut_view() is not None:
                self._navigate_up()
                e.accept()
                return

        # Delete 鍵：刪除右側搜尋結果中選取的檔案
        if e.key() == Qt.Key.Key_Delete:
            if self._delete_selected_focused_items():
                e.accept()
                return

        if e.key() == Qt.Key.Key_F2:
            if self._rename_selected_focused_item():
                return

        # F5 刷新：搜尋面板有焦點 → 重新查詢；檔案面板/目錄樹有焦點 → 重整檔案列表；
        # 無明確焦點 → 兩者都刷新，確保 F5 永遠有作用。
        if e.key() == Qt.Key.Key_F5:
            view = self._focused_file_view()
            if view is self.listView2:
                self.refresh_current_search_results()
            elif view in (self.listView, self.treeView):
                self.refresh_mid_panel(force=True)
            else:
                self.refresh_mid_panel(force=True)
                self.refresh_current_search_results()
            e.accept()
            return

        # F3/F4 縮減搜尋關鍵字範圍，其他鍵不觸發檔案式搜尋
        if e.key() == Qt.Key.Key_F3 and ref_e - ref_s > 0:
            ref_s = ref_s + 1
            if ref_e - ref_s > 0:
                self.execute_search_command('|'.join(global_keywords[ref_s:ref_e]))
        elif e.key() == Qt.Key.Key_F4 and ref_e - ref_s > 0:
            ref_e = ref_e - 1
            if ref_e - ref_s > 0:
                self.execute_search_command('|'.join(global_keywords[ref_s:ref_e]))

    # 半形與全形/CJK 括弧（點擊檔名以括弧內文字自動搜尋時辨識）。
    # 全形括弧（（）［］｛｝）、CJK 角括弧（【】〔〕「」『』〈〉《》）在檔名中
    # 與半形括弧同樣常用來標註，原本只認半形 ([{ )]}，導致全形括弧內的文字
    # （如「【tsf-saeki】」）點擊時無法被擷取為搜尋關鍵字。
    _OPEN_BRACKETS = "([{（［｛【〔「『〈《〖｟"
    _CLOSE_BRACKETS = ")]}）］｝】〕」』〉》〗｠"

    def extract_keywords(self, file_name):
        # 自定义解析文件名以提取多个参数，只提取括号内的文字
        keywords = []
        stack = []
        is_inside_brackets = False

        for char in file_name:
            if char in self._OPEN_BRACKETS:
                if not is_inside_brackets:
                    is_inside_brackets = True
                elif stack:
                    keywords.append("".join(stack))
                    stack = []
            elif char in self._CLOSE_BRACKETS:
                is_inside_brackets = False
                if stack:
                    keywords.append("".join(stack))
                stack = []
            elif is_inside_brackets:
                stack.append(char)

        keywords = [keyword.strip() for keyword in keywords if keyword.strip()]
        return keywords

    def _make_menu_icon(self):
        """畫一個漢堡選單（三條橫線）圖示給下拉式功能表按鈕使用。"""
        size = self._toolbar_icon_size
        pix = QPixmap(size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = size.width(), size.height()
        pen = QPen(self.palette().color(QPalette.WindowText), max(2, h // 16),
                   Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        margin = w // 4
        for frac in (0.34, 0.5, 0.66):
            y = int(h * frac)
            p.drawLine(margin, y, w - margin, y)
        p.end()
        return QIcon(pix)

    def _open_exclude_dialog(self):
        dialog = ExcludeSettingsDialog(self._exclude_enabled, self._exclude_dirs, self)
        if dialog.exec_() == QDialog.Accepted:
            enabled, dirs = dialog.result_values()
            self._exclude_enabled = enabled
            self._exclude_dirs = dirs
            self._apply_exclude_settings()
            self.save_config()

    def _apply_exclude_settings(self):
        """依目前排除設定更新比對用路徑，並重整檔案面板與搜尋結果。"""
        if self._exclude_enabled:
            self._exclude_norm = tuple(
                os.path.normcase(os.path.normpath(d)) for d in self._exclude_dirs if d
            )
        else:
            self._exclude_norm = ()
        if self.file_proxy is not None:
            self.file_proxy.set_excluded_dirs(self._exclude_norm)
        self.refresh_current_search_results()

    def _is_path_excluded(self, path):
        if not self._exclude_norm:
            return False
        norm = os.path.normcase(os.path.normpath(path))
        for ex in self._exclude_norm:
            if norm == ex:
                return True
            # 磁碟根目錄（如 C:\）normpath 後已帶尾端分隔符，避免補成雙分隔符。
            base = ex if ex.endswith(os.sep) else ex + os.sep
            if norm.startswith(base):
                return True
        return False

    def _on_left_tab_switched(self, path):
        """切換左側頁籤：導航目錄樹至儲存的路徑。"""
        self._navigate_to_path(path)

    def _on_mid_tab_switched(self, path):
        """切換中間頁籤：更新檔案列表至儲存的路徑，並同步左側目錄樹。"""
        self._navigate_to_path(path)

    def _on_left_drive_tree_activated(self, proxy_index):
        if not proxy_index.isValid():
            return
        path = self.model.filePath(self.tree_proxy.mapToSource(proxy_index)).strip()
        if path and os.path.isdir(path):
            self.left_drive_combo.hidePopup()
            self._navigate_to_path(path)

    def _on_left_drive_entered(self):
        path = self.left_drive_combo.currentText().strip() if self.left_drive_combo is not None else ""
        if path and os.path.isdir(path):
            self._navigate_to_path(path)
        else:
            self._sync_left_drive_combo(self._current_dir())

    def _on_combo_text_edited(self, text):
        """使用者輸入或貼上時更新關鍵字，停頓後自動搜尋。"""
        self._combo_typed_text = text
        self._combo_auto_search_timer.start(350)

    def _trigger_combo_auto_search(self):
        text = self._combo_typed_text.strip()
        if text:
            self.execute_search_command(text)

    def _on_combo_editing_finished(self):
        if self._combo_auto_search_timer.isActive():
            self._combo_auto_search_timer.stop()
            self._trigger_combo_auto_search()

    def _on_combo_return_pressed(self):
        """lineEdit returnPressed 信號。取得 textEdited 儲存的文字，
        用 singleShot 延遲從而讓 Qt 內部 _q_returnPressed 先執行完畢，
        再套用自定義搜尋。"""
        if self._combo_auto_search_timer.isActive():
            self._combo_auto_search_timer.stop()
        text = self._combo_typed_text.strip()
        if text:
            QTimer.singleShot(0, lambda t=text: self.execute_search_command(t))

    def eventFilter(self, obj, event):
        """追蹤 listView viewport 事件：滑鼠按下 + 拖放。"""
        if event.type() == QEvent.Wheel and obj in (self.treeView.viewport(), self.listView.viewport(), self.listView2.viewport()):
            if event.modifiers() & Qt.ControlModifier:
                delta_y = event.angleDelta().y()
                if delta_y < 0:
                    self.on_font_increase()
                    event.accept()
                    return True
                if delta_y > 0:
                    self.on_font_decrease()
                    event.accept()
                    return True

        if obj is getattr(self, 'left_drive_combo_view', None).viewport():
            if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
                proxy_index = self.left_drive_combo_view.indexAt(event.pos())
                if not proxy_index.isValid():
                    return False
                item_rect = self.left_drive_combo_view.visualRect(proxy_index)
                if event.pos().x() < item_rect.left():
                    self.left_drive_combo.keep_popup_open_once()
                    return False
                if event.type() == QEvent.MouseButtonRelease:
                    self._on_left_drive_tree_activated(proxy_index)
                    event.accept()
                    return True
            return False

        if obj is self.listView.viewport():
            et = event.type()
            if et == QEvent.MouseButtonPress:
                self._listview_mouse_pressed = True
                return False  # 不消費，讓事件繼續傳遞
            if et == QEvent.DragEnter:
                if event.mimeData().hasUrls():
                    # 右鍵拖曳：先接受讓 session 保持活躍，游標圖示由 DragMove 更新
                    event.accept()
                else:
                    event.ignore()
                return True
            if et == QEvent.DragMove:
                if event.mimeData().hasUrls():
                    event.accept()
                else:
                    event.ignore()
                return True
            if et == QEvent.Drop:
                target_dir = self._resolve_listview_drop_target(event.pos())
                src_paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
                if target_dir and src_paths:
                    if self._search_drag_button == Qt.RightButton:
                        # 右鍵拖曳：先完成 Shell 操作，再排程刷新，避免在 Shell 選單期間觸發模型重設
                        done = self._shell_right_drag_drop_to(src_paths, target_dir, event.pos())
                        if done:
                            self.track_file_operation(src_paths, target_dir)
                            event.setDropAction(Qt.CopyAction)
                            event.accept()
                            self._schedule_panel_refreshes((600, 1500), full_search=True)
                        else:
                            event.ignore()
                    else:
                        self.track_file_operation(src_paths, target_dir)
                        mods = event.keyboardModifiers()
                        if mods & Qt.ControlModifier:
                            op = "copy"
                        elif mods & Qt.ShiftModifier:
                            op = "move"
                        else:
                            s_drv = os.path.splitdrive(os.path.abspath(src_paths[0]))[0].lower()
                            d_drv = os.path.splitdrive(os.path.abspath(target_dir))[0].lower()
                            op = "move" if s_drv and s_drv == d_drv else "copy"
                        self._perform_file_op(src_paths, target_dir, op)
                        event.acceptProposedAction()
                        self._schedule_panel_refreshes((600, 1500), full_search=True)
                else:
                    event.ignore()
                return True
        return super().eventFilter(obj, event)

    def _on_right_tab_switched(self, keyword):
        """切換右側頁籤：側边發表 combobox 顯示並復原搜尋結果。
        不更新 tab 資料或 MRU 歷史，只復原查詢。"""
        self.right_info_combo.blockSignals(True)
        self.right_info_combo.lineEdit().setText(keyword)
        self.right_info_combo.blockSignals(False)
        if keyword:
            self._do_search(keyword)
        elif self.search_model:
            self.search_model.removeRows(0, self.search_model.rowCount())

    def _on_right_info_combo_list_pressed(self, model_index):
        """從下拉清單點擊選取項目時執行搜尋。"""
        text = self.right_info_combo.model().data(model_index)
        if text:
            self.execute_search_command(text)

    def execute_search_command(self, search_command):
        """使用者主動搜尋：更新頁籤資料、combobox MRU 歷史，並執行查詢。"""
        # 1. 儲存到目前頁籤
        self.right_tab_bar.set_current_data(search_command, search_command)
        # 2. 更新 combobox MRU 歷史（移除舊同名項目，插入至頂端）
        self.right_info_combo.blockSignals(True)
        for i in range(self.right_info_combo.count() - 1, -1, -1):
            if self.right_info_combo.itemText(i) == search_command:
                self.right_info_combo.removeItem(i)
        self.right_info_combo.insertItem(0, search_command)
        self.right_info_combo.setCurrentIndex(0)
        self.right_info_combo.blockSignals(False)
        self.right_info_combo.lineEdit().setText(search_command)
        # 3. 執行實際查詢
        self._do_search(search_command)

    def _normalize_search_command(self, search_command):
        """將以 | 分隔的關鍵詞個別正規化，避免含空白詞組被 Everything 拆散。"""
        normalized_terms = []
        for raw_term in search_command.split('|'):
            term = raw_term.strip()
            if not term:
                continue
            if any(ch.isspace() for ch in term) and not (term.startswith('"') and term.endswith('"')):
                term = f'"{term}"'
            normalized_terms.append(term)
        return '|'.join(normalized_terms)

    def _split_search_terms(self, search_command):
        return [term.strip() for term in search_command.split('|') if term.strip()]

    def _strip_search_term_quotes(self, term):
        candidate = term.strip()
        if candidate.startswith('"') and candidate.endswith('"') and len(candidate) >= 2:
            return candidate[1:-1]
        return candidate

    def _normalize_plain_keyword_text(self, text):
        normalized = unicodedata.normalize('NFKC', text or '').casefold()
        # 連字號（-）與點（.）不視為分隔符：像「A-10」「ver.2」「a.b.c」這類關鍵字
        # 需整體保留，不可被拆開。NFKC 已把全形 －／．正規化為半形 -／.。
        collapsed = re.sub(r'[^\w.-]+', ' ', normalized, flags=re.UNICODE)
        return ' '.join(collapsed.split())

    def _plain_keyword_tokens(self, term):
        normalized = self._normalize_plain_keyword_text(self._strip_search_term_quotes(term))
        # 過濾只剩連字號／點的孤立 token（如「tsf - saeki」中間的 -），避免污染查詢。
        return [token for token in normalized.split(' ') if token.strip('.-')]

    def _build_plain_keyword_queries(self, term):
        raw_term = self._strip_search_term_quotes(term)
        queries = []
        seen = set()

        def add_query(query_text, normalize=True):
            query_text = query_text.strip()
            if not query_text or query_text in seen:
                return
            seen.add(query_text)
            # normalize=False：保留原樣送出（用於空白分隔的 AND 查詢，
            # 不可被 _normalize_search_command 加引號變成片語比對）。
            queries.append(self._normalize_search_command(query_text) if normalize else query_text)

        add_query(raw_term)
        add_query(f'[{raw_term}]')

        # 全形括弧等符號（（）【】「」『』〔〕…）與連字號在檔名/關鍵字中通常只是
        # 標註或分隔，使用者真正想搜的是「符號之間的文字」。但原本只把含符號的原字串
        # 交給 Everything，實際檔名不含那些符號時就查無結果（如搜「（重要）」找不到
        # 「重要.txt」、搜「【tsf-saeki】」找不到「tsf-saeki」）。這裡改以去符號後的
        # tokens（NFKC 正規化＋去標點，已涵蓋全形/半形括弧與連字號）組查詢：
        #   單一詞 → 直接查該詞；
        #   多個詞 → 以空白分隔（Everything 原生 AND，不加引號、不需開 regex 旗標、
        #            也不要求詞序）查詢，最穩健；另保留 regex 依序串接作為輔助。
        tokens = self._plain_keyword_tokens(term)
        if len(tokens) == 1:
            add_query(tokens[0])
        elif len(tokens) >= 2:
            add_query(' '.join(tokens), normalize=False)
            add_query('regex:' + '.*'.join(re.escape(token) for token in tokens))

        return queries

    def _path_matches_plain_keyword(self, path, term):
        tokens = self._plain_keyword_tokens(term)
        if not tokens:
            return False

        normalized_path = self._normalize_plain_keyword_text(os.path.basename(path))
        # 以「去符號後的各詞是否都出現在檔名」為準，與查詢端一致：括弧會被正規化成
        # 空白，若仍要求整個 normalized_term 為連續子字串，會因括弧造成的空白差異
        # （如關鍵字「重要（報告）」對檔名「重要報告」）而誤判不符。改為各詞皆需命中。
        return all(token in normalized_path for token in tokens)

    def _is_plain_keyword_term(self, term):
        candidate = self._strip_search_term_quotes(term)
        if not candidate:
            return False
        return not any(token in candidate for token in (':', '<', '>', '!', '*', '?'))

    def _search_plain_keyword_terms(self, terms):
        results = []
        seen = set()
        for term in terms:
            for query_text in self._build_plain_keyword_queries(term):
                max_results = 2000 if query_text.startswith('regex:') or query_text == self._strip_search_term_quotes(term) else 800
                for path in self.everything.query(query_text, max_results=max_results):
                    if path in seen or not self._path_matches_plain_keyword(path, term):
                        continue
                    seen.add(path)
                    results.append(path)
        return results

    def _do_search(self, search_command):
        """只執行 Everything 查詢並更新展示，不修改頁籤資料或 combobox 歷史。復原搜尋用。"""
        terms = self._split_search_terms(search_command)
        normalized_command = self._normalize_search_command(search_command)
        if self.everything.is_available():
            if terms and all(self._is_plain_keyword_term(term) for term in terms):
                results = self._search_plain_keyword_terms(terms)
            else:
                results = self.everything.query(normalized_command)
            self.update_search_results(results)
            return

        if not self.sdk_warned:
            self.sdk_warned = True
            status = self.statusBar()
            if status is not None:
                status.showMessage("Everything SDK DLL not found. Place Everything64.dll next to main.py or in a sdk folder.")
            QMessageBox.information(
                self,
                "Everything SDK",
                "Everything SDK DLL not found.\n\nDownload Everything-SDK.zip and place Everything64.dll (or Everything32.dll) next to main.py or in a 'sdk' folder.",
            )
        subprocess.Popen('"Everything.exe" -search "' + normalized_command.replace('"', '\\"') + '"', shell=True)

    def _search_result_metadata(self, filepath):
        """回傳 (is_dir, size, mtime)。優先讀開啟時預載的磁碟快取，
        未命中（新檔案或尚未掃到）才 fallback 到 os.stat。"""
        cached = self.file_index.lookup(filepath)
        if cached is not None:
            return cached
        try:
            stat_result = os.stat(filepath)
            return os.path.isdir(filepath), stat_result.st_size, stat_result.st_mtime
        except OSError:
            return False, 0, 0

    def update_search_results(self, results):
        if self.search_model is None:
            return
        # 排除設定啟用時，濾掉落在被排除目錄（及其子路徑）下的結果。
        if self._exclude_norm:
            results = [p for p in results if not self._is_path_excluded(p)]
        self._search_model_updating = True
        rows = []
        for filepath in results:
            is_dir, size, mtime = self._search_result_metadata(filepath)

            name_item = QStandardItem(os.path.basename(filepath))
            name_item.setData(filepath, Qt.UserRole + 1)
            # 是否為資料夾旗標：供 SearchSortProxyModel 讓資料夾恆排於檔案之上
            name_item.setData(is_dir, SearchResultsModel.IS_DIR_ROLE)
            name_item.setIcon(self._icon_for_search_result(filepath, is_dir))

            dir_item = QStandardItem(os.path.dirname(filepath))
            dir_item.setEditable(False)

            if mtime:
                try:
                    dt_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    dt_str = ''
            else:
                dt_str = ''

            date_item = QStandardItem(dt_str)
            date_item.setEditable(False)
            date_item.setData(mtime, Qt.UserRole)

            size_str = '' if (is_dir or not size) else self._format_size(size)

            size_item = QStandardItem(size_str)
            size_item.setEditable(False)
            size_item.setData(size, Qt.UserRole)

            rows.append([name_item, dir_item, date_item, size_item])

        # 不可用 blockSignals 包住結構性變更：SearchSortProxyModel 靠 rowsRemoved/
        # rowsInserted 訊號維護「proxy 列 ↔ 來源列」對應表，擋掉訊號會讓對應表指向
        # 已刪除的 item，之後點擊搜尋結果映射時即解參考已釋放記憶體而崩潰。
        # itemChanged 連線的 _on_search_result_name_changed 已用 _search_model_updating
        # 旗標擋掉，無須再 blockSignals。
        #
        # 效能關鍵：search_proxy 預設 dynamicSortFilter=True，且 listView2 已啟用排序，
        # 因此每次 appendRow 都會觸發 proxy 重新尋找排序插入位置（O(n) 比較），
        # 大量結果（可達 2000 筆）逐筆插入即退化成 O(n²)，造成新增/刪除/改名後 GUI
        # 凍結 2~3 秒。改為批次插入前關閉動態排序，全部插入後再開啟、僅排序一次。
        # 關閉的是「排序」而非訊號，rowsInserted 仍正常發出，對應表不會失效。
        self.search_proxy.setDynamicSortFilter(False)
        self.search_model.removeRows(0, self.search_model.rowCount())
        for row in rows:
            self.search_model.appendRow(row)
        self.search_proxy.setDynamicSortFilter(True)
        self._search_model_updating = False

    def _icon_for_search_result(self, filepath, is_dir=None):
        if is_dir is None:
            is_dir = os.path.isdir(filepath)
        if is_dir:
            cache_key = ('dir', '')
        else:
            cache_key = ('file', os.path.splitext(filepath)[1].lower())

        icon = self._search_icon_cache.get(cache_key)
        if icon is None:
            icon = self._search_icon_provider.icon(QFileInfo(filepath))
            self._search_icon_cache[cache_key] = icon
        return icon

    def _format_size(self, size):
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"

    def on_listView2_doubleClicked(self, index):
        source_index = self.search_proxy.mapToSource(index)
        name_index = self.search_model.index(source_index.row(), 0)
        filepath = name_index.data(Qt.UserRole + 1)
        if filepath and os.path.exists(filepath):
            if os.path.isdir(filepath):
                tree_index = self.tree_proxy.mapFromSource(self.model.index(filepath))
                if tree_index.isValid():
                    self.treeView.setCurrentIndex(tree_index)
                    self.treeView.expand(tree_index)
                    self.treeView.scrollTo(tree_index)
            else:
                try:
                    os.startfile(filepath)
                except Exception as e:
                    QMessageBox.warning(self, "錯誤", f"無法開啟檔案: {e}")

    def _get_selected_search_paths(self):
        """回傳 listView2 中所有選取列的完整路徑。"""
        rows_seen = set()
        paths = []
        for proxy_index in self.listView2.selectedIndexes():
            if proxy_index.column() != 0:
                continue
            source_index = self.search_proxy.mapToSource(proxy_index)
            row = source_index.row()
            if row in rows_seen:
                continue
            rows_seen.add(row)
            item = self.search_model.item(row, 0)
            if item is not None:
                filepath = item.data(Qt.UserRole + 1)
                if filepath:
                    paths.append(filepath)
        return paths

    def _focused_file_view(self):
        fw = QApplication.focusWidget()
        for view in (self.treeView, self.listView, self.listView2):
            if fw is view or fw is view.viewport():
                return view
        return None

    def _focused_shortcut_view(self):
        view = self._focused_file_view()
        return view if view in (self.listView, self.listView2) else None

    def _normalize_clipboard_paths(self, paths):
        return tuple(os.path.normcase(os.path.normpath(path)) for path in paths if path)

    def _get_selected_paths_for_view(self, view):
        if view is self.listView2:
            return self._get_selected_search_paths()

        selection_model = view.selectionModel() if view is not None else None
        if selection_model is None:
            return []

        paths = []
        rows_seen = set()
        for index in selection_model.selectedRows(0):
            key = (index.row(), index.parent().internalId() if index.parent().isValid() else -1)
            if key in rows_seen:
                continue
            rows_seen.add(key)
            if view is self.treeView:
                path = self.model.filePath(self.tree_proxy.mapToSource(index))
            elif view is self.listView:
                path = self.file_proxy.filePath(index)
            else:
                path = ""
            if path:
                paths.append(path)
        return paths

    def _delete_paths_to_recycle_bin(self, paths):
        existing = [p for p in paths if os.path.exists(p)]
        if not existing:
            return False

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wt.HWND),
                ("wFunc", wt.UINT),
                ("pFrom", ctypes.c_wchar_p),
                ("pTo", ctypes.c_wchar_p),
                ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", wt.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", ctypes.c_wchar_p),
            ]

        FO_DELETE = 0x0003
        FOF_ALLOWUNDO = 0x0040
        FOF_WANTNUKEWARNING = 0x4000

        path_buf = ctypes.create_unicode_buffer('\0'.join(existing) + '\0')
        op = SHFILEOPSTRUCTW()
        op.hwnd = int(self.winId())
        op.wFunc = FO_DELETE
        op.pFrom = ctypes.cast(path_buf, ctypes.c_wchar_p)
        op.pTo = None
        op.fFlags = FOF_ALLOWUNDO | FOF_WANTNUKEWARNING

        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if result == 0 and not op.fAnyOperationsAborted:
            self.refresh_mid_panel()
            # 刪除只會「移除」搜尋結果，不可能新增符合項，故一律走輕量的逐列存在性
            # 檢查，避免重跑整個 Everything 查詢並重建模型而造成 GUI 凍結。
            self._refresh_search_results_existence()
            return True
        return False

    def _delete_selected_focused_items(self):
        view = self._focused_file_view()
        if view is None:
            return False
        if view is self.listView2:
            return self._delete_selected_search_files()
        paths = self._get_selected_paths_for_view(view)
        return self._delete_paths_to_recycle_bin(paths)

    def _set_clipboard_file_paths(self, paths, op):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths if path])
        if not mime.urls():
            return False

        QApplication.clipboard().setMimeData(mime)
        self._clipboard_file_op = op
        self._clipboard_paths = self._normalize_clipboard_paths(paths)
        return True

    def _copy_selected_paths_from_focused_view(self):
        view = self._focused_shortcut_view()
        if view is None:
            return False

        paths = self._get_selected_paths_for_view(view)
        if not paths:
            return False

        return self._set_clipboard_file_paths(paths, "copy")

    def _cut_selected_paths_from_focused_view(self):
        view = self._focused_shortcut_view()
        if view is None:
            return False

        paths = self._get_selected_paths_for_view(view)
        if not paths:
            return False

        return self._set_clipboard_file_paths(paths, "move")

    def _paste_into_current_dir_from_clipboard(self):
        view = self._focused_shortcut_view()
        if view is None:
            return False

        target_dir = self._current_dir()
        if not target_dir or not os.path.isdir(target_dir):
            return False

        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData() if clipboard is not None else None
        if mime is None or not mime.hasUrls():
            return False

        src_paths = []
        seen = set()
        for url in mime.urls():
            local_path = url.toLocalFile()
            if not local_path or local_path in seen:
                continue
            seen.add(local_path)
            src_paths.append(local_path)
        if not src_paths:
            return False

        clipboard_paths = self._normalize_clipboard_paths(src_paths)
        op = "move" if (self._clipboard_file_op == "move" and clipboard_paths == self._clipboard_paths) else "copy"
        self.track_file_operation(src_paths, target_dir)
        self._perform_file_op(src_paths, target_dir, op)
        return True

    def _rename_selected_focused_item(self):
        view = self._focused_file_view()
        if view is None:
            return False

        if view in (self.treeView, self.listView, self.listView2):
            selection_model = view.selectionModel()
            if selection_model is None:
                return False
            selected = selection_model.selectedRows(0)
            if len(selected) != 1:
                return False
            edit_index = selected[0]
            if view is self.listView2:
                edit_index = self.search_proxy.mapToSource(edit_index)
                edit_index = self.search_proxy.mapFromSource(edit_index)
            view.setCurrentIndex(edit_index)
            view.edit(edit_index)
            return True
        return False

    def _on_search_result_name_changed(self, item):
        if self._search_model_updating or self._search_item_rename_in_progress:
            return
        if item is None or item.column() != 0:
            return

        old_path = item.data(Qt.UserRole + 1)
        if not old_path or not os.path.exists(old_path):
            return

        old_name = os.path.basename(old_path)
        new_name = item.text().strip()
        if not new_name or new_name == old_name:
            self._search_item_rename_in_progress = True
            item.setText(old_name)
            self._search_item_rename_in_progress = False
            return
        if any(ch in new_name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "重新命名失敗", "檔名包含無效字元。")
            self._search_item_rename_in_progress = True
            item.setText(old_name)
            self._search_item_rename_in_progress = False
            return

        new_path = os.path.join(os.path.dirname(old_path), new_name)
        # Windows 上 os.path.exists 不分大小寫：把「同一檔案僅改大小寫」（如
        # Report.txt → report.txt）誤判為目標已存在而報錯。改名為自己（含純大小寫
        # 變更）不算衝突，交給 os.rename 處理；只有指向「不同」檔案時才視為已存在。
        same_file = (os.path.normcase(os.path.normpath(new_path)) ==
                     os.path.normcase(os.path.normpath(old_path)))
        if not same_file and os.path.exists(new_path):
            QMessageBox.warning(self, "重新命名失敗", "目標名稱已存在。")
            self._search_item_rename_in_progress = True
            item.setText(old_name)
            self._search_item_rename_in_progress = False
            return

        try:
            os.rename(old_path, new_path)
        except Exception as ex:
            QMessageBox.warning(self, "重新命名失敗", f"無法重新命名: {ex}")
            self._search_item_rename_in_progress = True
            item.setText(old_name)
            self._search_item_rename_in_progress = False
            return

        self._search_item_rename_in_progress = True
        item.setData(new_path, Qt.UserRole + 1)
        item.setText(os.path.basename(new_path))
        self._search_item_rename_in_progress = False
        # 該列已就地更新為新名稱／新路徑，無須重跑整個 Everything 查詢並重建模型
        # （那會造成 GUI 凍結）。只需刷新中間面板反映檔案系統異動即可。
        self.refresh_mid_panel()

    def _show_search_context_menu(self, pos):
        """在 listView2 上顯示 Windows 檔案總管相同的右鍵選單。"""
        paths = self._get_selected_search_paths()
        if not paths:
            return
        global_pos = self.listView2.viewport().mapToGlobal(pos)
        try:
            self._invoke_shell_context_menu(int(self.winId()), paths, global_pos.x(), global_pos.y())
        except Exception:
            traceback.print_exc()
            menu = QMenu(self)
            if len(paths) == 1 and os.path.exists(paths[0]):
                menu.addAction("開啟", lambda p=paths[0]: os.startfile(p))
            menu.addAction("刪除（移至資源回收桶）", self._delete_selected_search_files)
            menu.exec_(global_pos)

    def _show_file_context_menu(self, pos):
        """在 listView 上顯示 Windows 檔案總管相同的右鍵選單。"""
        paths = self._get_selected_paths_for_view(self.listView)
        if not paths:
            return
        global_pos = self.listView.viewport().mapToGlobal(pos)
        try:
            self._invoke_shell_context_menu(int(self.winId()), paths, global_pos.x(), global_pos.y())
        except Exception:
            traceback.print_exc()
            menu = QMenu(self)
            if len(paths) == 1 and os.path.exists(paths[0]):
                menu.addAction("開啟", lambda p=paths[0]: os.startfile(p))
            menu.exec_(global_pos)

    def _invoke_shell_context_menu(self, hwnd, paths, x, y, after_fn=None):
        """Show the Windows Shell context menu (identical to Explorer right-click)."""
        from win32com.shell import shell, shellcon
        import win32gui
        import win32con
        import pythoncom

        pythoncom.CoInitialize()
        do_rename = False
        try:
            # 依第一個路徑的父目錄分組（GetUIObjectOf 要求相同父目錄）
            parent_dir = os.path.normpath(os.path.dirname(os.path.abspath(paths[0])))
            norm_parent = os.path.normcase(parent_dir)
            same_parent = [
                p for p in paths
                if os.path.normcase(
                    os.path.normpath(os.path.dirname(os.path.abspath(p)))
                ) == norm_parent
            ]

            # 取得桌面 IShellFolder
            desktop = shell.SHGetDesktopFolder()

            # SHParseDisplayName 在此 pywin32 版本只接受 2 個參數: (name, sfgaoMask)
            parent_pidl = shell.SHParseDisplayName(parent_dir, 0)[0]

            # BindToObject: pbc 用 None 代表 NULL
            parent_sf = desktop.BindToObject(parent_pidl, None, shell.IID_IShellFolder)

            # 取得每個檔案相對於父目錄的子 PIDL
            # ParseDisplayName 回傳 (eaten, pidl, attrs)，取 index 1 為 PIDL
            child_pidls = []
            for p in same_parent:
                result = parent_sf.ParseDisplayName(hwnd, None, os.path.basename(p))
                child_pidls.append(result[1])

            # GetUIObjectOf 回傳 (reserved, IContextMenu)，取 index 1 為實際介面
            icm = parent_sf.GetUIObjectOf(
                hwnd, child_pidls, shell.IID_IContextMenu, 0
            )[1]

            # 建立彈出選單並填入 Shell 命令
            hmenu = win32gui.CreatePopupMenu()
            icm.QueryContextMenu(
                hmenu, 0, 1, 0x7FFF,
                shellcon.CMF_EXPLORE | shellcon.CMF_CANRENAME
            )

            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass

            cmd = win32gui.TrackPopupMenu(
                hmenu,
                win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON | win32con.TPM_RETURNCMD,
                x, y, 0, hwnd, None
            )
            win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
            win32gui.DestroyMenu(hmenu)

            if cmd > 0:
                # 偵測 rename verb：Shell InvokeCommand("rename") 會傳送 WM_CLOSE 給 hwnd，
                # 導致 Qt 主視窗關閉。改為觸發我們自己的 F2 重命名。
                try:
                    verb = icm.GetCommandString(cmd - 1, shellcon.GCS_VERBW)
                except Exception:
                    verb = ""
                if verb.lower() == "rename":
                    do_rename = True
                else:
                    ci = (0, hwnd, cmd - 1, None, None, win32con.SW_SHOWNORMAL, 0, None)
                    icm.InvokeCommand(ci)
                    QTimer.singleShot(800, after_fn if after_fn is not None else self._refresh_search_results_existence)
        finally:
            pythoncom.CoUninitialize()
        if do_rename:
            QTimer.singleShot(0, self._rename_selected_focused_item)

    def _refresh_search_results_existence(self):
        """移除搜尋結果中已不存在的檔案列。"""
        rows_to_remove = []
        for row in range(self.search_model.rowCount()):
            item = self.search_model.item(row, 0)
            if item is None:
                continue
            filepath = item.data(Qt.UserRole + 1)
            if filepath and not os.path.exists(filepath):
                rows_to_remove.append(row)
        for row in reversed(rows_to_remove):
            self.search_model.removeRow(row)

    def _resolve_listview_drop_target(self, pos):
        """依 viewport 座標決定中間面板的拖放目標目錄。"""
        idx = self.listView.indexAt(pos)
        if idx.isValid():
            path = self.file_proxy.filePath(idx)
            path = os.path.normpath(path) if path else ""
            if path and os.path.isdir(path):
                return path
            if path:
                parent = os.path.dirname(path)
                if os.path.isdir(parent):
                    return parent
        root_idx = self.listView.rootIndex()
        if root_idx.isValid():
            path = self.file_proxy.filePath(root_idx)
            path = os.path.normpath(path) if path else ""
            if path and os.path.isdir(path):
                return path
        return ""

    def _shell_right_drag_drop_to(self, src_paths, target_dir, viewport_pos):
        """從中間面板 viewport 座標呼叫 Shell IDropTarget::Drop(MK_RBUTTON)。
        顯示原生右鍵拖曳選單，失敗時 fallback 到自訂 Qt 選單。
        回傳 True 表示已完成（含使用者選擇後執行），False 表示取消。"""
        try:
            from win32com.shell import shell
            import pythoncom

            pythoncom.CoInitialize()
            try:
                hwnd = int(self.winId())
                desktop = shell.SHGetDesktopFolder()

                # --- 建立來源 IDataObject ---
                src_parent = os.path.normpath(os.path.dirname(os.path.abspath(src_paths[0])))
                src_parent_pidl = shell.SHParseDisplayName(src_parent, 0)[0]
                src_sf = desktop.BindToObject(src_parent_pidl, None, shell.IID_IShellFolder)
                child_pidls = []
                for p in src_paths:
                    r = src_sf.ParseDisplayName(hwnd, None, os.path.basename(p))
                    child_pidls.append(r[1])
                data_obj = src_sf.GetUIObjectOf(
                    hwnd, child_pidls, pythoncom.IID_IDataObject, 0
                )[1]

                # --- 取得目標資料夾的 IDropTarget ---
                tdir = os.path.normpath(target_dir)
                tparent = os.path.dirname(tdir)
                tname = os.path.basename(tdir)
                tparent_pidl = shell.SHParseDisplayName(tparent, 0)[0]
                tparent_sf = desktop.BindToObject(tparent_pidl, None, shell.IID_IShellFolder)
                tdir_pidl = tparent_sf.ParseDisplayName(hwnd, None, tname)[1]
                drop_target = tparent_sf.GetUIObjectOf(
                    hwnd, [tdir_pidl], pythoncom.IID_IDropTarget, 0
                )[1]

                # --- 模擬右鍵拖放 ---
                MK_RBUTTON = 2
                DROPEFFECT_NONE = 0
                DROPEFFECT_ALL = 7

                gpos = self.listView.viewport().mapToGlobal(viewport_pos)
                pt = (gpos.x(), gpos.y())

                drop_target.DragEnter(data_obj, MK_RBUTTON, pt, DROPEFFECT_ALL)
                result_effect = drop_target.Drop(data_obj, MK_RBUTTON, pt, DROPEFFECT_ALL)
                return result_effect != DROPEFFECT_NONE
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            traceback.print_exc()
            # COM 路徑失敗：fallback 到 Qt 選單
            return self._fallback_right_drag_menu_fm(src_paths, target_dir, viewport_pos)

    def _fallback_right_drag_menu_fm(self, src_paths, target_dir, viewport_pos):
        """Shell IDropTarget 不可用時，以符合 Windows 風格的 Qt 選單處理右鍵拖曳。"""
        menu = QMenu(self)
        font_bold = QFont(menu.font())
        font_bold.setBold(True)

        act_move = menu.addAction("移動到這裡(&M)")
        act_move.setFont(font_bold)
        act_copy = menu.addAction("複製到這裡(&C)")
        act_link = menu.addAction("建立捷徑到這裡(&S)")
        menu.addSeparator()
        menu.addAction("取消")

        gpos = self.listView.viewport().mapToGlobal(viewport_pos)
        chosen = menu.exec_(gpos)

        if chosen == act_move:
            self._perform_file_op(src_paths, target_dir, "move")
            return True
        if chosen == act_copy:
            self._perform_file_op(src_paths, target_dir, "copy")
            return True
        if chosen == act_link:
            self._create_shortcuts_fm(src_paths, target_dir)
            return True
        return False

    def _create_shortcuts_fm(self, src_paths, target_dir):
        """在 target_dir 建立 src_paths 的 Windows 捷徑（.lnk）。"""
        try:
            import pythoncom
            from win32com.shell import shell

            pythoncom.CoInitialize()
            try:
                for src in src_paths:
                    if not os.path.exists(src):
                        continue
                    base = os.path.splitext(os.path.basename(src))[0]
                    lnk_path = os.path.join(target_dir, f"{base} - 捷徑.lnk")
                    link = pythoncom.CoCreateInstance(
                        shell.CLSID_ShellLink, None,
                        pythoncom.CLSCTX_INPROC_SERVER,
                        shell.IID_IShellLink
                    )
                    link.SetPath(src)
                    link.SetWorkingDirectory(os.path.dirname(src))
                    persist = link.QueryInterface(pythoncom.IID_IPersistFile)
                    persist.Save(lnk_path, True)
            finally:
                pythoncom.CoUninitialize()
        except Exception as ex:
            QMessageBox.warning(self, "建立捷徑失敗", f"無法建立捷徑：{ex}")

    def _perform_file_op(self, src_paths, target_dir, op):
        """使用 Windows SHFileOperationW 執行複製或移動。"""
        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wt.HWND),
                ("wFunc", wt.UINT),
                ("pFrom", ctypes.c_wchar_p),
                ("pTo", ctypes.c_wchar_p),
                ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", wt.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", ctypes.c_wchar_p),
            ]

        FO_MOVE = 0x0001
        FO_COPY = 0x0002
        FOF_SIMPLEPROGRESS = 0x0100

        target_dir = os.path.normpath(target_dir)
        valid_sources = []
        for src in src_paths:
            src = os.path.normpath(src)
            if not os.path.exists(src):
                continue
            dest = os.path.join(target_dir, os.path.basename(src))
            if os.path.abspath(src) == os.path.abspath(dest):
                continue
            valid_sources.append(src)

        if not valid_sources:
            return

        from_buf = ctypes.create_unicode_buffer("\0".join(valid_sources) + "\0\0")
        to_buf = ctypes.create_unicode_buffer(target_dir + "\0")

        op_struct = SHFILEOPSTRUCTW()
        op_struct.hwnd = int(self.winId())
        op_struct.wFunc = FO_MOVE if op == "move" else FO_COPY
        op_struct.pFrom = ctypes.cast(from_buf, ctypes.c_wchar_p)
        op_struct.pTo = ctypes.cast(to_buf, ctypes.c_wchar_p)
        op_struct.fFlags = FOF_SIMPLEPROGRESS
        op_struct.lpszProgressTitle = "正在處理檔案..."

        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op_struct))
        if result != 0 and not op_struct.fAnyOperationsAborted:
            QMessageBox.warning(self, "拖曳作業失敗", f"Windows 檔案作業失敗，錯誤碼: {result}")
            return False

        if result == 0 and not op_struct.fAnyOperationsAborted:
            # 不可同步刷新：拖放來源（如搜尋面板 listView2）的 drag.exec_() 巢狀
            # 事件迴圈可能仍在堆疊上，立即重設其 model 會造成原生層存取已釋放物件
            # 而導致程式崩潰自關。改以延遲排程，等拖曳迴圈解開後再刷新。
            self._schedule_panel_refreshes((600, 1500), full_search=True)
            return True

        return False

    def _watch_mid_dir(self, dir_path: str):
        """更新 QFileSystemWatcher：監看中間面板目前目錄，任何異動皆即時刷新。"""
        old = self._mid_fs_watcher.directories()
        if old:
            self._mid_fs_watcher.removePaths(old)
        if dir_path and os.path.isdir(dir_path):
            self._mid_fs_watcher.addPath(dir_path)

    def track_file_operation(self, src_paths, target_dir):
        """暫時監看拖放操作涉及的目錄，等檔案實際變更後再刷新面板。"""
        watch_dirs = set()
        for src in src_paths or []:
            src_dir = os.path.dirname(os.path.normpath(src)) if src else ""
            if src_dir and os.path.isdir(src_dir):
                watch_dirs.add(src_dir)
        if target_dir:
            norm_target = os.path.normpath(target_dir)
            if os.path.isdir(norm_target):
                watch_dirs.add(norm_target)

        old = self._op_fs_watcher.directories()
        if old:
            self._op_fs_watcher.removePaths(old)
        if watch_dirs:
            self._op_fs_watcher.addPaths(sorted(watch_dirs))

        self._schedule_panel_refreshes((250, 900, 1800), full_search=True)
        QTimer.singleShot(4000, self._clear_operation_watch_dirs)

    def _clear_operation_watch_dirs(self):
        dirs = self._op_fs_watcher.directories()
        if dirs:
            self._op_fs_watcher.removePaths(dirs)

    def _on_operation_dir_changed(self, _path: str):
        """來源/目標目錄真的發生異動後，立即補刷中央與右側面板。
        此事件源自我們發起的貼上/移動操作，可能新增符合搜尋的檔案，故需完整重查。"""
        self._schedule_panel_refreshes((120, 450), full_search=True)

    def _schedule_panel_refreshes(self, delays_ms, full_search=False):
        # 每次呼叫都重設計時器：最後一次呼叫後 max(delays_ms) ms 才真正執行，
        # 避免多個來源在短時間內連續觸發導致 update_search_results 被重複呼叫。
        # full_search：本次排程是否需要重跑完整查詢（貼上/移動/新增等可能新增結果者）。
        # 多來源合併到同一次刷新時，只要任一來源要求即保留 True。
        if full_search:
            self._pending_full_search = True
        self._panel_refresh_timer.start(max(delays_ms) if delays_ms else 500)

    def _do_scheduled_panel_refresh(self):
        if getattr(self.listView, '_drag_in_progress', False):
            self._panel_refresh_timer.start(400)
            return
        do_full_search = self._pending_full_search
        self._pending_full_search = False
        self.refresh_mid_panel()
        if do_full_search:
            # 可能新增了符合搜尋條件的檔案，需重跑查詢才能讓新項目出現。
            self.refresh_current_search_results()
        else:
            # 刪除/改名/外部異動：只剔除已不存在的列，省去整個 Everything 重查與重建。
            self._refresh_search_results_existence()

    def _on_mid_dir_changed(self, _path: str):
        """QFileSystemWatcher 偵測到目錄內容異動（新增/刪除/改名）時自動刷新面板。"""
        self._schedule_panel_refreshes((300, 400))

    def refresh_mid_panel(self, force=False):
        """讓中間面板反映目前目錄的最新內容。

        關鍵：QFileSystemModel 對其 rootPath 目錄已啟用內建監看，檔案新增/刪除/
        改名會自動增刪、更新對應列，無須干預。先前無論如何都以 setRootPath("")
        再設回原目錄「強制重載」，會清空整份清單再由背景 gatherer 重新串流，期間
        FileSystemSortProxyModel 對每個項目呼叫 fileInfo() 比較排序，全在 GUI
        執行緒上執行——目錄檔案一多就停頓數秒，使用者得等檔案面板更新完才能繼續操作。

        因導覽（_navigate_to_path）已讓 rootPath 與顯示目錄同步，絕大多數刷新都是
        「同一目錄」：此時直接交給內建監看，不重載即可即時反映且不卡頓。
        force=True 才執行強制重讀（如手動重新整理），因 setRootPath(同路徑) 為
        no-op，須先設空再設回。切換到不同目錄則直接 setRootPath 即可（非 no-op）。
        """
        if getattr(self.listView, '_drag_in_progress', False):
            return
        root_idx = self.listView.rootIndex()
        if root_idx.isValid():
            dir_path = self.file_proxy.filePath(root_idx)
        else:
            dir_path = self.fileListModel.rootPath()
        if not dir_path or not os.path.isdir(dir_path):
            return
        self._watch_mid_dir(dir_path)

        current_root = self.fileListModel.rootPath()
        same_dir = (os.path.normcase(os.path.normpath(current_root or "")) ==
                    os.path.normcase(os.path.normpath(dir_path)))
        if same_dir:
            if not force:
                # 模型已監看此目錄，內容變動自動反映，無須重載（避免 GUI 停頓）。
                return
            # 明確要求強制重讀：setRootPath(同路徑) 是 no-op，須先設空再設回。
            self.fileListModel.setRootPath("")
        new_idx = self.fileListModel.setRootPath(dir_path)
        self.listView.setRootIndex(self.file_proxy.mapFromSource(new_idx))

    def _current_dir(self):
        root_idx = self.listView.rootIndex()
        if root_idx.isValid():
            path = self.file_proxy.filePath(root_idx)
            if path and os.path.isdir(path):
                return path
        indexes = self.treeView.selectedIndexes()
        if indexes:
            path = self.model.filePath(self.tree_proxy.mapToSource(indexes[0]))
            if path and os.path.isdir(path):
                return path
        path = self.mid_tab_bar.current_data() or self.left_tab_bar.current_data()
        return path if path and os.path.isdir(path) else ""

    def _apply_two_panel_layout(self):
        """左側面板已移除後，固定保留中/右兩欄對稱配置。"""
        if self.right_splitter is not None:
            self._set_right_panel_layout(self.right_splitter.orientation())

    def _set_right_panel_layout(self, orientation):
        if self.right_splitter is None:
            return

        current_orientation = self.right_splitter.orientation()
        if current_orientation in self._right_splitter_sizes_by_orientation:
            self._right_splitter_sizes_by_orientation[current_orientation] = self.right_splitter.sizes()

        self.right_splitter.setOrientation(orientation)
        sizes = self._right_splitter_sizes_by_orientation.get(orientation) or [1, 1]
        self.right_splitter.setSizes(sizes)
        self._sync_right_header_spacing()
        self._update_layout_buttons()

    def _update_layout_buttons(self):
        current_orientation = self.right_splitter.orientation() if self.right_splitter is not None else Qt.Orientation.Horizontal
        horizontal_active = current_orientation == Qt.Orientation.Horizontal
        vertical_active = current_orientation == Qt.Orientation.Vertical
        if hasattr(self, 'layout_horizontal_button'):
            self.layout_horizontal_button.setIcon(self._make_layout_icon(Qt.Orientation.Horizontal, active=horizontal_active))
        if hasattr(self, 'layout_vertical_button'):
            self.layout_vertical_button.setIcon(self._make_layout_icon(Qt.Orientation.Vertical, active=vertical_active))

    def _sync_left_drive_combo(self, path):
        if self.left_drive_combo is None:
            return
        text = path or self.mid_tab_bar.current_data() or self.left_tab_bar.current_data() or ""
        self.left_drive_combo.blockSignals(True)
        self.left_drive_combo.lineEdit().setText(text)
        self.left_drive_combo.blockSignals(False)
        self._expand_left_drive_combo_tree(text)

    def _expand_left_drive_combo_tree(self, path):
        if not path or self.left_drive_combo_view is None:
            return
        proxy_index = self.tree_proxy.mapFromSource(self.model.index(path))
        if not proxy_index.isValid():
            return
        parent = proxy_index.parent()
        while parent.isValid():
            self.left_drive_combo_view.expand(parent)
            parent = parent.parent()
        self.left_drive_combo_view.expand(proxy_index)
        self.left_drive_combo_view.scrollTo(proxy_index)
        self.left_drive_combo.setRootModelIndex(self.tree_proxy.mapFromSource(self.model.index("")))

    def _sync_tab_bar_heights(self):
        """三個頁籤列共用同一高度，避免右側因自身 sizeHint 較大而變高。"""
        base_height = max(self.mid_tab_bar.tab_bar.sizeHint().height(), 22)
        for tab_container in (self.left_tab_bar, self.mid_tab_bar, self.right_tab_bar):
            tab_container.sync_height(base_height)

    def _sync_right_header_spacing(self):
        """右側沒有工具列，補一段同高留白，讓右側頁籤垂直對齊左側頁籤列。"""
        if self.right_splitter is not None and self.right_splitter.orientation() == Qt.Orientation.Vertical:
            spacer_height = 0
        else:
            spacer_height = max(self.mid_panel_toolbar.sizeHint().height(), 0)
        self.right_header_spacer.setFixedHeight(spacer_height)

    def _record_history(self, path):
        if not path or not os.path.isdir(path):
            return
        if self._nav_history_index >= 0 and self._nav_history[self._nav_history_index] == path:
            self._update_nav_buttons()
            return
        if self._nav_history_index < len(self._nav_history) - 1:
            self._nav_history = self._nav_history[:self._nav_history_index + 1]
        self._nav_history.append(path)
        self._nav_history_index = len(self._nav_history) - 1
        self._update_nav_buttons()

    def _update_nav_buttons(self):
        can_back = self._nav_history_index > 0
        can_forward = 0 <= self._nav_history_index < len(self._nav_history) - 1
        current_dir = self._current_dir()
        can_up = bool(current_dir and os.path.dirname(os.path.normpath(current_dir)) and os.path.dirname(os.path.normpath(current_dir)) != current_dir)
        can_new_folder = bool(current_dir)
        for buttons in (getattr(self, 'left_nav_buttons', []), getattr(self, 'mid_nav_buttons', [])):
            if len(buttons) >= 4:
                buttons[0].setEnabled(can_back)
                buttons[1].setEnabled(can_forward)
                buttons[2].setEnabled(can_up)
                buttons[3].setEnabled(can_new_folder)

    def _navigate_to_path(self, path, record_history=True):
        if not path or not os.path.isdir(path):
            self._update_nav_buttons()
            return

        self.fileListModel.setRootPath(path)
        self.fileListModel.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
        root_index = self.fileListModel.index(path)
        self.listView.setRootIndex(self.file_proxy.mapFromSource(root_index))
        self._watch_mid_dir(path)

        idx = self.tree_proxy.mapFromSource(self.model.index(path))
        if idx.isValid():
            self._ignore_tree_selection = True
            try:
                self.treeView.setCurrentIndex(idx)
            finally:
                self._ignore_tree_selection = False
            self.treeView.scrollTo(idx)
            self.treeView.expand(idx)
        self.treeView.resizeColumnToContents(0)

        self.left_tab_bar.set_current_data(path, path)
        self.mid_tab_bar.set_current_data(path, path)
        self.left_info_combo.lineEdit().setText(path)
        self.mid_info_combo.lineEdit().setText(path)
        self._sync_left_drive_combo(path)

        if record_history:
            self._record_history(path)
        else:
            self._update_nav_buttons()

    def _navigate_back(self):
        if self._nav_history_index > 0:
            self._nav_history_index -= 1
            self._navigate_to_path(self._nav_history[self._nav_history_index], record_history=False)

    def _navigate_forward(self):
        if self._nav_history_index < len(self._nav_history) - 1:
            self._nav_history_index += 1
            self._navigate_to_path(self._nav_history[self._nav_history_index], record_history=False)

    def _navigate_up(self):
        current_dir = self._current_dir()
        if not current_dir:
            return
        parent_dir = os.path.dirname(os.path.normpath(current_dir))
        if parent_dir and parent_dir != current_dir and os.path.isdir(parent_dir):
            self._navigate_to_path(parent_dir)

    def _create_folder_in_current_dir(self):
        current_dir = self._current_dir()
        if not current_dir:
            return

        base_name = "新增資料夾"
        folder_name = base_name
        index = 2
        while os.path.exists(os.path.join(current_dir, folder_name)):
            folder_name = f"{base_name} ({index})"
            index += 1

        new_dir = os.path.join(current_dir, folder_name)
        try:
            os.makedirs(new_dir, exist_ok=False)
        except Exception as e:
            QMessageBox.warning(self, "建立資料夾失敗", f"無法建立資料夾: {e}")
            return

        self._pending_new_folder_path = os.path.normcase(os.path.normpath(new_dir))
        self.refresh_mid_panel()
        self._navigate_to_path(current_dir)
        QTimer.singleShot(0, lambda path=new_dir: self._focus_new_folder_for_rename(path))

    def _focus_new_folder_for_rename(self, folder_path, retries=8, start_edit=True):
        if not folder_path or self.listView is None or self.fileListModel is None:
            return False

        source_index = self.fileListModel.index(folder_path)
        edit_index = self.file_proxy.mapFromSource(source_index)
        if not edit_index.isValid():
            if retries > 0:
                QTimer.singleShot(120, lambda path=folder_path, remaining=retries - 1, do_edit=start_edit: self._focus_new_folder_for_rename(path, remaining, do_edit))
            return False

        selection_model = self.listView.selectionModel()
        if selection_model is not None:
            selection_model.setCurrentIndex(edit_index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self.listView.setCurrentIndex(edit_index)
        self.listView.scrollTo(edit_index)
        self.listView.setFocus()
        if start_edit:
            self.listView.edit(edit_index)
        return True

    def _on_file_list_item_renamed(self, parent_path, old_name, new_name):
        if not self._pending_new_folder_path:
            return

        old_path = os.path.normcase(os.path.normpath(os.path.join(parent_path, old_name)))
        if old_path != self._pending_new_folder_path:
            return

        self._pending_new_folder_path = ""
        new_path = os.path.join(parent_path, new_name)
        QTimer.singleShot(0, self.refresh_mid_panel)
        QTimer.singleShot(120, lambda path=new_path: self._focus_new_folder_for_rename(path, start_edit=False))

    def refresh_current_search_results(self):
        """依目前右側關鍵字重新查詢，確保拖曳後結果更新。"""
        if getattr(self.listView, '_drag_in_progress', False):
            return
        keyword = self.right_tab_bar.current_data().strip() if self.right_tab_bar is not None else ""
        if not keyword and self.right_info_combo is not None:
            keyword = self.right_info_combo.lineEdit().text().strip()
        if keyword:
            self._do_search(keyword)
        else:
            self._refresh_search_results_existence()

    def _delete_selected_search_files(self):
        """將選取的檔案移至資源回收桶（Delete 鍵 / 備援選單）。"""
        return self._delete_paths_to_recycle_bin(self._get_selected_search_paths())

    def on_new(self):
        # 保留舊功能（建立新檔案），但不再由工具列第一個按鈕觸發
        dir_path = self.fileListModel.rootPath()
        base = "new_file"
        i = 0
        while True:
            name = f"{base}{i}.txt"
            path = os.path.join(dir_path, name)
            if not os.path.exists(path):
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('')
                break
            i += 1
        # 刷新列表
        self.fileListModel.setRootPath(dir_path)
        self.listView.setRootIndex(self.file_proxy.mapFromSource(self.fileListModel.index(dir_path)))

    def on_open(self):
        # 保留舊功能（用系統開啟檔案），但不再由工具列第二個按鈕觸發
        indexes = self.listView.selectedIndexes()
        if not indexes:
            return
        path = self.file_proxy.filePath(indexes[0])
        try:
            os.startfile(path)
        except Exception as e:
            QMessageBox.warning(self, "錯誤", f"無法開啟檔案: {e}")

    def _apply_font_size(self, new_size):
        """將字型大小套用至所有 listview 及頁籤列。"""
        for widget in (self.treeView, self.listView, self.listView2):
            current_font = widget.font()
            f = QFont(current_font.family(), new_size)
            widget.setFont(f)
        # 同步頁籤列字型
        for tab_container in (self.left_tab_bar, self.mid_tab_bar, self.right_tab_bar):
            tb = tab_container.tab_bar
            current_font = tb.font()
            f = QFont(current_font.family(), new_size)
            tb.setFont(f)
            tb.update()
        self._sync_right_header_spacing()
        self._sync_tab_bar_heights()
        # 同步 info combobox 字型
        for combo in (self.left_info_combo, self.mid_info_combo, self.right_info_combo):
            current_font = combo.font()
            f = QFont(current_font.family(), new_size)
            combo.setFont(f)
        if self.left_drive_combo is not None:
            current_font = self.left_drive_combo.font()
            f = QFont(current_font.family(), new_size)
            self.left_drive_combo.setFont(f)

    def on_font_increase(self):
        # 放大字型，各增加 1pt（限制最大 72pt）
        current_font = self.treeView.font()
        current_size = current_font.pointSize() if current_font.pointSize() > 0 else 10
        new_size = min(current_size + 1, 72)
        self._apply_font_size(new_size)
        self.update_status_bar()

    def on_font_decrease(self):
        # 縮小字型，各減少 1pt（限制最小 6pt）
        current_font = self.treeView.font()
        current_size = current_font.pointSize() if current_font.pointSize() > 0 else 10
        new_size = max(current_size - 1, 6)
        self._apply_font_size(new_size)
        self.update_status_bar()

    def update_status_bar(self):
        # 更新狀態列以顯示左側視圖的目前字型大小
        left_font = self.treeView.font()
        left_size = left_font.pointSize() if left_font.pointSize() > 0 else 10
        status = self.statusBar()
        if status is not None:
            status.showMessage(f"字型: {left_size}pt")

    def _current_font_size(self):
        font = self.treeView.font()
        return font.pointSize() if font.pointSize() > 0 else 10

    def _config_path(self):
        return os.path.join(_runtime_root(), 'config.ini')

    def load_config(self):
        """從 config.ini 讀取參數並還原狀態。"""
        cfg = configparser.ConfigParser()
        cfg.read(self._config_path(), encoding='utf-8')

        # 還原主視窗大小與狀態
        saved_geometry = cfg.get('Layout', 'window_geometry', fallback='')
        if saved_geometry:
            try:
                geometry_bytes = base64.b64decode(saved_geometry.encode('ascii'))
                self.restoreGeometry(geometry_bytes)
            except Exception:
                pass
        saved_window_state = cfg.get('Layout', 'window_state', fallback='normal')
        if saved_window_state == 'maximized':
            self.setWindowState(self.windowState() | Qt.WindowMaximized)
        elif saved_window_state == 'fullscreen':
            self.setWindowState(self.windowState() | Qt.WindowFullScreen)

        # 還原字型大小
        saved_font_size = cfg.getint('General', 'font_size', fallback=10)
        self._apply_font_size(max(6, min(saved_font_size, 72)))
        self.update_status_bar()

        # 還原排除目錄設定（須在還原頁籤觸發搜尋之前，過濾才會生效）
        self._exclude_enabled = cfg.getboolean('Exclude', 'enabled', fallback=False)
        raw_exclude = cfg.get('Exclude', 'dirs', fallback='')
        if raw_exclude:
            try:
                loaded = json.loads(raw_exclude)
                self._exclude_dirs = [str(d) for d in loaded if d]
            except Exception:
                self._exclude_dirs = []
        self._apply_exclude_settings()

        # 還原左側目錄樹選取的目錄
        left_dir = cfg.get('General', 'left_dir', fallback='')
        if left_dir and os.path.isdir(left_dir):
            def restore_left_dir_once(_loaded_path, target_dir=left_dir):
                try:
                    self.model.directoryLoaded.disconnect(restore_left_dir_once)
                except Exception:
                    pass
                self._try_select_dir(target_dir)

            self.model.directoryLoaded.connect(restore_left_dir_once)
            self.model.setRootPath(left_dir)

        # 還原分割器大小
        splitter_sizes = cfg.get('Layout', 'splitter_sizes', fallback='')
        if splitter_sizes and self.splitter is not None:
            try:
                self.splitter.setSizes([int(x) for x in splitter_sizes.split(',')])
            except Exception:
                pass
        right_splitter_sizes = cfg.get('Layout', 'right_splitter_sizes', fallback='')
        if right_splitter_sizes:
            try:
                self._right_splitter_sizes_by_orientation[Qt.Orientation.Horizontal] = [int(x) for x in right_splitter_sizes.split(',')]
            except Exception:
                pass
        right_splitter_vertical_sizes = cfg.get('Layout', 'right_splitter_vertical_sizes', fallback='')
        if right_splitter_vertical_sizes:
            try:
                self._right_splitter_sizes_by_orientation[Qt.Orientation.Vertical] = [int(x) for x in right_splitter_vertical_sizes.split(',')]
            except Exception:
                pass
        right_splitter_orientation = cfg.get('Layout', 'right_splitter_orientation', fallback='horizontal').lower()
        self._set_right_panel_layout(Qt.Orientation.Vertical if right_splitter_orientation == 'vertical' else Qt.Orientation.Horizontal)

        # 還原左側 treeView 欄位寬度
        left_col_widths = cfg.get('Columns', 'left_col_widths', fallback='')
        if left_col_widths:
            try:
                for i, w in enumerate(left_col_widths.split(',')):
                    self.treeView.setColumnWidth(i, int(w))
            except Exception:
                pass

        # 還原中間 listView 欄位寬度與順序
        mid_header = self.listView.header()
        if mid_header is not None:
            mid_col_widths = cfg.get('Columns', 'mid_col_widths', fallback='')
            if mid_col_widths:
                try:
                    for i, w in enumerate(mid_col_widths.split(',')):
                        self.listView.setColumnWidth(i, int(w))
                except Exception:
                    pass
            mid_col_order = cfg.get('Columns', 'mid_col_order', fallback='')
            if mid_col_order:
                try:
                    order = [int(x) for x in mid_col_order.split(',')]
                    for vi, li in enumerate(order):
                        cur = mid_header.visualIndex(li)
                        if cur != vi:
                            mid_header.moveSection(cur, vi)
                except Exception:
                    pass

        # 還原右側 listView2 欄位寬度與順序
        right_header = self.listView2.header()
        if right_header is not None:
            right_col_widths = cfg.get('Columns', 'right_col_widths', fallback='')
            if right_col_widths:
                try:
                    for i, w in enumerate(right_col_widths.split(',')):
                        self.listView2.setColumnWidth(i, int(w))
                except Exception:
                    pass
            right_col_order = cfg.get('Columns', 'right_col_order', fallback='')
            if right_col_order:
                try:
                    order = [int(x) for x in right_col_order.split(',')]
                    for vi, li in enumerate(order):
                        cur = right_header.visualIndex(li)
                        if cur != vi:
                            right_header.moveSection(cur, vi)
                except Exception:
                    pass

        # 還原中間 listView 排序方式
        mid_sort_col = cfg.get('Sort', 'mid_sort_column', fallback='')
        mid_sort_ord = cfg.get('Sort', 'mid_sort_order', fallback='')
        if mid_sort_col and mid_sort_ord:
            try:
                col = int(mid_sort_col)
                order = Qt.SortOrder.AscendingOrder if int(mid_sort_ord) == 0 else Qt.SortOrder.DescendingOrder
                self.listView.sortByColumn(col, order)
            except Exception:
                pass

        # 還原右側 listView2 排序方式
        right_sort_col = cfg.get('Sort', 'right_sort_column', fallback='')
        right_sort_ord = cfg.get('Sort', 'right_sort_order', fallback='')
        if right_sort_col and right_sort_ord:
            try:
                col = int(right_sort_col)
                order = Qt.SortOrder.AscendingOrder if int(right_sort_ord) == 0 else Qt.SortOrder.DescendingOrder
                self.listView2.sortByColumn(col, order)
            except Exception:
                pass

        # 還原三個面板的頁籤資訊
        for key, tab_widget in (('left', self.left_tab_bar), ('mid', self.mid_tab_bar), ('right', self.right_tab_bar)):
            raw = cfg.get('Tabs', f'{key}_tabs', fallback='')
            current = cfg.getint('Tabs', f'{key}_tabs_current', fallback=0)
            if raw:
                try:
                    tabs = [(d, l) for d, l in json.loads(raw)]
                    tab_widget.restore_tabs(tabs, current)
                except Exception:
                    pass

        # 啟動時主動執行右側當前頁籤的搜尋，補上 restore_tabs 不觸發 tab_switched 的缺口
        initial_keyword = self.right_tab_bar.current_data()
        if initial_keyword:
            self.right_info_combo.lineEdit().setText(initial_keyword)
            QTimer.singleShot(0, lambda kw=initial_keyword: self._do_search(kw))

        self._sync_left_drive_combo(self.mid_tab_bar.current_data() or self.left_tab_bar.current_data() or left_dir)

        # 載入搜尋歷史至右側 combobox
        raw_history = cfg.get('General', 'search_history', fallback='')
        if raw_history:
            try:
                history = json.loads(raw_history)
                self.right_info_combo.blockSignals(True)
                for item in reversed(history):  # reversed 使最新的在頂
                    self.right_info_combo.insertItem(0, item)
                self.right_info_combo.blockSignals(False)
            except Exception:
                pass

    def _try_select_dir(self, dir_path):
        """嘗試在左側樹狀視圖中選取並展開指定目錄。"""
        self._navigate_to_path(dir_path)

    def save_config(self):
        """將目前狀態寫入 config.ini。"""
        cfg = configparser.ConfigParser()
        cfg.read(self._config_path(), encoding='utf-8')

        if not cfg.has_section('General'):
            cfg.add_section('General')
        if not cfg.has_section('Layout'):
            cfg.add_section('Layout')
        if not cfg.has_section('Columns'):
            cfg.add_section('Columns')
        if not cfg.has_section('Sort'):
            cfg.add_section('Sort')
        if not cfg.has_section('Tabs'):
            cfg.add_section('Tabs')
        if not cfg.has_section('Exclude'):
            cfg.add_section('Exclude')

        # 儲存排除目錄設定
        cfg.set('Exclude', 'enabled', 'true' if self._exclude_enabled else 'false')
        cfg.set('Exclude', 'dirs', json.dumps(self._exclude_dirs, ensure_ascii=False))

        # 儲存右側 combobox 歷史（最多 20 筆）
        history = [self.right_info_combo.itemText(i) for i in range(self.right_info_combo.count())]
        cfg.set('General', 'search_history', json.dumps(history[:20], ensure_ascii=False))

        # 儲存左側目錄樹目前選取的目錄
        indexes = self.treeView.selectedIndexes()
        if indexes:
            left_dir = self.model.filePath(self.tree_proxy.mapToSource(indexes[0]))
        else:
            left_dir = ''
        cfg.set('General', 'left_dir', left_dir)
        cfg.set('General', 'font_size', str(self._current_font_size()))

        # 儲存主視窗大小與狀態
        cfg.set('Layout', 'window_geometry', base64.b64encode(self.saveGeometry().data()).decode('ascii'))
        if self.isFullScreen():
            window_state = 'fullscreen'
        elif self.isMaximized():
            window_state = 'maximized'
        else:
            window_state = 'normal'
        cfg.set('Layout', 'window_state', window_state)

        # 儲存分割器大小
        if self.splitter is not None:
            cfg.set('Layout', 'splitter_sizes', ','.join(str(s) for s in self.splitter.sizes()))
        else:
            cfg.set('Layout', 'splitter_sizes', '')
        self._right_splitter_sizes_by_orientation[self.right_splitter.orientation()] = self.right_splitter.sizes()
        cfg.set('Layout', 'right_splitter_orientation', 'vertical' if self.right_splitter.orientation() == Qt.Orientation.Vertical else 'horizontal')
        cfg.set('Layout', 'right_splitter_sizes', ','.join(str(s) for s in self._right_splitter_sizes_by_orientation.get(Qt.Orientation.Horizontal, [])))
        cfg.set('Layout', 'right_splitter_vertical_sizes', ','.join(str(s) for s in self._right_splitter_sizes_by_orientation.get(Qt.Orientation.Vertical, [])))

        # 儲存左側 treeView 欄位寬度
        left_widths = []
        for i in range(self.model.columnCount()):
            left_widths.append(str(self.treeView.columnWidth(i)))
        cfg.set('Columns', 'left_col_widths', ','.join(left_widths))

        # 儲存中間 listView 欄位寬度與順序
        mid_header = self.listView.header()
        if mid_header is not None:
            mid_widths = []
            mid_order = []
            for i in range(mid_header.count()):
                mid_widths.append(str(self.listView.columnWidth(i)))
                mid_order.append(str(mid_header.logicalIndex(i)))
            cfg.set('Columns', 'mid_col_widths', ','.join(mid_widths))
            cfg.set('Columns', 'mid_col_order', ','.join(mid_order))

        # 儲存右側 listView2 欄位寬度與順序
        right_header = self.listView2.header()
        if right_header is not None:
            right_widths = []
            right_order = []
            for i in range(right_header.count()):
                right_widths.append(str(self.listView2.columnWidth(i)))
                right_order.append(str(right_header.logicalIndex(i)))
            cfg.set('Columns', 'right_col_widths', ','.join(right_widths))
            cfg.set('Columns', 'right_col_order', ','.join(right_order))

        # 儲存中間 listView 排序方式
        mid_header = self.listView.header()
        if mid_header is not None:
            cfg.set('Sort', 'mid_sort_column', str(mid_header.sortIndicatorSection()))
            cfg.set('Sort', 'mid_sort_order', str(int(mid_header.sortIndicatorOrder())))

        # 儲存右側 listView2 排序方式
        right_header = self.listView2.header()
        if right_header is not None:
            cfg.set('Sort', 'right_sort_column', str(right_header.sortIndicatorSection()))
            cfg.set('Sort', 'right_sort_order', str(int(right_header.sortIndicatorOrder())))

        # 儲存三個面板的頁籤資訊
        for key, tab_widget in (('left', self.left_tab_bar), ('mid', self.mid_tab_bar), ('right', self.right_tab_bar)):
            tabs, current = tab_widget.get_all_tabs()
            cfg.set('Tabs', f'{key}_tabs', json.dumps(tabs, ensure_ascii=False))
            cfg.set('Tabs', f'{key}_tabs_current', str(current))

        with open(self._config_path(), 'w', encoding='utf-8') as f:
            cfg.write(f)

    def closeEvent(self, event):
        # 等背景執行緒把索引寫回磁碟（含本次新掃到的部分），下次開啟可快速載入
        self.file_index.stop(wait_timeout=15)
        self.save_config()
        super().closeEvent(event)


def _install_crash_logger():
    """安裝崩潰記錄器：把原生崩潰（存取違規）、Qt 致命訊息與未捕捉的 Python
    例外都寫進 crash.log，讓「無聲消失」的原生崩潰留下可診斷的呼叫堆疊。

    回傳開啟中的 log 檔物件——必須在整個行程生命週期保持開啟，faulthandler
    才能在崩潰當下寫入。"""
    import faulthandler
    from datetime import datetime as _dt

    log_path = os.path.join(_runtime_root(), 'crash.log')
    try:
        log_file = open(log_path, 'a', buffering=1, encoding='utf-8')
    except Exception:
        return None

    log_file.write(f"\n===== session start {_dt.now():%Y-%m-%d %H:%M:%S} =====\n")
    log_file.flush()

    # faulthandler：在 SIGSEGV / Windows 存取違規等致命錯誤時 dump 所有執行緒的
    # Python 堆疊到 log_file（含造成崩潰的那一行）。
    try:
        faulthandler.enable(file=log_file, all_threads=True)
    except Exception:
        pass

    # 未捕捉的 Python 例外也寫入 log（保留原本的主控台輸出）。
    _prev_excepthook = sys.excepthook

    def _excepthook(exc_type, exc_value, exc_tb):
        try:
            log_file.write(f"\n----- uncaught exception {_dt.now():%Y-%m-%d %H:%M:%S} -----\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=log_file)
            log_file.flush()
        except Exception:
            pass
        _prev_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    # Qt 端的警告/致命訊息（QSortFilterProxyModel 索引越界常以 qWarning 先示警）。
    try:
        from PyQt5.QtCore import qInstallMessageHandler, QtMsgType

        def _qt_message_handler(mode, context, message):
            label = {
                QtMsgType.QtDebugMsg: 'DEBUG',
                QtMsgType.QtInfoMsg: 'INFO',
                QtMsgType.QtWarningMsg: 'WARNING',
                QtMsgType.QtCriticalMsg: 'CRITICAL',
                QtMsgType.QtFatalMsg: 'FATAL',
            }.get(mode, 'MSG')
            try:
                log_file.write(f"[Qt {label}] {message}\n")
                log_file.flush()
            except Exception:
                pass

        qInstallMessageHandler(_qt_message_handler)
    except Exception:
        pass

    return log_file


def main():
    # 保持參考避免被 GC；log 檔需在整個行程期間開啟供 faulthandler 寫入。
    _crash_log = _install_crash_logger()  # noqa: F841
    app = QApplication(sys.argv)
    window = FileManager()
    window.show()
    sys.exit(app.exec_())
