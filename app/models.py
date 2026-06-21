import os

from PyQt5.QtCore import Qt, QSortFilterProxyModel, QMimeData, QUrl
from PyQt5.QtGui import QStandardItemModel


class DrivesSortProxyModel(QSortFilterProxyModel):
    """讓左側目錄樹頂層的磁碟機代號依字母順序排列。"""
    def lessThan(self, left, right):
        # 只對頂層項目（父節點無效 = 磁碟機列表）做字母排序
        if not left.parent().isValid():
            src = self.sourceModel()
            l_path = src.filePath(left).upper()
            r_path = src.filePath(right).upper()
            return l_path < r_path
        return super().lessThan(left, right)


class FileSystemSortProxyModel(QSortFilterProxyModel):
    """中間檔案面板的排序代理：資料夾恆排於所有檔案之上（任一欄位、升冪/降冪皆然），
    與搜尋面板（見 SearchSortProxyModel）行為一致。

    大小、日期欄位以實際數值排序，而非 QFileSystemModel 的顯示字串，避免
    「10 KB 排在 2 KB 之前」之類的字串排序錯誤。

    另對外轉送 QFileSystemModel 常用方法（filePath/isDir/fileName/fileInfo/
    rootPath），參數皆為「本代理」的 index，內部自動 mapToSource，讓既有以
    來源模型 API 操作 view index 的程式碼可直接改用本代理。

    另支援「排除目錄」：set_excluded_dirs() 設定一組已正規化的絕對路徑後，
    凡是落在這些目錄（或其子路徑）下的項目都不列出（filterAcceptsRow）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._excluded_dirs = ()

    def set_excluded_dirs(self, dirs):
        """設定要排除的目錄（已正規化的絕對路徑序列）；空序列代表不排除。"""
        self._excluded_dirs = tuple(dirs)
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._excluded_dirs:
            return True
        src = self.sourceModel()
        if src is None:
            return True
        index = src.index(source_row, 0, source_parent)
        path = os.path.normcase(os.path.normpath(src.filePath(index)))
        for ex in self._excluded_dirs:
            if path == ex:
                return False
            # 磁碟根目錄（如 C:\）normpath 後已帶尾端分隔符，不可再補一個，
            # 否則 "c:\\" 變 "c:\\\\" 而永遠比對不到底下的檔案。
            base = ex if ex.endswith(os.sep) else ex + os.sep
            if path.startswith(base):
                return False
        return True

    def lessThan(self, left, right):
        src = self.sourceModel()
        if src is None:
            return super().lessThan(left, right)

        # left / right 為來源模型的 index。
        l_info = src.fileInfo(left)
        r_info = src.fileInfo(right)
        l_dir = l_info.isDir()
        r_dir = r_info.isDir()
        if l_dir != r_dir:
            # 升冪時資料夾視為「較小」排前面；降冪時 Qt 會反轉 lessThan 的結果，
            # 故先反轉以確保資料夾仍維持在最上方。
            folder_first = l_dir  # left 是資料夾 → left 應在前
            if self.sortOrder() == Qt.DescendingOrder:
                return not folder_first
            return folder_first

        col = left.column()
        if col == 1:  # 大小
            if l_info.size() != r_info.size():
                return l_info.size() < r_info.size()
        elif col == 2:  # 類型（副檔名）
            l_suffix = l_info.suffix().lower()
            r_suffix = r_info.suffix().lower()
            if l_suffix != r_suffix:
                return l_suffix < r_suffix
        elif col == 3:  # 修改日期
            l_mtime = l_info.lastModified()
            r_mtime = r_info.lastModified()
            if l_mtime != r_mtime:
                return l_mtime < r_mtime
        # 名稱欄位，或上述欄位數值相等時：以檔名不分大小寫排序。
        return l_info.fileName().lower() < r_info.fileName().lower()

    # --- 轉送 QFileSystemModel 介面（參數為本代理的 index） ---
    def _to_source(self, proxy_index):
        return self.mapToSource(proxy_index) if proxy_index.isValid() else proxy_index

    def filePath(self, proxy_index):
        return self.sourceModel().filePath(self._to_source(proxy_index))

    def isDir(self, proxy_index):
        return self.sourceModel().isDir(self._to_source(proxy_index))

    def fileName(self, proxy_index):
        return self.sourceModel().fileName(self._to_source(proxy_index))

    def fileInfo(self, proxy_index):
        return self.sourceModel().fileInfo(self._to_source(proxy_index))

    def rootPath(self):
        return self.sourceModel().rootPath()


class SearchSortProxyModel(QSortFilterProxyModel):
    """Proxy model for proper numeric sorting on date and size columns.

    資料夾恆排於所有檔案之上，不論排序欄位或升冪/降冪。"""
    def lessThan(self, left, right):
        # 先以「是否為資料夾」分組：資料夾永遠在檔案之前。
        # is_dir 旗標存於第 0 欄的 item（見 update_search_results）。
        left_dir = bool(left.sibling(left.row(), 0).data(SearchResultsModel.IS_DIR_ROLE))
        right_dir = bool(right.sibling(right.row(), 0).data(SearchResultsModel.IS_DIR_ROLE))
        if left_dir != right_dir:
            # 升冪時資料夾視為「較小」即排前面；降冪時 Qt 會反轉 lessThan 的結果，
            # 故需先反轉以確保資料夾仍維持在最上方。
            folder_first = left_dir  # left 是資料夾 → left 應在前
            if self.sortOrder() == Qt.DescendingOrder:
                return not folder_first
            return folder_first

        col = left.column()
        if col in (2, 3):  # Date or Size columns
            left_val = left.data(Qt.UserRole)
            right_val = right.data(Qt.UserRole)
            if left_val is not None and right_val is not None:
                return left_val < right_val
        return super().lessThan(left, right)

    def mimeTypes(self):
        source = self.sourceModel()
        if source is not None and hasattr(source, "mimeTypes"):
            return source.mimeTypes()
        return super().mimeTypes()

    def mimeData(self, indexes):
        source = self.sourceModel()
        if source is None:
            return super().mimeData(indexes)

        source_indexes = []
        seen = set()
        for proxy_idx in indexes:
            if not proxy_idx.isValid():
                continue
            src_idx = self.mapToSource(proxy_idx)
            key = (src_idx.row(), src_idx.column(), src_idx.parent().internalId())
            if key in seen:
                continue
            seen.add(key)
            source_indexes.append(src_idx)
        return source.mimeData(source_indexes)

    def supportedDragActions(self):
        source = self.sourceModel()
        if source is not None and hasattr(source, "supportedDragActions"):
            return source.supportedDragActions()
        return super().supportedDragActions()


class SearchResultsModel(QStandardItemModel):
    """Search results model that supports dragging files to external apps."""

    FILEPATH_ROLE = Qt.UserRole + 1
    IS_DIR_ROLE = Qt.UserRole + 2

    def flags(self, index):
        base = super().flags(index)
        if index.isValid():
            flags = base | Qt.ItemIsDragEnabled
            if index.column() == 0:
                flags |= Qt.ItemIsEditable
            return flags
        return base

    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, indexes):
        mime = QMimeData()
        if not indexes:
            return mime

        urls = []
        seen = set()
        for index in indexes:
            src = index if index.column() == 0 else index.sibling(index.row(), 0)
            filepath = src.data(self.FILEPATH_ROLE)
            if not filepath or filepath in seen:
                continue
            if os.path.exists(filepath):
                urls.append(QUrl.fromLocalFile(filepath))
                seen.add(filepath)

        if urls:
            mime.setUrls(urls)
        return mime

    def supportedDragActions(self):
        return Qt.CopyAction | Qt.MoveAction | Qt.LinkAction
