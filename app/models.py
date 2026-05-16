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
    """Proxy model for proper numeric sorting on date and size columns."""
    def lessThan(self, left, right):
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
