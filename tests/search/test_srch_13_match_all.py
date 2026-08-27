"""SRCH-13：`match='all'` 時逐詞搜完取交集。

`|` 在搜尋管線裡是 OR，要 AND 只能自己算——把每個詞各搜一次，再取路徑的交集。

純函式，不需要 QApplication，也不需要真的 Everything。
"""
import os

import pytest

from app import hermes_mcp
from app.search.everything import SearchResult

pytestmark = pytest.mark.logic


class PerTermEverything:
    """依查詢字串回不同結果的假引擎。

    真實管線會把一個關鍵詞展開成多個查詢變體，所以這裡用「查詢字串裡含哪個詞」
    來決定回什麼，而不是要求完全相等。
    """

    def __init__(self, by_term):
        self._by_term = by_term
        self.queries = []

    def is_available(self):
        return True

    def query(self, search_text, max_results=200):
        self.queries.append(search_text)
        for term, paths in self._by_term.items():
            if term in search_text:
                return [SearchResult(p, False, 100, 0) for p in paths]
        return []


@pytest.fixture
def install(monkeypatch):
    monkeypatch.setattr(hermes_mcp.gui_bridge, 'gui_is_running', lambda: True)

    def _install(by_term):
        engine = PerTermEverything(by_term)
        monkeypatch.setattr(hermes_mcp, '_get_everything', lambda: engine)
        return engine

    return _install


BOTH = 'D:' + os.sep + 'kou_saeki.zip'
ONLY_KOU = 'D:' + os.sep + 'kou_other.zip'
ONLY_SAEKI = 'D:' + os.sep + 'other_saeki.zip'


def test_srch_13_match_all_keeps_only_what_every_term_found(install):
    install({'kou': [BOTH, ONLY_KOU], 'saeki': [BOTH, ONLY_SAEKI]})

    result = hermes_mcp.fm_search('kou|saeki', match='all')

    assert [r['path'] for r in result['results']] == [BOTH]


def test_srch_13_match_any_is_the_union(install):
    install({'kou': [BOTH, ONLY_KOU], 'saeki': [BOTH, ONLY_SAEKI]})

    result = hermes_mcp.fm_search('kou|saeki', match='any')

    assert {r['path'] for r in result['results']} == {BOTH, ONLY_KOU, ONLY_SAEKI}


def test_srch_13_match_all_with_a_term_that_finds_nothing_yields_nothing(install):
    install({'kou': [BOTH], 'saeki': []})

    result = hermes_mcp.fm_search('kou|saeki', match='all')

    assert result['results'] == []
    assert result['total'] == 0


def test_srch_13_a_single_term_behaves_the_same_either_way(install):
    """只有一個詞時取交集等於它自己，兩種 match 應該一致。"""
    install({'kou': [BOTH, ONLY_KOU]})

    all_mode = hermes_mcp.fm_search('kou', match='all')
    any_mode = hermes_mcp.fm_search('kou', match='any')

    assert {r['path'] for r in all_mode['results']} == \
           {r['path'] for r in any_mode['results']}


def test_srch_13_intersection_result_is_stable_in_path_order(install):
    """交集本身沒有順序，實作以路徑排序，回傳才不會每次都不一樣。"""
    both_b = 'D:' + os.sep + 'b_kou_saeki.zip'
    both_a = 'D:' + os.sep + 'a_kou_saeki.zip'
    install({'kou': [both_b, both_a], 'saeki': [both_b, both_a]})

    paths = [r['path'] for r in hermes_mcp.fm_search('kou|saeki', match='all')['results']]

    assert paths == sorted(paths)
