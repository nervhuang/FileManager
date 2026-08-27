"""INT-6 到 INT-19：搜尋工具的語意、關聯維護，以及每執行緒一份的搜尋引擎。

閘門本身在 test_int_01_05_gui_gate.py。這裡把閘門打開，驗工具真正做的事。

不需要 QApplication，也不需要真的 Everything——搜尋引擎是可注入的。
"""
import threading

import pytest

from app import hermes_mcp
from app.search.everything import SearchResult

pytestmark = pytest.mark.logic


class FakeEverything:
    """假引擎，介面同 `EverythingSDK.query(search_text, max_results)`。

    記下每次被索取的筆數，INT-8 就靠它驗——`fm_search_all` 必須向 Everything
    要更多，否則 total 會被 GUI 用的預設上限先砍掉。
    """

    def __init__(self, count):
        self._results = [SearchResult(f'D:\\keep{i}.txt', False, 100, 0)
                         for i in range(count)]
        self.max_results_seen = []

    def is_available(self):
        return True

    def query(self, search_text, max_results=200):
        self.max_results_seen.append(max_results)
        return list(self._results)


@pytest.fixture
def install_engine(monkeypatch):
    """打開閘門，並提供一個「換上指定筆數的假引擎」的函式。"""
    monkeypatch.setattr(hermes_mcp.gui_bridge, 'gui_is_running', lambda: True)

    def install(count):
        fake = FakeEverything(count)
        monkeypatch.setattr(hermes_mcp, '_get_everything', lambda: fake)
        return fake

    return install


@pytest.fixture
def engine(install_engine):
    return install_engine(250)


# ── INT-6／INT-7：預設值與上限 ──────────────────────────────────────────

def test_int_6_fm_search_defaults_to_200(engine):
    result = hermes_mcp.fm_search('keep')
    assert result['ok'] is True
    assert result['count'] == 200


def test_int_7_fm_search_all_defaults_to_200_too(engine):
    assert hermes_mcp.fm_search_all('keep')['count'] == 200


@pytest.mark.parametrize("asked, expected", [
    pytest.param(5000, 2000, id="超過上限就砍到2000"),
    pytest.param(0, 200, id="零視為沒給改用預設"),
    pytest.param(-1, 1, id="負數提到下限1"),
])
def test_int_7_fm_search_all_clamps_the_page_size(install_engine, asked, expected):
    """單頁上限 2000：每筆約 0.28KB，2000 筆已經約 560KB。

    路徑要各不相同——搜尋管線會以 path 去重，重複同一批只會被縮回去。
    """
    install_engine(2500)
    assert hermes_mcp.fm_search_all('keep', limit=asked)['count'] == expected


# ── INT-8：只有 fm_search_all 放大向 Everything 索取的筆數 ──────────────

def test_int_8_fm_search_all_asks_everything_for_more(engine):
    hermes_mcp.fm_search_all('keep')
    scaled = max(engine.max_results_seen)

    engine.max_results_seen.clear()
    hermes_mcp.fm_search('keep')
    plain = max(engine.max_results_seen)

    assert scaled > plain, 'fm_search_all 應該向 Everything 要更多'
    assert scaled == plain * 100, '規格說放大 100 倍'


def test_int_8_fm_search_does_not_affect_the_apps_own_limit(engine):
    """放大只影響 fm_search_all 自己的呼叫。"""
    hermes_mcp.fm_search_all('keep')
    engine.max_results_seen.clear()
    hermes_mcp.fm_search('keep')
    assert max(engine.max_results_seen) <= 2000


# ── INT-9：分頁欄位 ─────────────────────────────────────────────────────

def test_int_9_paging_fields_describe_the_whole_result_set(engine):
    page = hermes_mcp.fm_search_all('keep', limit=100, offset=200)
    assert page['total'] == 250
    assert page['offset'] == 200
    assert page['count'] == 50
    assert page['has_more'] is False


def test_int_9_paging_through_reaches_everything_exactly_once(engine):
    seen, offset = [], 0
    while True:
        page = hermes_mcp.fm_search_all('keep', limit=100, offset=offset)
        seen.extend(r['path'] for r in page['results'])
        if not page['has_more']:
            break
        offset += page['count']

    assert len(seen) == 250
    assert len(set(seen)) == 250, '分頁之間不該重複也不該漏'


# ── INT-19：每執行緒各自持有 EverythingSDK ──────────────────────────────

def test_int_19_each_thread_gets_its_own_engine(monkeypatch):
    """這曾經是 bug：快取成跨執行緒單例時，其他執行緒收不到 Everything 的回覆，
    query() 安靜逾時回空清單，呼叫端只看到「查不到任何檔案」。

    MCP 框架用 anyio.to_thread.run_sync 執行工具呼叫，同一支工具的連續兩次
    呼叫可能落在不同的 worker thread 上。

    **刻意不去 monkeypatch `_local`**：換掉它就等於測試自己造的 threading.local，
    不管原始碼把快取放在哪都會通過。這裡只清掉主執行緒上殘留的那一份，
    真正被驗的是模組自己的選擇。
    """
    created = []

    class Probe:
        def __init__(self):
            created.append(threading.get_ident())

    monkeypatch.setattr(hermes_mcp, 'EverythingSDK', Probe)
    if hasattr(hermes_mcp._local, 'everything'):
        del hermes_mcp._local.everything

    instances = {}

    def grab(tag):
        instances[tag] = hermes_mcp._get_everything()

    try:
        grab('main')
        grab('main-again')
        thread = threading.Thread(target=grab, args=('worker',))
        thread.start()
        thread.join()

        assert instances['main'] is instances['main-again'], '同一執行緒要重用'
        assert instances['main'] is not instances['worker'], '不同執行緒不可共用'
        assert len(created) == 2
    finally:
        # 別把 Probe 留在主執行緒的快取裡給後面的測試用
        if hasattr(hermes_mcp._local, 'everything'):
            del hermes_mcp._local.everything
