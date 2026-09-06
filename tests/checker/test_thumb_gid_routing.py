"""縮圖路由要認得兩個來源的 gid。見 docs/spec/checker.md「第二個來源」。

`/thumb/<gid>` 的 gid 會被拿去查資料庫、也會變成快取檔名，所以必須消毒；
原本的消毒是「只留數字」，那是 exhentai gid 全為數字時代的寫法。wnacg 的
`wn-377256` 被它洗成 `377256`——查不到那筆，於是每張 wnacg 的卡片都只拿到
佔位圖；更糟的情況是站方剛好有同號的畫廊，圖就會張冠李戴。

不需要起伺服器：消毒是純函式。
"""
import pytest

from app.checker import webui

pytestmark = pytest.mark.logic


def test_both_sources_survive_the_sanitiser():
    assert webui.safe_gid('4140403') == '4140403'
    assert webui.safe_gid('wn-377256') == 'wn-377256'


def test_path_separators_and_dots_never_get_through():
    """gid 會變成快取檔名，跳脫目錄或改副檔名都不行。"""
    import os
    for evil in ('../../etc/passwd', 'wn-1/../../x', 'a' + chr(92) + 'b', 'x.py', 'wn-1.。'):
        cleaned = webui.safe_gid(evil)
        assert os.path.basename(cleaned) == cleaned, evil
        assert '/' not in cleaned and chr(92) not in cleaned and '.' not in cleaned, evil


def test_nothing_usable_left_is_empty():
    assert webui.safe_gid('') == ''
    assert webui.safe_gid('///') == ''


def test_the_page_asks_for_the_gid_as_it_is():
    """頁面不得自己改寫 gid，否則兩邊的消毒規則會各走各的。"""
    page = webui._render_page('tok')
    assert '/thumb/${esc(i.gid)}' in page
