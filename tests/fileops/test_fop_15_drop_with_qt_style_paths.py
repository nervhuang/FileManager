"""FOP-15：左鍵拖放要能搬動檔案，即使路徑是 Qt 給的正斜線形式。

`QUrl.toLocalFile()` 在 Windows 上回的是 `D:/a/b.txt`——正斜線。拖放的來源路徑
就是從那裡來的（`_extract_source_paths_from_mime`）。

而 `SHFileOperationW` 不吃正斜線：實測傳 `D:/src/a.txt` 會回錯誤碼 183
（ERROR_ALREADY_EXISTS 的代碼，但實際意思是路徑無效），檔案原地不動。
"""
import os

import pytest
from PyQt5.QtWidgets import QMessageBox, QWidget

from app.views import _ShellDropMixin

pytestmark = pytest.mark.gui


class _FakeView(_ShellDropMixin, QWidget):
    """只提供 _apply_drop_operation 會用到的東西。"""

    def __init__(self):
        super().__init__()
        self.refresh_calls = []

    def _notify_search_refresh_delayed(self, src_paths=None, target_dir=''):
        self.refresh_calls.append((src_paths, target_dir))


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """攔下警告對話框。

    失敗路徑會跳 QMessageBox.warning，那是模態的——在測試裡永遠等不到人按，
    整支測試就掛在那裡。改成記下來，測試才問得出「有沒有跳警告」。
    """
    shown = []
    monkeypatch.setattr(QMessageBox, 'warning',
                        staticmethod(lambda *args, **kwargs: shown.append(args)))
    return shown


@pytest.fixture
def view(qapp):
    widget = _FakeView()
    widget.show()          # winId() 要有效，SHFileOperationW 需要
    qapp.processEvents()
    yield widget
    widget.close()


def _make_tree(tmp_path):
    src_dir = tmp_path / 'src'
    dst_dir = tmp_path / 'dst'
    src_dir.mkdir()
    dst_dir.mkdir()
    src_file = src_dir / 'a.txt'
    src_file.write_text('x', encoding='utf-8')
    return src_file, dst_dir


def test_fop_15_drop_moves_file_with_backslash_paths(view, tmp_path):
    """對照組：正常的反斜線路徑本來就會動。"""
    src_file, dst_dir = _make_tree(tmp_path)
    view._apply_drop_operation([str(src_file)], str(dst_dir), 'move')

    assert not src_file.exists()
    assert (dst_dir / 'a.txt').exists()


def test_fop_15_drop_moves_file_with_forward_slash_paths(view, tmp_path):
    """Qt 給的路徑是正斜線，拖放一樣要成功。"""
    src_file, dst_dir = _make_tree(tmp_path)
    qt_src = str(src_file).replace(os.sep, '/')
    qt_dst = str(dst_dir).replace(os.sep, '/')

    view._apply_drop_operation([qt_src], qt_dst, 'move')

    assert not src_file.exists(), (
        '來源還在原地——SHFileOperationW 不吃正斜線，路徑要先正規化')
    assert (dst_dir / 'a.txt').exists()
