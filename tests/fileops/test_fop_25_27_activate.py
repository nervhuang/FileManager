"""FOP-25 到 FOP-27：雙擊／Enter 要開什麼。

判定抽成純函式之後，「多選時忽略資料夾」「超過門檻先問一聲」這些規則在 CI 上
測得到——真正開檔的 `os.startfile` 需要真實 shell，所以它是可注入的。
"""
import pytest

from app.fileops import activate, activate_ui

pytestmark = pytest.mark.logic

DIRS = {r'D:\books', r'D:\books\sub'}
FILES = {r'D:\books\a.txt', r'D:\books\b.zip'}


def _isdir(path):
    return path in DIRS


def _exists(path):
    return path in DIRS or path in FILES


def _plan(paths):
    return activate.plan_activation(paths, isdir=_isdir, exists=_exists)


# ── FOP-25：單選 ────────────────────────────────────────────────────────

def test_fop_25_single_folder_is_navigated_into():
    assert _plan([r'D:\books']) == activate.Plan(r'D:\books', ())


def test_fop_25_single_file_is_opened():
    assert _plan([r'D:\books\a.txt']) == activate.Plan(None, (r'D:\books\a.txt',))


def test_fop_25_missing_path_opens_nothing():
    assert _plan([r'D:\gone.txt']) == activate.NOTHING_TO_DO


def test_fop_25_empty_selection_opens_nothing():
    assert _plan([]) == activate.NOTHING_TO_DO
    assert _plan([None, '']) == activate.NOTHING_TO_DO


# ── FOP-27：多選 ────────────────────────────────────────────────────────

def test_fop_27_multi_selection_opens_every_file():
    paths = [r'D:\books\a.txt', r'D:\books\b.zip']
    assert _plan(paths) == activate.Plan(None, tuple(paths))


def test_fop_27_multi_selection_ignores_folders():
    """導覽一次只能去一個地方，混選時資料夾直接略過，不是整批不做。"""
    plan = _plan([r'D:\books', r'D:\books\a.txt'])
    assert plan == activate.Plan(None, (r'D:\books\a.txt',))


def test_fop_27_asks_before_opening_more_than_the_threshold():
    few = activate.Plan(None, tuple(f'f{i}.txt' for i in range(activate.CONFIRM_THRESHOLD)))
    many = activate.Plan(None, tuple(f'f{i}.txt' for i in range(activate.CONFIRM_THRESHOLD + 1)))
    assert not activate.needs_confirmation(few)
    assert activate.needs_confirmation(many)


# ── activate_ui：把判定做出來 ───────────────────────────────────────────

class _FakeMessageBox:
    """替掉 QMessageBox：測試不開對話框，只記下有沒有問、有沒有報錯。"""
    Yes, No = 1, 0

    def __init__(self):
        self.asked = []
        self.warned = []
        self.answer = self.Yes

    def question(self, parent, title, text, buttons=None, default=None):
        self.asked.append(text)
        return self.answer

    def warning(self, parent, title, text):
        self.warned.append(text)


@pytest.fixture
def box(monkeypatch):
    fake = _FakeMessageBox()
    monkeypatch.setattr(activate_ui, 'QMessageBox', fake)
    return fake


def test_fop_25_folder_goes_to_navigate_not_to_startfile(box, tmp_path):
    opened, visited = [], []
    handled = activate_ui.activate_paths([str(tmp_path)], visited.append,
                                         open_file=opened.append)
    assert handled and visited == [str(tmp_path)] and opened == []


def test_fop_25_file_goes_to_startfile(box, tmp_path):
    target = tmp_path / 'a.txt'
    target.write_text('x', encoding='utf-8')
    opened, visited = [], []
    handled = activate_ui.activate_paths([str(target)], visited.append,
                                         open_file=opened.append)
    assert handled and opened == [str(target)] and visited == []


def test_fop_25_nothing_to_open_is_not_handled(box):
    """回 False 才能讓 Enter 繼續往下傳給其他處理。"""
    assert activate_ui.activate_paths([r'D:\gone.txt'], lambda p: None,
                                      open_file=lambda p: None) is False


def test_fop_27_declining_the_confirmation_opens_nothing(box, tmp_path):
    files = []
    for i in range(activate.CONFIRM_THRESHOLD + 1):
        f = tmp_path / f'f{i}.txt'
        f.write_text('x', encoding='utf-8')
        files.append(str(f))
    box.answer = _FakeMessageBox.No
    opened = []
    handled = activate_ui.activate_paths(files, lambda p: None, open_file=opened.append)
    assert handled and box.asked and opened == []


def test_fop_27_one_failure_reports_once_and_stops(box, tmp_path):
    files = []
    for name in ('a.txt', 'b.txt', 'c.txt'):
        f = tmp_path / name
        f.write_text('x', encoding='utf-8')
        files.append(str(f))

    def boom(path):
        raise OSError('沒有關聯的程式')

    activate_ui.activate_paths(files, lambda p: None, open_file=boom)
    assert len(box.warned) == 1
