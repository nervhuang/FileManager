"""INT-4、INT-10 到 INT-18：關聯維護、排除設定共用、橋接與資料目錄。

閘門在 test_int_01_05_gui_gate.py，搜尋語意在 test_int_06_19_tool_semantics.py。
"""
import os

import pytest

from app import gui_bridge, hermes_mcp, paths
from app.authors import db as authors_db
from app.search.everything import SearchResult

pytestmark = pytest.mark.logic


@pytest.fixture
def mcp(tmp_path, monkeypatch):
    """打開閘門，把資料目錄指到暫存處，並換掉搜尋引擎。"""
    monkeypatch.setenv('FILEMANAGER_HOME', str(tmp_path))
    monkeypatch.setattr(hermes_mcp.gui_bridge, 'gui_is_running', lambda: True)

    class FakeEverything:
        def is_available(self):
            return True

        def query(self, search_text, max_results=200):
            return [SearchResult(r'D:\保留\keep.txt', False, 100, 0),
                    SearchResult(r'D:\排除\keep.txt', False, 100, 0)]

    monkeypatch.setattr(hermes_mcp, '_get_everything', lambda: FakeEverything())
    return tmp_path


# ── INT-4：閘門的判定不建立連線 ────────────────────────────────────────

def test_int_4_the_gate_probe_does_not_connect(monkeypatch):
    """判定只看命名管道存不存在。若改成真的連線，每次工具呼叫都要付連線成本，
    而且 GUI 忙碌時會被判成沒開。
    """
    called = []
    monkeypatch.setattr(gui_bridge, 'send_command',
                        lambda *a, **k: called.append(a))

    gui_bridge.gui_is_running()

    assert called == [], 'gui_is_running 不該送出任何指令'


# ── INT-10：排除設定與 GUI 共用同一份 ──────────────────────────────────

def test_int_10_mcp_applies_the_same_exclude_settings(mcp, monkeypatch):
    """設定寫進 config.ini 之後，MCP 這一側要看得到——三個進程讀同一份檔案。"""
    from app.settings import ConfigStore

    store = ConfigStore.load(paths.config_path())
    store.set_bool('Exclude', 'enabled', True)
    store.set_json('Exclude', 'dirs', [r'D:\排除'])
    store.save()

    result = hermes_mcp.fm_search('keep')

    found = {r['path'] for r in result['results']}
    assert found == {r'D:\保留\keep.txt'}, '被排除目錄下的結果不該回給 Hermes'


def test_int_10_disabled_exclusion_returns_everything(mcp):
    from app.settings import ConfigStore

    store = ConfigStore.load(paths.config_path())
    store.set_bool('Exclude', 'enabled', False)
    store.set_json('Exclude', 'dirs', [r'D:\排除'])
    store.save()

    assert hermes_mcp.fm_search('keep')['count'] == 2


# ── INT-11：fm_authors_link 單獨建立關聯，任一邊不存在就自動建 ─────────

def test_int_11_link_creates_both_sides_when_missing(mcp):
    result = hermes_mcp.fm_authors_link('新作者', '新團體')
    assert result['ok'] is True

    conn = authors_db.connect()
    try:
        author = authors_db.find_entity(conn, '新作者', authors_db.AUTHOR)
        circle = authors_db.find_entity(conn, '新團體', authors_db.CIRCLE)
        assert author is not None and circle is not None
        linked = authors_db.get_entity(conn, circle['id'])['linked']
        assert [e['name'] for e in linked] == ['新作者']
    finally:
        conn.close()


def test_int_11_unlink_removes_only_that_pair(mcp):
    hermes_mcp.fm_authors_link('甲作者', '某團體')
    hermes_mcp.fm_authors_link('乙作者', '某團體')

    hermes_mcp.fm_authors_link('甲作者', '某團體', unlink=True)

    conn = authors_db.connect()
    try:
        circle = authors_db.find_entity(conn, '某團體', authors_db.CIRCLE)
        linked = authors_db.get_entity(conn, circle['id'])['linked']
        assert [e['name'] for e in linked] == ['乙作者']
    finally:
        conn.close()


# ── INT-12：upsert 的說明必須講清楚 linked_names 要一併送 ───────────────

def test_int_12_upsert_docstring_tells_the_model_to_send_linked_names():
    """模型只讀得到工具說明。沒寫清楚的話它會建出兩筆互不相關的資料。"""
    doc = hermes_mcp.fm_authors_upsert.__doc__ or ''
    assert 'linked_names' in doc


# ── INT-13／INT-13a：合併語意與英文名反查 ──────────────────────────────

def test_int_13_upsert_merges_links_through_the_tool(mcp):
    hermes_mcp.fm_authors_upsert([
        {'name': '某團體', 'type': 'circle', 'linked_names': ['甲作者']}])
    hermes_mcp.fm_authors_upsert([
        {'name': '某團體', 'type': 'circle', 'linked_names': ['乙作者']}])

    conn = authors_db.connect()
    try:
        circle = authors_db.find_entity(conn, '某團體', authors_db.CIRCLE)
        names = sorted(e['name'] for e in authors_db.get_entity(conn, circle['id'])['linked'])
        assert names == ['乙作者', '甲作者']
    finally:
        conn.close()


def test_int_13a_unlink_resolves_by_english_name(mcp):
    """解除關聯走 _resolve_entity，因此認得英文名。"""
    hermes_mcp.fm_authors_upsert([
        {'name': '甲作者', 'type': 'author', 'english_name': 'Kou',
         'linked_names': ['某團體']}])

    result = hermes_mcp.fm_authors_link('Kou', '某團體', unlink=True)
    assert result['ok'] is True

    conn = authors_db.connect()
    try:
        circle = authors_db.find_entity(conn, '某團體', authors_db.CIRCLE)
        assert authors_db.get_entity(conn, circle['id'])['linked'] == []
    finally:
        conn.close()


def test_int_13b_linking_by_english_name_creates_a_duplicate(mcp):
    """INT-13b **[未驗]** 建立關聯與解除關聯的行為不對稱，這裡鎖住的是現況。

    解除走 _resolve_entity（認得英文名），建立走 _ensure_entity（只認名稱，
    找不到就建）。於是用英文名建立關聯會安靜地多出一筆叫 Kou 的作者，
    而不是接到既有的「甲作者」——正是 INT-12 警告的「建出兩筆互不相關的資料」。

    要改成一致的話，先改規格與這支測試。
    """
    hermes_mcp.fm_authors_upsert([
        {'name': '甲作者', 'type': 'author', 'english_name': 'Kou'}])

    hermes_mcp.fm_authors_link('Kou', '某團體')

    conn = authors_db.connect()
    try:
        circle = authors_db.find_entity(conn, '某團體', authors_db.CIRCLE)
        names = [e['name'] for e in authors_db.get_entity(conn, circle['id'])['linked']]
        assert names == ['Kou'], '現況：另外建了一筆'
        assert authors_db.find_entity(conn, 'Kou', authors_db.AUTHOR) is not None
    finally:
        conn.close()


def test_int_13a_list_filters_by_english_name(mcp):
    hermes_mcp.fm_authors_upsert([
        {'name': '甲作者', 'type': 'author', 'english_name': 'Kou'}])

    listed = hermes_mcp.fm_authors_list(keyword='kou')
    assert [e['name'] for e in listed['entities']] == ['甲作者']


# ── INT-14／INT-15：GUI 橋接 ───────────────────────────────────────────

def test_int_14_bridge_reports_not_running_when_there_is_no_pipe(monkeypatch):
    monkeypatch.setattr(gui_bridge, 'gui_is_running', lambda: False)
    assert hermes_mcp.fm_open_search_tab('x')['reason'] == 'gui_not_running'


def test_int_15_writes_notify_the_gui(mcp, monkeypatch):
    """Hermes 改了清單之後要推給 GUI，面板才會立刻重新整理。"""
    notified = []
    monkeypatch.setattr(hermes_mcp.gui_bridge, 'notify_authors_changed',
                        lambda *a, **k: notified.append(True))

    hermes_mcp.fm_authors_upsert([{'name': '甲作者', 'type': 'author'}])

    assert notified, '寫入之後應該通知 GUI'


# ── INT-17／INT-18：資料目錄一致性 ─────────────────────────────────────

def test_int_17_all_three_processes_resolve_the_same_directory(tmp_path, monkeypatch):
    """不設 FILEMANAGER_HOME 時 MCP server 與 exe 會各讀一份，Hermes 寫進去的
    資料在程式裡完全看不到。設了就必須一致。"""
    monkeypatch.setenv('FILEMANAGER_HOME', str(tmp_path))
    assert paths.config_path() == os.path.join(str(tmp_path), 'config.ini')
    assert paths.authors_db_path() == os.path.join(str(tmp_path), 'authors.db')


def test_int_18_the_server_instructions_state_the_resolved_directory():
    """兩端對不上時要一眼看得出來，而不是靜默不一致。

    instructions 在模組匯入時就組好，之後改環境變數不會重算——所以這裡驗的是
    「裡面確實寫著兩個資料檔的完整路徑」，不是某個特定目錄。
    """
    instructions = hermes_mcp.server.instructions
    assert 'authors.db' in instructions
    assert 'config.ini' in instructions
    assert os.sep in instructions, '要寫完整路徑，只寫檔名看不出兩端有沒有對上'
