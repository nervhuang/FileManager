"""FOP-7、FOP-9、FOP-19：回收筒的旗標與拖放落點判定。

回收筒**真的送出去**那一步是 [手動]——測試裡呼叫下去會把檔案丟進使用者的
回收筒，還可能跳出系統對話框。這裡驗的是「送出去之前那些決定」，那部分
CI 驗得到，而且旗標設錯的後果最嚴重（永久刪除而不是送回收筒）。
"""
import inspect
import os

import pytest
from PyQt5.QtCore import QPoint

from app.fileops import shell as shell_ops

pytestmark = pytest.mark.gui


def _same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


# ── FOP-7／FOP-9：旗標決定「送回收筒」還是「永久刪除」 ────────────────

def test_fop_7_delete_uses_allow_undo():
    """FOF_ALLOWUNDO 就是「送回收筒」與「永久刪除」的差別。

    少了它，使用者按刪除就是真的沒了，而且不會有任何提示。
    """
    assert shell_ops.FOF_ALLOWUNDO == 0x0040


def test_fop_9_delete_asks_windows_to_warn_before_nuking():
    """無法送回收筒時（容量不足、網路磁碟）由系統跳警告，
    而不是靜默改成永久刪除。"""
    assert shell_ops.FOF_WANTNUKEWARNING == 0x4000


def test_fop_7_the_delete_function_actually_uses_both_flags():
    """常數對了但沒用上等於沒有，所以連原始碼一起看。"""
    source = inspect.getsource(shell_ops.delete_to_recycle_bin)
    assert 'FOF_ALLOWUNDO' in source
    assert 'FOF_WANTNUKEWARNING' in source
    assert 'FO_DELETE' in source


def test_fop_7_move_and_copy_never_use_the_delete_verb():
    source = inspect.getsource(shell_ops.move_or_copy)
    assert 'FO_DELETE' not in source


# ── FOP-19：落點要分得出「放在資料夾上」與「放在空白處」 ─────────────

def test_fop_19_drop_on_empty_space_targets_the_current_directory(
        main_window, qapp, tmp_path):
    """放在清單空白處＝放進目前這個目錄，不是放進最後一個項目裡。"""
    (tmp_path / '子目錄').mkdir()
    main_window._navigate_to_path(str(tmp_path))
    qapp.processEvents()

    below_everything = QPoint(5, main_window.listView.viewport().height() - 2)
    target = main_window._resolve_listview_drop_target(below_everything)

    assert _same_path(target, str(tmp_path))


def test_fop_19_drop_target_is_never_a_file(main_window, qapp, tmp_path):
    """放在檔案上時要退回它所在的目錄——檔案不能當成放置目標。"""
    (tmp_path / 'a.txt').write_text('x', encoding='utf-8')
    main_window._navigate_to_path(str(tmp_path))
    qapp.processEvents()

    for y in range(0, main_window.listView.viewport().height(), 8):
        target = main_window._resolve_listview_drop_target(QPoint(20, y))
        if target:
            assert os.path.isdir(target), f'落點 {target!r} 不是目錄'


# ── FOP-14：新建資料夾之後要能直接改名 ────────────────────────────────

def test_fop_14_creating_a_folder_makes_it_and_queues_the_rename(
        main_window, qapp, tmp_path):
    """建好之後要自動聚焦並進入更名狀態，使用者才能直接打字命名。

    實際的「進入編輯狀態」排在事件圈之後（QTimer.singleShot），這裡驗的是
    「資料夾真的建了」與「待更名的目標已經記下來」。
    """
    main_window._navigate_to_path(str(tmp_path))
    qapp.processEvents()

    main_window._create_folder_in_current_dir()
    qapp.processEvents()

    created = tmp_path / '新增資料夾'
    assert created.is_dir()
    assert main_window._pending_new_folder_path == \
        os.path.normcase(os.path.normpath(str(created)))


def test_fop_14_a_second_folder_gets_a_numbered_name(main_window, qapp, tmp_path):
    """同名時要往後編號，而不是失敗或覆蓋。"""
    main_window._navigate_to_path(str(tmp_path))
    qapp.processEvents()

    main_window._create_folder_in_current_dir()
    qapp.processEvents()
    main_window._create_folder_in_current_dir()
    qapp.processEvents()

    assert (tmp_path / '新增資料夾').is_dir()
    assert (tmp_path / '新增資料夾 (2)').is_dir()
