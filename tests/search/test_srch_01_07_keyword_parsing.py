"""SRCH-1 到 SRCH-7：關鍵字的正規化、切分與查詢組裝。

每一條都是修 bug 修出來的，而且症狀都一樣——「明明有這個檔案，卻搜不到」。
純函式，不需要 QApplication。
"""
import pytest

from app.search.query import (build_queries, is_plain_keyword_term,
                              keyword_tokens, normalize_search_command,
                              normalize_text, path_matches, split_terms,
                              strip_term_quotes)

pytestmark = pytest.mark.logic


# ── SRCH-1：多關鍵字以 | 分隔，含空白的詞組要加引號 ──────────────────────

def test_srch_01_splits_on_pipe():
    assert split_terms('甲|乙|丙') == ['甲', '乙', '丙']


def test_srch_01_drops_empty_terms():
    assert split_terms('甲||乙|  |丙') == ['甲', '乙', '丙']


def test_srch_01_quotes_terms_containing_spaces():
    """不加引號的話 Everything 會把詞組拆成兩個條件。"""
    assert normalize_search_command('as 109') == '"as 109"'


def test_srch_01_does_not_double_quote():
    assert normalize_search_command('"as 109"') == '"as 109"'


def test_srch_01_quotes_each_term_independently():
    assert normalize_search_command('as 109|zero') == '"as 109"|zero'


def test_strip_term_quotes_removes_only_a_matching_pair():
    assert strip_term_quotes('"abc"') == 'abc'
    assert strip_term_quotes('"abc') == '"abc'
    assert strip_term_quotes('abc"') == 'abc"'


# ── SRCH-2：NFKC ＋ casefold ──────────────────────────────────────────────

def test_srch_02_full_width_alphanumerics_become_half_width():
    assert normalize_text('ＡＢＣ１２３') == 'abc123'


def test_srch_02_is_case_insensitive():
    assert normalize_text('AbC') == normalize_text('aBc')


# ── SRCH-3：連字號與點不是分隔符 ─────────────────────────────────────────

@pytest.mark.parametrize("text", ['A-10', 'ver.2', 'a.b.c', 'tsf-saeki'])
def test_srch_03_hyphen_and_dot_stay_inside_one_token(text):
    """這些整體才有意義，被拆開就搜不到了。"""
    assert keyword_tokens(text) == [normalize_text(text)]


def test_srch_03_full_width_hyphen_and_dot_are_normalised_first():
    """NFKC 把全形 －／． 變成半形，因此同樣不會被當成分隔符。"""
    assert keyword_tokens('Ａ－１０') == ['a-10']


# ── SRCH-4：只剩符號的孤立 token 要濾掉 ──────────────────────────────────

def test_srch_04_drops_tokens_made_only_of_hyphens_or_dots():
    """「tsf - saeki」中間那個 - 不是關鍵字，留著會污染查詢。"""
    assert keyword_tokens('tsf - saeki') == ['tsf', 'saeki']


def test_srch_04_drops_a_lone_dot():
    assert keyword_tokens('a . b') == ['a', 'b']


# ── SRCH-5：括號內的文字才是使用者要搜的 ─────────────────────────────────

@pytest.mark.parametrize("term, token", [
    pytest.param('（重要）', '重要', id="全形圓括號"),
    pytest.param('【tsf-saeki】', 'tsf-saeki', id="方頭括號含連字號"),
    pytest.param('［標題］', '標題', id="全形方括號"),
    pytest.param('「引用」', '引用', id="單引號"),
])
def test_srch_05_brackets_are_stripped_before_querying(term, token):
    """搜「（重要）」要找得到「重要.txt」——原本只把含符號的原字串送給
    Everything，檔名不含那些符號時就查無結果。"""
    assert keyword_tokens(term) == [token]
    assert token in build_queries(term)


def test_srch_05_multiple_tokens_use_space_separated_and():
    """多個詞用 Everything 原生的空白 AND，不加引號、不要求詞序。"""
    queries = build_queries('（甲 乙）')
    assert '甲 乙' in queries, '應該有一個不加引號的空白 AND 查詢'
    assert any(q.startswith('regex:') for q in queries), '另外保留 regex 作為輔助'


def test_srch_05_keeps_the_original_term_as_a_query_too():
    """去符號只是「多一種找法」，原字串仍要送——檔名真的含括號時靠它命中。"""
    assert any('重要' in q for q in build_queries('（重要）'))


def test_build_queries_does_not_repeat_itself():
    queries = build_queries('abc')
    assert len(queries) == len(set(queries))


# ── SRCH-6：比對用 token 子集，不要求連續子字串 ──────────────────────────

def test_srch_06_matches_when_brackets_differ_between_term_and_filename():
    """關鍵字「重要（報告）」要對得上檔名「重要報告」。

    括號被正規化成空白，若還要求整串是連續子字串就會誤判不符。
    """
    assert path_matches(r'D:\某處\重要報告.txt', '重要（報告）') is True


def test_srch_06_requires_every_token_to_appear():
    assert path_matches(r'D:\某處\只有重要.txt', '重要（報告）') is False


def test_srch_06_ignores_the_directory_part():
    """只比對檔名。目錄名剛好含關鍵字不算命中。"""
    assert path_matches(r'D:\重要\其他.txt', '重要') is False


def test_srch_06_empty_term_matches_nothing():
    assert path_matches(r'D:\a.txt', '') is False
    assert path_matches(r'D:\a.txt', '（）') is False


# ── SRCH-7：含原生語法時整串原樣送出 ─────────────────────────────────────

@pytest.mark.parametrize("term", ['ext:zip', 'path:D:\\NAS', 'size:>1mb',
                                  'a*b', 'a?b', '!abc'])
def test_srch_07_native_syntax_is_not_treated_as_a_plain_keyword(term):
    assert is_plain_keyword_term(term) is False


@pytest.mark.parametrize("term", ['abc', '重要', 'tsf-saeki', 'ver.2', '"as 109"'])
def test_srch_07_ordinary_terms_are_plain_keywords(term):
    assert is_plain_keyword_term(term) is True


def test_srch_07_empty_term_is_not_a_plain_keyword():
    assert is_plain_keyword_term('') is False
    assert is_plain_keyword_term('""') is False
