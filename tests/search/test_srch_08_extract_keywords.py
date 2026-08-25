"""SRCH-8：從檔名的括號內取出自動搜尋用的關鍵字。

同人誌檔名的慣例是 `[團體 (作者)] 標題 [語言]`，有用的檢索詞都在括號裡。
純函式，不需要 QApplication。
"""
import pytest

from app.search.query import extract_keywords

pytestmark = pytest.mark.logic


@pytest.mark.parametrize("file_name, expected", [
    pytest.param('[サイクロン (和泉)] とある標題 [中國翻訳].zip',
                 ['サイクロン', '和泉', '中國翻訳'], id="同人誌慣例"),
    pytest.param('[zero戦 (xxzero)] 作品.zip', ['zero戦', 'xxzero'], id="巢狀括號拆成兩個"),
    pytest.param('沒有括號的檔名.txt', [], id="沒有括號"),
    pytest.param('', [], id="空字串"),
])
def test_srch_08_extracts_bracketed_text(file_name, expected):
    assert extract_keywords(file_name) == expected


@pytest.mark.parametrize("file_name, expected", [
    pytest.param('【重要】報告.txt', ['重要'], id="CJK方頭括號"),
    pytest.param('（全形）.txt', ['全形'], id="全形圓括號"),
    pytest.param('［方括］.txt', ['方括'], id="全形方括號"),
    pytest.param('｛大｝.txt', ['大'], id="全形大括號"),
    pytest.param('〔龜〕.txt', ['龜'], id="龜甲括號"),
    pytest.param('「引用」.txt', ['引用'], id="單引號"),
    pytest.param('『雙引』.txt', ['雙引'], id="雙引號"),
    pytest.param('〈角〉.txt', ['角'], id="角括號"),
    pytest.param('《書名》.txt', ['書名'], id="書名號"),
    pytest.param('(半形).txt', ['半形'], id="半形圓括號"),
    pytest.param('{大括}.txt', ['大括'], id="半形大括號"),
])
def test_srch_08_recognises_full_width_and_cjk_brackets(file_name, expected):
    """只認 ASCII 括號的話，這個專案的檔名幾乎都取不到關鍵字。"""
    assert extract_keywords(file_name) == expected


def test_srch_08_strips_surrounding_whitespace():
    assert extract_keywords('[  作者  ] 標題.zip') == ['作者']


def test_srch_08_drops_empty_brackets():
    """空括號與只有空白的括號不產生關鍵字，否則查詢會被空字串污染。"""
    assert extract_keywords('[] [   ] [有效].zip') == ['有效']


def test_srch_08_unclosed_bracket_still_yields_nothing_after_it():
    """未閉合的括號不得把後面整串檔名都吞進關鍵字。"""
    assert extract_keywords('[未閉合 括號.zip') == []


def test_srch_08_text_outside_brackets_is_ignored():
    assert extract_keywords('標題在外面 [裡面] 也在外面.zip') == ['裡面']
