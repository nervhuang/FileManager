"""TAB-18：把絕對路徑拆成麵包屑分段。

回傳 `[(顯示文字, 完整路徑), …]`——顯示文字是那一層的名字，完整路徑是點下去
要導覽到的地方，兩者不同（第一段顯示 `D:` 但要導到 `D:\\`）。

純函式，不需要 QApplication。
"""
import os

import pytest

from app.tabs.breadcrumb import split_path

pytestmark = pytest.mark.logic

SEP = os.sep


def test_tab_18_splits_a_normal_path():
    assert split_path(r'D:\PycharmProjects\FileManager') == [
        ('D:', 'D:' + SEP),
        ('PycharmProjects', r'D:\PycharmProjects'),
        ('FileManager', r'D:\PycharmProjects\FileManager'),
    ]


def test_tab_18_drive_letter_navigates_to_the_root():
    """顯示的是 `D:`，但點下去要到 `D:\\`——少了分隔符 Windows 會解讀成
    「該磁碟的當前目錄」，不是根目錄。"""
    display, target = split_path('D:' + SEP)[0]
    assert display == 'D:'
    assert target == 'D:' + SEP


def test_tab_18_drive_without_separator_is_normalised():
    assert split_path('C:') == split_path('C:' + SEP)


def test_tab_18_trailing_separator_adds_no_empty_segment():
    assert split_path('D:' + SEP + 'a' + SEP + 'b' + SEP) == [
        ('D:', 'D:' + SEP), ('a', r'D:\a'), ('b', r'D:\a\b'),
    ]


def test_tab_18_handles_non_ascii_names():
    assert split_path(r'D:\同人誌\新刊') == [
        ('D:', 'D:' + SEP), ('同人誌', r'D:\同人誌'), ('新刊', r'D:\同人誌\新刊'),
    ]


def test_tab_18_normalises_dot_dot():
    """路徑正規化後才分段，`..` 不會變成一顆麵包屑。"""
    assert split_path(r'D:\a\..\b') == [('D:', 'D:' + SEP), ('b', r'D:\b')]


def test_tab_18_unc_path_keeps_server_and_share_together():
    """`\\\\server\\share` 是一個不可分的根，拆開來的任何一半都不是有效路徑。"""
    segments = split_path(r'\\server\share\dir')
    assert segments[0] == (r'\\server\share', '\\\\server\\share' + SEP)
    assert segments[1] == ('dir', r'\\server\share\dir')


@pytest.mark.parametrize("path", ['', '.'])
def test_tab_18_empty_and_dot_yield_no_segments(path):
    """沒有可顯示的路徑時回空清單，麵包屑因此顯示成空的而不是一顆假的分段。"""
    assert split_path(path) == []
