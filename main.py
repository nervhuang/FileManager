import sys
import subprocess
import os
import shutil
import ctypes
import ctypes.wintypes as wt
import struct
import time
import configparser
from PyQt5.QtWidgets import QApplication, QMainWindow, QTreeView, QFileSystemModel, QListView, QWidget, QHBoxLayout, QVBoxLayout, QToolBar, QAction, QMessageBox, QStyle, QToolButton, QSplitter, QLineEdit, QSizePolicy, QFileIconProvider
from PyQt5.QtCore import QDir, Qt, QSize, QSortFilterProxyModel, QFileInfo
from PyQt5.QtGui import QKeySequence, QIcon, QFont, QPixmap, QPainter, QColor, QPalette, QStandardItemModel, QStandardItem
from datetime import datetime
# Optional SVG renderer (may not be present in minimal PyQt installs)
try:
    from PyQt5.QtSvg import QSvgRenderer
    HAVE_SVG_RENDERER = True
except Exception:
    QSvgRenderer = None
    HAVE_SVG_RENDERER = False

ref_s = 0
ref_e = 1
global_keywords = []


class EverythingSDK:
    """Everything IPC client supporting both 1.5a (pure IPC2) and 1.4 (DLL)."""

    WM_COPYDATA = 0x004A
    EVERYTHING_IPC_COPYDATA_QUERY2W = 18
    EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME = 0x00000004

    # Window class names for different Everything versions
    _IPC_WNDCLASS_15A = "EVERYTHING_TASKBAR_NOTIFICATION_(1.5a)"
    _IPC_WNDCLASS_14 = "EVERYTHING_TASKBAR_NOTIFICATION"

    def __init__(self):
        self._setup_winapi()
        self._ipc_results = []
        self._ipc_got_reply = False
        self._wndproc_ref = self._WNDPROCTYPE(self._wnd_proc)

    def _setup_winapi(self):
        """Configure ctypes signatures for Windows API calls."""
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32

        self._kernel32.GetModuleHandleW.restype = wt.HMODULE
        self._kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        self._user32.FindWindowW.restype = wt.HWND
        self._user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
        self._user32.DefWindowProcW.restype = ctypes.c_longlong
        self._user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong]
        self._user32.SendMessageW.restype = ctypes.c_longlong
        self._user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong]
        self._user32.PeekMessageW.restype = wt.BOOL
        self._user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
        self._user32.CreateWindowExW.argtypes = [
            wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p
        ]
        self._user32.CreateWindowExW.restype = wt.HWND
        self._user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]

    class _COPYDATASTRUCT(ctypes.Structure):
        _fields_ = [
            ("dwData", ctypes.c_ulonglong),
            ("cbData", wt.DWORD),
            ("lpData", ctypes.c_void_p),
        ]

    _WNDPROCTYPE = ctypes.CFUNCTYPE(ctypes.c_longlong, wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong)

    class _WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wt.UINT), ("style", wt.UINT),
            ("lpfnWndProc", ctypes.CFUNCTYPE(ctypes.c_longlong, wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong)),
            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
            ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
            ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
            ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON),
        ]

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """Window procedure to receive IPC2 reply from Everything."""
        if msg == self.WM_COPYDATA:
            pCds = ctypes.cast(lparam, ctypes.POINTER(self._COPYDATASTRUCT))
            cds = pCds.contents
            if cds.cbData > 0 and cds.lpData:
                raw = (ctypes.c_ubyte * cds.cbData).from_address(cds.lpData)
                data = bytes(raw)
                self._parse_ipc2_response(data)
            self._ipc_got_reply = True
            return 1
        return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _parse_ipc2_response(self, data):
        """Parse EVERYTHING_IPC_LIST2 response data."""
        if len(data) < 20:
            return
        totitems, numitems, offset, req_flags, sort_type = struct.unpack_from('<IIIII', data, 0)
        items_start = 20
        for i in range(numitems):
            item_off = items_start + i * 8
            if item_off + 8 > len(data):
                break
            flags, data_offset = struct.unpack_from('<II', data, item_off)
            if data_offset + 4 > len(data):
                continue
            str_len_chars = struct.unpack_from('<I', data, data_offset)[0]
            str_start = data_offset + 4
            str_bytes = str_len_chars * 2
            if str_start + str_bytes <= len(data):
                full_path = data[str_start:str_start + str_bytes].decode('utf-16-le', errors='replace')
                self._ipc_results.append(full_path)

    def _find_everything_hwnd(self):
        """Find Everything IPC window (1.5a or 1.4)."""
        hwnd = self._user32.FindWindowW(self._IPC_WNDCLASS_15A, None)
        if hwnd:
            return hwnd
        hwnd = self._user32.FindWindowW(self._IPC_WNDCLASS_14, None)
        return hwnd

    def is_available(self):
        return bool(self._find_everything_hwnd())

    def query(self, search_text, max_results=200):
        """Query Everything via IPC2 (WM_COPYDATA)."""
        self._ipc_results = []
        self._ipc_got_reply = False

        everything_hwnd = self._find_everything_hwnd()
        if not everything_hwnd:
            return []

        hInst = self._kernel32.GetModuleHandleW(None)
        cls_name = f"EvIPC{time.time_ns()}"

        wc = self._WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(self._WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hInst
        wc.lpszClassName = cls_name
        self._user32.RegisterClassExW(ctypes.byref(wc))

        reply_hwnd = self._user32.CreateWindowExW(
            0, cls_name, "R", 0, 0, 0, 0, 0, None, None, hInst, None
        )
        if not reply_hwnd:
            try:
                self._user32.UnregisterClassW(cls_name, hInst)
            except Exception:
                pass
            return []

        # Build EVERYTHING_IPC_QUERY2: reply_hwnd, reply_msg, search_flags, offset, max, req_flags, sort
        search_bytes = search_text.encode('utf-16-le') + b'\x00\x00'
        reply_hwnd_32 = reply_hwnd & 0xFFFFFFFF
        header = struct.pack('<IIIIIII', reply_hwnd_32, 0, 0, 0, max_results,
                             self.EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME, 1)
        query_data = header + search_bytes
        data_buf = ctypes.create_string_buffer(query_data)

        cds = self._COPYDATASTRUCT()
        cds.dwData = self.EVERYTHING_IPC_COPYDATA_QUERY2W
        cds.cbData = len(query_data)
        cds.lpData = ctypes.cast(data_buf, ctypes.c_void_p)

        result = self._user32.SendMessageW(
            everything_hwnd, self.WM_COPYDATA, reply_hwnd, ctypes.addressof(cds)
        )

        if result:
            msg = wt.MSG()
            end_time = time.time() + 5
            while time.time() < end_time and not self._ipc_got_reply:
                ret = self._user32.PeekMessageW(ctypes.byref(msg), reply_hwnd, 0, 0, 1)
                if ret:
                    self._user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.01)

        self._user32.DestroyWindow(reply_hwnd)
        try:
            self._user32.UnregisterClassW(cls_name, hInst)
        except Exception:
            pass

        return list(self._ipc_results)


class CustomTreeView(QTreeView):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.expanded_indexes = set()
        self.expanding_in_progress = False

    def mouseDoubleClickEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid() and index not in self.expanded_indexes:
            self.setExpanded(index, not self.isExpanded(index))
            self.expanded_indexes.add(index)

    def setExpanded(self, index, expanded):
        if not self.expanding_in_progress:
            self.expanding_in_progress = True
            super().setExpanded(index, expanded)
            self.expanding_in_progress = False


class SearchSortProxyModel(QSortFilterProxyModel):
    """Proxy model for proper numeric sorting on date and size columns."""
    def lessThan(self, left, right):
        col = left.column()
        if col in (2, 3):  # Date or Size columns
            left_val = left.data(Qt.UserRole)
            right_val = right.data(Qt.UserRole)
            if left_val is not None and right_val is not None:
                return left_val < right_val
        return super().lessThan(left, right)


class FileManager(QMainWindow):
    def __init__(self):
        super().__init__()

        self.everything = EverythingSDK()
        self.search_model = None
        self.sdk_warned = False
        self.initUI()

    def initUI(self):
        self.setWindowTitle("文件管理器")
        self.setGeometry(100, 100, 800, 600)

        # 创建左侧的目录树视图
        self.treeView = CustomTreeView(self)
        self.treeView.setHeaderHidden(True)

        # 设置左侧目录树的根目录为计算机的顶级目录
        root_path = ""
        self.model = QFileSystemModel()
        self.model.setRootPath(root_path)

        # 只显示目录和磁盘驱动器，不显示目录属性
        self.model.setFilter(QDir.Dirs | QDir.Drives | QDir.NoDotAndDotDot)

        self.treeView.setModel(self.model)
        root_idx = self.model.index(root_path)
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

        # 使用 QToolBar（橫跨左右兩側）並加入快捷鍵與事件
        self.toolbar = QToolBar("Main Toolbar", self)
        self.addToolBar(self.toolbar)
        # 設定圖示大小與 icon-only 顯示
        self.toolbar.setIconSize(QSize(24, 24))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        # 簡單 hover 效果，並讓按鈕與主題顏色相容
        self.toolbar.setStyleSheet('QToolButton { padding: 4px; } QToolButton:hover { background-color: rgba(0,0,0,0.05); }')

        # 前兩個按鈕改為直接調整字型大小（放大 / 縮小）
        action_new = QAction("字型放大", self)
        action_new.setShortcut(QKeySequence("Ctrl+N"))
        action_new.setToolTip("放大字型 (Ctrl+N)")
        action_new.triggered.connect(self.on_font_increase)

        action_open = QAction("字型縮小", self)
        action_open.setShortcut(QKeySequence("Ctrl+O"))
        action_open.setToolTip("縮小字型 (Ctrl+O)")
        action_open.triggered.connect(self.on_font_decrease)

        # 嘗試從 resources/icons 載入自訂圖示；若不存在或無法載入 SVG，會 fallback 或動態繪製一個文字圖示
        icons_dir = os.path.join(os.path.dirname(__file__), "resources", "icons")
        def make_text_icon(ch, font_size=14, color="#222"):
            size = self.toolbar.iconSize()
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
            size = self.toolbar.iconSize()
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
                        pm = icon.pixmap(self.toolbar.iconSize())
                        if pm and not pm.isNull():
                            return icon
                    pix = QPixmap(path)
                    if not pix.isNull():
                        pm = pix.scaled(
                            self.toolbar.iconSize(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        return QIcon(pm)
                    if HAVE_SVG_RENDERER and QSvgRenderer is not None:
                        renderer = QSvgRenderer(path)
                        size = self.toolbar.iconSize()
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

        action_new.setIcon(load_icon('A_large', QStyle.StandardPixmap.SP_FileIcon))
        action_open.setIcon(load_icon('A_small', QStyle.StandardPixmap.SP_DialogOpenButton))

        # 使用 QToolButton 並將其明確命名（以便後續啟用/停用）
        self.btn_increase = QToolButton(self)
        self.btn_increase.setDefaultAction(action_new)
        self.btn_increase.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_increase.setIconSize(self.toolbar.iconSize())
        self.btn_increase.setAutoRaise(True)
        self.toolbar.addWidget(self.btn_increase)

        self.btn_decrease = QToolButton(self)
        self.btn_decrease.setDefaultAction(action_open)
        self.btn_decrease.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_decrease.setIconSize(self.toolbar.iconSize())
        self.btn_decrease.setAutoRaise(True)
        self.toolbar.addWidget(self.btn_decrease)

        # 创建右侧的文件列表视图
        self.listView = QTreeView(self)
        self.listView.setSortingEnabled(True)
        self.listView2 = QTreeView(self)
        self.listView2.setSortingEnabled(True)

        self.mid_container = QWidget()
        mid_vbox = QVBoxLayout()
        mid_vbox.setContentsMargins(0, 0, 0, 0)
        mid_vbox.setSpacing(0)
        mid_vbox.addWidget(self.listView, 1)
        self.mid_container.setLayout(mid_vbox)

        self.right_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.right_splitter.addWidget(self.mid_container)
        self.right_splitter.addWidget(self.listView2)
        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 1)

        right_container = QWidget()
        right_vbox = QVBoxLayout()
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.addWidget(self.right_splitter)
        right_container.setLayout(right_vbox)

        # 创建一个可调整大小的分割器
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.treeView)
        self.splitter.addWidget(right_container)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([200, 600])

        self.setCentralWidget(self.splitter)

        # 初始化狀態列並顯示目前字型大小
        status = self.statusBar()
        if status is not None:
            status.showMessage("")

        self.list_input = QLineEdit(self)
        self.list_input.setPlaceholderText("Input text")
        self.list_input.setFixedHeight(self.toolbar.iconSize().height() + 8)
        self.list_input.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.toolbar_spacer = QWidget(self)
        self.toolbar_spacer.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.toolbar.addWidget(self.toolbar_spacer)
        self.toolbar.addWidget(self.list_input)
        self.right_splitter.splitterMoved.connect(self._update_toolbar_input)
        self.splitter.splitterMoved.connect(self._update_toolbar_input)
        self._update_toolbar_input()


        # 设置右侧文件列表的模型
        self.fileListModel = QFileSystemModel()
        self.listView.setModel(self.fileListModel)
        self.search_model = QStandardItemModel(self.listView2)
        self.search_model.setHorizontalHeaderLabels(["檔名", "目錄", "日期", "大小"])
        self.search_proxy = SearchSortProxyModel(self.listView2)
        self.search_proxy.setSourceModel(self.search_model)
        self.listView2.setModel(self.search_proxy)

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

        # 设置默认排序为日期排序
        self.listView.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self.listView2.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        # 连接目录树的项选择事件到显示文件列表的函数
        tree_selection = self.treeView.selectionModel()
        if tree_selection is not None:
            tree_selection.selectionChanged.connect(self.on_treeView_selectionChanged)

        # 載入 config.ini 並還原上次狀態
        self.load_config()

    def on_treeView_selectionChanged(self, selected, deselected):
        # 当左侧目录树中的项被选择时，更新右侧文件列表
        if selected.indexes():
            path = self.model.filePath(selected.indexes()[0])

            # 设置右侧文件列表的模型，再次确保不显示目录属性
            self.fileListModel.setRootPath(path)
            self.fileListModel.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)

            root_index = self.fileListModel.index(path)
            self.listView.setRootIndex(root_index)
            self.treeView.resizeColumnToContents(0)  # 自动调整列宽

    def on_listView_clicked(self, index):
        """处理中央视窗文件单击事件"""
        global ref_s, ref_e, global_keywords
        
        if not self.fileListModel.isDir(index):
            file_name = self.fileListModel.fileName(index)
            keywords = self.extract_keywords(file_name)
            global_keywords = keywords
            
            if keywords:
                ref_s = 0
                ref_e = len(keywords)
                search_command = '|'.join(keywords)
                self.execute_search_command(search_command)


    def on_listView_doubleClicked(self, index):
        path = self.fileListModel.filePath(index)
        if self.fileListModel.isDir(index):
            self.listView.setRootIndex(index)
            tree_index = self.model.index(path)
            if tree_index.isValid():
                self.treeView.setCurrentIndex(tree_index)
                self.treeView.expand(tree_index)
                self.treeView.scrollTo(tree_index)
        else:
            try:
                os.startfile(path)
            except Exception as e:
                QMessageBox.warning(self, "錯誤", f"無法開啟檔案: {e}")
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_toolbar_input()

    def _update_toolbar_input(self):
        if self.list_input is None or self.toolbar_spacer is None:
            return
        buttons_width = 0
        for btn in (self.btn_increase, self.btn_decrease):
            if btn is not None:
                buttons_width += btn.sizeHint().width()

        target_left = self.treeView.width()
        spacer_width = max(target_left - buttons_width, 0)
        self.toolbar_spacer.setFixedWidth(spacer_width)

    def keyPressEvent(self, e):
        global ref_s, ref_e, global_keywords
        # 参数超过一个以上才能缩减
        if ref_e - ref_s > 0:
            if e.key() == Qt.Key.Key_F3:
                # 开头指针向后移一格
                ref_s = ref_s + 1

            if e.key() == Qt.Key.Key_F4:
                # 结尾指表向前移一格
                ref_e = ref_e - 1

        # 有超过一个以上的参数，所以需要插入|
        if ref_e - ref_s > 0:
            # 参数指针初始化，开头设为0，结尾设为参数总数
            search_command = '|'.join(global_keywords[ref_s:ref_e])
            self.execute_search_command(search_command)

    def extract_keywords(self, file_name):
        # 自定义解析文件名以提取多个参数，只提取括号内的文字
        keywords = []
        stack = []
        is_inside_brackets = False

        for char in file_name:
            if char in "([{":
                if not is_inside_brackets:
                    is_inside_brackets = True
                elif stack:
                    keywords.append("".join(stack))
                    stack = []
            elif char in ")]}":
                is_inside_brackets = False
                if stack:
                    keywords.append("".join(stack))
                stack = []
            elif is_inside_brackets:
                stack.append(char)

        keywords = [keyword for keyword in keywords if keyword.strip()]
        return keywords

    def execute_search_command(self, search_command):
        # 使用 Everything SDK 查詢
        if self.everything.is_available():
            results = self.everything.query(search_command)
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

        search_command = '"Everything.exe" -search "' + search_command + '"'
        subprocess.Popen(search_command, shell=True)

    def update_search_results(self, results):
        if self.search_model is None:
            return
        self.search_model.removeRows(0, self.search_model.rowCount())
        icon_provider = QFileIconProvider()
        for filepath in results:
            name_item = QStandardItem(os.path.basename(filepath))
            name_item.setEditable(False)
            name_item.setData(filepath, Qt.UserRole + 1)
            name_item.setIcon(icon_provider.icon(QFileInfo(filepath)))

            dir_item = QStandardItem(os.path.dirname(filepath))
            dir_item.setEditable(False)

            try:
                mtime = os.path.getmtime(filepath)
                dt_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                mtime = 0
                dt_str = ''

            date_item = QStandardItem(dt_str)
            date_item.setEditable(False)
            date_item.setData(mtime, Qt.UserRole)

            try:
                if os.path.isdir(filepath):
                    size = 0
                    size_str = ''
                else:
                    size = os.path.getsize(filepath)
                    size_str = self._format_size(size)
            except Exception:
                size = 0
                size_str = ''

            size_item = QStandardItem(size_str)
            size_item.setEditable(False)
            size_item.setData(size, Qt.UserRole)

            self.search_model.appendRow([name_item, dir_item, date_item, size_item])

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
                tree_index = self.model.index(filepath)
                if tree_index.isValid():
                    self.treeView.setCurrentIndex(tree_index)
                    self.treeView.expand(tree_index)
                    self.treeView.scrollTo(tree_index)
            else:
                try:
                    os.startfile(filepath)
                except Exception as e:
                    QMessageBox.warning(self, "錯誤", f"無法開啟檔案: {e}")

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
        self.listView.setRootIndex(self.fileListModel.index(dir_path))

    def on_open(self):
        # 保留舊功能（用系統開啟檔案），但不再由工具列第二個按鈕觸發
        indexes = self.listView.selectedIndexes()
        if not indexes:
            return
        path = self.fileListModel.filePath(indexes[0])
        try:
            os.startfile(path)
        except Exception as e:
            QMessageBox.warning(self, "錯誤", f"無法開啟檔案: {e}")

    def on_font_increase(self):
        # 放大字型，各增加 1pt（限制最大 72pt）
        for widget in (self.treeView, self.listView):
            current_font = widget.font()
            current_size = current_font.pointSize() if current_font.pointSize() > 0 else 10
            new_size = min(current_size + 1, 72)
            f = QFont(current_font.family(), new_size)
            widget.setFont(f)
        self.update_status_bar()

    def on_font_decrease(self):
        # 縮小字型，各減少 1pt（限制最小 6pt）
        for widget in (self.treeView, self.listView):
            current_font = widget.font()
            current_size = current_font.pointSize() if current_font.pointSize() > 0 else 10
            new_size = max(current_size - 1, 6)
            f = QFont(current_font.family(), new_size)
            widget.setFont(f)
        self.update_status_bar()

    def update_status_bar(self):
        # 更新狀態列以顯示左側視圖的目前字型大小
        left_font = self.treeView.font()
        left_size = left_font.pointSize() if left_font.pointSize() > 0 else 10
        status = self.statusBar()
        if status is not None:
            status.showMessage(f"字型: {left_size}pt")

    def _config_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')

    def load_config(self):
        """從 config.ini 讀取參數並還原狀態。"""
        cfg = configparser.ConfigParser()
        cfg.read(self._config_path(), encoding='utf-8')

        # 還原左側目錄樹選取的目錄
        left_dir = cfg.get('General', 'left_dir', fallback='')
        if left_dir and os.path.isdir(left_dir):
            self.model.directoryLoaded.connect(lambda path, d=left_dir: self._try_select_dir(d))
            self.model.setRootPath(left_dir)

        # 還原分割器大小
        splitter_sizes = cfg.get('Layout', 'splitter_sizes', fallback='')
        if splitter_sizes:
            try:
                self.splitter.setSizes([int(x) for x in splitter_sizes.split(',')])
            except Exception:
                pass
        right_splitter_sizes = cfg.get('Layout', 'right_splitter_sizes', fallback='')
        if right_splitter_sizes:
            try:
                self.right_splitter.setSizes([int(x) for x in right_splitter_sizes.split(',')])
            except Exception:
                pass

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

    def _try_select_dir(self, dir_path):
        """嘗試在左側樹狀視圖中選取並展開指定目錄。"""
        idx = self.model.index(dir_path)
        if idx.isValid():
            self.treeView.setCurrentIndex(idx)
            self.treeView.scrollTo(idx)
            self.treeView.expand(idx)
            # 同時更新中間檔案列表
            self.fileListModel.setRootPath(dir_path)
            self.fileListModel.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
            self.listView.setRootIndex(self.fileListModel.index(dir_path))

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

        # 儲存左側目錄樹目前選取的目錄
        indexes = self.treeView.selectedIndexes()
        if indexes:
            left_dir = self.model.filePath(indexes[0])
        else:
            left_dir = ''
        cfg.set('General', 'left_dir', left_dir)

        # 儲存分割器大小
        cfg.set('Layout', 'splitter_sizes', ','.join(str(s) for s in self.splitter.sizes()))
        cfg.set('Layout', 'right_splitter_sizes', ','.join(str(s) for s in self.right_splitter.sizes()))

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

        with open(self._config_path(), 'w', encoding='utf-8') as f:
            cfg.write(f)

    def closeEvent(self, event):
        self.save_config()
        super().closeEvent(event)

def main():
    app = QApplication(sys.argv)
    window = FileManager()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
