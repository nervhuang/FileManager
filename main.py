import sys
import subprocess
import argparse
from PyQt5.QtWidgets import QApplication, QMainWindow, QTreeView, QFileSystemModel, QListView, QWidget, QHBoxLayout
from PyQt5.QtCore import QDir, Qt, QTimer

ref_s = 0
ref_e = 1
global_keywords = []


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
        self.treeView.setRootIndex(self.model.index(root_path))
        self.treeView.hideColumn(1)
        self.treeView.hideColumn(2)
        self.treeView.hideColumn(3)

        # 创建右侧的文件列表视图
        self.listView = QListView(self)

        # 创建一个水平布局，包含左侧目录树和右侧文件列表
        hbox = QHBoxLayout()
        hbox.addWidget(self.treeView)
        hbox.addWidget(self.listView)

        # 创建一个主窗口小部件并设置布局
        centralWidget = QWidget()
        centralWidget.setLayout(hbox)
        self.setCentralWidget(centralWidget)

        # 设置右侧文件列表的模型
        self.fileListModel = QFileSystemModel()
        self.listView.setModel(self.fileListModel)

        # 设置默认排序为日期排序
        self.fileListModel.sort(3, Qt.DescendingOrder)

        # 连接目录树的项选择事件到显示文件列表的函数
        self.treeView.selectionModel().selectionChanged.connect(self.on_treeView_selectionChanged)

    def on_treeView_selectionChanged(self, selected, deselected):
        # 当左侧目录树中的项被选择时，更新右侧文件列表
        if selected.indexes():
            path = self.model.filePath(selected.indexes()[0])

            # 设置右侧文件列表的模型，再次确保不显示目录属性
            self.fileListModel.setRootPath(path)
            self.fileListModel.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)

            self.listView.setRootIndex(self.fileListModel.index(path))
            self.treeView.resizeColumnToContents(0)  # 自动调整列宽

            # 连接右侧文件列表的项选择事件到提取关键字的函数
            self.listView.selectionModel().selectionChanged.connect(self.on_listView_selectionChanged)

    def on_listView_selectionChanged(self, selected, deselected):
        global ref_s, ref_e, global_keywords
        # 当右侧文件列表中的项被选择时，提取关键字并执行搜索操作
        if selected.indexes():
            file_name = self.fileListModel.fileName(selected.indexes()[0])
            keywords = self.extract_keywords(file_name)
            global_keywords = keywords
            # 有超过一个以上的参数，所以需要插入|
            if keywords:
                # 参数指针初始化，开头设为0，结尾设为参数总数
                ref_s = 0
                ref_e = len(keywords)
                search_command = '|'.join(keywords)
                self.execute_search_command(search_command)

    def keyPressEvent(self, e):
        global ref_s, ref_e, global_keywords
        # 参数超过一个以上才能缩减
        if ref_e - ref_s > 0:
            if e.key() == Qt.Key_F3:
                # 开头指针向后移一格
                ref_s = ref_s + 1

            if e.key() == Qt.Key_F4:
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
        # 执行搜索命令
        search_command = '"Everything.exe" -search "' + search_command + '"'
        subprocess.Popen(search_command, shell=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', nargs='?', const=3, type=int, help='Auto exit after seconds (default 3)')
    args = parser.parse_args()

    app = QApplication(sys.argv)
    window = FileManager()
    window.show()

    # If running in test mode, quit after given seconds to allow automated tests
    if args.test:
        QTimer.singleShot(args.test * 1000, app.quit)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
