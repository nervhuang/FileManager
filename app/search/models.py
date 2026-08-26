"""搜尋結果的模型與排序 proxy。

從 `app/models.py` 搬過來——那個檔案同時裝著檔案面板與搜尋面板的模型，
名字叫 models 卻不屬於任何一個域。
"""

import os
from datetime import datetime

from PyQt5.QtCore import Qt, QSortFilterProxyModel, QMimeData, QUrl
from PyQt5.QtGui import QStandardItem, QStandardItemModel

from .results import format_size


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


def build_rows(results, icon_for):
    """把 `SearchResult` 清單做成模型的列。

    `icon_for(filepath, is_dir)` 由呼叫端提供——圖示要快取，而快取是誰的
    生命週期就歸誰管。

    中繼資料（大小、時間、是否為目錄）直接用 Everything 給的，不逐筆 os.stat
    （docs/spec/search.md 的 SRCH-15）。只有檔名欄可編輯，其餘三欄鎖住。
    """
    rows = []
    for filepath, is_dir, size, mtime in results:
        name_item = QStandardItem(os.path.basename(filepath))
        name_item.setData(filepath, Qt.UserRole + 1)
        # 資料夾旗標供 SearchSortProxyModel 讓資料夾恆排於檔案之上（SRCH-14）
        name_item.setData(is_dir, SearchResultsModel.IS_DIR_ROLE)
        name_item.setIcon(icon_for(filepath, is_dir))

        dir_item = QStandardItem(os.path.dirname(filepath))
        dir_item.setEditable(False)

        try:
            date_text = (datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                         if mtime else '')
        except (OverflowError, OSError, ValueError):
            # Everything 偶爾會給出無法轉成本地時間的時間戳（0、負數、超出範圍）
            date_text = ''
        date_item = QStandardItem(date_text)
        date_item.setEditable(False)
        date_item.setData(mtime, Qt.UserRole)

        size_item = QStandardItem('' if (is_dir or not size) else format_size(size))
        size_item.setEditable(False)
        size_item.setData(size, Qt.UserRole)

        rows.append([name_item, dir_item, date_item, size_item])
    return rows


def populate(model, proxy, rows):
    """把列批次填進模型。

    **不可用 `blockSignals` 包住結構性變更**：`SearchSortProxyModel` 靠
    `rowsRemoved` / `rowsInserted` 維護「proxy 列 ↔ 來源列」的對應表，擋掉訊號
    會讓對應表指向已刪除的 item，之後點擊搜尋結果就會解參考已釋放記憶體而崩潰
    （SRCH-18）。

    **填入期間要關掉動態排序**：proxy 預設 `dynamicSortFilter=True` 且 view 已
    啟用排序，逐筆 `appendRow` 會讓 proxy 每次都重找插入位置（O(n) 比較），
    2000 筆就退化成 O(n²)，新增／刪除／改名後 GUI 凍結兩三秒（SRCH-17）。
    關的是排序不是訊號，`rowsInserted` 照常發出，對應表不會失效。
    """
    proxy.setDynamicSortFilter(False)
    model.removeRows(0, model.rowCount())
    for row in rows:
        model.appendRow(row)
    proxy.setDynamicSortFilter(True)
