"""同一本書掛在相連的作者與團體底下時，一個決定要同時擋住兩邊。
見 docs/spec/checker.md「決定的作用範圍」。

同人誌同時掛作者 tag 與社團 tag，兩邊各是一次獨立的掃描、各自抓回不同的 gid。
決定的身分是 `(entity_id, core)`，於是在「モモのすけ」按下的忽略擋不住
「モモかん」那一邊，同一本書再冒出來一次——實測資料庫裡 34 筆是這樣來的，
其中 31 筆的兩個實體在 `links` 裡本來就相連（是同一個人的兩個身分）。

剩下 3 筆是合志本（`COMIC ExE 69`、`HotMilk Festival All Star Comic`），
不同作者共用一個標題，那不在這條規則的範圍內：跨不相連的作者仍然不共用，
核心標題短起來只有幾個字（實測有 `zds`、`rgb`），共用會誤殺別人的書。
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
    con.execute('CREATE TABLE links (author_id INTEGER, circle_id INTEGER,'
                ' PRIMARY KEY (author_id, circle_id))')
    con.execute("INSERT INTO entities VALUES (1, 'モモのすけ', 'author')")
    con.execute("INSERT INTO entities VALUES (2, 'モモかん', 'circle')")
    con.execute("INSERT INTO entities VALUES (3, '不相干的作者', 'author')")
    con.execute('INSERT INTO links VALUES (1, 2)')     # 作者與他的社團
    store.ensure_schema(con)
    yield con
    con.close()


def _add(conn, gid, *, core, entity_id, verdict=matcher.VERDICT_NEW):
    store.save_findings(conn, entity_id, [
        {'gid': gid, 'core': core, 'verdict': verdict, 'title': core}])


def _visible(conn):
    return {item['gid'] for item in store.load_findings(conn)}


def test_a_decision_covers_the_same_work_under_the_linked_circle(conn):
    """在作者那邊按的忽略，也擋住社團那邊抓回來的同一本書。"""
    _add(conn, '111', core='催眠えっち調教', entity_id=1)
    _add(conn, '222', core='催眠えっち調教', entity_id=2)   # 社團 tag 抓到的同一本
    store.set_decision(conn, '111', store.STATE_IGNORED, entity_id=1)

    assert _visible(conn) == set()
    assert store.counts(conn)[matcher.VERDICT_NEW] == 0


def test_the_link_works_in_both_directions(conn):
    """決定按在社團那一邊也一樣：links 只有一列，方向不該決定結果。"""
    _add(conn, '111', core='催眠えっち調教', entity_id=1)
    _add(conn, '222', core='催眠えっち調教', entity_id=2)
    store.set_decision(conn, '222', store.STATE_IGNORED, entity_id=2)

    assert _visible(conn) == set()


def test_a_later_scan_of_the_circle_cannot_bring_the_work_back(conn):
    """決定在前、社團那一輪掃描在後：新抓到的 gid 同樣不該冒出來。"""
    _add(conn, '111', core='催眠えっち調教', entity_id=1)
    store.set_decision(conn, '111', store.STATE_IGNORED, entity_id=1)

    _add(conn, '222', core='催眠えっち調教', entity_id=2)
    assert _visible(conn) == set()


def test_unrelated_authors_still_do_not_share_decisions(conn):
    """沒有 links 相連的兩位作者不共用：短核心標題會互相誤殺。"""
    _add(conn, '111', core='zds', entity_id=1)
    _add(conn, '333', core='zds', entity_id=3)
    store.set_decision(conn, '111', store.STATE_IGNORED, entity_id=1)

    assert _visible(conn) == {'333'}
