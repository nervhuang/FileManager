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
