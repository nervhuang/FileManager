"""使用者的決定以「作品」為單位生效。見 docs/spec/checker.md「決定的作用範圍」。

站上同一本書會被重複上傳、也會有多語版本，每一次上傳都是不同的 gid。決定只認
gid 的話，按過「忽略」的書會在下一次掃描抓到另一次上傳時原封不動再冒出來，
而且永遠按不掉——每按一次只擋住那一個 gid。實測資料庫裡 3300 張卡片有 149 張
是這樣來的。

不需要 Qt，也不需要 authors.db 以外的東西：這裡自己開一個記憶體資料庫。
"""
import sqlite3

import pytest

from app.checker import matcher, store

pytestmark = pytest.mark.logic


@pytest.fixture
def conn():
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    # store 的查詢會 LEFT JOIN entities 取作者名；那張表屬於 authors_db，
    # 這裡只需要它存在，欄位取 store 真的會讀到的那幾個。
    con.execute('CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT, type TEXT)')
    con.execute("INSERT INTO entities VALUES (1, 'As109', 'artist')")
    con.execute("INSERT INTO entities VALUES (2, '別的作者', 'artist')")
    store.ensure_schema(con)
    yield con
    con.close()


def _add(conn, gid, *, core, entity_id=1, verdict=matcher.VERDICT_NEW):
    store.save_findings(conn, entity_id, [
        {'gid': gid, 'core': core, 'verdict': verdict, 'title': core}])


def _visible(conn):
    return {item['gid'] for item in store.load_findings(conn)}


def test_a_decision_covers_every_upload_of_the_same_work(conn):
    """同一部作品的其他上傳與其他語言版本，一併不再出現。"""
    _add(conn, '111', core='鬼針草')
    _add(conn, '222', core='鬼針草')          # 同一本書的另一次上傳
    _add(conn, '333', core='別本書')
    store.set_decision(conn, '111', store.STATE_IGNORED, entity_id=1)

    assert _visible(conn) == {'333'}
    assert store.counts(conn)[matcher.VERDICT_NEW] == 1


def test_a_later_scan_cannot_bring_the_work_back(conn):
    """決定在前、掃描在後：新抓到的上傳同樣不該冒出來。

    這才是真正的症狀。決定當下就地展開（把同 core 的 gid 一起寫進決定表）擋不住
    這條路——下一次掃描抓到的 gid 在按下按鈕的當下還不存在。
    """
    _add(conn, '111', core='鬼針草')
    store.set_decision(conn, '111', store.STATE_IGNORED, entity_id=1)
    _add(conn, '999', core='鬼針草')          # 重新掃描抓到的新上傳

    assert _visible(conn) == set()


def test_downloaded_also_covers_the_whole_work(conn):
    """「已下載」同理：下載的是那部作品，不是那一次上傳。"""
    _add(conn, '111', core='鬼針草')
    _add(conn, '222', core='鬼針草')
    store.set_decision(conn, '111', store.STATE_DOWNLOADED, entity_id=1)

    assert _visible(conn) == set()


def test_the_same_core_under_another_author_is_another_work(conn):
    """作品的身分是 (entity_id, core)，與 scanner.aggregate() 的分組鍵同源。

    核心標題短起來只有幾個字（實測有 'zds'、'rgb'），跨作者共用一個 core
    完全可能。不分作者的話，忽略一本會連帶消掉別人的另一本。
    """
    _add(conn, '111', core='zds', entity_id=1)
    _add(conn, '222', core='zds', entity_id=2)
    store.set_decision(conn, '111', store.STATE_IGNORED, entity_id=1)

    assert _visible(conn) == {'222'}


def test_an_empty_core_falls_back_to_the_gid(conn):
    """解析不出核心標題時退回只認 gid。

    不退回的話，所有 core 為空的項目會被當成同一部作品互相消掉——按一本
    就整批消失。
    """
    _add(conn, '111', core='')
    _add(conn, '222', core='')
    store.set_decision(conn, '111', store.STATE_IGNORED, entity_id=1)

    assert _visible(conn) == {'222'}


def test_clearing_the_decision_brings_the_whole_work_back(conn):
    _add(conn, '111', core='鬼針草')
    _add(conn, '222', core='鬼針草')
    store.set_decision(conn, '111', store.STATE_IGNORED, entity_id=1)
    store.clear_decision(conn, '111')

    assert _visible(conn) == {'111', '222'}
