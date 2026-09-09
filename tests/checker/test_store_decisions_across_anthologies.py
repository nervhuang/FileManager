"""合志本與商業誌：核心標題與掛名都相同，就是同一本書，不管掃到它的是誰。
見 docs/spec/checker.md「決定的作用範圍」。

`COMIC ExE 69` 這種商業誌與 `[フェチズムポケット (よろず)]` 這種合志本，會在
每一位參與作者的 tag 底下各出現一次，各自是不同的 gid。作者之間沒有 `links`
關係（他們本來就是不同的人），所以「相同或相連的實體」那條規則擋不住——
實測按過忽略之後仍有 7 部這樣的作品回到清單裡。

判準是**掛名**（`titles.attribution_key`），不是核心標題的長度。實測資料庫裡
`C108 おまけ本`（8 字）是兩位作者各自的不同書、`fanbox`（6 字）也是，
而合志本 `酒と愛液と男と女` 同樣是 8 字——長度分不開這兩類，掛名可以。
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
    con.execute("INSERT INTO entities VALUES (1, 'ぴろまゆ', 'author')")
    con.execute("INSERT INTO entities VALUES (2, 'へんりいだ', 'author')")  # 不相連
    store.ensure_schema(con)
    yield con
    con.close()


def _add(conn, gid, title, entity_id):
    """照實際掃描的樣子存：`core` 與掛名都由 store 從標題自己算。"""
    from app.checker import titles
    parsed = titles.parse(title)
    store.save_findings(conn, entity_id, [
        {'gid': gid, 'core': parsed['core'], 'title': title, 'title_jpn': title,
         'verdict': matcher.VERDICT_NEW}])


def _visible(conn):
    return {item['gid'] for item in store.load_findings(conn)}


def test_a_commercial_magazine_is_one_work_across_authors(conn):
    """商業誌兩邊都沒有社團括號，核心標題相同即同一本。"""
    _add(conn, '3882030', 'コミック エグゼ 69 [DL版]', 1)
    _add(conn, '4054001', 'コミック エグゼ 69 [中国翻訳] [DL版]', 2)
    store.set_decision(conn, '3882030', store.STATE_IGNORED, entity_id=1)

    assert _visible(conn) == set()


def test_an_anthology_is_one_work_across_contributors(conn):
    """合志本的 `[社團 (よろず)]` 在每位參與作者底下都一模一樣。"""
    _add(conn, '2034988', '[フェチズムポケット (よろず)] 酒と愛液と男と女 [DL版]', 1)
    _add(conn, '3530371', '[フェチズムポケット (よろず)] 酒と愛液と男と女 [中国翻訳] [DL版]', 2)
    store.set_decision(conn, '2034988', store.STATE_IGNORED, entity_id=1)

    assert _visible(conn) == set()


def test_the_same_core_under_a_different_name_is_a_different_book(conn):
    """核心標題碰巧相同、掛名不同：那是兩本書，忽略一本不該消掉另一本。"""
    _add(conn, '4153797', '(C108) [リンゴヤ (あるぷ)] C108 おまけ本 (ラブライブ!)', 1)
    _add(conn, '4166948', '[玉之けだま] C108おまけ本', 2)
    store.set_decision(conn, '4153797', store.STATE_IGNORED, entity_id=1)

    assert _visible(conn) == {'4166948'}


def test_punctuation_differences_in_the_name_do_not_split_the_work(conn):
    """掛名與核心標題用同一套正規化：不同來源的標點與空白幾乎必定不同。"""
    _add(conn, '111', '[青水庵 (四万十川 、にやすけ)] デリヘルでみつけたドM天使 1-2', 1)
    _add(conn, '222', '[青水庵 (四万十川、にやすけ)] デリヘルでみつけたドM天使 1-2 [DL版]', 2)
    store.set_decision(conn, '111', store.STATE_IGNORED, entity_id=1)

    assert _visible(conn) == set()


def test_a_short_bare_title_is_not_shared_across_authors(conn):
    """兩邊都沒有社團括號時，短核心標題不共用。

    空掛名不構成「同一本」的證據。光靠核心標題相同就共用，會讓兩位作者各自那本
    短標題的書互相消掉（規格舉的 `zds`、`rgb`）。實測空掛名而真的該合併的最短是
    `コミックエグゼ69`（9 字），會誤傷的最長是 3 字，門檻取 8。
    """
    _add(conn, '111', 'zds', 1)
    _add(conn, '222', 'zds', 2)
    store.set_decision(conn, '111', store.STATE_IGNORED, entity_id=1)

    assert _visible(conn) == {'222'}
