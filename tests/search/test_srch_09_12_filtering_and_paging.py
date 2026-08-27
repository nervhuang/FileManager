"""SRCH-9 到 SRCH-12：排除目錄、路徑／副檔名限縮，以及分頁欄位的語意。

SRCH-10（同一份排除設定給 GUI、MCP、CLI 三個進程共用）另見
tests/integration/test_int_10_18_authors_and_bridge.py。

Everything 在 CI 上不存在，所以這裡餵一個假的搜尋引擎——規格說搜尋引擎必須是
可注入的介面，這支測試就是那句話的兌現。

純函式，不需要 QApplication。
"""
import os

import pytest

from app.search.everything import SearchResult
from app.search.query import (is_path_excluded, normalize_exclude_dirs,
                              run_search)

pytestmark = pytest.mark.logic


class FakeEverything:
    """假的搜尋引擎，介面與 `app.search.everything.EverythingSDK` 相同：
    `query(search_text, max_results)` 回一個 list。

    真實的 Everything 用「回傳筆數等於索取上限」判定索引端是否撈滿，這裡照同一套
    來——`fill_to_limit` 時就回滿 `max_results` 筆，讓 capped 自然為真，
    而不是另開一個旗標把答案直接餵給測試。

    查詢結果之後還會被 `path_matches` 過濾，所以測試用的路徑必須真的含有查詢詞，
    否則會被濾光而看不出在測什麼。這裡一律用 `keep` 當查詢詞。
    """

    def __init__(self, paths, fill_to_limit=False):
        self._paths = list(paths)
        self._fill_to_limit = fill_to_limit
        self.queries = []

    @staticmethod
    def _result(path):
        is_dir = '.' not in os.path.basename(path)
        return SearchResult(path, is_dir, 0 if is_dir else 100, 0)

    def is_available(self):
        return True

    def query(self, search_text, max_results=200):
        self.queries.append((search_text, max_results))
        if self._fill_to_limit:
            return [self._result('D:' + os.sep + f'zip{i}.zip')
                    for i in range(max_results)]
        return [self._result(p) for p in self._paths]


def _paths(results):
    return [r.path for r in results]


def _numbered(count):
    return ['D:' + os.sep + f'keep{i}.txt' for i in range(count)]


# ── SRCH-9：排除目錄及其子路徑 ───────────────────────────────────────────

def test_srch_09_excludes_a_directory_and_everything_under_it():
    exclude = normalize_exclude_dirs([r'D:\排除'])
    assert is_path_excluded(r'D:\排除', exclude) is True
    assert is_path_excluded(r'D:\排除\深\一點.txt', exclude) is True
    assert is_path_excluded(r'D:\保留\檔案.txt', exclude) is False


def test_srch_09_is_case_and_separator_insensitive():
    exclude = normalize_exclude_dirs([r'D:\NAS'])
    assert is_path_excluded('d:/nas/a.txt', exclude) is True


def test_srch_09_does_not_exclude_a_sibling_with_a_shared_prefix():
    """排除「D:\\排除」不該連「D:\\排除中的東西」一起排掉。"""
    exclude = normalize_exclude_dirs([r'D:\排除'])
    assert is_path_excluded(r'D:\排除中的東西\a.txt', exclude) is False


def test_srch_09_drive_root_exclusion_works():
    """磁碟根目錄 normpath 後已帶尾端分隔符，不可再補一個。"""
    exclude = normalize_exclude_dirs(['C:' + os.sep])
    assert is_path_excluded(r'C:\Users\a.txt', exclude) is True
    assert is_path_excluded(r'D:\Users\a.txt', exclude) is False


def test_srch_09_no_exclusions_means_nothing_is_excluded():
    assert is_path_excluded(r'C:\任何東西', ()) is False


def test_srch_09_exclusion_is_applied_to_search_results():
    engine = FakeEverything([r'D:\保留\keep.txt', r'D:\排除\keep.txt'])
    results, info = run_search(engine, 'keep', normalize_exclude_dirs([r'D:\排除']))
    assert _paths(results) == [r'D:\保留\keep.txt']
    assert info['total'] == 1, 'total 是過濾後的筆數'


# ── 路徑與副檔名限縮 ─────────────────────────────────────────────────────

def test_under_dir_keeps_only_paths_below_it():
    engine = FakeEverything([r'D:\甲\keep.txt', r'D:\乙\keep.txt'])
    results, _ = run_search(engine, 'keep', under_dir=r'D:\甲')
    assert _paths(results) == [r'D:\甲\keep.txt']


def test_ext_filter_ignores_case_and_a_leading_dot():
    engine = FakeEverything([r'D:\keep.ZIP', r'D:\keep.txt'])
    results, _ = run_search(engine, 'keep', ext='.zip')
    assert _paths(results) == [r'D:\keep.ZIP']


def test_ext_filter_never_returns_directories():
    engine = FakeEverything([r'D:\keep目錄', r'D:\keep.zip'])
    results, _ = run_search(engine, 'keep', ext='zip')
    assert _paths(results) == [r'D:\keep.zip']


# ── SRCH-11／SRCH-12：四個欄位彼此獨立 ──────────────────────────────────

def test_srch_11_total_is_not_affected_by_limit_or_offset():
    engine = FakeEverything(_numbered(10))
    _, info = run_search(engine, 'keep', limit=3, offset=5)
    assert info['total'] == 10
    assert info['offset'] == 5
    assert info['returned'] == 3


def test_srch_11_has_more_is_true_while_the_page_stops_short():
    engine = FakeEverything(_numbered(10))
    _, info = run_search(engine, 'keep', limit=3, offset=0)
    assert info['has_more'] is True


def test_srch_11_has_more_is_false_on_the_last_page():
    engine = FakeEverything(_numbered(10))
    _, info = run_search(engine, 'keep', limit=3, offset=9)
    assert info['returned'] == 1
    assert info['has_more'] is False


def test_srch_12_capped_and_has_more_are_independent():
    """capped 說「索引裡可能還有更多沒取回」，has_more 說「這次分頁沒給完」。

    舊版只有一個 truncated 且只反映 limit 的裁切，撞到 Everything 上限時會謊報
    未截斷——這正是把兩者分開的原因。

    用帶原生語法的查詢走 raw 路徑（SRCH-7），讓假引擎剛好回滿索取上限。
    """
    engine = FakeEverything([], fill_to_limit=True)
    _, info = run_search(engine, 'ext:zip')     # 沒有 limit，整批都給了
    assert info['has_more'] is False, '這次全給了'
    assert info['capped'] is True, '但索引端撈滿了上限，total 仍可能低估'


def test_srch_12_capped_is_false_when_the_engine_did_not_fill_the_limit():
    engine = FakeEverything(['D:' + os.sep + 'keep.txt'])
    _, info = run_search(engine, 'keep')
    assert info['capped'] is False


def test_offset_beyond_the_end_returns_nothing_and_says_so():
    engine = FakeEverything(['D:' + os.sep + 'keep.txt'])
    results, info = run_search(engine, 'keep', offset=99)
    assert results == []
    assert info['returned'] == 0
    assert info['has_more'] is False


def test_a_negative_offset_is_clamped_to_zero():
    engine = FakeEverything(['D:' + os.sep + 'keep.txt'])
    _, info = run_search(engine, 'keep', offset=-5)
    assert info['offset'] == 0
