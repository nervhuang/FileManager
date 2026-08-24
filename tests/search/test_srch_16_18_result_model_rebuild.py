"""SRCH-16、SRCH-18：重建搜尋結果模型後，proxy 對應表必須保持有效。

損毀時的症狀是使用者點某一列，proxy 把它映射到一個已經不存在的來源列——
輕則讀到 None，重則在原生層直接崩潰。列數變少的重建最容易暴露。

兩個層級：
  - 模型層：直接操作 SearchResultsModel / SearchSortProxyModel，快
  - 主視窗層：走真正的 update_search_results 與 selectionModel，貼近使用者情境

原 scripts/test_search_click_proxy.py 與 scripts/test_search_click_realapp.py。
"""
import os

import pytest
from PyQt5.QtCore import Qt, QItemSelectionModel
from PyQt5.QtGui import QStandardItem
from PyQt5.QtWidgets import QTreeView

from app.everything_sdk import SearchResult
from app.models import SearchResultsModel, SearchSortProxyModel

pytestmark = pytest.mark.gui

FILEPATH_ROLE = Qt.UserRole + 1

FIRST_PATHS = [f"C:\\a\\file_{i}.txt" for i in range(8)]
SECOND_PATHS = [f"C:\\b\\doc_{i}.txt" for i in range(3)]


def _make_rows(paths):
    rows = []
    for path in paths:
        name = QStandardItem(os.path.basename(path))
        name.setData(path, FILEPATH_ROLE)
        rows.append([name, QStandardItem(os.path.dirname(path))])
    return rows


def _click_map_all(proxy, model):
    """模擬逐列點擊：把每個 proxy 索引映射回來源並讀資料。

    回傳讀到的路徑清單；映射損毀時該列的 item 為 None，會出現在清單裡。
    """
    got = []
    for row in range(proxy.rowCount()):
        source_index = proxy.mapToSource(proxy.index(row, 0))
        item = model.itemFromIndex(source_index)
        got.append(None if item is None else item.data(FILEPATH_ROLE))
    return got


@pytest.fixture
def model_and_proxy(qapp):
    model = SearchResultsModel()
    model.setHorizontalHeaderLabels(["檔名", "目錄"])
    proxy = SearchSortProxyModel()
    proxy.setSourceModel(model)
    view = QTreeView()
    view.setModel(proxy)
    view.setSortingEnabled(True)
    return model, proxy


def _rebuild(model, paths):
    """讓 rowsRemoved / rowsInserted 正常發出。

    舊作法用 blockSignals 包住結構變更再補一個 layoutChanged，proxy 因此
    收不到列數變化，對應表停留在舊的列數上。見本檔的對照測試。
    """
    model.removeRows(0, model.rowCount())
    for row in _make_rows(paths):
        model.appendRow(row)


def test_srch_18_proxy_mapping_survives_shrinking_rebuild(model_and_proxy):
    model, proxy = model_and_proxy

    _rebuild(model, FIRST_PATHS)
    _rebuild(model, SECOND_PATHS)   # 重建成較少筆數

    assert model.rowCount() == len(SECOND_PATHS)
    assert proxy.rowCount() == len(SECOND_PATHS)

    got = _click_map_all(proxy, model)
    assert None not in got, "proxy 有列映射到不存在的來源列"
    assert set(got) == set(SECOND_PATHS)


# 這裡刻意沒有「舊 blockSignals 作法」的對照測試。原本的 scripts 版本有跑它，
# 但那組在這個最小化環境下映射並沒有損毀（腳本只把結果印出來，沒有斷言，
# 所以沒人發現對照組是空的）。損毀需要完整的主視窗路徑——真正的
# update_search_results、啟用排序的 view、真正的 selectionModel——才會出現。
# 下面那支 main_window 測試才是實際守著這個行為的。


def test_srch_16_update_search_results_takes_search_results(main_window, qapp, tmp_path):
    """update_search_results 收 SearchResult 四元組，不收字串路徑。

    中繼資料由 Everything 查詢直接帶回，不逐筆 os.stat（SRCH-15）。
    """
    def make(prefix, count):
        results = []
        for i in range(count):
            path = tmp_path / f"{prefix}_{i}.txt"
            path.write_text("x", encoding="utf-8")
            stat = path.stat()
            results.append(SearchResult(str(path), False, stat.st_size, int(stat.st_mtime)))
        return results

    first, second = make("first", 9), make("second", 3)

    main_window.update_search_results(first)
    qapp.processEvents()
    assert main_window.search_proxy.rowCount() == len(first)

    main_window.update_search_results(second)
    qapp.processEvents()
    assert main_window.search_proxy.rowCount() == len(second)

    # 走真正的 selectionModel，逐列選取後映射回來源——損毀時這裡會崩潰。
    proxy = main_window.search_proxy
    selection_model = main_window.listView2.selectionModel()
    got = []
    for row in range(proxy.rowCount()):
        proxy_index = proxy.index(row, 0)
        selection_model.setCurrentIndex(
            proxy_index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        source_index = proxy.mapToSource(proxy_index)
        item = main_window.search_model.itemFromIndex(source_index)
        got.append(None if item is None else item.data(FILEPATH_ROLE))
    qapp.processEvents()

    assert None not in got
    assert set(got) == {r.path for r in second}
