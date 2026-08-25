"""AUT-17 到 AUT-21：貼上「團體 (作者)」自動拆分。

規格條文目前標著 **[未驗]**——是從程式碼逆向寫出來的，原意還沒經人工確認。
這些測試鎖住的是**現在的行為**，不是「應該的行為」。條文確認之後若有出入，
先改規格與測試，再改程式碼。

純函式，不需要 QApplication。
"""
import pytest

from app.authors.names import parse_circle_author

pytestmark = pytest.mark.logic


# ── 基本格式 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    pytest.param('zero戦 (xxzero)', ('zero戦', ['xxzero']), id="半形括號"),
    pytest.param('zero戦（xxzero）', ('zero戦', ['xxzero']), id="全形括號"),
    pytest.param('[zero戦 (xxzero)]', ('zero戦', ['xxzero']), id="外層方括號"),
    pytest.param('  zero戦 (xxzero)  ', ('zero戦', ['xxzero']), id="前後空白"),
    pytest.param('zero戦(xxzero)', ('zero戦', ['xxzero']), id="括號前沒有空白"),
])
def test_aut_18_bracket_variants(text, expected):
    assert parse_circle_author(text) == expected


# ── 括號內多位作者（AUT-18）────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected_authors", [
    pytest.param('サイクロン (和泉、冷泉)', ['和泉', '冷泉'], id="頓號"),
    pytest.param('サイクロン (和泉,冷泉)', ['和泉', '冷泉'], id="半形逗號"),
    pytest.param('サイクロン (和泉，冷泉)', ['和泉', '冷泉'], id="全形逗號"),
    pytest.param('社團 (甲、乙、丙、丁)', ['甲', '乙', '丙', '丁'], id="四位不限數量"),
    pytest.param('社團 (甲、 乙 、丙)', ['甲', '乙', '丙'], id="分隔符前後有空白"),
])
def test_aut_18_multiple_authors_in_brackets(text, expected_authors):
    circle, authors = parse_circle_author(text)
    assert circle == 'サイクロン' or circle == '社團'
    assert authors == expected_authors


# ── 取尾端最後一組括號（AUT-19）────────────────────────────────────────────

def test_aut_19_takes_the_last_bracket_group():
    """團體名本身含括號時不得被錯拆。"""
    assert parse_circle_author('社團(附註) (作者)') == ('社團(附註)', ['作者'])


def test_aut_19_trailing_text_after_the_bracket_is_not_accepted():
    """正則錨定在字串尾端，括號後面還有字就不算符合格式。"""
    assert parse_circle_author('社團 (作者) 多出來的字') is None


# ── 不符合格式時維持原樣（AUT-20、AUT-21）──────────────────────────────────

@pytest.mark.parametrize("text", [
    pytest.param('只有名字', id="沒有括號"),
    pytest.param('(只有作者)', id="團體名為空"),
    pytest.param('社團 ()', id="括號內為空"),
    pytest.param('社團 (   )', id="括號內只有空白"),
    pytest.param('社團 (、、)', id="括號內只有分隔符"),
    pytest.param('社團 (內層(又有)括號)', id="內層再含括號"),
    pytest.param('', id="空字串"),
    pytest.param('   ', id="只有空白"),
])
def test_aut_21_unparseable_returns_none(text):
    """不符合格式回 None，呼叫端據此維持原樣、不報錯。"""
    assert parse_circle_author(text) is None
