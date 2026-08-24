"""FOP-22：移動成功後不得同步重設 model，改為延遲排程。

同步重設是崩潰來源，也是操作後 2–3 秒 UI 凍結的成因之一
（見 docs/spec/search.md 的 SRCH-17、SRCH-19）。

原 scripts/test_move_no_sync_refresh.py。
"""
import pytest
from PyQt5.QtWidgets import QWidget

from app.file_manager import FileManager

pytestmark = pytest.mark.gui


class _FakeFileManager(QWidget):
    """只提供 _perform_file_op 會用到的屬性與方法，把它與主視窗其餘部分隔開。"""

    def __init__(self):
        super().__init__()
        self.sync_refresh_calls = []      # 同步刷新若發生會被記到這裡
        self.scheduled_refreshes = []     # 延遲排程

    def refresh_mid_panel(self):
        self.sync_refresh_calls.append('mid')

    def refresh_current_search_results(self):
        self.sync_refresh_calls.append('search')

    def _schedule_panel_refreshes(self, delays_ms, full_search=False):
        self.scheduled_refreshes.append(tuple(delays_ms))


@pytest.fixture
def fake_window(qapp):
    window = _FakeFileManager()
    window.show()          # 讓 winId() 有效，SHFileOperationW 需要
    qapp.processEvents()
    yield window
    window.close()


def test_fop_22_move_schedules_refresh_instead_of_running_it_synchronously(
        fake_window, tmp_path):
    src_dir = tmp_path / 'src'
    dst_dir = tmp_path / 'dst'
    src_dir.mkdir()
    dst_dir.mkdir()
    src_file = src_dir / '測試檔案.txt'
    src_file.write_text('hello', encoding='utf-8')

    result = FileManager._perform_file_op(
        fake_window, [str(src_file)], str(dst_dir), 'move')

    assert result is True
    assert not src_file.exists()
    assert (dst_dir / '測試檔案.txt').exists()

    assert fake_window.sync_refresh_calls == [], (
        "移動後不得同步刷新面板——那正是崩潰與 UI 凍結的來源")
    assert fake_window.scheduled_refreshes, (
        "移動後必須排程延遲刷新，否則面板不會反映結果")
