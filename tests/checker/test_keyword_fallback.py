"""沒有英文名稱的作者改用關鍵字搜尋。見 docs/spec/checker.md「掃描規則」。

站上不是每位作者都有 artist/group tag——部分作者根本沒被定義過英文名稱，
tag 查詢對他們永遠是空的。原本這種情況一律記成「略過」，等於這些作者
從來沒被檢查過。改成拿名稱本身去跑站上的關鍵字搜尋（`?f_search=`）。

不碰網路：`urlopen` 由測試換掉。
"""
import urllib.request

import pytest

from app.checker import fetcher, scanner

pytestmark = pytest.mark.logic


# ── 查詢從哪來 ──────────────────────────────────────────────────────────

def test_english_name_makes_a_tag_query():
    assert fetcher.query_for({'name': '南浜よりこ', 'type': 'author',
                              'english_name': 'Minamihama Yoriko'}) \
        == ('tag', 'artist:minamihama yoriko')


def test_latin_name_makes_a_tag_query_too():
    assert fetcher.query_for({'name': 'MAFIC', 'type': 'circle'}) == ('tag', 'group:mafic')


def test_name_without_english_falls_back_to_a_keyword_query():
    assert fetcher.query_for({'name': '南浜よりこ', 'type': 'author'}) \
        == ('keyword', '南浜よりこ')
    assert fetcher.query_for({'name': '低空MSコンボ', 'type': 'circle'}) \
        == ('keyword', '低空MSコンボ')


def test_a_nameless_entity_has_nothing_to_query():
    assert fetcher.query_for({'name': '   ', 'type': 'author'}) is None


def test_tag_for_still_answers_only_about_tags():
    """既有呼叫端（報告、紀錄）拿 tag_for 判斷「有沒有 tag」，語意不變。"""
    assert fetcher.tag_for({'name': '南浜よりこ', 'type': 'author'}) is None


# ── 關鍵字頁的網址 ──────────────────────────────────────────────────────

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


def test_keyword_page_uses_the_site_search(monkeypatch):
    urls = []

    def fake_urlopen(request, timeout=None):
        urls.append(request.full_url)
        return _Response(_PAGE)

    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    f = fetcher.Fetcher('cookie=1', delay=0, jitter=0, sleeper=lambda s: None)
    f.fetch_search_page('低空MSコンボ')

    assert len(urls) == 1
    assert urls[0].startswith('https://exhentai.org/?f_search=')
    # 名稱要被 URL 編碼；翻頁見 test_listing_pagination.py。
    assert '%E4%BD%8E%E7%A9%BA' in urls[0]


# ── 掃描時真的走關鍵字這條路 ────────────────────────────────────────────

class _Fetch:
    def __init__(self):
        self.tag_calls, self.keyword_calls = [], []

    def fetch_tag_page(self, tag, after_gid=None):
        self.tag_calls.append((tag, after_gid))
        return []

    def fetch_search_page(self, keyword, after_gid=None):
        self.keyword_calls.append((keyword, after_gid))
        return []

    def fetch_metadata(self, pairs):
        return {}


def test_scan_uses_keyword_search_when_there_is_no_english_name():
    fetch = _Fetch()
    result = scanner.scan_entity({'id': 1, 'name': '低空MSコンボ', 'type': 'circle'},
                                 fetch, lambda e: [])

    assert fetch.keyword_calls and fetch.keyword_calls[0][0] == '低空MSコンボ'
    assert not fetch.tag_calls
    assert result['skipped'] is None, '不再略過'
    assert result['keyword'] == '低空MSコンボ'
    assert result['tag'] is None


def test_scan_still_prefers_the_tag_when_there_is_one():
    fetch = _Fetch()
    result = scanner.scan_entity({'id': 1, 'name': 'X', 'type': 'author',
                                  'english_name': 'Ex'}, fetch, lambda e: [])
    assert fetch.tag_calls and fetch.tag_calls[0][0] == 'artist:ex'
    assert not fetch.keyword_calls
    assert result['tag'] == 'artist:ex' and result['keyword'] is None


def test_only_a_nameless_entity_is_skipped():
    fetch = _Fetch()
    result = scanner.scan_entity({'id': 1, 'name': '', 'type': 'author'},
                                 fetch, lambda e: [])
    assert result['skipped'] == 'no_english_name'
    assert not fetch.tag_calls and not fetch.keyword_calls


# ── 掃描紀錄要標明走的是哪一條 ──────────────────────────────────────────

@pytest.mark.gui
def test_log_marks_the_entities_scanned_by_keyword(qapp, tmp_path, monkeypatch):
    """關鍵字比 tag 鬆，撈到的可能只是提到這個名字的作品。不標就會被當成 tag 結果去信任。"""
    monkeypatch.setenv('FILEMANAGER_HOME', str(tmp_path))
    from app.checker.panel import CheckerPanel

    panel = CheckerPanel()
    try:
        panel._on_entity_done(0, 1, {'name': '低空MSコンボ', 'keyword': '低空MSコンボ',
                                     'works': [], 'excluded': 0})
        assert '關鍵字搜尋' in panel.log_view.toPlainText()

        panel._on_entity_done(0, 1, {'name': 'X', 'tag': 'artist:x',
                                     'works': [], 'excluded': 0})
        assert panel.log_view.toPlainText().count('關鍵字搜尋') == 1
    finally:
        panel.close()
