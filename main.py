import sys
import subprocess
import os
import shutil
import ctypes
from PyQt5.QtWidgets import QApplication, QMainWindow, QTreeView, QFileSystemModel, QListView, QWidget, QHBoxLayout, QVBoxLayout, QToolBar, QAction, QMessageBox, QStyle, QToolButton, QSplitter, QLineEdit, QSizePolicy
from PyQt5.QtCore import QDir, Qt, QSize
from PyQt5.QtGui import QKeySequence, QIcon, QFont, QPixmap, QPainter, QColor, QPalette, QStandardItemModel, QStandardItem
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
    EVERYTHING_REQUEST_FILE_NAME = 0x00000001
    EVERYTHING_REQUEST_PATH = 0x00000002
    EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME = 0x00000004

    def __init__(self):
        self.dll = self._load_dll()
        if self.dll is None:
            return

        self.dll.Everything_SetSearchW.argtypes = [ctypes.c_wchar_p]
        self.dll.Everything_SetSearchW.restype = None
        self.dll.Everything_SetRequestFlags.argtypes = [ctypes.c_uint]
        self.dll.Everything_SetRequestFlags.restype = None
        self.dll.Everything_SetMax.argtypes = [ctypes.c_uint]
        self.dll.Everything_SetMax.restype = None
        self.dll.Everything_QueryW.argtypes = [ctypes.c_int]
        self.dll.Everything_QueryW.restype = ctypes.c_int
        self.dll.Everything_GetNumResults.argtypes = []
        self.dll.Everything_GetNumResults.restype = ctypes.c_uint
        self.dll.Everything_GetResultFullPathNameW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
        self.dll.Everything_GetResultFullPathNameW.restype = None

    def _load_dll(self):
        candidates = [
            os.path.join(os.path.dirname(__file__), "Everything64.dll"),
            os.path.join(os.path.dirname(__file__), "Everything32.dll"),
            os.path.join(os.path.dirname(__file__), "sdk", "Everything64.dll"),
            os.path.join(os.path.dirname(__file__), "sdk", "Everything32.dll"),
            "Everything64.dll",
            "Everything32.dll",
        ]
        for candidate in candidates:
            try:
                if os.path.isabs(candidate) and not os.path.exists(candidate):
                    continue
                return ctypes.WinDLL(candidate)
            except Exception:
                continue
        return None

    def is_available(self):
        return self.dll is not None

    def query(self, search_text, max_results=200):
        if not self.is_available():
            return []

        self.dll.Everything_SetSearchW(search_text)
        self.dll.Everything_SetRequestFlags(self.EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME)
        self.dll.Everything_SetMax(max_results)

        if not self.dll.Everything_QueryW(1):
            return []

        num = self.dll.Everything_GetNumResults()
        results = []
        buffer = ctypes.create_unicode_buffer(32768)
        for i in range(num):
            self.dll.Everything_GetResultFullPathNameW(i, buffer, len(buffer))
            results.append(buffer.value)
        return results


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
        self.search_model.setHorizontalHeaderLabels(["Everything results"])
        self.listView2.setModel(self.search_model)

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
        except Exception:
            pass

        # 设置默认排序为日期排序
        self.listView.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self.listView2.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        # 连接目录树的项选择事件到显示文件列表的函数
        tree_selection = self.treeView.selectionModel()
        if tree_selection is not None:
            tree_selection.selectionChanged.connect(self.on_treeView_selectionChanged)

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

            # 连接右侧文件列表的项选择事件到提取关键字的函数
            list_selection = self.listView.selectionModel()
            if list_selection is not None:
                list_selection.selectionChanged.connect(self.on_listView_selectionChanged)


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
    def on_listView_selectionChanged(self, selected, deselected):
        global ref_s, ref_e, global_keywords
        # 当右侧文件列表中的项被选择时，提取关键字并执行搜索操作
        if selected.indexes():
            index = selected.indexes()[0]
            if not self.fileListModel.isDir(index):
                file_name = self.fileListModel.fileName(index)
                keywords = self.extract_keywords(file_name)
                global_keywords = keywords
                # 有超过一个以上的参数，所以需要插入|
                if keywords:
                    # 参数指针初始化，开头设为0，结尾设为参数总数
                    ref_s = 0
                    ref_e = len(keywords)
                    search_command = '|'.join(keywords)
                    self.execute_search_command(search_command)

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
        # 使用 Everything SDK 查詢並更新右側第二個列表；若不可用則回退到 CLI
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
        for path in results:
            item = QStandardItem(path)
            item.setEditable(False)
            self.search_model.appendRow(item)

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

def main():
    app = QApplication(sys.argv)
    window = FileManager()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
