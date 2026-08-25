"""搜尋結果的大小欄位格式化。純函式，不需要 QApplication。"""
import pytest

from app.search.results import format_size

pytestmark = pytest.mark.logic

KB = 1024
MB = 1024 ** 2
GB = 1024 ** 3


@pytest.mark.parametrize("size, expected", [
    pytest.param(0, '0 B', id="零"),
    pytest.param(1, '1 B', id="一位元組"),
    pytest.param(KB - 1, '1023 B', id="未滿1KB仍顯示位元組"),
    pytest.param(KB, '1.0 KB', id="剛好1KB"),
    pytest.param(MB - 1, '1024.0 KB', id="未滿1MB"),
    pytest.param(MB, '1.0 MB', id="剛好1MB"),
    pytest.param(GB - 1, '1024.0 MB', id="未滿1GB"),
    pytest.param(GB, '1.0 GB', id="剛好1GB"),
    pytest.param(5 * GB + GB // 2, '5.5 GB', id="數GB"),
])
def test_format_size_at_each_boundary(size, expected):
    assert format_size(size) == expected


def test_format_size_keeps_one_decimal():
    """搜尋結果一次幾百列，小數點後兩位只會讓欄位變寬。"""
    assert format_size(int(1.25 * MB)) == '1.2 MB'


def test_format_size_beyond_gb_stays_in_gb():
    """沒有 TB：超過 1024GB 就繼續用 GB，不再往上換算單位。"""
    assert format_size(2048 * GB) == '2048.0 GB'
