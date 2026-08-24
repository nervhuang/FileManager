"""用真實的 FileManager 實例驗證：搜尋結果重建後，選取/點擊不會崩潰。

流程貼近使用者情境：
  1. 用真實檔案填充 listView2（呼叫真正的 update_search_results）
  2. 選取一列（等同點擊）→ 透過真實 search_proxy + selectionModel 映射
  3. 重建搜尋結果（較少筆數）—— 這是會讓舊 blockSignals 作法損毀 proxy 的步驟
  4. 再次選取/映射每一列（等同再次點擊）→ 若映射損毀，原生層會在此崩潰
  5. processEvents，確認進程仍存活

執行： python scripts/test_search_click_realapp.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 測試必須與開發者的個人設定隔離：FileManager 會讀 runtime_root() 底下的
# config.ini，而真實設定裡的 [Exclude] 可能排除整個磁碟，把測試資料濾光。
# 用 FILEMANAGER_HOME 指向一個空的暫存目錄（見 docs/spec/settings.md 的 SET-1），
# 程式會以內建預設值執行（SET-5），設定也只寫進那裡。
os.environ['FILEMANAGER_HOME'] = tempfile.mkdtemp(prefix='fm_test_home_')

from PyQt5.QtCore import Qt, QItemSelectionModel
from PyQt5.QtWidgets import QApplication
from app.everything_sdk import SearchResult
from app.file_manager import FileManager

FILEPATH_ROLE = Qt.UserRole + 1


def make_files(dirpath, prefix, n):
    """建立檔案並回傳 SearchResult 清單。

    update_search_results 收的是 everything_sdk.SearchResult（可解包為
    path/is_dir/size/mtime），不是字串路徑——中繼資料由 Everything 查詢直接
    帶回來，不逐筆 os.stat。見 docs/spec/search.md 的 SRCH-15、SRCH-16。
    """
    results = []
    for i in range(n):
        p = os.path.join(dirpath, f"{prefix}_{i}.txt")
        with open(p, 'w', encoding='utf-8') as f:
            f.write('x')
        st = os.stat(p)
        results.append(SearchResult(p, False, st.st_size, int(st.st_mtime)))
    return results


def simulate_clicks(win):
    """模擬逐列點擊：選取每個 proxy 列並把它映射回來源讀資料。"""
    proxy = win.search_proxy
    model = win.search_model
    selmodel = win.listView2.selectionModel()
    read = []
    for r in range(proxy.rowCount()):
        pidx = proxy.index(r, 0)
        selmodel.setCurrentIndex(pidx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        sidx = proxy.mapToSource(pidx)
        item = model.itemFromIndex(sidx)   # 損毀時越界 → None 或崩潰
        read.append(None if item is None else item.data(FILEPATH_ROLE))
    return read


def main():
    app = QApplication(sys.argv)
    win = FileManager()
    win.show()
    app.processEvents()

    tmp = tempfile.mkdtemp(prefix='fm_click_test_')
    first = make_files(tmp, 'first', 9)
    second = make_files(tmp, 'second', 3)   # 重建為較少筆數，最易暴露越界映射

    # 1+2. 填充並點擊
    win.update_search_results(first)
    app.processEvents()
    r1 = simulate_clicks(win)
    app.processEvents()

    # 3. 重建（這步在舊作法下會損毀 proxy 對應表）
    win.update_search_results(second)
    app.processEvents()

    # 4. 再次點擊每一列——舊作法會在此原生崩潰
    r2 = simulate_clicks(win)
    app.processEvents()

    ok = True
    print('第一次點擊讀到筆數 :', len([x for x in r1 if x]), '(預期 9)')
    if len([x for x in r1 if x]) != 9:
        ok = False
    print('重建後 proxy 列數  :', win.search_proxy.rowCount(), '(預期 3)')
    if win.search_proxy.rowCount() != 3:
        ok = False
    print('第二次點擊全部有效 :', all(x for x in r2) and len(r2) == 3, '(預期 True)')
    if not (all(x for x in r2) and len(r2) == 3):
        ok = False
    second_paths = {r.path for r in second}
    print('第二次點擊內容正確 :', set(x for x in r2 if x) == second_paths)
    if set(x for x in r2 if x) != second_paths:
        ok = False

    print()
    print('進程存活、點擊未崩潰。')
    print('結果:', 'PASS' if ok else 'FAIL')
    win.close()
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
