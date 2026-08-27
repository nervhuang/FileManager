"""AUT-8 到 AUT-16：作者面板與它的編輯對話框。

面板自己開資料庫連線（`authors_db.connect()` 走 `FILEMANAGER_HOME`），
conftest 已把那裡指到暫存目錄，所以這裡的寫入不會碰到真實的 authors.db。
"""
import pytest
from PyQt5.QtWidgets import QToolBar

from app.authors import db as authors_db
from app.authors.panel import AuthorsPanel, EntityEditDialog

pytestmark = pytest.mark.gui


@pytest.fixture
def panel(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv('FILEMANAGER_HOME', str(tmp_path))
    widget = AuthorsPanel()
    widget.resize(660, 800)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close_db()
    widget.close()


def _tree_texts(panel):
    """樹上所有節點的文字，含群組標題。"""
    texts = []
    model = panel.tree.model()

    def walk(parent):
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            texts.append(index.data())
            walk(index)

    walk(panel.tree.rootIndex())
    return texts


# ── AUT-8：單擊開搜尋分頁，查詢字串含名稱與每一個別名 ──────────────────

def test_aut_8_clicking_an_entity_emits_name_and_every_alias(panel, qapp):
    authors_db.upsert(panel._conn, [
        {'name': '甲作者', 'type': authors_db.AUTHOR, 'aliases': ['筆名一', '筆名二']}])
    panel.reload()
    qapp.processEvents()

    emitted = []
    panel.search_requested.connect(emitted.append)

    model = panel.tree.model()
    for row in range(model.rowCount()):
        group = model.index(row, 0)
        for child in range(model.rowCount(group)):
            index = model.index(child, 0, group)
            if index.data() and '甲作者' in index.data():
                panel._on_clicked(index)

    assert emitted, '單擊實體應該要發出搜尋請求'
    assert emitted[0] == '甲作者|筆名一|筆名二'


def test_aut_8_clicking_a_group_header_does_nothing(panel, qapp):
    panel.reload()
    qapp.processEvents()
    emitted = []
    panel.search_requested.connect(emitted.append)

    panel._on_clicked(panel.tree.model().index(0, 0))

    assert emitted == [], '群組標題不是實體，點了不該搜尋'


# ── AUT-9：作者群組列出全部作者，含已歸屬團體者 ────────────────────────

def test_aut_9_every_author_is_listed_even_when_it_belongs_to_a_circle(panel, qapp):
    authors_db.upsert(panel._conn, [
        {'name': '有團體的作者', 'type': authors_db.AUTHOR,
         'linked_names': ['某團體']},
        {'name': '沒團體的作者', 'type': authors_db.AUTHOR}])
    panel.reload()
    qapp.processEvents()

    texts = _tree_texts(panel)
    assert any('有團體的作者' in t for t in texts)
    assert any('沒團體的作者' in t for t in texts)


def test_aut_9_the_group_count_matches_what_it_lists(panel, qapp):
    """標題上的數字要與實際列出的筆數一致——這正是當初只列「無團體者」的問題。"""
    authors_db.upsert(panel._conn, [
        {'name': '甲', 'type': authors_db.AUTHOR, 'linked_names': ['某團體']},
        {'name': '乙', 'type': authors_db.AUTHOR}])
    panel.reload()
    qapp.processEvents()

    model = panel.tree.model()
    for row in range(model.rowCount()):
        group = model.index(row, 0)
        title = group.data() or ''
        if title.startswith('作者'):
            listed = model.rowCount(group)
            assert f'（{listed}）' in title, f'標題 {title!r} 與列出的 {listed} 筆對不上'
            assert listed == 2
            return
    pytest.fail('找不到「作者」群組')


# ── AUT-10／AUT-11：工具列的六個動作與停用狀態 ─────────────────────────

def test_aut_10_toolbar_has_the_six_actions(panel):
    bar = panel.findChild(QToolBar)
    labels = [a.text() for a in bar.actions() if not a.isSeparator()]
    assert labels == ['新增作者', '新增團體', '編輯', '刪除', '重新整理', '變更']


def test_aut_11_edit_and_delete_are_disabled_without_a_selection(panel, qapp):
    panel.reload()
    panel.tree.clearSelection()
    panel._update_toolbar_state()
    qapp.processEvents()

    bar = panel.findChild(QToolBar)
    disabled = {a.text() for a in bar.actions() if not a.isSeparator() and not a.isEnabled()}
    assert disabled == {'編輯', '刪除'}


# ── AUT-12：預設寬度與最小寬度 ─────────────────────────────────────────

def test_aut_12_minimum_width_leaves_room_for_the_toolbar(panel):
    """實測值 151px。太寬的話左側面板的分割握把會拖不動。"""
    assert panel.minimumSizeHint().width() == 151


# ── AUT-14：面板與對話框都跟隨字型 ─────────────────────────────────────

def test_aut_14_apply_font_size_reaches_the_tree_and_filter(panel, qapp):
    panel.apply_font_size(19)
    qapp.processEvents()
    assert panel.font().pointSize() == 19
    assert panel.tree.font().pointSize() == 19
    assert panel.filter_edit.font().pointSize() == 19


def test_aut_14_dialogs_do_not_inherit_across_the_window_boundary(panel, qapp):
    """Qt 在頂層視窗邊界停止字型傳播，對話框必須自己套用。

    這裡驗的是「對話框確實拿到了面板的字型」——如果哪天有人把 _inherit_font
    拿掉，開出來的對話框會回到應用程式預設字級。
    """
    panel.apply_font_size(19)
    qapp.processEvents()

    dialog = EntityEditDialog(panel._conn, parent=panel)
    try:
        assert dialog.font().pointSize() == 19
    finally:
        dialog.close()


# ── AUT-15／AUT-16：編輯對話框 ─────────────────────────────────────────

def test_aut_15_dialog_has_all_the_documented_fields(panel):
    dialog = EntityEditDialog(panel._conn, parent=panel)
    try:
        for attr in ('name_edit', 'type_combo', 'note_edit',
                     'english_name_edit', 'alias_list', 'link_list'):
            assert hasattr(dialog, attr), f'少了 {attr}'
    finally:
        dialog.close()


def _pending_input(dialog, placeholder_starts_with):
    """別名／關聯的輸入框沒有存成屬性，用 placeholder 認。"""
    from PyQt5.QtWidgets import QLineEdit

    for line in dialog.findChildren(QLineEdit):
        if line.placeholderText().startswith(placeholder_starts_with):
            return line
    raise AssertionError(f'找不到 placeholder 以 {placeholder_starts_with!r} 開頭的輸入框')


def test_aut_16_pending_alias_text_is_committed_on_accept(panel, qapp):
    """打完別名沒按 Enter 就直接按 OK，內容不該被無聲丟掉。"""
    dialog = EntityEditDialog(panel._conn, parent=panel)
    try:
        dialog.name_edit.setText('甲作者')
        _pending_input(dialog, '新增別名').setText('還沒按 Enter 的別名')
        dialog._on_accept()
        qapp.processEvents()

        assert '還沒按 Enter 的別名' in dialog.result_entry()['aliases']
    finally:
        dialog.close()


def test_aut_16_pending_link_text_is_committed_too(panel, qapp):
    """關聯漏掉的後果更嚴重：項目會變成孤立實體，而使用者以為建好了。"""
    dialog = EntityEditDialog(panel._conn, parent=panel)
    try:
        dialog.name_edit.setText('甲作者')
        _pending_input(dialog, '輸入名稱').setText('還沒按 Enter 的團體')
        dialog._on_accept()
        qapp.processEvents()

        assert '還沒按 Enter 的團體' in dialog.result_entry()['linked_names']
    finally:
        dialog.close()


# ── AUT-17／AUT-17a：貼上拆分只在「新增」模式攔截 ──────────────────────

def test_aut_17_pasting_a_circle_author_name_splits_it(panel, qapp):
    """貼上「團體 (作者)」之後，名稱欄只剩團體名，作者進到關聯清單，
    類型也自動切成團體。"""
    dialog = EntityEditDialog(panel._conn, parent=panel)
    try:
        dialog.name_edit.setText('サイクロン (和泉、冷泉)')
        dialog.name_edit.editingFinished.emit()
        qapp.processEvents()

        assert dialog.name_edit.text() == 'サイクロン'
        assert dialog.type_combo.currentData() == authors_db.CIRCLE
        links = [dialog.link_list.item(i).text()
                 for i in range(dialog.link_list.count())]
        assert links == ['和泉', '冷泉']
    finally:
        dialog.close()


def test_aut_17a_editing_an_existing_entity_never_splits(panel, qapp):
    """既有項目的名稱本來就可能合法地含括號，不該被這條規則誤拆。

    做法是「編輯模式根本不接這條訊號」，所以這裡直接驗名稱沒被動過。
    """
    authors_db.upsert(panel._conn, [
        {'name': '社團 (附註)', 'type': authors_db.CIRCLE}])
    existing = authors_db.get_entity(
        panel._conn,
        authors_db.find_entity(panel._conn, '社團 (附註)', authors_db.CIRCLE)['id'])

    dialog = EntityEditDialog(panel._conn, entity=existing, parent=panel)
    try:
        dialog.name_edit.editingFinished.emit()
        qapp.processEvents()

        assert dialog.name_edit.text() == '社團 (附註)', '編輯模式不該拆名稱'
        assert dialog.link_list.count() == 0
    finally:
        dialog.close()
