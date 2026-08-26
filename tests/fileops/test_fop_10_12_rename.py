"""FOP-10 到 FOP-12：重新命名的判定。

FOP-12（僅改大小寫）是曾經出過問題的那一條：Windows 的 `os.path.exists` 不分
大小寫，會把「同一個檔案改大小寫」誤判成目標已存在而拒絕。修好之後一直沒有
測試守著。

純函式，不需要 QApplication。
"""
import os

import pytest

from app.fileops.rename import INVALID_CHARS, NOTHING_TO_DO, plan_rename

pytestmark = pytest.mark.logic


@pytest.fixture
def existing(tmp_path):
    path = tmp_path / 'Report.txt'
    path.write_text('x', encoding='utf-8')
    return path


# ── FOP-10：沒有要改 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("new_name", ['', '   ', 'Report.txt', '  Report.txt  '])
def test_fop_10_empty_or_unchanged_name_does_nothing(existing, new_name):
    """空白或與原名相同都不算錯誤，呼叫端只要把顯示還原。"""
    assert plan_rename(str(existing), new_name) == NOTHING_TO_DO


def test_fop_10_none_is_treated_as_empty(existing):
    assert plan_rename(str(existing), None) == NOTHING_TO_DO


# ── FOP-11：無效字元 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("ch", list(INVALID_CHARS))
def test_fop_11_rejects_every_invalid_character(existing, ch):
    plan = plan_rename(str(existing), f'a{ch}b.txt')
    assert plan.new_path is None
    assert plan.error == '檔名包含無效字元。'


def test_fop_11_accepts_characters_windows_allows(existing):
    """空白、點、括號、中日文都是合法檔名字元，不該被擋。"""
    plan = plan_rename(str(existing), '新 檔名 (v2).ver.1 とある.txt')
    assert plan.error is None
    assert os.path.basename(plan.new_path) == '新 檔名 (v2).ver.1 とある.txt'


# ── FOP-12：僅改大小寫 ────────────────────────────────────────────────────

def test_fop_12_case_only_rename_is_allowed(existing):
    """這是曾經壞掉的那一條：os.path.exists 不分大小寫，
    「Report.txt → report.txt」會被誤判成目標已存在。"""
    plan = plan_rename(str(existing), 'report.txt')
    assert plan.error is None, '僅改大小寫不該被當成名稱衝突'
    assert os.path.basename(plan.new_path) == 'report.txt'


def test_fop_12_rejects_a_name_taken_by_a_different_file(existing, tmp_path):
    other = tmp_path / 'Other.txt'
    other.write_text('y', encoding='utf-8')

    plan = plan_rename(str(existing), 'Other.txt')
    assert plan.new_path is None
    assert plan.error == '目標名稱已存在。'


def test_fop_12_rejects_a_taken_name_regardless_of_its_case(existing, tmp_path):
    """目標是另一個檔案時，大小寫不同也要擋——Windows 上那就是同一個名字。"""
    (tmp_path / 'Other.txt').write_text('y', encoding='utf-8')
    assert plan_rename(str(existing), 'other.txt').error == '目標名稱已存在。'


# ── 目標路徑 ──────────────────────────────────────────────────────────────

def test_new_path_stays_in_the_same_directory(existing):
    plan = plan_rename(str(existing), '改好的名字.txt')
    assert os.path.dirname(plan.new_path) == os.path.dirname(str(existing))
