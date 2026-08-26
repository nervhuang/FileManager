"""AUT-1 到 AUT-7：作者／團體資料庫。

AUT-7（`linked_names` 是新增合併而非整組取代）曾經是 bug：Hermes 一次處理一位
作者、對同一個團體分開多次呼叫 upsert，後寫入的把前面已記錄的關聯整批洗掉。
修好之後一直沒有測試守著。

不依賴 Qt，資料庫開在暫存目錄。
"""
import pytest

from app.authors import db

pytestmark = pytest.mark.logic


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / 'authors.db'))
    yield connection
    connection.close()


def _entity(conn, name, type_):
    found = db.find_entity(conn, name, type_)
    assert found is not None, f'找不到 {type_} {name!r}'
    return db.get_entity(conn, found['id'])


def _linked_names(conn, name, type_):
    return sorted(e['name'] for e in _entity(conn, name, type_)['linked'])


# ── AUT-1／AUT-2：單一來源、一張實體表 ──────────────────────────────────

def test_aut_2_authors_and_circles_live_in_one_table_separated_by_type(conn):
    db.upsert(conn, [{'name': '同名', 'type': db.AUTHOR},
                     {'name': '同名', 'type': db.CIRCLE}])

    assert _entity(conn, '同名', db.AUTHOR)['type'] == db.AUTHOR
    assert _entity(conn, '同名', db.CIRCLE)['type'] == db.CIRCLE


def test_aut_2_aliases_are_replaced_as_a_whole(conn):
    """別名只屬於這個實體自己，整組取代不會影響到別人。"""
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR, 'aliases': ['A', 'B']}])
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR, 'aliases': ['C']}])
    assert _entity(conn, '甲', db.AUTHOR)['aliases'] == ['C']


def test_aliases_are_left_alone_when_not_given(conn):
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR, 'aliases': ['A']}])
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR, 'note': '只改備註'}])
    assert _entity(conn, '甲', db.AUTHOR)['aliases'] == ['A']


# ── AUT-7：linked_names 是新增合併，不是整組取代 ────────────────────────

def test_aut_7_linked_names_merges_instead_of_replacing(conn):
    """這就是曾經壞掉的那一條。

    一筆關聯同時是作者清單的一項、也是團體清單的一項。整組取代會先刪光「這一側」
    的全部關聯列，而那些列同時屬於對方。Hermes 一次處理一位作者、對同一個團體
    分開呼叫多次 upsert，第二次就把第一次寫進去的洗掉了。
    """
    db.upsert(conn, [{'name': '某團體', 'type': db.CIRCLE,
                      'linked_names': ['甲作者']}])
    db.upsert(conn, [{'name': '某團體', 'type': db.CIRCLE,
                      'linked_names': ['乙作者']}])

    assert _linked_names(conn, '某團體', db.CIRCLE) == ['乙作者', '甲作者']


def test_aut_7_upserting_authors_one_at_a_time_also_keeps_both(conn):
    """從作者那一側分開寫入，同樣不該互相洗掉。"""
    db.upsert(conn, [{'name': '甲作者', 'type': db.AUTHOR,
                      'linked_names': ['某團體']}])
    db.upsert(conn, [{'name': '乙作者', 'type': db.AUTHOR,
                      'linked_names': ['某團體']}])

    assert _linked_names(conn, '某團體', db.CIRCLE) == ['乙作者', '甲作者']


def test_aut_7_re_upserting_with_fewer_links_keeps_the_others(conn):
    db.upsert(conn, [{'name': '某團體', 'type': db.CIRCLE,
                      'linked_names': ['甲作者', '乙作者']}])
    db.upsert(conn, [{'name': '某團體', 'type': db.CIRCLE,
                      'linked_names': ['甲作者']}])

    assert _linked_names(conn, '某團體', db.CIRCLE) == ['乙作者', '甲作者']


def test_aut_7_removing_a_link_needs_unlink(conn):
    """要移除關聯得明確呼叫 unlink，不能靠「送一組比較少的 linked_names」。"""
    db.upsert(conn, [{'name': '某團體', 'type': db.CIRCLE,
                      'linked_names': ['甲作者', '乙作者']}])
    author = db.find_entity(conn, '乙作者', db.AUTHOR)
    circle = db.find_entity(conn, '某團體', db.CIRCLE)

    db.unlink(conn, author['id'], circle['id'])

    assert _linked_names(conn, '某團體', db.CIRCLE) == ['甲作者']


def test_linked_names_creates_the_counterpart_when_missing(conn):
    db.upsert(conn, [{'name': '甲作者', 'type': db.AUTHOR,
                      'linked_names': ['還沒建過的團體']}])
    assert db.find_entity(conn, '還沒建過的團體', db.CIRCLE) is not None


def test_link_is_visible_from_both_sides(conn):
    """作者⇄團體是多對多，一筆關聯同時屬於雙方清單。"""
    db.upsert(conn, [{'name': '甲作者', 'type': db.AUTHOR,
                      'linked_names': ['某團體']}])
    assert _linked_names(conn, '甲作者', db.AUTHOR) == ['某團體']
    assert _linked_names(conn, '某團體', db.CIRCLE) == ['甲作者']


# ── AUT-3：軟刪除與異動日誌 ─────────────────────────────────────────────

def test_aut_3_delete_is_soft_and_hides_the_entity_from_listing(conn):
    db.upsert(conn, [{'name': '要刪的', 'type': db.AUTHOR}])
    entity = db.find_entity(conn, '要刪的', db.AUTHOR)

    db.soft_delete(conn, [entity['id']])

    assert db.find_entity(conn, '要刪的', db.AUTHOR) is None
    listed = [e['name'] for e in db.list_entities(conn, include_deleted=True)]
    assert '要刪的' in listed, '軟刪除的資料仍在庫裡，只是預設不列出'


def test_aut_3_every_write_is_journalled_with_before_and_after(conn):
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR, 'note': '第一版'}])
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR, 'note': '第二版'}])

    changes = db.recent_changes(conn)
    assert len(changes) >= 2
    latest = changes[0]
    assert latest['before'] is not None, '更新要留下前後快照才還原得回去'
    assert latest['after']['note'] == '第二版'


def test_aut_3_a_change_can_be_reverted(conn):
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR, 'note': '原本'}])
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR, 'note': '被 Hermes 改壞'}])

    db.revert_change(conn, db.recent_changes(conn)[0]['id'])

    assert _entity(conn, '甲', db.AUTHOR)['note'] == '原本'


# ── AUT-4／AUT-5：english_name ──────────────────────────────────────────

def test_aut_4_english_name_is_kept_when_not_given(conn):
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR, 'english_name': 'Kou'}])
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR, 'note': '只改備註'}])
    assert _entity(conn, '甲', db.AUTHOR)['english_name'] == 'Kou'


def test_aut_4_english_name_does_not_affect_local_search_terms(conn):
    """純中繼資料，只給網站查詢用，不併入搜尋詞。"""
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR,
                      'aliases': ['別名'], 'english_name': 'Kou'}])
    terms = db.search_terms_for(_entity(conn, '甲', db.AUTHOR))
    assert 'Kou' not in terms
    assert terms == '甲|別名'


# ── AUT-6：查詢涵蓋名稱、別名與英文名，且大小寫不敏感 ──────────────────

@pytest.mark.parametrize("keyword", ['甲', '別名', 'kou', 'KOU'])
def test_aut_6_keyword_matches_name_alias_and_english_name(conn, keyword):
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR,
                      'aliases': ['別名'], 'english_name': 'Kou'}])
    found = [e['name'] for e in db.list_entities(conn, keyword=keyword)]
    assert found == ['甲']


def test_aut_6_keyword_that_matches_nothing_returns_nothing(conn):
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR}])
    assert db.list_entities(conn, keyword='完全不相干') == []


# ── search_terms_for ────────────────────────────────────────────────────

def test_search_terms_join_name_and_aliases_with_or(conn):
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR, 'aliases': ['A', 'B']}])
    assert db.search_terms_for(_entity(conn, '甲', db.AUTHOR)) == '甲|A|B'


def test_search_terms_drop_duplicates_and_blanks(conn):
    db.upsert(conn, [{'name': '甲', 'type': db.AUTHOR, 'aliases': ['甲', '  ', 'B']}])
    assert db.search_terms_for(_entity(conn, '甲', db.AUTHOR)) == '甲|B'
