"""TAB-7 到 TAB-16（含 TAB-14）：「所有分頁」清單與分頁的建立／關閉。

`build_tab_list_menu` 的 docstring 寫著「分開建構與顯示以便測試」——這支測試
就是那句話的兌現。選單建好但不顯示，因此不需要真的彈出視窗。
"""
import pytest

from app.tabs.bar import PathTabBar

pytestmark = pytest.mark.gui


@pytest.fixture
def bar(qapp):
    widget = PathTabBar()
    widget.resize(600, 40)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


def _fill(bar, entries):
    """把分頁換成指定的 (data, label)，回傳分頁數。"""
    bar.restore_tabs(entries, 0)
    return bar.tab_bar.count()


def _action_texts(menu):
    return [a.text() for a in menu.actions()]


# ── TAB-13：沒有資料的分頁退回顯示標籤 ───────────────────────────────────

def test_tab_13_menu_shows_the_label_for_a_dataless_tab(bar):
    """空白分頁沒有路徑或關鍵字，清單上要顯示它的標籤而不是空字串。"""
    _fill(bar, [('', '新頁籤'), (r'D:\有資料', 'D:')])
    texts = _action_texts(bar.build_tab_list_menu())
    assert '新頁籤' in texts
    assert any('有資料' in t for t in texts)


# ── TAB-9：顯示完整路徑，過長時從中間省略 ───────────────────────────────

def test_tab_9_shows_the_full_path_not_the_short_tab_label(bar):
    _fill(bar, [(r'D:\很長的\路徑\結尾資料夾', 'D:')])
    texts = _action_texts(bar.build_tab_list_menu())
    assert texts[0] != 'D:', '清單要顯示完整資料，不是頁籤上那個 10 字標籤'


def test_tab_9_elides_in_the_middle_keeping_both_ends(bar):
    """磁碟機與最後一層資料夾都是辨識關鍵，頭尾都要保留。"""
    long_path = 'D:' + '\\很長的資料夾名稱' * 12 + r'\結尾'
    _fill(bar, [(long_path, 'D:')])
    text = _action_texts(bar.build_tab_list_menu())[0]

    assert len(text) < len(long_path), '這麼長的路徑應該被省略'
    assert text.startswith('D:'), '開頭的磁碟機要留著'
    assert text.endswith('結尾'), '結尾的資料夾要留著'
    assert '…' in text or '...' in text


def test_tab_9_full_text_stays_in_the_tooltip(bar):
    long_path = 'D:' + '\\很長的資料夾名稱' * 12 + r'\結尾'
    _fill(bar, [(long_path, 'D:')])
    action = bar.build_tab_list_menu().actions()[0]
    assert action.toolTip() == long_path


# ── TAB-10：當前分頁加勾選記號並顯示為粗體 ──────────────────────────────

def test_tab_10_marks_only_the_current_tab(bar):
    _fill(bar, [(r'D:\甲', '甲'), (r'D:\乙', '乙'), (r'D:\丙', '丙')])
    bar.tab_bar.setCurrentIndex(1)

    actions = bar.build_tab_list_menu().actions()
    checked = [i for i, a in enumerate(actions) if a.isChecked()]
    bold = [i for i, a in enumerate(actions) if a.font().bold()]

    assert checked == [1]
    assert bold == [1]


# ── TAB-11：點選任一列切換到該分頁 ───────────────────────────────────────

def test_tab_11_triggering_an_entry_switches_to_that_tab(bar, qapp):
    _fill(bar, [(r'D:\甲', '甲'), (r'D:\乙', '乙'), (r'D:\丙', '丙')])
    bar.tab_bar.setCurrentIndex(0)

    bar.build_tab_list_menu().actions()[2].trigger()
    qapp.processEvents()

    assert bar.tab_bar.currentIndex() == 2
    assert bar.current_data() == r'D:\丙'


# ── TAB-8：按在頁籤本身上不做任何事 ─────────────────────────────────────

def test_tab_8_right_click_on_a_tab_does_not_open_the_list(bar, monkeypatch):
    _fill(bar, [(r'D:\甲', '甲'), (r'D:\乙', '乙')])
    opened = []
    monkeypatch.setattr(bar, '_show_tab_list_menu', lambda pos: opened.append(pos))

    on_tab = bar.tab_bar.tabRect(0).center()
    bar._on_tab_bar_context_menu(on_tab)

    assert opened == [], '在頁籤上按右鍵不該叫出清單'


def test_tab_8_right_click_on_blank_space_opens_the_list(bar, monkeypatch):
    _fill(bar, [(r'D:\甲', '甲')])
    opened = []
    monkeypatch.setattr(bar, '_show_tab_list_menu', lambda pos: opened.append(pos))

    blank = bar.tab_bar.rect().bottomRight()
    assert bar.tab_bar.tabAt(blank) < 0, '這個點應該落在空白處，測試前提才成立'
    bar._on_tab_bar_context_menu(blank)

    assert len(opened) == 1


# ── 永遠至少有一個分頁 ───────────────────────────────────────────────────

def test_restoring_no_tabs_still_leaves_one_blank_tab(bar):
    """面板不允許零個分頁——沒有分頁就沒有東西可顯示，連新增鈕的落點都沒有。

    `build_tab_list_menu` 的「沒有分頁就回 None」因此是防禦性的，
    走 restore_tabs 這條路進不去。
    """
    bar.restore_tabs([], 0)

    assert bar.tab_bar.count() == 1
    assert bar.current_data() == ''
    assert bar.build_tab_list_menu() is not None


# ── TAB-15／TAB-16：分頁的建立與資料往返 ────────────────────────────────

def test_tab_15_added_tabs_keep_their_data_and_label(bar):
    bar.restore_tabs([], 0)
    bar.add_tab(r'D:\新的', '新的')
    tabs, _current = bar.get_all_tabs()
    assert (r'D:\新的', '新的') in tabs


def test_tab_16_get_all_tabs_round_trips_through_restore(bar):
    entries = [(r'D:\甲', '甲'), ('', '新頁籤'), (r'D:\丙', '丙')]
    bar.restore_tabs(entries, 2)

    tabs, current = bar.get_all_tabs()
    assert tabs == entries
    assert current == 2
    assert bar.current_data() == r'D:\丙'


def test_set_current_data_updates_only_the_current_tab(bar):
    bar.restore_tabs([(r'D:\甲', '甲'), (r'D:\乙', '乙')], 1)
    bar.set_current_data(r'D:\改過', '改過')

    tabs, _ = bar.get_all_tabs()
    assert tabs[0] == (r'D:\甲', '甲')
    assert tabs[1] == (r'D:\改過', '改過')
