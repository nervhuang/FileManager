"""搜尋結果的呈現。不依賴 Qt。"""

_UNITS = (
    (1024 ** 3, 'GB'),
    (1024 ** 2, 'MB'),
    (1024, 'KB'),
)


def format_size(size):
    """把位元組數格式化成人看的大小。

    未滿 1 KB 顯示整數位元組，其餘取一位小數——搜尋結果一次幾百列，
    小數點後兩位只會讓欄位變寬而不會讓人更懂。
    """
    for threshold, unit in _UNITS:
        if size >= threshold:
            return f'{size / threshold:.1f} {unit}'
    return f'{size} B'
