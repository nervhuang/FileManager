"""TAB-22 到 TAB-24：導覽歷史與上一層。

TAB-24（從歷史往回走時不得再記進歷史）是最容易寫壞的一條——寫壞的症狀是
「上一頁」按下去在兩個目錄之間彈來彈去，永遠回不到更早的地方。

純函式，不需要 QApplication。
"""
import os

import pytest

from app.tabs.history import NavigationHistory, parent_of

pytestmark = pytest.mark.logic


@pytest.fixture
def history():
    return NavigationHistory()


# ── 記錄 ──────────────────────────────────────────────────────────────────

def test_empty_history_can_go_nowhere(history):
    assert history.current is None
    assert history.can_go_back is False
    assert history.can_go_forward is False
    assert history.go_back() is None
    assert history.go_forward() is None


def test_recording_moves_current_to_the_new_path(history):
    assert history.record(r'C:\a') is True
    assert history.current == r'C:\a'
    assert history.can_go_back is False      # 只有一筆，回不去


def test_recording_the_same_path_twice_does_nothing(history):
    history.record(r'C:\a')
    assert history.record(r'C:\a') is False
    assert len(history) == 1


def test_recording_an_empty_path_does_nothing(history):
    assert history.record('') is False
    assert history.record(None) is False
    assert len(history) == 0


def test_the_same_path_may_appear_again_after_visiting_elsewhere(history):
    """A → B → A 是三筆。只有「連續重複」才不記。"""
    for path in (r'C:\a', r'C:\b', r'C:\a'):
        history.record(path)
    assert history.entries == (r'C:\a', r'C:\b', r'C:\a')


# ── 上一頁／下一頁 ────────────────────────────────────────────────────────

def test_back_and_forward_walk_the_list(history):
    for path in (r'C:\a', r'C:\b', r'C:\c'):
        history.record(path)

    assert history.go_back() == r'C:\b'
    assert history.go_back() == r'C:\a'
    assert history.can_go_back is False
    assert history.go_forward() == r'C:\b'
    assert history.go_forward() == r'C:\c'
    assert history.can_go_forward is False


def test_tab_24_walking_back_does_not_grow_the_history(history):
    """走歷史不該污染歷史，否則上一頁會在兩個目錄之間彈來彈去。"""
    for path in (r'C:\a', r'C:\b', r'C:\c'):
        history.record(path)
    before = history.entries

    history.go_back()
    history.go_back()
    history.go_forward()

    assert history.entries == before


def test_navigating_somewhere_new_after_going_back_truncates_the_forward_entries(history):
    """分支出去就回不到原來那條線，與瀏覽器一致。"""
    for path in (r'C:\a', r'C:\b', r'C:\c'):
        history.record(path)
    history.go_back()                       # 回到 b，前方還有 c

    history.record(r'C:\新分支')

    assert history.entries == (r'C:\a', r'C:\b', r'C:\新分支')
    assert history.can_go_forward is False


def test_recording_the_current_path_after_going_back_keeps_the_forward_entries(history):
    """回到 b 之後又「導覽到 b」（例如點了同一個分頁），不該截掉 c。"""
    for path in (r'C:\a', r'C:\b', r'C:\c'):
        history.record(path)
    history.go_back()

    assert history.record(r'C:\b') is False
    assert history.can_go_forward is True


# ── 上一層 ────────────────────────────────────────────────────────────────

def test_tab_22_parent_of_a_normal_path():
    assert parent_of(r'D:\a\b') == r'D:\a'


def test_tab_22_parent_of_a_drive_root_is_none():
    """os.path.dirname 對 C:\\ 回的是它自己，這就是「已經到頂」的判斷方式。"""
    assert parent_of('C:' + os.sep) is None


def test_tab_22_parent_ignores_a_trailing_separator():
    assert parent_of('D:' + os.sep + 'a' + os.sep) == 'D:' + os.sep


@pytest.mark.parametrize("path", ['', None])
def test_tab_22_parent_of_nothing_is_none(path):
    assert parent_of(path) is None
