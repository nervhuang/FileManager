"""wnacg 的結果與 exhentai 混在同一份 findings 裡。見 docs/spec/checker.md。

主鍵共用，所以來源要能從 gid 認出來：網址、縮圖、判定都靠它分辨。
`checker_state` 另外記 wnacg 自己的分頁基準——兩個站的發布時間各走各的，
共用一個基準會讓第二個來源第一次跑就只抓到最近幾天。

不需要 Qt：這裡自己開一個記憶體資料庫。
"""
import sqlite3

import pytest

from app.checker import matcher, store, wnacg

pytestmark = pytest.mark.logic


@pytest.fixture
def conn():
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute('CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT, type TEXT)')
    # `_UNDECIDED` 會查作者與社團的相連關係（同一個人的兩個身分共用決定）。
    con.execute('CREATE TABLE links (author_id INTEGER, circle_id INTEGER,'
                ' PRIMARY KEY (author_id, circle_id))')
    con.execute("INSERT INTO entities VALUES (1, '南浜よりこ', 'artist')")
    store.ensure_schema(con)
    yield con
    con.close()


def test_findings_from_both_sources_live_side_by_side(conn):
    store.save_findings(conn, 1, [
        {'gid': '4140403', 'token': 'abc', 'core': '甲', 'title': '甲',
         'verdict': matcher.VERDICT_NEW},
        {'gid': 'wn-377256', 'core': '乙', 'title': '乙',
         'verdict': matcher.VERDICT_NEW, 'markers': [wnacg.MARKER]},
    ])
    by_gid = {i['gid']: i for i in store.load_findings(conn)}
    assert by_gid['4140403']['url'] == 'https://exhentai.org/g/4140403/abc/'
    assert by_gid['wn-377256']['url'] == \
        'https://www.wnacg.com/photos-index-aid-377256.html'
    assert wnacg.MARKER in by_gid['wn-377256']['markers'], '卡片要看得出來源'


def test_the_two_sources_keep_separate_scan_cursors(conn):
    store.record_scan(conn, 1, newest_posted='2026-08-30 21:29')
    assert store.last_wnacg_posted(conn, 1) is None, 'wnacg 還沒掃過'

    store.record_scan(conn, 1, wnacg_posted=1786735479)
    assert store.last_wnacg_posted(conn, 1) == 1786735479
    # exhentai 那邊的基準不能被洗掉。
    assert store.last_posted(conn, 1).strftime('%Y-%m-%d %H:%M') == '2026-08-30 21:29'


def test_an_empty_wnacg_scan_keeps_the_previous_cursor(conn):
    """抓取失敗或這輪沒有新書時不得把基準往前推，否則會跳過沒掃到的區間。"""
    store.record_scan(conn, 1, wnacg_posted=1786735479)
    store.record_scan(conn, 1, newest_posted='2026-09-01 00:00')
    assert store.last_wnacg_posted(conn, 1) == 1786735479


def test_schema_upgrades_an_old_database_in_place():
    """舊資料庫沒有 wnacg_posted 欄位，開起來要自己補上，不是炸掉。"""
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute('CREATE TABLE checker_state ('
                ' entity_id INTEGER PRIMARY KEY, last_scan_at TEXT NOT NULL,'
                " last_posted TEXT NOT NULL DEFAULT '', truncated INTEGER NOT NULL DEFAULT 0,"
                " error TEXT NOT NULL DEFAULT '')")
    con.execute("INSERT INTO checker_state VALUES (1, '2026-01-01', '2026-01-01 00:00', 0, '')")

    store.ensure_schema(con)

    assert store.last_wnacg_posted(con, 1) is None
    store.record_scan(con, 1, wnacg_posted=123)
    assert store.last_wnacg_posted(con, 1) == 123
    con.close()
