"""名稱本身就是英文時，更新檢查器要拿它當 tag，不該跳過。

見 docs/spec/checker.md「掃描規則」。原本 `tag_for` 只認 `english_name`，
名字已經是英文的作者（實測 6 筆）一律記成 `no_english_name` 跳過——
那些作者從功能上線以來從來沒被掃過，而畫面上只寫「略過」。

判準與作者面板的「僅顯示無英文名稱」共用同一支 `is_latin_name`，不得各寫一份。
"""
import pytest

from app.checker.fetcher import tag_for

pytestmark = pytest.mark.logic


def test_english_name_still_wins():
    assert tag_for({'name': '南浜よりこ', 'type': 'author',
                    'english_name': 'Minamihama Yoriko'}) == 'artist:minamihama yoriko'


def test_latin_name_is_used_when_english_name_is_blank():
    assert tag_for({'name': 'MAFIC', 'type': 'circle', 'english_name': ''}) == 'group:mafic'
    assert tag_for({'name': 'blue soda', 'type': 'author'}) == 'artist:blue soda'


def test_non_latin_name_without_english_name_is_still_skipped():
    """日文名字沒填英文名稱時仍然查不到，維持跳過並回報 no_english_name。"""
    assert tag_for({'name': '南浜よりこ', 'type': 'author', 'english_name': ''}) is None
