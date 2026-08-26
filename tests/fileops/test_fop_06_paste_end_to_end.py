"""FOP-5、FOP-6：走真正的剪貼簿把檔案複製／搬移過去。

上面那支純函式測試驗的是判定；這支驗的是**接線**——剪貼簿真的被寫入、貼上真的
拿得回來、檔案真的移動了。

這支測試的由來：把剪貼簿判定抽成 `app/fileops/clipboard.py` 之後，
`_paste_clipboard_into_dir` 裡的區域變數 `clipboard = QApplication.clipboard()`
把模組名遮蔽掉，貼上整條路徑都會炸——而當時全部 190 個測試照樣全綠，因為
沒有任何一支跑到貼上。
"""
import pytest
from PyQt5.QtWidgets import QMessageBox

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """警告對話框是模態的，測試裡永遠等不到人按。"""
    shown = []
    monkeypatch.setattr(QMessageBox, 'warning',
                        staticmethod(lambda *args, **kwargs: shown.append(args)))
    return shown


@pytest.fixture
def tree(tmp_path):
    src_dir = tmp_path / 'src'
    dst_dir = tmp_path / 'dst'
    src_dir.mkdir()
    dst_dir.mkdir()
    src_file = src_dir / '測試檔案.txt'
    src_file.write_text('x', encoding='utf-8')
    return src_file, dst_dir


def test_fop_6_copy_then_paste_puts_a_copy_at_the_target(main_window, qapp, tree):
    src_file, dst_dir = tree

    assert main_window._set_clipboard_file_paths([str(src_file)], 'copy') is True
    assert main_window._paste_clipboard_into_dir(str(dst_dir)) is True
    qapp.processEvents()

    assert (dst_dir / '測試檔案.txt').exists()
    assert src_file.exists(), '複製不該動到來源'


def test_fop_5_cut_then_paste_moves(main_window, qapp, tree):
    src_file, dst_dir = tree

    assert main_window._set_clipboard_file_paths([str(src_file)], 'move') is True
    assert main_window._paste_clipboard_into_dir(str(dst_dir)) is True
    qapp.processEvents()

    assert (dst_dir / '測試檔案.txt').exists()
    assert not src_file.exists(), '剪下之後來源應該不見了'


def test_fop_5_cut_then_someone_else_copies_falls_back_to_copy(main_window, qapp, tree):
    """剪下之後剪貼簿被別的內容蓋掉，貼上必須退回複製，不能搬走原本那些。"""
    src_file, dst_dir = tree
    other = src_file.parent / '別的檔案.txt'
    other.write_text('y', encoding='utf-8')

    main_window._set_clipboard_file_paths([str(src_file)], 'move')
    # 模擬別的程式（或本程式的另一次複製）改寫了剪貼簿內容
    main_window._set_clipboard_file_paths([str(other)], 'copy')

    assert main_window._paste_clipboard_into_dir(str(dst_dir)) is True
    qapp.processEvents()

    assert other.exists(), '被複製的那個不該被搬走'
    assert src_file.exists(), '先前剪下的那個完全不該被碰到'


def test_paste_into_a_path_that_is_not_a_directory_does_nothing(main_window, tree):
    src_file, _ = tree
    main_window._set_clipboard_file_paths([str(src_file)], 'copy')
    assert main_window._paste_clipboard_into_dir(str(src_file)) is False


def test_paste_with_an_empty_clipboard_does_nothing(main_window, qapp, tmp_path):
    from PyQt5.QtWidgets import QApplication
    QApplication.clipboard().clear()
    qapp.processEvents()
    assert main_window._paste_clipboard_into_dir(str(tmp_path)) is False
