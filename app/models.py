"""檔案面板的模型與排序 proxy。

搜尋面板的那兩個已經搬到 `app/search/models.py`。這個檔案還沒有名副其實的家——
它屬於檔案面板域，等那個域拆出來時應該一起搬走。
"""

import os

from PyQt5.QtCore import Qt, QSortFilterProxyModel


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

    # QFileSystemModel 的表頭取自 Qt 內建翻譯，本專案未載入中文語系而顯示為
    # Name/Size/Type/Date Modified，與搜尋面板的中文表頭不一致，故在代理層改寫。
    COLUMN_LABELS = ("檔名", "大小", "類型", "修改時間")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._excluded_dirs = ()

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if (orientation == Qt.Horizontal and role == Qt.DisplayRole
                and 0 <= section < len(self.COLUMN_LABELS)):
            return self.COLUMN_LABELS[section]
        return super().headerData(section, orientation, role)

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
