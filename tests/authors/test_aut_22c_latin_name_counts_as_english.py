"""AUT-22c：名稱本身就是拉丁字母時，不算「沒有英文名稱」。

實測資料庫裡 17 筆沒填 english_name 的實體中，有 6 筆的名字本來就是英文
（`MAFIC`、`blue soda`、`Panda Boxing`、`FishBone`、`I'm moralist`、`Fu-Ta`）。
把它們列進「還沒填英文名稱」的盤點清單，看起來就是壞掉的功能。

同一個判準也決定更新檢查器查不查得到這個實體（見 docs/spec/checker.md），
所以判準只能有一份，放在不依賴 Qt 的 app/authors/names.py。
"""
import pytest

from app.authors import db as authors_db
from app.authors.names import is_latin_name

pytestmark = pytest.mark.logic


@pytest.mark.parametrize('name', [
    'MAFIC', 'blue soda', 'Panda Boxing', 'FishBone', "I'm moralist", 'Fu-Ta',
])
def test_aut_22c_latin_names_are_usable_as_they_are(name):
    assert is_latin_name(name)


@pytest.mark.parametrize('name', [
    '南浜よりこ', 'リヒャルト・バフマン', '低空MSコンボ', '超苦鉄質岩', '規制当局',
    '', '   ', '123', '＠＃＄',
])
def test_aut_22c_non_latin_or_letterless_names_are_not(name):
    """沒有半形英文字母就不算：純數字或全形符號當 tag 查不到東西。"""
    assert not is_latin_name(name)


def test_aut_22c_filter_skips_entities_whose_name_is_already_english(tmp_path):
    conn = authors_db.connect(str(tmp_path / 'authors.db'))
    try:
        authors_db.upsert(conn, [
            {'name': 'MAFIC', 'type': authors_db.CIRCLE},
            {'name': 'blue soda', 'type': authors_db.AUTHOR},
            {'name': '南浜よりこ', 'type': authors_db.AUTHOR},
            {'name': '有英文的', 'type': authors_db.AUTHOR, 'english_name': 'Has English'},
        ])
        names = {e['name'] for e in
                 authors_db.list_entities(conn, missing_english_only=True)}
        assert names == {'南浜よりこ'}, (
            '只有「英文名稱空白，而且名字本身也不是英文」的才該列出來')
    finally:
        conn.close()
