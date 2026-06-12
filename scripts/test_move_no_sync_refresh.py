"""驗證 _perform_file_op 修正：移動成功後不再同步重設 model（崩潰來源），改為延遲排程。

執行方式： python scripts/test_move_no_sync_refresh.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PyQt5.QtWidgets import QApplication, QWidget
from app.file_manager import FileManager


class FakeFM(QWidget):
    """只提供 _perform_file_op 會用到的屬性/方法，用以隔離測試。"""
    def __init__(self):
        super().__init__()
        self.sync_refresh_calls = []      # 同步刷新若發生會被記錄（修正後應為空）
        self.scheduled_refreshes = []     # 延遲排程（修正後應有值）

    def refresh_mid_panel(self):
        self.sync_refresh_calls.append('mid')

    def refresh_current_search_results(self):
        self.sync_refresh_calls.append('search')

    def _schedule_panel_refreshes(self, delays_ms):
        self.scheduled_refreshes.append(tuple(delays_ms))


def main():
    app = QApplication(sys.argv)
    fake = FakeFM()
    fake.show()              # 讓 winId() 有效，供 SHFileOperationW 使用
    app.processEvents()

    tmp = tempfile.mkdtemp(prefix='fm_move_test_')
    src_dir = os.path.join(tmp, 'src')
    dst_dir = os.path.join(tmp, 'dst')
    os.makedirs(src_dir)
    os.makedirs(dst_dir)
    src_file = os.path.join(src_dir, '測試檔案.txt')
    with open(src_file, 'w', encoding='utf-8') as f:
        f.write('hello')

    # 以真實的 FileManager._perform_file_op 執行移動
    result = FileManager._perform_file_op(fake, [src_file], dst_dir, 'move')

    moved_path = os.path.join(dst_dir, '測試檔案.txt')

    ok = True
    print('回傳值          :', result, '(預期 True)')
    if result is not True:
        ok = False

    print('來源已不存在    :', not os.path.exists(src_file), '(預期 True)')
    if os.path.exists(src_file):
        ok = False

    print('目標已存在      :', os.path.exists(moved_path), '(預期 True)')
    if not os.path.exists(moved_path):
        ok = False

    print('同步刷新呼叫    :', fake.sync_refresh_calls, '(預期 []  ← 崩潰來源已消除)')
    if fake.sync_refresh_calls:
        ok = False

    print('延遲排程刷新    :', fake.scheduled_refreshes, '(預期非空)')
    if not fake.scheduled_refreshes:
        ok = False

    print()
    print('結果:', 'PASS ✓' if ok else 'FAIL ✗')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
