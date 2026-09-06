"""AUT-22、AUT-22a、AUT-22b、AUT-23、AUT-24：「僅顯示無英文名稱」檢視。

英文名稱只在對外查詢時用得到（AUT-4），沒填的那幾筆更新檢查器抓不到東西。
四百筆的清單裡看不出是哪幾筆，所以要有一個只列出它們的檢視。

資料層的篩選是純 SQL，不需要 Qt，測在 logic；選單與標題需要 widget，測在 gui。
"""
import pytest
from PyQt5.QtWidgets import QMenu

from app.authors import db as authors_db
from app.authors.panel import AuthorsPanel


# ── AUT-22b：資料層的判準（logic）────────────────────────────────────────

@pytest.mark.logic
def test_aut_22b_blank_and_null_english_names_both_count_as_missing(tmp_path):
    conn = authors_db.connect(str(tmp_path / 'authors.db'))
    try:
        authors_db.upsert(conn, [
            {'name': '有英文', 'type': authors_db.AUTHOR, 'english_name': 'Has English'},
            {'name': '沒英文', 'type': authors_db.AUTHOR},
            {'name': '空白英文', 'type': authors_db.AUTHOR, 'english_name': '   '},
            {'name': '沒英文的團體', 'type': authors_db.CIRCLE},
        ])

        names = {e['name'] for e in
                 authors_db.list_entities(conn, missing_english_only=True)}
        assert names == {'沒英文', '空白英文', '沒英文的團體'}

        # 預設不篩選，既有呼叫端的行為一字不變。
        assert len(authors_db.list_entities(conn)) == 4
    finally:
        conn.close()


@pytest.mark.logic
def test_aut_22b_filter_combines_with_keyword(tmp_path):
    conn = authors_db.connect(str(tmp_path / 'authors.db'))
    try:
        authors_db.upsert(conn, [
            {'name': '甲沒英文', 'type': authors_db.AUTHOR},
            {'name': '乙沒英文', 'type': authors_db.AUTHOR},
            {'name': '甲有英文', 'type': authors_db.AUTHOR, 'english_name': 'Jia'},
        ])
        names = {e['name'] for e in authors_db.list_entities(
            conn, keyword='甲', missing_english_only=True)}
        assert names == {'甲沒英文'}
    finally:
        conn.close()


# ── 面板（gui）──────────────────────────────────────────────────────────

@pytest.fixture
def panel(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv('FILEMANAGER_HOME', str(tmp_path))
    widget = AuthorsPanel()
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close_db()
    widget.close()


def _seed(panel):
    authors_db.upsert(panel._conn, [
        {'name': '有英文作者', 'type': authors_db.AUTHOR, 'english_name': 'Has'},
        {'name': '沒英文作者', 'type': authors_db.AUTHOR},
        {'name': '有英文團體', 'type': authors_db.CIRCLE, 'english_name': 'HasCircle',
         'linked_names': ['沒英文作者']},
        {'name': '沒英文團體', 'type': authors_db.CIRCLE},
    ])
    panel.reload()


def _texts(panel):
    model = panel.tree.model()
    out = []

    def walk(parent):
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            out.append(index.data())
            walk(index)

    walk(panel.tree.rootIndex())
    return out


def _group_index(panel, prefix):
    model = panel.tree.model()
    for row in range(model.rowCount()):
        index = model.index(row, 0)
        if index.data().startswith(prefix):
            return index
    raise AssertionError(f'找不到最上層節點 {prefix}')


@pytest.mark.gui
def test_aut_24_default_view_is_everything(panel, qapp):
    _seed(panel)
    texts = _texts(panel)
    assert any('有英文作者' in t for t in texts), '預設是「全部」，不篩選'
    assert not panel.missing_english_only()


@pytest.mark.gui
def test_aut_22_only_missing_english_is_listed(panel, qapp):
    _seed(panel)
    panel.set_missing_english_only(True)
    qapp.processEvents()

    texts = ' '.join(t for t in _texts(panel) if t)
    assert '沒英文作者' in texts
    assert '沒英文團體' in texts
    assert '有英文作者' not in texts
    # AUT-22b：有英文名的團體自己不出現，它旗下沒填的作者仍列在「作者」群組。
    assert '有英文團體' not in texts


@pytest.mark.gui
def test_aut_23_group_titles_say_the_filter_is_on(panel, qapp):
    _seed(panel)
    panel.set_missing_english_only(True)
    qapp.processEvents()

    assert '僅無英文' in _group_index(panel, '團體').data()
    assert '僅無英文' in _group_index(panel, '作者').data()

    panel.set_missing_english_only(False)
    qapp.processEvents()
    assert '僅無英文' not in _group_index(panel, '團體').data()


@pytest.mark.gui
def test_aut_22_top_level_nodes_offer_the_toggle(panel, qapp):
    """AUT-22a：兩個最上層節點都給得出切換，而且切的是同一個狀態。"""
    _seed(panel)
    for prefix in ('團體', '作者'):
        index = _group_index(panel, prefix)
        rect = panel.tree.visualRect(index)
        menu = panel._build_context_menu(rect.center())
        assert isinstance(menu, QMenu)
        labels = [a.text() for a in menu.actions()]
        assert '全部' in labels and '僅顯示無英文名稱' in labels, (
            f'{prefix} 節點的右鍵選單少了檢視切換，實際有 {labels}')

        by_text = {a.text(): a for a in menu.actions()}
        assert by_text['全部'].isCheckable() and by_text['僅顯示無英文名稱'].isCheckable()
        assert by_text['全部'].isChecked() is not panel.missing_english_only()

        by_text['僅顯示無英文名稱'].trigger()
        qapp.processEvents()
        assert panel.missing_english_only(), f'{prefix} 節點切不動'
        panel.set_missing_english_only(False)
        menu.deleteLater()


@pytest.mark.gui
def test_aut_22_entity_nodes_do_not_offer_the_toggle(panel, qapp):
    """切換掛在最上層節點上；實體節點的選單維持原本那幾項。"""
    _seed(panel)
    group = _group_index(panel, '作者')
    child = panel.tree.model().index(0, 0, group)
    menu = panel._build_context_menu(panel.tree.visualRect(child).center())
    labels = [a.text() for a in menu.actions()]
    assert '僅顯示無英文名稱' not in labels
    assert '編輯…' in labels
    menu.deleteLater()
