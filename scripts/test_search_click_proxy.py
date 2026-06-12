"""驗證搜尋結果重建後，proxy 對應表保持一致（點擊映射不會指向已刪除的 item）。

模擬 update_search_results 的「重建」流程，然後像點擊一樣把每個 proxy 索引
mapToSource 並讀取資料，確認映射有效且筆數正確。

執行： python scripts/test_search_click_proxy.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QTreeView
from PyQt5.QtGui import QStandardItem
from app.models import SearchResultsModel, SearchSortProxyModel

FILEPATH_ROLE = Qt.UserRole + 1


def make_rows(paths):
    rows = []
    for p in paths:
        name = QStandardItem(os.path.basename(p))
        name.setData(p, FILEPATH_ROLE)
        d = QStandardItem(os.path.dirname(p))
        rows.append([name, d])
    return rows


def rebuild_blocksignals(model, paths):
    """舊（壞）作法：blockSignals 包住結構變更。"""
    model.blockSignals(True)
    model.removeRows(0, model.rowCount())
    for row in make_rows(paths):
        model.appendRow(row)
    model.blockSignals(False)
    model.layoutChanged.emit()


def rebuild_fixed(model, paths):
    """新（修正）作法：讓 rowsRemoved/rowsInserted 正常發出。"""
    model.removeRows(0, model.rowCount())
    for row in make_rows(paths):
        model.appendRow(row)


def click_map_all(view, proxy, model):
    """模擬點擊每個可見列：透過 proxy 映射回來源並讀資料，回傳成功讀到的路徑。"""
    got = []
    for r in range(proxy.rowCount()):
        proxy_idx = proxy.index(r, 0)
        src_idx = proxy.mapToSource(proxy_idx)
        item = model.itemFromIndex(src_idx)        # 若映射損毀，src 列會越界 → item 為 None
        if item is None:
            return None, r                          # 損毀：映射指向不存在的列
        got.append(item.data(FILEPATH_ROLE))
    return got, None


def run_case(label, rebuild_fn):
    model = SearchResultsModel()
    model.setHorizontalHeaderLabels(["檔名", "目錄"])
    proxy = SearchSortProxyModel()
    proxy.setSourceModel(model)
    view = QTreeView()
    view.setModel(proxy)
    view.setSortingEnabled(True)

    first = [f"C:\\a\\file_{i}.txt" for i in range(8)]
    second = [f"C:\\b\\doc_{i}.txt" for i in range(3)]   # 重建成較少筆數，最易暴露越界

    rebuild_fn(model, first)
    rebuild_fn(model, second)   # 第二次重建：proxy 對應表是否仍正確？

    got, bad_row = click_map_all(view, proxy, model)
    expected = set(second)

    print(f"[{label}]")
    print(f"  來源列數        : {model.rowCount()} (預期 3)")
    print(f"  proxy 列數      : {proxy.rowCount()} (預期 3)")
    if got is None:
        print(f"  點擊映射        : 損毀！proxy 第 {bad_row} 列映射到不存在的來源列")
        return False
    print(f"  點擊映射全部有效: {set(got) == expected}")
    ok = (model.rowCount() == 3 and proxy.rowCount() == 3 and set(got) == expected)
    return ok


def main():
    app = QApplication(sys.argv)
    # 對照組：示範舊作法會損毀；正式驗證新作法
    bad_ok = run_case("舊 blockSignals 作法 (對照)", rebuild_blocksignals)
    print()
    fixed_ok = run_case("修正後作法", rebuild_fixed)
    print()
    print("對照組(舊作法)是否暴露問題:", "是 (proxy 損毀)" if not bad_ok else "未暴露")
    print("結果:", "PASS" if fixed_ok else "FAIL")
    sys.exit(0 if fixed_ok else 1)


if __name__ == '__main__':
    main()
