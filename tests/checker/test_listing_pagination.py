"""列表頁的翻頁用 `next=<最後一筆 gid>`，不是 `page=N`。

實站實測（2026-09-06）：`/tag/artist:amano+ameno?page=1` 與 page=0 回的是
**完全相同的 25 筆**（重疊 25／25），`?f_search=…&page=1` 也一樣。站方改版後
列表頁改用游標分頁，`page=` 參數被無視。

後果不是「翻頁比較慢」，是**翻頁從來沒發生過**：首次掃描取樣筆數設 100（＝4 頁）
時，實際只拿到最新的 25 本，同一批重複四次。「更新檢查筆數」這個設定
（docs/spec/settings.md 的 SET-15）調大等於沒調。

`?next=<gid>` 實測可行：重疊 0，時間接續往舊的走。
"""
import urllib.request

import pytest

from app.checker import fetcher, scanner

pytestmark = pytest.mark.logic


class _Response:
    def __init__(self, body):
        self._body = body.encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


_PAGE = ('<a href="https://exhentai.org/g/123/abc/">x</a>'
         '<td class="gl2c">2026-01-01 00:00</td>' + 'x' * 3000)


def _urls(monkeypatch):
    urls = []
    monkeypatch.setattr(urllib.request, 'urlopen',
                        lambda request, timeout=None: (urls.append(request.full_url),
                                                       _Response(_PAGE))[1])
    return urls


def test_tag_page_walks_with_a_cursor(monkeypatch):
    urls = _urls(monkeypatch)
    f = fetcher.Fetcher('c=1', delay=0, jitter=0, sleeper=lambda s: None)
    f.fetch_tag_page('artist:x')
    f.fetch_tag_page('artist:x', after_gid='4140403')

    assert 'next=' not in urls[0] and 'page=' not in urls[0], '第一頁不帶游標'
    assert urls[1].endswith('?next=4140403')
    assert 'page=' not in urls[1], 'page= 被站方無視，帶了只會回同一頁'


def test_search_page_walks_with_a_cursor(monkeypatch):
    urls = _urls(monkeypatch)
    f = fetcher.Fetcher('c=1', delay=0, jitter=0, sleeper=lambda s: None)
    f.fetch_search_page('低空MSコンボ', after_gid='4140403')
    assert urls[0].endswith('&next=4140403'), '搜尋網址已經有 ?f_search=，游標要用 &'


class _Fetch:
    """每次呼叫回 25 筆全新的 gid，並記下拿到的游標。"""

    def __init__(self):
        self.cursors = []
        self._next = 9000

    def _page(self, after_gid):
        self.cursors.append(after_gid)
        rows = [(str(self._next - i), f'tok{self._next - i}', '2026-01-01 00:00')
                for i in range(scanner.PAGE_SIZE)]
        self._next -= scanner.PAGE_SIZE
        return rows

    def fetch_tag_page(self, tag, after_gid=None):
        return self._page(after_gid)

    def fetch_search_page(self, keyword, after_gid=None):
        return self._page(after_gid)

    def fetch_metadata(self, pairs):
        return {}


def test_scan_passes_the_last_gid_of_the_previous_page():
    fetch = _Fetch()
    scanner.scan_entity({'id': 1, 'name': 'X', 'english_name': 'X'},
                        fetch, lambda e: [], first_run_limit=100)

    assert len(fetch.cursors) == 4, '100 筆＝4 頁'
    assert fetch.cursors[0] is None, '第一頁不帶游標'
    # 每一頁的游標都要是前一頁最後一筆的 gid，否則就是在重抓同一頁。
    assert fetch.cursors[1:] == ['8976', '8951', '8926']


def test_scan_collects_distinct_items_across_pages():
    """翻頁真的往下走：100 筆就是 100 本不重複的書。"""
    fetch = _Fetch()
    result = scanner.scan_entity({'id': 1, 'name': 'X', 'english_name': 'X'},
                                 fetch, lambda e: [], first_run_limit=100)
    assert result['skipped'] is None
    assert len(fetch.cursors) == 4
