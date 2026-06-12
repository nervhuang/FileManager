"""驗證搜尋結果排序：資料夾恆排於所有檔案之上（任一欄位、升冪/降冪皆然）。

執行： python scripts/test_folder_first_sort.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QTreeView
from PyQt5.QtGui import QStandardItem
from app.models import SearchResultsModel, SearchSortProxyModel


def add_row(model, name, is_dir, mtime, size):
    n = QStandardItem(name)
    n.setData(name, SearchResultsModel.FILEPATH_ROLE)
    n.setData(is_dir, SearchResultsModel.IS_DIR_ROLE)
    d = QStandardItem("C:\\x")
    dt = QStandardItem(str(mtime)); dt.setData(mtime, Qt.UserRole)
    sz = QStandardItem(str(size)); sz.setData(size, Qt.UserRole)
    model.appendRow([n, d, dt, sz])


def proxy_order(view, proxy):
    """回傳目前可見順序的 (name, is_dir) 清單。"""
    out = []
    for r in range(proxy.rowCount()):
        pidx = proxy.index(r, 0)
        sidx = proxy.mapToSource(pidx)
        name = sidx.data(Qt.DisplayRole)
        is_dir = bool(sidx.data(SearchResultsModel.IS_DIR_ROLE))
        out.append((name, is_dir))
    return out


def folders_all_on_top(order):
    """檢查：一旦出現檔案，後面就不能再有資料夾。"""
    seen_file = False
    for _, is_dir in order:
        if not is_dir:
            seen_file = True
        elif seen_file:
            return False
    return True


def main():
    app = QApplication(sys.argv)
    model = SearchResultsModel()
    model.setHorizontalHeaderLabels(["檔名", "目錄", "日期", "大小"])
    proxy = SearchSortProxyModel()
    proxy.setSourceModel(model)
    view = QTreeView()
    view.setModel(proxy)
    view.setSortingEnabled(True)

    # 混合：資料夾與檔案交錯，名稱/日期/大小刻意打亂，確保排序後仍資料夾在上
    add_row(model, "zebra_file.txt", False, 300, 900)
    add_row(model, "apple_folder",   True,  100, 0)
    add_row(model, "mango_file.txt", False, 500, 100)
    add_row(model, "banana_folder",  True,  200, 0)
    add_row(model, "kiwi_file.txt",  False, 400, 500)
    add_row(model, "delta_folder",   True,  600, 0)

    ok = True
    cases = [
        (0, Qt.AscendingOrder,  "檔名↑"),
        (0, Qt.DescendingOrder, "檔名↓"),
        (2, Qt.AscendingOrder,  "日期↑"),
        (2, Qt.DescendingOrder, "日期↓"),
        (3, Qt.AscendingOrder,  "大小↑"),
        (3, Qt.DescendingOrder, "大小↓"),
    ]
    for col, order, label in cases:
        proxy.sort(col, order)
        result = proxy_order(view, proxy)
        passed = folders_all_on_top(result)
        n_folder_top = sum(1 for _, d in result[:3] if d)
        print(f"  {label}: 前三筆資料夾數={n_folder_top}/3, 資料夾全在上={passed}")
        print(f"         順序: {[name for name, _ in result]}")
        if not (passed and n_folder_top == 3):
            ok = False

    print()
    print("結果:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
