"""FOP-1 到 FOP-4、FOP-8、FOP-13、FOP-23、FOP-24、SRCH-20：選取、跳過不存在的來源、
改名旗標、以及操作後的刷新排程。

原生 shell 的部分（右鍵選單、右鍵拖放、真的送回收筒）標成 [手動]，這裡只驗
它們周圍那些 CI 驗得到的判斷。
"""
import pytest
from PyQt5.QtWidgets import QAbstractItemView, QMessageBox

from app.fileops.shell import NOTHING_TO_DO, delete_to_recycle_bin

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, 'warning',
                        staticmethod(lambda *args, **kwargs: shown.append(args)))
    return shown


# ── FOP-1：兩個面板都可多選 ─────────────────────────────────────────────

def test_fop_1_both_panels_allow_multiple_selection(main_window):
    """檔案面板曾經是單選，一次只能拖一個檔案。"""
    for view in (main_window.listView, main_window.listView2):
        assert view.selectionMode() == QAbstractItemView.ExtendedSelection


# ── FOP-2／FOP-3／FOP-4：多選拖曳的前置狀態 ────────────────────────────

def test_fop_2_views_track_the_press_position(main_window):
    """按在已選取項目上時 Qt 留在 NoState，第一次移動會被當成框選而清掉多選。

    兩個 view 因此自己記下按下的位置，用移動距離判斷該不該手動啟動拖曳。
    """
    for view in (main_window.listView, main_window.listView2):
        assert hasattr(view, '_press_pos'), f'{type(view).__name__} 少了 _press_pos'


def test_fop_4_start_drag_reads_the_whole_selection(main_window):
    """startDrag 由 view 自己覆寫，才能一次拖走全部選取。"""
    for view in (main_window.listView, main_window.listView2):
        assert type(view).startDrag is not QAbstractItemView.startDrag


# ── FOP-8：送出前先濾掉已不存在的路徑 ──────────────────────────────────

def test_fop_8_deleting_only_missing_paths_does_nothing(tmp_path):
    """全部都不存在時不呼叫 shell——真的呼叫下去會跳出系統對話框。"""
    outcome = delete_to_recycle_bin(0, [str(tmp_path / '不存在.txt')])
    assert outcome == NOTHING_TO_DO
    assert outcome.ran is False


def test_fop_8_deleting_an_empty_list_does_nothing():
    assert delete_to_recycle_bin(0, []).ran is False


# ── FOP-13：程式自身的改名不得再觸發改名處理 ───────────────────────────

def test_fop_13_reverting_the_display_does_not_re_enter_the_handler(main_window, qapp):
    """還原顯示時若不擋住 itemChanged，會再進一次改名流程。"""
    from PyQt5.QtGui import QStandardItem

    item = QStandardItem('原本.txt')
    main_window.search_model.appendRow([item])
    qapp.processEvents()

    calls = []
    original = main_window._on_search_result_name_changed
    main_window._on_search_result_name_changed = lambda i: calls.append(i)
    try:
        main_window._revert_search_item_text(item, '還原後.txt')
        qapp.processEvents()
    finally:
        main_window._on_search_result_name_changed = original

    assert item.text() == '還原後.txt'
    assert main_window._search_item_rename_in_progress is False, '旗標要清乾淨'


def test_fop_13_the_guard_flag_is_off_when_idle(main_window):
    assert main_window._search_item_rename_in_progress is False
    assert main_window._search_model_updating is False


# ── FOP-24：多個來源的刷新要合併成一次 ─────────────────────────────────

def test_fop_24_repeated_scheduling_collapses_into_one_timer(main_window):
    """拖放會從多個來源觸發刷新。不合併的話，單一次拖放可以跑三次完整查詢，
    那正是拖放後卡頓兩三秒的成因。
    """
    main_window._schedule_panel_refreshes((250, 900, 1800))
    main_window._schedule_panel_refreshes((600, 1500))

    timer = main_window._panel_refresh_timer
    assert timer.isActive()
    assert timer.interval() == 1500, (
        '第二次呼叫要重設同一個計時器（取該次的最大延遲），'
        '而不是另外排一個——排隊的話一次拖放就會刷新兩次')


def test_fop_24_full_search_sticks_once_any_source_asks_for_it(main_window):
    """多來源併成同一次刷新時，只要任一來源要求完整查詢就得保留。"""
    main_window._pending_full_search = False
    main_window._schedule_panel_refreshes((250,), full_search=False)
    assert main_window._pending_full_search is False

    main_window._schedule_panel_refreshes((250,), full_search=True)
    main_window._schedule_panel_refreshes((250,), full_search=False)
    assert main_window._pending_full_search is True, '不可被後來的 False 蓋掉'


# ── FOP-23：操作涉及的目錄要被監看，且事後解除 ─────────────────────────

def test_fop_23_tracking_watches_both_source_and_target(main_window, tmp_path):
    src_dir = tmp_path / 'src'
    dst_dir = tmp_path / 'dst'
    src_dir.mkdir()
    dst_dir.mkdir()
    src_file = src_dir / 'a.txt'
    src_file.write_text('x', encoding='utf-8')

    main_window.track_file_operation([str(src_file)], str(dst_dir))

    watched = {str(p) for p in main_window._op_fs_watcher.directories()}
    assert str(src_dir) in watched
    assert str(dst_dir) in watched


def test_fop_23_tracking_replaces_the_previous_watch_set(main_window, tmp_path):
    """不解除舊的就會無限累積 watcher。"""
    first, second = tmp_path / '第一批', tmp_path / '第二批'
    first.mkdir()
    second.mkdir()

    main_window.track_file_operation([], str(first))
    main_window.track_file_operation([], str(second))

    watched = {str(p) for p in main_window._op_fs_watcher.directories()}
    assert watched == {str(second)}


def test_fop_23_missing_directories_are_not_watched(main_window, tmp_path):
    main_window.track_file_operation([], str(tmp_path / '不存在的目錄'))
    assert main_window._op_fs_watcher.directories() == []
