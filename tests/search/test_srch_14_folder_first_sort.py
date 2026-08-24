"""SRCH-14：資料夾恆排於所有檔案之上，任一欄位、升冪降冪皆然。

原 scripts/test_folder_first_sort.py。
"""
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QStandardItem
from PyQt5.QtWidgets import QTreeView

from app.models import SearchResultsModel, SearchSortProxyModel

pytestmark = pytest.mark.gui

# 資料夾與檔案交錯，名稱／日期／大小刻意打亂，任一欄位排序後資料夾都必須仍在上面。
ROWS = [
    ("zebra_file.txt", False, 300, 900),
    ("apple_folder",   True,  100, 0),
    ("mango_file.txt", False, 500, 100),
    ("banana_folder",  True,  200, 0),
    ("kiwi_file.txt",  False, 400, 500),
    ("delta_folder",   True,  600, 0),
]

FOLDER_COUNT = sum(1 for _, is_dir, _, _ in ROWS if is_dir)

SORT_CASES = [
    (0, Qt.AscendingOrder,  "檔名遞增"),
    (0, Qt.DescendingOrder, "檔名遞減"),
    (2, Qt.AscendingOrder,  "日期遞增"),
    (2, Qt.DescendingOrder, "日期遞減"),
    (3, Qt.AscendingOrder,  "大小遞增"),
    (3, Qt.DescendingOrder, "大小遞減"),
]


def _add_row(model, name, is_dir, mtime, size):
    name_item = QStandardItem(name)
    name_item.setData(name, SearchResultsModel.FILEPATH_ROLE)
    name_item.setData(is_dir, SearchResultsModel.IS_DIR_ROLE)
    dir_item = QStandardItem("C:\\x")
    date_item = QStandardItem(str(mtime))
    date_item.setData(mtime, Qt.UserRole)
    size_item = QStandardItem(str(size))
    size_item.setData(size, Qt.UserRole)
    model.appendRow([name_item, dir_item, date_item, size_item])


def _visible_order(proxy):
    """目前可見順序的 (名稱, 是否為資料夾) 清單。"""
    out = []
    for row in range(proxy.rowCount()):
        source_index = proxy.mapToSource(proxy.index(row, 0))
        out.append((
            source_index.data(Qt.DisplayRole),
            bool(source_index.data(SearchResultsModel.IS_DIR_ROLE)),
        ))
    return out


@pytest.fixture
def sorted_view(qapp):
    model = SearchResultsModel()
    model.setHorizontalHeaderLabels(["檔名", "目錄", "日期", "大小"])
    proxy = SearchSortProxyModel()
    proxy.setSourceModel(model)
    view = QTreeView()
    view.setModel(proxy)
    view.setSortingEnabled(True)
    for row in ROWS:
        _add_row(model, *row)
    return proxy


@pytest.mark.parametrize("column, order, label", SORT_CASES,
                         ids=[case[2] for case in SORT_CASES])
def test_srch_14_folders_stay_above_files(sorted_view, column, order, label):
    sorted_view.sort(column, order)
    visible = _visible_order(sorted_view)

    assert len(visible) == len(ROWS)

    leading = visible[:FOLDER_COUNT]
    assert all(is_dir for _, is_dir in leading), (
        f"{label}：前 {FOLDER_COUNT} 筆應全為資料夾，實際為 "
        f"{[(n, d) for n, d in leading]}")

    # 一旦出現檔案，後面就不能再有資料夾。
    seen_file = False
    for name, is_dir in visible:
        if not is_dir:
            seen_file = True
        else:
            assert not seen_file, f"{label}：資料夾 {name} 排在檔案之後"
