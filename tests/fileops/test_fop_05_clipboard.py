"""FOP-5、FOP-5a、FOP-6：剪貼簿的判定。

重點在 `decide_paste_op`：剪下之後，如果使用者在別的程式又複製了東西，
貼上必須退回「複製」而不是「搬移」。這條規則的代價不對稱——判成複製最多多一份
檔案，判成搬移卻會動到使用者只想複製的東西。

純函式，不需要 QApplication。
"""
import os

import pytest

from app.fileops.clipboard import (COPY, MOVE, decide_paste_op, normalise,
                                   unique_paths)

pytestmark = pytest.mark.logic


# ── 正規化 ────────────────────────────────────────────────────────────────

def test_normalise_makes_windows_paths_comparable():
    """大小寫、分隔符、`..` 全部統一之後才比得出「是不是同一批」。"""
    a = normalise([r'D:\A\B.txt'])
    b = normalise(['d:/a/b.txt'])
    c = normalise([r'D:\A\x\..\B.txt'])
    assert a == b == c


def test_normalise_drops_empty_entries():
    assert normalise([r'D:\a', '', None]) == normalise([r'D:\a'])


# ── 去重 ──────────────────────────────────────────────────────────────────

def test_unique_paths_keeps_the_first_occurrence_order():
    assert unique_paths([r'D:\b', r'D:\a', r'D:\b']) == [r'D:\b', r'D:\a']


def test_unique_paths_drops_empty_entries():
    assert unique_paths(['', r'D:\a', None]) == [r'D:\a']


def test_unique_paths_does_not_normalise():
    """去重只看字面。正規化是比對用的，不該把實際要操作的路徑改掉。"""
    assert unique_paths([r'D:\A.txt', r'd:\a.txt']) == [r'D:\A.txt', r'd:\a.txt']


# ── 貼上要搬還是要複製 ────────────────────────────────────────────────────

def test_fop_5_cut_then_paste_the_same_files_moves():
    cut = [r'D:\a.txt', r'D:\b.txt']
    assert decide_paste_op(MOVE, normalise(cut), cut) == MOVE


def test_fop_5_copy_then_paste_copies():
    copied = [r'D:\a.txt']
    assert decide_paste_op(COPY, normalise(copied), copied) == COPY


def test_fop_5_cut_then_someone_else_wrote_the_clipboard_copies():
    """在檔案總管複製了別的東西之後貼上——不能搬走那些檔案。"""
    cut = [r'D:\a.txt']
    from_explorer = [r'D:\完全不同的檔案.txt']
    assert decide_paste_op(MOVE, normalise(cut), from_explorer) == COPY


def test_fop_5_cut_then_clipboard_gained_an_extra_file_copies():
    """內容變了就不算同一批，即使原本那些還在裡面。"""
    cut = [r'D:\a.txt']
    now = [r'D:\a.txt', r'D:\多出來的.txt']
    assert decide_paste_op(MOVE, normalise(cut), now) == COPY


def test_fop_5_paste_matches_regardless_of_case_or_separator():
    """剪貼簿回來的路徑可能是 Qt 的正斜線形式，仍該認得出是同一批。"""
    cut = [r'D:\A\B.txt']
    from_clipboard = ['D:/a/b.txt']
    assert decide_paste_op(MOVE, normalise(cut), from_clipboard) == MOVE


def test_fop_5_order_matters_because_it_is_a_tuple_comparison():
    """[未驗] 目前以順序敏感的方式比對。同一批但順序不同會退回複製——
    偏安全的方向，但若之後認為該視為同一批，先改規格與這支測試。"""
    cut = [r'D:\a.txt', r'D:\b.txt']
    reordered = [r'D:\b.txt', r'D:\a.txt']
    assert decide_paste_op(MOVE, normalise(cut), reordered) == COPY


def test_fop_5_nothing_remembered_copies():
    assert decide_paste_op(COPY, (), [r'D:\a.txt']) == COPY
    assert decide_paste_op(MOVE, (), [r'D:\a.txt']) == COPY
