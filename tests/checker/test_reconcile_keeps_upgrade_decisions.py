"""按在「版本升級」上的「已下載」不可被 `reconcile_downloads()` 洗掉。
見 docs/spec/checker.md「狀態記憶」的第 3 條。

`reconcile_downloads()` 的用意是「檔案落地了就把待驗轉正」，判準是判定變成
已有／版本升級。但版本升級這一格的項目**按下按鈕的當下就已經是版本升級**，
判準立刻成立，下一輪掃描就把決定刪掉，那本書原封不動回到清單裡——使用者按幾次
都一樣。實測資料庫裡 48 筆待驗的決定沒有任何一筆是版本升級或已有，正是被洗光的
結果。

轉正的條件應該是「判定**變了**」，不是「判定是那兩種」。
"""
import sqlite3

import pytest

from app.checker import matcher, store

pytestmark = pytest.mark.logic


@pytest.fixture
def conn():
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute('CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT, type TEXT)')
    # `_UNDECIDED` 會查作者與社團的相連關係（同一個人的兩個身分共用決定）。
    con.execute('CREATE TABLE links (author_id INTEGER, circle_id INTEGER,'
                ' PRIMARY KEY (author_id, circle_id))')
    con.execute("INSERT INTO entities VALUES (1, 'As109', 'artist')")
    store.ensure_schema(con)
    yield con
    con.close()


def _add(conn, gid, *, core, verdict, entity_id=1):
    store.save_findings(conn, entity_id, [
        {'gid': gid, 'core': core, 'verdict': verdict, 'title': core}])


def _reverdict(conn, gid, verdict):
    conn.execute('UPDATE checker_findings SET verdict = ? WHERE gid = ?', (verdict, gid))
    conn.commit()


def _visible(conn):
    return {item['gid'] for item in store.load_findings(conn)}


def test_download_marked_on_an_upgrade_survives_the_next_scan(conn):
    """在「版本升級」按「已下載」，下一輪掃描不該讓它重新冒出來。"""
    _add(conn, '111', core='鬼針草', verdict=matcher.VERDICT_UPGRADE)
    store.set_decision(conn, '111', store.STATE_DOWNLOADED, entity_id=1)
    assert _visible(conn) == set()

    assert store.reconcile_downloads(conn, 1) == []
    assert _visible(conn) == set()


def test_download_marked_on_a_have_survives_too(conn):
    """「已有」那一格同理：判定沒變就不算檔案剛落地。"""
    _add(conn, '111', core='鬼針草', verdict=matcher.VERDICT_HAVE)
    store.set_decision(conn, '111', store.STATE_DOWNLOADED, entity_id=1)

    assert store.reconcile_downloads(conn, 1) == []
    assert _visible(conn) == set()


def test_new_book_still_gets_confirmed_when_the_file_lands(conn):
    """原本的用途不能壞：新書按了「已下載」，檔案出現後仍要轉正。"""
    _add(conn, '111', core='鬼針草', verdict=matcher.VERDICT_NEW)
    store.set_decision(conn, '111', store.STATE_DOWNLOADED, entity_id=1)
    assert _visible(conn) == set()

    _reverdict(conn, '111', matcher.VERDICT_HAVE)   # refresh_verdicts() 的效果
    assert store.reconcile_downloads(conn, 1) == ['111']
    assert _visible(conn) == {'111'}


def test_upgrade_marked_then_downgraded_to_have_gets_confirmed(conn):
    """在版本升級按了已下載、更好的版本真的進來了：判定變成已有，該轉正。"""
    _add(conn, '111', core='鬼針草', verdict=matcher.VERDICT_UPGRADE)
    store.set_decision(conn, '111', store.STATE_DOWNLOADED, entity_id=1)

    _reverdict(conn, '111', matcher.VERDICT_HAVE)
    assert store.reconcile_downloads(conn, 1) == ['111']
