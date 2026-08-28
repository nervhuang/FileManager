import sys
import subprocess
import os
import traceback

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QFileSystemModel, QWidget,
    QHBoxLayout, QVBoxLayout, QAction, QMessageBox,
    QSplitter, QSizePolicy, QFileIconProvider,
    QAbstractItemView, QMenu, QComboBox,
    QDialog, QActionGroup, QShortcut, QFrame,
)
from PyQt5.QtCore import QDir, Qt, QSize, QFileInfo, QEvent, QTimer, QFileSystemWatcher, QItemSelectionModel, QMimeData, QUrl
from PyQt5.QtGui import QKeySequence, QIcon, QFont

from . import crashlog, font_scaling, gui_bridge, icons, paths, settings
from .search import query as search_query, results as search_results
from .search.exclude_dialog import ExcludeSettingsDialog
from .authors import icons as authors_icons
from .authors.panel import AuthorsPanel
from .checker.panel import CheckerPanel, make_checker_icon
from .search.everything import EverythingSDK
from .models import FileSystemSortProxyModel
from .search import models as search_models
from .search.models import SearchResultsModel, SearchSortProxyModel
from .views import SearchListView, FileListView
from . import columns, toolbar
from .fileops import clipboard, drag_menu, rename, shell as shell_ops
from .tabs import history
from .tabs.bar import PathTabBar
from .tabs.breadcrumb import BreadcrumbBar

ref_s = 0
ref_e = 1
global_keywords = []


# 路徑解析實作已移至 app/paths.py（不依賴 Qt，MCP server 也用同一份）。
_bundle_root = paths.bundle_root
_runtime_root = paths.runtime_root


class FileManager(QMainWindow):
    # 欄位顯示切換相關設定（見 _setup_column_visibility_menus）
    DEFAULT_COLUMN_WIDTH = 120
    # 第 0 欄是樹狀縮排、圖示與重新命名編輯所在的欄位，隱藏它會讓面板無法操作，
    # 故在選單中恆為已勾選且停用。
    LOCKED_COLUMNS = (0,)
    # 首次啟動（config.ini 尚無 *_col_hidden 鍵）時預設隱藏的欄位：
    # 中間面板的「類型」欄向來不顯示，保持升級前後畫面一致。
    DEFAULT_HIDDEN_COLUMNS = {'mid': (2,), 'right': ()}

    def __init__(self):
        super().__init__()

        self.everything = EverythingSDK()
        # 搜尋結果的 is_dir/size/mtime 直接由 Everything IPC 查詢回傳（其索引本身
        # 就有這些欄位），不再於啟動時自建全碟中繼資料快取。清掉舊版遺留的快取檔。
        for leftover in ('file_index_cache.dat', 'file_index_cache.dat.tmp'):
            try:
                os.remove(os.path.join(_runtime_root(), leftover))
            except OSError:
                pass
        self.search_model = None
        self.sdk_warned = False
        # 排除目錄設定：被排除的目錄（及其子路徑）不在中間面板與搜尋結果中列出。
        # _exclude_dirs 保存使用者原始路徑（供顯示），_exclude_norm 為比對用正規化路徑。
        self._exclude_enabled = False
        self._exclude_dirs = []
        self._exclude_norm = ()
        self._search_drag_button = Qt.NoButton
        self._toolbar_icon_size = QSize(64, 64)
        self._nav_history = history.NavigationHistory()
        self._search_model_updating = False
        self._search_item_rename_in_progress = False
        self._search_icon_provider = QFileIconProvider()
        self._search_icon_cache = {}
        self._clipboard_file_op = clipboard.COPY
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
        # 左側作者／團體面板：可隨時切換回原本的雙面板版面，狀態存 config.ini。
        # 這兩個值必須在 initUI 之前就位（initUI 會直接套用）。
        self._authors_panel_visible = True
        self._authors_panel_width = 660
        self.authors_panel = None
        self.main_splitter = None
        self._bridge_server = None
        # 更新檢查器面板：預設收起，靠工具列圖示或 Ctrl+Shift+U 叫出來。
        # 預設不顯示是因為它只有在剛掃描完才有東西可看，常駐佔寬度不划算。
        self._checker_panel_visible = False
        self._checker_panel_width = 520
        self.checker_panel = None
        # 監控中間面板目前目錄，任何外部檔案異動皆可即時刷新
        self._mid_fs_watcher = QFileSystemWatcher(self)
        self._mid_fs_watcher.directoryChanged.connect(self._on_mid_dir_changed)
        # 監控本次檔案操作涉及的來源/目標目錄，等異動真正落地後再刷新
        self._op_fs_watcher = QFileSystemWatcher(self)
        self._op_fs_watcher.directoryChanged.connect(self._on_operation_dir_changed)
        self.initUI()

    def initUI(self):
        self.setWindowTitle("文件管理器")
        self.setGeometry(100, 100, 800, 600)

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

        # 分頁切換熱鍵：下一個 Ctrl+PageDown、上一個 Ctrl+PageUp（檔案/搜尋面板皆適用）。
        # 以 QAction 註冊（WindowShortcut），優先於清單視圖對 PageUp/Down 的預設處理。
        action_next_tab = QAction("下一個分頁", self)
        action_next_tab.setShortcut(QKeySequence("Ctrl+PgDown"))
        action_next_tab.triggered.connect(lambda: self._switch_tab(1))
        action_prev_tab = QAction("上一個分頁", self)
        action_prev_tab.setShortcut(QKeySequence("Ctrl+PgUp"))
        action_prev_tab.triggered.connect(lambda: self._switch_tab(-1))
        self.addAction(action_next_tab)
        self.addAction(action_prev_tab)

        # 關閉目前分頁：Ctrl+W（檔案/搜尋面板皆適用，至少保留一個分頁）。
        action_close_tab = QAction("關閉分頁", self)
        action_close_tab.setShortcut(QKeySequence("Ctrl+W"))
        action_close_tab.triggered.connect(self._close_current_tab)
        self.addAction(action_close_tab)

        self._make_layout_icon = (
            lambda orientation, active=False: icons.make_layout_icon(
                orientation, active, self._toolbar_icon_size))
        up_folder_icon = icons.make_up_folder_icon(self._toolbar_icon_size)
        horizontal_layout_icon = self._make_layout_icon(Qt.Orientation.Horizontal, active=True)
        vertical_layout_icon = self._make_layout_icon(Qt.Orientation.Vertical)

        # 兩個面板的清單：中間是檔案，右邊是搜尋結果。右鍵選單都走原生 shell 選單。
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
        self.mid_panel_toolbar, self.mid_nav_buttons = toolbar.build(self, self._toolbar_icon_size, [
            (icons.make_back_icon(self._toolbar_icon_size), "前一頁", self._navigate_back),
            (icons.make_forward_icon(self._toolbar_icon_size), "後一頁", self._navigate_forward),
            (up_folder_icon, "回到上一層目錄", self._navigate_up),
            toolbar.SEPARATOR,       # 導覽 ┃ 新增+排列
            (icons.make_new_folder_icon(self._toolbar_icon_size), "新增資料夾",
             self._create_folder_in_current_dir),
        ])
        # 兩個側邊面板的入口並列成一組（SHL-15a）：只靠選單與快捷鍵叫得出來的
        # 面板等於藏起來了。更新檢查器預設就是收起的；作者面板雖然預設顯示，
        # 關掉之後同樣只剩選單找得回來。
        self.mid_panel_toolbar.addSeparator()
        self.authors_toolbar_button = toolbar.make_nav_button(
            self, authors_icons.make_glyph_icon('group'),
            "作者／團體清單：切換左側面板顯示",
            lambda: self._set_authors_panel_visible(not self._authors_panel_visible),
            self._toolbar_icon_size)
        self.mid_panel_toolbar.addWidget(self.authors_toolbar_button)
        self.checker_toolbar_button = toolbar.make_nav_button(
            self, make_checker_icon(), "更新檢查器：比對站上新書與本機藏書",
            self._toggle_checker_panel, self._toolbar_icon_size)
        self.mid_panel_toolbar.addWidget(self.checker_toolbar_button)

        self.act_cut = toolbar.make_action_button(self, icons.make_file_action_icon("cut", self._toolbar_icon_size), "剪下",
            self._cut_selected_paths_from_focused_view, self._toolbar_icon_size)
        self.act_copy = toolbar.make_action_button(self, icons.make_file_action_icon("copy", self._toolbar_icon_size), "複製",
            self._copy_selected_paths_from_focused_view, self._toolbar_icon_size)
        self.act_paste = toolbar.make_action_button(self, icons.make_file_action_icon("paste", self._toolbar_icon_size), "貼上",
            self._paste_from_toolbar, self._toolbar_icon_size)
        self.act_rename = toolbar.make_action_button(self, icons.make_file_action_icon("rename", self._toolbar_icon_size), "重新命名",
            self._rename_selected_focused_item, self._toolbar_icon_size)
        self.act_delete = toolbar.make_action_button(self, icons.make_trash_icon(self._toolbar_icon_size), "刪除",
            self._delete_selected_focused_items, self._toolbar_icon_size)
        self.act_refresh = toolbar.make_action_button(self, icons.make_refresh_icon(self._toolbar_icon_size), "重新整理",
            lambda: self.refresh_mid_panel(force=True), self._toolbar_icon_size)
        # 上下/左右排列鈕緊接「新增資料夾」，排在操作按鈕左邊
        self.layout_horizontal_button = toolbar.make_nav_button(
            self, horizontal_layout_icon, "左右排列",
            lambda: self._set_right_panel_layout(Qt.Orientation.Horizontal),
            self._toolbar_icon_size)
        self.mid_panel_toolbar.addWidget(self.layout_horizontal_button)
        self.layout_vertical_button = toolbar.make_nav_button(
            self, vertical_layout_icon, "上下排列",
            lambda: self._set_right_panel_layout(Qt.Orientation.Vertical),
            self._toolbar_icon_size)
        self.mid_panel_toolbar.addWidget(self.layout_vertical_button)
        # 新增+排列 ┃ 操作
        self.mid_panel_toolbar.addSeparator()
        for _btn in (self.act_cut, self.act_copy, self.act_paste, self.act_rename, self.act_delete, self.act_refresh):
            self.mid_panel_toolbar.addWidget(_btn)

        # 「選項…」等功能改由視窗頂端的功能表列（檔案 選單）提供，不再放漢堡選單。
        self._build_menu_bar()

        # 檔案總管風格的混合式麵包屑路徑列（取代舊的樹狀下拉 path_combo）
        # 置於工具列下方獨立一行（加入 mid_vbox），不再擠在工具列裡
        self.path_bar = BreadcrumbBar(self)
        self.path_bar.path_selected.connect(self._on_breadcrumb_selected)
        # Ctrl+L / Alt+D：聚焦到路徑列的可編輯文字框並全選
        for seq in ("Ctrl+L", "Alt+D"):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(self.path_bar.focus_edit)
        self.mid_tab_bar = PathTabBar(self)
        self.mid_info_combo = QComboBox()
        self.mid_info_combo.setEditable(True)
        self.mid_info_combo.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.mid_info_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.mid_container = QWidget()
        mid_vbox = QVBoxLayout()
        mid_vbox.setContentsMargins(0, 0, 0, 0)
        mid_vbox.setSpacing(0)
        # 列間極淡水平分隔線 + 麵包屑上下少許留白，讓工具列/位址列/分頁列層次分明。
        # 位址列上方共有：工具列 + 1px 線 + 3px 留白 + 麵包屑 + 3px 留白 + 1px 線 = 額外 8px，
        # 右面板 spacer 需補上這 8px 才能與左側分頁列對齊（見 _sync_right_header_spacing）。
        self._mid_header_extra = 8
        mid_vbox.addWidget(self.mid_panel_toolbar)
        mid_vbox.addWidget(self._make_hline())
        mid_vbox.addSpacing(3)
        mid_vbox.addWidget(self.path_bar)
        mid_vbox.addSpacing(3)
        mid_vbox.addWidget(self._make_hline())
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

        # 作者／團體面板放在「外層」分割器，而非 right_splitter 內：後者會在橫/直
        # 版面切換時改變方向，若把左面板放進去，切成垂直時它會跑到最上方。
        self.authors_panel = AuthorsPanel(self)
        # 工具列圖示與中間檔案面板同尺寸（面板可獨立關閉，故不併入主工具列）
        self.authors_panel.set_toolbar_icon_size(self._toolbar_icon_size)
        self.authors_panel.search_requested.connect(self._on_authors_search_requested)

        # 更新檢查器面板放在最右側：它是「看結果」的地方，與左側「選作者」的
        # 動線相反，擺在同一邊會互相搶寬度。
        self.checker_panel = CheckerPanel(self)
        self.checker_panel.set_toolbar_icon_size(self._toolbar_icon_size)
        self.checker_panel.status_message.connect(self._show_checker_status)
        self.checker_panel.detail_requested.connect(self._on_checker_detail_requested)

        # 三條工具列各自獨立卻左右並排，高度差一階就看得出來，統一釘成同一個值。
        # 這個值依字型計算，字型改變時必須重算（見 font_scaling）。
        font_scaling.sync_toolbar_heights(self)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.addWidget(self.authors_panel)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.addWidget(self.checker_panel)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes(
            [self._authors_panel_width, 1200, self._checker_panel_width])
        self.authors_panel.setVisible(self._authors_panel_visible)
        self.checker_panel.setVisible(self._checker_panel_visible)

        right_container = QWidget()
        right_vbox = QVBoxLayout()
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.addWidget(self.main_splitter)
        right_container.setLayout(right_vbox)

        # 主畫面：作者清單（左，可隱藏）＋ 檔案（中）/搜尋（右）兩面板的對稱分割
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

        header2 = self.listView2.header()
        if header2 is not None:
            header2.setStretchLastSection(True)

        # 欄位顯示切換：記錄各欄最後一次的可見寬度，隱藏欄的 columnWidth() 恆為 0，
        # 靠這份快取才能在勾回來與寫入 config 時給出正確寬度。
        self._col_width_cache = {'mid': {}, 'right': {}}
        self._setup_column_visibility_menus()
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
        # 記錄目前操作焦點所在的面板：'mid'（檔案）或 'right'（搜尋）。
        self._active_panel = 'mid'
        self.listView.viewport().installEventFilter(self)
        self.listView2.viewport().installEventFilter(self)

        # 设置默认排序为日期排序
        self.listView.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self.listView2.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        # 頁籤列切換訊號
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
        self._setup_action_buttons_state()
        self._start_bridge_server()

    def on_listView_clicked(self, index):
        """处理中央视窗文件单击事件"""
        # 只有在 listView viewport 上確實發生過滑鼠按下時才觸發搜尋
        if not self._listview_mouse_pressed:
            return
        self._listview_mouse_pressed = False
        global ref_s, ref_e, global_keywords

        if not self.file_proxy.isDir(index):
            file_name = self.file_proxy.fileName(index)
            keywords = search_query.extract_keywords(file_name)
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

        # F5 刷新：搜尋面板有焦點 → 重新查詢；檔案面板有焦點 → 重整檔案列表；
        # 無明確焦點 → 兩者都刷新，確保 F5 永遠有作用。
        if e.key() == Qt.Key.Key_F5:
            view = self._focused_file_view()
            if view is self.listView2:
                self.refresh_current_search_results()
            elif view is self.listView:
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
            self._exclude_norm = search_query.normalize_exclude_dirs(self._exclude_dirs)
        else:
            self._exclude_norm = ()
        if self.file_proxy is not None:
            self.file_proxy.set_excluded_dirs(self._exclude_norm)
        self.refresh_current_search_results()

    def _is_path_excluded(self, path):
        return search_query.is_path_excluded(path, self._exclude_norm)

    def _on_mid_tab_switched(self, path):
        """切換中間頁籤：更新檔案列表至儲存的路徑，並同步左側目錄樹。
        空白分頁（無路徑）預設顯示所有磁碟機。"""
        self._active_panel = 'mid'
        if not path:
            self._show_all_drives()
        else:
            self._navigate_to_path(path)

    def _on_breadcrumb_selected(self, path):
        """麵包屑分段／箭頭下拉／換碟／編輯輸入所選的路徑。
        空字串代表「本機（所有磁碟機）」；無效路徑則還原顯示。"""
        self._active_panel = 'mid'
        path = (path or "").strip()
        if not path:
            self._show_all_drives()
            self._sync_breadcrumb("")
        elif os.path.isdir(path):
            self._navigate_to_path(path)
        else:
            self._sync_breadcrumb(self._current_dir())

    def _on_combo_text_edited(self, text):
        """使用者輸入或貼上時更新關鍵字，停頓後自動搜尋。"""
        self._active_panel = 'right'
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
        if event.type() == QEvent.Wheel and obj in (self.listView.viewport(), self.listView2.viewport()):
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

        # 追蹤操作焦點所在面板：點在搜尋清單→'right'，點在檔案清單→'mid'。
        if event.type() == QEvent.MouseButtonPress:
            if obj is self.listView2.viewport():
                self._active_panel = 'right'
            elif obj is self.listView.viewport():
                self._active_panel = 'mid'

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
        self._active_panel = 'right'
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
        """使用者主動搜尋：更新頁籤資料、combobox MRU 歷史，並執行查詢。

        注意：此方法也會被「在檔案面板點檔案」觸發（以檔名做搜尋），
        因此不可在這裡把操作焦點設為搜尋面板，否則會誤判 Ctrl+T 的目標面板。
        """
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

    def _do_search(self, search_command):
        """只執行 Everything 查詢並更新展示，不修改頁籤資料或 combobox 歷史。復原搜尋用。"""
        normalized_command = search_query.normalize_search_command(search_command)
        if self.everything.is_available():
            results, _capped = search_query.query_everything(self.everything, search_command)
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

    def update_search_results(self, results):
        """把 Everything 回來的結果填進搜尋面板。

        results 是 search.everything.SearchResult 的清單。
        """
        if self.search_model is None:
            return
        if self._exclude_norm:
            # 排除設定啟用時，濾掉落在被排除目錄（及其子路徑）下的結果（SRCH-9）
            results = [r for r in results if not self._is_path_excluded(r.path)]

        # 這面旗標擋掉 itemChanged 接的改名處理：批次填入不是使用者在改名。
        self._search_model_updating = True
        search_models.populate(
            self.search_model, self.search_proxy,
            search_models.build_rows(results, self._icon_for_search_result))
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

    def on_listView2_doubleClicked(self, index):
        source_index = self.search_proxy.mapToSource(index)
        name_index = self.search_model.index(source_index.row(), 0)
        filepath = name_index.data(Qt.UserRole + 1)
        if filepath and os.path.exists(filepath):
            if os.path.isdir(filepath):
                # 資料夾：在檔案面板開啟該目錄
                self._navigate_to_path(filepath)
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
        for view in (self.listView, self.listView2):
            if fw is view or fw is view.viewport():
                return view
        return None

    def _focused_shortcut_view(self):
        view = self._focused_file_view()
        return view if view in (self.listView, self.listView2) else None

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
            path = self.file_proxy.filePath(index) if view is self.listView else ""
            if path:
                paths.append(path)
        return paths

    def _delete_paths_to_recycle_bin(self, paths):
        """送回收筒。成功時順帶刷新兩個面板。"""
        outcome = shell_ops.delete_to_recycle_bin(int(self.winId()), paths)
        if not (outcome.ran and outcome.code == 0 and not outcome.aborted):
            return False
        self.refresh_mid_panel()
        # 刪除只會「移除」搜尋結果，不可能新增符合項，故一律走輕量的逐列存在性
        # 檢查，避免重跑整個 Everything 查詢並重建模型而造成 GUI 凍結。
        self._refresh_search_results_existence()
        return True

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
        self._clipboard_paths = clipboard.normalise(paths)
        return True

    def _copy_selected_paths_from_focused_view(self):
        view = self._focused_shortcut_view()
        if view is None:
            return False

        paths = self._get_selected_paths_for_view(view)
        if not paths:
            return False

        return self._set_clipboard_file_paths(paths, clipboard.COPY)

    def _cut_selected_paths_from_focused_view(self):
        view = self._focused_shortcut_view()
        if view is None:
            return False

        paths = self._get_selected_paths_for_view(view)
        if not paths:
            return False

        return self._set_clipboard_file_paths(paths, clipboard.MOVE)

    def _paste_into_current_dir_from_clipboard(self):
        # 鍵盤 Ctrl+V：需有清單取得焦點才貼上（與其他快捷鍵一致）
        if self._focused_shortcut_view() is None:
            return False
        return self._paste_clipboard_into_dir(self._current_dir())

    def _paste_from_toolbar(self):
        # 工具列「貼上」：一律貼到中間面板目前目錄，不要求某個清單有焦點
        return self._paste_clipboard_into_dir(self._current_dir())

    def _paste_clipboard_into_dir(self, target_dir):
        if not target_dir or not os.path.isdir(target_dir):
            return False

        board = QApplication.clipboard()
        mime = board.mimeData() if board is not None else None
        if mime is None or not mime.hasUrls():
            return False

        src_paths = clipboard.unique_paths(url.toLocalFile() for url in mime.urls())
        if not src_paths:
            return False

        op = clipboard.decide_paste_op(
            self._clipboard_file_op, self._clipboard_paths, src_paths)
        self.track_file_operation(src_paths, target_dir)
        self._perform_file_op(src_paths, target_dir, op)
        return True

    def _rename_selected_focused_item(self):
        view = self._focused_file_view()
        if view is None:
            return False

        if view in (self.listView, self.listView2):
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

    def _revert_search_item_text(self, item, text):
        """把該列的顯示文字還原，且不觸發自己這個改名處理。"""
        self._search_item_rename_in_progress = True
        item.setText(text)
        self._search_item_rename_in_progress = False

    def _on_search_result_name_changed(self, item):
        """搜尋面板就地改名。判定在 fileops.rename，這裡只負責做與呈現。"""
        if self._search_model_updating or self._search_item_rename_in_progress:
            return
        if item is None or item.column() != 0:
            return

        old_path = item.data(Qt.UserRole + 1)
        if not old_path or not os.path.exists(old_path):
            return
        old_name = os.path.basename(old_path)

        plan = rename.plan_rename(old_path, item.text())
        if plan.new_path is None:
            if plan.error:
                QMessageBox.warning(self, "重新命名失敗", plan.error)
            self._revert_search_item_text(item, old_name)
            return

        try:
            os.rename(old_path, plan.new_path)
        except Exception as ex:      # 維持搬移前的攔截範圍；要收窄請另開 commit
            QMessageBox.warning(self, "重新命名失敗", f"無法重新命名: {ex}")
            self._revert_search_item_text(item, old_name)
            return

        self._search_item_rename_in_progress = True
        item.setData(plan.new_path, Qt.UserRole + 1)
        item.setText(os.path.basename(plan.new_path))
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
        """顯示 Windows 原生右鍵選單，並接手它做不了的後續動作。"""
        outcome = shell_ops.show_context_menu(hwnd, paths, x, y)
        if outcome == shell_ops.CHOSE_RENAME:
            # Shell 的 rename 會送 WM_CLOSE 關掉主視窗，改走自己的 F2 流程。
            QTimer.singleShot(0, self._rename_selected_focused_item)
        elif outcome == shell_ops.INVOKED:
            QTimer.singleShot(800, after_fn if after_fn is not None
                              else self._refresh_search_results_existence)

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
        """右鍵拖放：交給 Shell 顯示原生選單並執行。失敗時退回自訂 Qt 選單。"""
        gpos = self.listView.viewport().mapToGlobal(viewport_pos)
        try:
            return shell_ops.right_drag_drop(int(self.winId()), src_paths, target_dir,
                                             gpos.x(), gpos.y())
        except Exception:
            traceback.print_exc()
            return self._fallback_right_drag_menu_fm(src_paths, target_dir, viewport_pos)

    def _fallback_right_drag_menu_fm(self, src_paths, target_dir, viewport_pos):
        """Shell IDropTarget 不可用時的後備 Qt 選單。"""
        action = drag_menu.ask_right_drag_action(
            self, self.listView.viewport().mapToGlobal(viewport_pos))
        if action == drag_menu.LINK:
            self._create_shortcuts_fm(src_paths, target_dir)
            return True
        if action is not drag_menu.CANCELLED:
            self._perform_file_op(src_paths, target_dir, action)
            return True
        return False

    def _create_shortcuts_fm(self, src_paths, target_dir):
        """在 target_dir 建立 src_paths 的 Windows 捷徑（.lnk）。"""
        try:
            shell_ops.create_shortcuts(src_paths, target_dir)
        except Exception as ex:
            QMessageBox.warning(self, "建立捷徑失敗", f"無法建立捷徑：{ex}")

    def _perform_file_op(self, src_paths, target_dir, op):
        """以 Windows shell 執行複製或移動。"""
        outcome = shell_ops.move_or_copy(int(self.winId()), src_paths, target_dir, op)
        if not outcome.ran:
            return
        if outcome.code != 0 and not outcome.aborted:
            QMessageBox.warning(self, "拖曳作業失敗",
                                f"Windows 檔案作業失敗，錯誤碼: {outcome.code}")
            return False
        if outcome.code == 0 and not outcome.aborted:
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
        path = self.mid_tab_bar.current_data()
        return path if path and os.path.isdir(path) else ""

    def _build_menu_bar(self):
        """建立視窗頂端的傳統功能表列（Alt+F 拉下「檔案」等）。"""
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("檔案(&F)")
        self.action_new_folder = file_menu.addAction("新增資料夾(&N)")
        self.action_new_folder.triggered.connect(self._create_folder_in_current_dir)
        self.action_new_tab = file_menu.addAction("新增分頁(&T)")
        self.action_new_tab.setShortcut(QKeySequence("Ctrl+T"))
        self.action_new_tab.triggered.connect(self._new_tab)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("離開(&X)")
        exit_action.triggered.connect(self.close)

        go_menu = menu_bar.addMenu("移至(&G)")
        self.action_back = go_menu.addAction("前一頁(&B)")
        self.action_back.setShortcut(QKeySequence("Alt+Left"))
        self.action_back.triggered.connect(self._navigate_back)
        self.action_forward = go_menu.addAction("後一頁(&F)")
        self.action_forward.setShortcut(QKeySequence("Alt+Right"))
        self.action_forward.triggered.connect(self._navigate_forward)
        self.action_up = go_menu.addAction("回到上一層目錄(&U)")
        self.action_up.setShortcut(QKeySequence("Alt+Up"))
        self.action_up.triggered.connect(self._navigate_up)

        view_menu = menu_bar.addMenu("檢視(&V)")
        self._layout_action_group = QActionGroup(self)
        self._layout_action_group.setExclusive(True)
        self.action_layout_horizontal = view_menu.addAction("左右排列(&H)")
        self.action_layout_horizontal.setCheckable(True)
        self._layout_action_group.addAction(self.action_layout_horizontal)
        self.action_layout_horizontal.triggered.connect(lambda: self._set_right_panel_layout(Qt.Orientation.Horizontal))
        self.action_layout_vertical = view_menu.addAction("上下排列(&V)")
        self.action_layout_vertical.setCheckable(True)
        self._layout_action_group.addAction(self.action_layout_vertical)
        self.action_layout_vertical.triggered.connect(lambda: self._set_right_panel_layout(Qt.Orientation.Vertical))

        view_menu.addSeparator()
        self.action_authors_panel = view_menu.addAction("顯示作者清單面板(&A)")
        self.action_authors_panel.setCheckable(True)
        self.action_authors_panel.setChecked(self._authors_panel_visible)
        # Ctrl+L 已被麵包屑的 focus_edit 佔用（見 path_bar 的快捷鍵註冊），
        # 兩者同綁會變成模稜兩可的快捷鍵而互相失效。
        self.action_authors_panel.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self.action_authors_panel.toggled.connect(self._set_authors_panel_visible)

        self.action_checker_panel = view_menu.addAction("顯示更新檢查器(&U)")
        self.action_checker_panel.setCheckable(True)
        self.action_checker_panel.setChecked(self._checker_panel_visible)
        self.action_checker_panel.setShortcut(QKeySequence("Ctrl+Shift+U"))
        self.action_checker_panel.toggled.connect(self._set_checker_panel_visible)

        # 「選項」為頂層選單，排在「檢視」右邊，底下提供「排除設定」項目。
        option_menu = menu_bar.addMenu("選項(&O)")
        self.action_exclude_settings = option_menu.addAction("排除設定(&E)…")
        self.action_exclude_settings.triggered.connect(self._open_exclude_dialog)

    def _new_tab(self):
        """依目前操作焦點，在對應面板最左邊新增一個空白分頁。

        焦點在搜尋清單→新增空白搜尋分頁；否則→新增顯示所有磁碟機的檔案分頁。
        分頁一律插入最左邊。
        """
        if self._active_panel == 'right':
            self.right_tab_bar.add_tab("", "", index=0)
        else:
            # 檔案分頁：資料為空，切換時由 _on_mid_tab_switched 顯示所有磁碟機。
            self.mid_tab_bar.add_tab("", "本機", index=0)

    def _switch_tab(self, delta):
        """在目前操作焦點所在的面板切換分頁（環狀）。

        delta=+1 下一個（Ctrl+PageDown）、-1 上一個（Ctrl+PageUp）；
        檔案面板與搜尋面板皆適用，依 _active_panel 決定作用對象。
        """
        tab_bar = (self.right_tab_bar if self._active_panel == 'right' else self.mid_tab_bar).tab_bar
        count = tab_bar.count()
        if count <= 1:
            return
        tab_bar.setCurrentIndex((tab_bar.currentIndex() + delta) % count)

    def _close_current_tab(self):
        """關閉目前操作焦點所在面板的目前分頁（至少保留一個）。

        檔案面板與搜尋面板皆適用，依 _active_panel 決定作用對象。
        """
        tab_widget = self.right_tab_bar if self._active_panel == 'right' else self.mid_tab_bar
        tab_widget.close_current_tab()

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
        if hasattr(self, 'action_layout_horizontal'):
            self.action_layout_horizontal.setChecked(horizontal_active)
        if hasattr(self, 'action_layout_vertical'):
            self.action_layout_vertical.setChecked(vertical_active)

    # ── 作者／團體面板與 Hermes 橋接 ────────────────────────────────────

    def _set_authors_panel_visible(self, visible):
        """切換左側作者清單面板；隱藏時即回復原本的雙面板版面。"""
        visible = bool(visible)
        if self.authors_panel is None or self.main_splitter is None:
            self._authors_panel_visible = visible
            return
        if not visible and self.authors_panel.isVisible():
            # 記住目前寬度，下次顯示時回到同樣位置。
            width = self.main_splitter.sizes()[0]
            if width > 0:
                self._authors_panel_width = width
        self._authors_panel_visible = visible
        self.authors_panel.setVisible(visible)
        if visible:
            self._apply_main_splitter_sizes()
        if hasattr(self, 'action_authors_panel'):
            self.action_authors_panel.setChecked(visible)

    def _apply_main_splitter_sizes(self):
        """重算三欄寬度：左作者面板、中間檔案區、右更新檢查器。

        必須一次給滿三個值。main_splitter 從兩欄變三欄之後，若還是只傳兩個，
        第三欄會被壓成 0 寬——切換左面板時右面板就無聲消失了。
        """
        if self.main_splitter is None:
            return
        total = sum(self.main_splitter.sizes())
        left = self._authors_panel_width if self._authors_panel_visible else 0
        right = self._checker_panel_width if self._checker_panel_visible else 0
        self.main_splitter.setSizes([left, max(total - left - right, 1), right])

    def _set_checker_panel_visible(self, visible):
        """切換右側更新檢查器面板。"""
        visible = bool(visible)
        if self.checker_panel is None or self.main_splitter is None:
            self._checker_panel_visible = visible
            return
        if not visible and self.checker_panel.isVisible():
            width = self.main_splitter.sizes()[2]
            if width > 0:
                self._checker_panel_width = width
        self._checker_panel_visible = visible
        self.checker_panel.setVisible(visible)
        if visible:
            self.checker_panel.refresh()
            self._apply_main_splitter_sizes()
        if hasattr(self, 'action_checker_panel'):
            self.action_checker_panel.setChecked(visible)

    def _toggle_checker_panel(self):
        self._set_checker_panel_visible(not self._checker_panel_visible)

    def _show_checker_status(self, message):
        """把檢查器的進度與錯誤送到狀態列。掃描一輪要半小時，得看得到進度。"""
        self.statusBar().showMessage(message, 15000)

    def _on_checker_detail_requested(self, gid):
        """在系統預設瀏覽器開啟檢查器的詳細清單。"""
        self.checker_panel.open_detail(gid)

    def _on_authors_search_requested(self, query):
        """點左面板的項目：在搜尋面板開一個新分頁並執行查詢。"""
        self._open_search_in_new_tab(query)

    def _open_search_in_new_tab(self, query):
        query = (query or '').strip()
        if not query:
            return False
        self._active_panel = 'right'
        self.right_tab_bar.add_tab(query, query, index=0)
        self.execute_search_command(query)
        return True

    def _open_search_tab_from_bridge(self, query):
        self._open_search_in_new_tab(query)
        self.raise_()
        self.activateWindow()

    def _start_bridge_server(self):
        """開啟給 Hermes MCP server 用的本機管道。

        多開時只有第一個實例佔得到管道名稱，其餘實例靜默略過（不搶）。
        """
        self._bridge_server = gui_bridge.create_server(self._handle_bridge_command, self)

    def _handle_bridge_command(self, request):
        """處理管道指令。在 Qt 主執行緒被呼叫，可直接操作 UI。"""
        command = (request or {}).get('cmd')
        if command == 'ping':
            return {'ok': True, 'pid': os.getpid()}
        if command == 'open_search_tab':
            query = (request.get('query') or '').strip()
            if not query:
                return {'ok': False, 'reason': 'empty_query'}
            # 搜尋是同步的（Everything 查詢加上結果模型重建可達數秒），若在這裡
            # 跑完才回應，呼叫端會先撞到逾時。改為排程到下一次事件迴圈再執行，
            # 立刻回覆「已接受」。
            QTimer.singleShot(0, lambda: self._open_search_tab_from_bridge(query))
            return {'ok': True, 'query': query}
        if command == 'authors_changed':
            if self.authors_panel is not None:
                self.authors_panel.reload()
            return {'ok': True}
        return {'ok': False, 'reason': 'unknown_command', 'cmd': command}

    def _sync_breadcrumb(self, path):
        if getattr(self, 'path_bar', None) is None:
            return
        text = path or self.mid_tab_bar.current_data() or ""
        self.path_bar.set_path(text)

    def _sync_tab_bar_heights(self):
        """兩個頁籤列共用同一高度，避免右側因自身 sizeHint 較大而變高。"""
        base_height = max(self.mid_tab_bar.tab_bar.sizeHint().height(), 22)
        for tab_container in (self.mid_tab_bar, self.right_tab_bar):
            tab_container.sync_height(base_height)

    def _make_hline(self):
        """列與列之間的極淡水平分隔線。"""
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setStyleSheet("color: rgba(127, 127, 127, 0.30);")
        line.setFixedHeight(1)
        return line

    def _sync_right_header_spacing(self):
        """右側沒有工具列，補一段同高留白，讓右側頁籤垂直對齊左側頁籤列。"""
        if self.right_splitter is not None and self.right_splitter.orientation() == Qt.Orientation.Vertical:
            spacer_height = 0
        else:
            # 左側頁籤列上方有「工具列 + 分隔線 + 麵包屑 + 分隔線」，右側補相同總高才對齊
            # 工具列已固定高度（與左側作者面板工具列對齊），此時 sizeHint 會小於
            # 實際高度，只看 sizeHint 會讓右側頁籤列短一截而對不齊。
            spacer_height = max(self.mid_panel_toolbar.sizeHint().height(),
                                self.mid_panel_toolbar.minimumHeight())
            if getattr(self, 'path_bar', None) is not None:
                # 麵包屑實際高度受 minimumHeight 影響，可能大於 sizeHint
                spacer_height += max(self.path_bar.sizeHint().height(), self.path_bar.minimumHeight())
            spacer_height += getattr(self, '_mid_header_extra', 0)
            spacer_height = max(spacer_height, 0)
        self.right_header_spacer.setFixedHeight(spacer_height)

    def _record_history(self, path):
        """記下一次導覽。走歷史（上一頁／下一頁）不會經過這裡（TAB-24）。"""
        if not path or not os.path.isdir(path):
            return
        self._nav_history.record(path)
        self._update_nav_buttons()

    def _update_nav_buttons(self):
        can_back = self._nav_history.can_go_back
        can_forward = self._nav_history.can_go_forward
        current_dir = self._current_dir()
        can_up = history.parent_of(current_dir) is not None
        can_new_folder = bool(current_dir)
        buttons = getattr(self, 'mid_nav_buttons', [])
        if len(buttons) >= 4:
            buttons[0].setEnabled(can_back)
            buttons[1].setEnabled(can_forward)
            buttons[2].setEnabled(can_up)
            buttons[3].setEnabled(can_new_folder)
        if hasattr(self, 'action_back'):
            self.action_back.setEnabled(can_back)
            self.action_forward.setEnabled(can_forward)
            self.action_up.setEnabled(can_up)
            self.action_new_folder.setEnabled(can_new_folder)
        # 導覽後目前目錄改變，貼上目標也跟著變 → 一併刷新操作按鈕灰階
        self._update_action_buttons_state()

    def _setup_action_buttons_state(self):
        """掛上會影響操作按鈕可用性的訊號：焦點切換、兩面板選取變化、剪貼簿內容變化。"""
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(lambda *_: self._update_action_buttons_state())
        for view in (self.listView, self.listView2):
            sel = view.selectionModel() if view is not None else None
            if sel is not None:
                sel.selectionChanged.connect(lambda *_: self._update_action_buttons_state())
        board = QApplication.clipboard()
        if board is not None:
            board.dataChanged.connect(self._update_action_buttons_state)
        self._update_action_buttons_state()

    def _update_action_buttons_state(self):
        """依目前焦點面板的選取與剪貼簿內容，更新操作按鈕的灰階狀態（重新整理永遠可用）。"""
        if not hasattr(self, 'act_cut'):
            return
        view = self._focused_file_view()
        paths = self._get_selected_paths_for_view(view) if view is not None else []
        has_selection = bool(paths)
        single_selection = len(paths) == 1
        board = QApplication.clipboard()
        mime = board.mimeData() if board is not None else None
        can_paste = bool(mime and mime.hasUrls()) and bool(self._current_dir())
        self.act_cut.setEnabled(has_selection)
        self.act_copy.setEnabled(has_selection)
        self.act_rename.setEnabled(single_selection)
        self.act_delete.setEnabled(has_selection)
        self.act_paste.setEnabled(can_paste)

    def _show_all_drives(self):
        """在檔案清單顯示所有磁碟機（本機根目錄），供空白檔案分頁預設呈現。"""
        if self.fileListModel is None or self.listView is None:
            return
        self.fileListModel.setRootPath("")
        self.fileListModel.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
        root_index = self.fileListModel.index("")
        self.listView.setRootIndex(self.file_proxy.mapFromSource(root_index))
        self.mid_tab_bar.set_current_data("", "本機")
        self.mid_info_combo.lineEdit().setText("")
        self._update_nav_buttons()

    def _navigate_to_path(self, path, record_history=True):
        if not path or not os.path.isdir(path):
            self._update_nav_buttons()
            return

        self.fileListModel.setRootPath(path)
        self.fileListModel.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
        root_index = self.fileListModel.index(path)
        self.listView.setRootIndex(self.file_proxy.mapFromSource(root_index))
        self._watch_mid_dir(path)

        self.mid_tab_bar.set_current_data(path, path)
        self.mid_info_combo.lineEdit().setText(path)
        self._sync_breadcrumb(path)

        if record_history:
            self._record_history(path)
        else:
            self._update_nav_buttons()

    def _navigate_back(self):
        path = self._nav_history.go_back()
        if path:
            self._navigate_to_path(path, record_history=False)

    def _navigate_forward(self):
        path = self._nav_history.go_forward()
        if path:
            self._navigate_to_path(path, record_history=False)

    def _navigate_up(self):
        parent_dir = history.parent_of(self._current_dir())
        if parent_dir and os.path.isdir(parent_dir):
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

    def _apply_font_size(self, new_size):
        """把字級套用到整個應用程式。

        遞迴走訪整棵 widget 樹，不是逐一列舉。列舉法必須有人記得維護，
        作者面板與更新檢查器已經各漏過一次（見 app/font_scaling.py）。
        """
        # 必須先取：遞迴一跑，listView 的字級就變了。
        old_size = self._current_font_size()
        if new_size == old_size:
            return
        font_scaling.apply(self, old_size, new_size)
        # 工具列高度是釘死的，不重算就會把放大後的按鈕文字裁掉。
        font_scaling.sync_toolbar_heights(self)

        # 以下都是遞迴蓋不到的：設了 stylesheet 而阻斷傳播的、需要重繪的、
        # 以及自己帶特殊規則的面板。必須在遞迴之後跑，才不會被遞迴蓋掉。
        for tab_container in (self.mid_tab_bar, self.right_tab_bar):
            tab_container.tab_bar.update()
        self._sync_right_header_spacing()
        self._sync_tab_bar_heights()

        if getattr(self, 'path_bar', None) is not None:
            # 位址列與其中的按鈕、編輯框各自設了 stylesheet，Qt 視其字型為已明確
            # 指定，父層字型不再傳下去，必須由它自己逐一套用（見
            # BreadcrumbBar.apply_font）。導覽後重建的麵包屑也要繼承。
            self.path_bar.apply_font(QFont(self.path_bar.font().family(), new_size))
            self.path_bar.set_path(self._current_dir())
        # 這兩個面板的內部有刻意的相對差距（計數列大一級、執行紀錄等寬且小一級、
        # 下限 8pt），由它們自己決定。
        if getattr(self, 'authors_panel', None) is not None:
            self.authors_panel.apply_font_size(new_size)
        if getattr(self, 'checker_panel', None) is not None:
            self.checker_panel.apply_font_size(new_size)

        # 位址列高度隨字型改變，須在它更新後再算一次右側留白，否則右側頁籤列
        # 會沿用舊高度而與左側錯開幾個像素。
        self._sync_right_header_spacing()

    def on_font_increase(self):
        # 放大字型，各增加 1pt（限制最大 72pt）
        new_size = min(self._current_font_size() + 1, 72)
        self._apply_font_size(new_size)
        self.update_status_bar()

    def on_font_decrease(self):
        # 縮小字型，各減少 1pt（限制最小 6pt）
        new_size = max(self._current_font_size() - 1, 6)
        self._apply_font_size(new_size)
        self.update_status_bar()

    def update_status_bar(self):
        # 更新狀態列以顯示目前字型大小
        status = self.statusBar()
        if status is not None:
            status.showMessage(f"字型: {self._current_font_size()}pt")

    def _current_font_size(self):
        font = self.listView.font()
        return font.pointSize() if font.pointSize() > 0 else 10

    # ---- 欄位顯示切換 -------------------------------------------------------
    def _column_views(self):
        """設定檔鍵名前綴 → 對應面板；兩面板的欄位顯示設定彼此獨立。"""
        return (('mid', self.listView), ('right', self.listView2))

    def _setup_column_visibility_menus(self):
        """兩個面板的表頭掛上右鍵選單，整條表頭（含右側空白區）皆可觸發。"""
        for key, view in self._column_views():
            header = view.header()
            if header is None:
                continue
            header.setContextMenuPolicy(Qt.CustomContextMenu)
            header.customContextMenuRequested.connect(
                lambda pos, k=key, v=view: self._show_column_menu(k, v, pos))

    def _show_column_menu(self, key, view, pos):
        menu = columns.build_column_visibility_menu(
            view,
            locked_columns=self.LOCKED_COLUMNS,
            on_toggled=lambda col, visible, k=key, v=view: self._set_column_visible(k, v, col, visible),
            parent=self,
        )
        header = view.header()
        if header is not None:
            menu.exec_(header.mapToGlobal(pos))

    def _set_column_visible(self, key, view, column, visible):
        """切換單一欄位的顯示狀態，並維護欄寬快取。

        隱藏欄位前先記下當下寬度；勾回來時若寬度為 0（例如舊版 config 對隱藏欄存下
        的 0），就補上記憶中的寬度或預設寬度，避免欄位「顯示了卻看不見」。
        排序不受影響：setColumnHidden 不會改動排序指示器，隱藏目前的排序欄只是箭頭
        暫時看不見，勾回來仍在原處。"""
        cache = self._col_width_cache.setdefault(key, {})
        if not visible:
            width = view.columnWidth(column)
            if width > 0:
                cache[column] = width
            view.setColumnHidden(column, True)
            return
        view.setColumnHidden(column, False)
        if view.columnWidth(column) <= 0:
            view.setColumnWidth(column, cache.get(column, self.DEFAULT_COLUMN_WIDTH))

    def _restore_columns(self, cfg, key, view):
        columns.restore(cfg, key, view, self._col_width_cache.setdefault(key, {}),
                        default_width=self.DEFAULT_COLUMN_WIDTH,
                        default_hidden=self.DEFAULT_HIDDEN_COLUMNS,
                        locked=self.LOCKED_COLUMNS)

    def _save_columns(self, cfg, key, view):
        columns.save(cfg, key, view, self._col_width_cache.setdefault(key, {}),
                     default_width=self.DEFAULT_COLUMN_WIDTH)

    def _config_path(self):
        return os.path.join(_runtime_root(), 'config.ini')

    def load_config(self):
        """從 config.ini 還原狀態。

        這裡只做編排：取值與型別轉換在 app/settings，套用到 widget 在這裡，
        面板內部的版面由面板自己的 restore_* 負責。
        """
        cfg = settings.ConfigStore.load(self._config_path())

        geometry = cfg.get_bytes('Layout', 'window_geometry')
        if geometry is not None:
            self.restoreGeometry(geometry)
        window_state = cfg.get_str('Layout', 'window_state', 'normal')
        if window_state == 'maximized':
            self.setWindowState(self.windowState() | Qt.WindowMaximized)
        elif window_state == 'fullscreen':
            self.setWindowState(self.windowState() | Qt.WindowFullScreen)

        self._apply_font_size(cfg.get_int('General', 'font_size', 10, minimum=6, maximum=72))
        self.update_status_bar()

        # 排除設定須在還原頁籤觸發搜尋之前就位，過濾才會生效
        self._exclude_enabled = cfg.get_bool('Exclude', 'enabled', False)
        excluded = cfg.get_json('Exclude', 'dirs', [])
        self._exclude_dirs = ([str(d) for d in excluded if d]
                              if isinstance(excluded, list) else [])
        self._apply_exclude_settings()

        # 兩種配置的分割尺寸各自保存。讀不到就沿用建構時的預設，不要覆蓋成空清單。
        for orientation, option in (
            (Qt.Orientation.Horizontal, 'right_splitter_sizes'),
            (Qt.Orientation.Vertical, 'right_splitter_vertical_sizes'),
        ):
            sizes = cfg.get_int_list('Layout', option)
            if sizes:
                self._right_splitter_sizes_by_orientation[orientation] = sizes
        orientation = cfg.get_str('Layout', 'right_splitter_orientation', 'horizontal').lower()
        self._set_right_panel_layout(Qt.Orientation.Vertical if orientation == 'vertical'
                                     else Qt.Orientation.Horizontal)

        self._authors_panel_width = cfg.get_int('Layout', 'authors_panel_width', 660, minimum=80)
        self._set_authors_panel_visible(cfg.get_bool('Layout', 'authors_panel_visible', True))

        # 更新檢查器：外層寬度與顯隱由主視窗管，面板內部的 splitter 與欄寬
        # 由面板自己還原（見 CheckerPanel.restore_layout）。
        self._checker_panel_width = cfg.get_int('Layout', 'checker_panel_width', 520, minimum=80)
        self._set_checker_panel_visible(cfg.get_bool('Layout', 'checker_panel_visible', False))
        if self.checker_panel is not None:
            self.checker_panel.restore_layout(
                split=cfg.get_int_list('Layout', 'checker_split_sizes'),
                columns=cfg.get_int_list('Layout', 'checker_col_widths'))

        for key, view in self._column_views():
            self._restore_columns(cfg, key, view)

        for key, view in (('mid', self.listView), ('right', self.listView2)):
            column = cfg.get_int('Sort', f'{key}_sort_column', -1)
            order = cfg.get_int('Sort', f'{key}_sort_order', -1)
            if column >= 0 and order >= 0:
                view.sortByColumn(column, Qt.SortOrder.AscendingOrder if order == 0
                                  else Qt.SortOrder.DescendingOrder)

        for key, tab_widget in (('mid', self.mid_tab_bar), ('right', self.right_tab_bar)):
            tabs = cfg.get_json('Tabs', f'{key}_tabs', None)
            if isinstance(tabs, list) and tabs:
                try:
                    tab_widget.restore_tabs([(d, l) for d, l in tabs],
                                            cfg.get_int('Tabs', f'{key}_tabs_current', 0))
                except (TypeError, ValueError):
                    pass

        # restore_tabs 不觸發 tab_switched，兩個面板的內容都得在這裡主動補上
        # （見 docs/spec/settings.md 的 SET-12）。
        initial_dir = self.mid_tab_bar.current_data()
        if initial_dir and os.path.isdir(initial_dir):
            QTimer.singleShot(0, lambda d=initial_dir: self._navigate_to_path(d))
        else:
            QTimer.singleShot(0, self._show_all_drives)

        initial_keyword = self.right_tab_bar.current_data()
        if initial_keyword:
            self.right_info_combo.lineEdit().setText(initial_keyword)
            QTimer.singleShot(0, lambda kw=initial_keyword: self._do_search(kw))

        self._sync_breadcrumb(self.mid_tab_bar.current_data())

        history = cfg.get_json('General', 'search_history', [])
        if isinstance(history, list):
            self.right_info_combo.blockSignals(True)
            for item in reversed(history):      # reversed 使最新的在頂
                self.right_info_combo.insertItem(0, item)
            self.right_info_combo.blockSignals(False)

    def save_config(self):
        """將目前狀態寫入 config.ini。"""
        cfg = settings.ConfigStore.load(self._config_path())

        cfg.set_bool('Exclude', 'enabled', self._exclude_enabled)
        cfg.set_json('Exclude', 'dirs', self._exclude_dirs)

        history = [self.right_info_combo.itemText(i)
                   for i in range(self.right_info_combo.count())]
        cfg.set_json('General', 'search_history', history[:20])   # 最多留 20 筆
        cfg.set('General', 'font_size', self._current_font_size())

        cfg.set_bytes('Layout', 'window_geometry', self.saveGeometry().data())
        if self.isFullScreen():
            window_state = 'fullscreen'
        elif self.isMaximized():
            window_state = 'maximized'
        else:
            window_state = 'normal'
        cfg.set('Layout', 'window_state', window_state)

        current_orientation = self.right_splitter.orientation()
        self._right_splitter_sizes_by_orientation[current_orientation] = self.right_splitter.sizes()
        cfg.set('Layout', 'right_splitter_orientation',
                'vertical' if current_orientation == Qt.Orientation.Vertical else 'horizontal')
        cfg.set_int_list('Layout', 'right_splitter_sizes',
                         self._right_splitter_sizes_by_orientation.get(Qt.Orientation.Horizontal, []))
        cfg.set_int_list('Layout', 'right_splitter_vertical_sizes',
                         self._right_splitter_sizes_by_orientation.get(Qt.Orientation.Vertical, []))

        # 面板隱藏時 main_splitter 給的寬度是 0，沿用先前記住的值
        for index, visible_attr, width_attr, prefix in (
            (0, '_authors_panel_visible', '_authors_panel_width', 'authors_panel'),
            (2, '_checker_panel_visible', '_checker_panel_width', 'checker_panel'),
        ):
            if self.main_splitter is not None and getattr(self, visible_attr):
                width = self.main_splitter.sizes()[index]
                if width > 0:
                    setattr(self, width_attr, width)
            cfg.set_bool('Layout', f'{prefix}_visible', getattr(self, visible_attr))
            cfg.set('Layout', f'{prefix}_width', getattr(self, width_attr))

        if self.checker_panel is not None:
            state = self.checker_panel.layout_state()
            cfg.set_int_list('Layout', 'checker_split_sizes', state['split'])
            cfg.set_int_list('Layout', 'checker_col_widths', state['columns'])

        for key, view in self._column_views():
            self._save_columns(cfg, key, view)

        for key, view in (('mid', self.listView), ('right', self.listView2)):
            header = view.header()
            if header is not None:
                cfg.set('Sort', f'{key}_sort_column', header.sortIndicatorSection())
                cfg.set('Sort', f'{key}_sort_order', int(header.sortIndicatorOrder()))

        for key, tab_widget in (('mid', self.mid_tab_bar), ('right', self.right_tab_bar)):
            tabs, current = tab_widget.get_all_tabs()
            cfg.set_json('Tabs', f'{key}_tabs', tabs)
            cfg.set('Tabs', f'{key}_tabs_current', current)

        cfg.save()

    def closeEvent(self, event):
        self.save_config()
        if self._bridge_server is not None:
            self._bridge_server.close()
            self._bridge_server = None
        if self.authors_panel is not None:
            self.authors_panel.close_db()
        if self.checker_panel is not None:
            # 掃描執行緒還在跑時直接關視窗，Qt 會硬砍執行緒，可能留下半寫入的
            # 交易。先送出取消再等它收尾。
            self.checker_panel.shutdown()
        super().closeEvent(event)


def main():
    # 保持參考避免被 GC；log 檔需在整個行程期間開啟供 faulthandler 寫入。
    _crash_log = crashlog.install()  # noqa: F841
    app = QApplication(sys.argv)
    icon_path = os.path.join(_bundle_root(), 'icon.ico')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = FileManager()
    window.show()
    sys.exit(app.exec_())
