"""整頁只准有一種字型種類。見 docs/spec/checker.md「字型」。

瀏覽器不讓 button／input／select 繼承頁面字型，沒明講就落到系統 UI 字型——
分頁按鈕（`.tab`）因此和搜尋框、卡片各用各的字，同一畫面上看得出三種筆畫。
這裡擋的是「又有人加了一個沒設字型的控制項」，字級不管（大小是刻意的階層）。

頁面是純字串，不需要 Qt，也不需要起伺服器。
"""
import re

import pytest

from app.checker import webui

pytestmark = pytest.mark.logic


def _page():
    return webui._render_page('tok-en')


def _rule(selector):
    """抓出某個 CSS 選擇器的宣告內容。選擇器一律頂格寫，所以認行首就夠。"""
    page = _page()
    head = '\n' + selector + '{'
    start = page.index(head) + len(head)
    return page[start:page.index('}', start)]


def test_form_controls_inherit_the_page_font_family():
    """一條規則涵蓋所有表單元件，不是逐個 widget 登記的白名單。"""
    rule = _rule('button,input,select,textarea')
    assert 'font-family:inherit' in rule


def test_only_body_names_an_actual_font_family():
    """除了 body 那份字型堆疊，任何區塊都不得自己指定字型種類。"""
    css = _page().split('</style>')[0]
    named = [decl for decl in re.findall(r'font(?:-family)?\s*:\s*([^;}]+)', css)
             if 'inherit' not in decl]
    assert len(named) == 1, f'只有 body 可以指定字型種類，實際有 {named}'
    assert 'Microsoft JhengHei' in named[0]
