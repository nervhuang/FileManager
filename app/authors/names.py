"""作者／團體名稱的解析與判別。不依賴 Qt。

同人圈的清單標記法是「團體 (作者)」，貼進名稱欄時自動拆開，
省去手動建兩筆再拉關聯。規格見 docs/spec/authors.md 的 AUT-17 到 AUT-21。

`is_latin_name` 回答「這個名字本身就能當站上的 tag 用嗎」。它同時被作者面板的
「僅顯示無英文名稱」（AUT-22c）與更新檢查器的 `tag_for` 用到，兩邊必須是同一份
判準：一邊說「這筆不缺英文名」、另一邊卻照樣跳過不掃，那份盤點清單就在說謊。
"""

import re


# 同人圈慣用的「團體 (作者)」標記，外層方括號可有可無，括號可半形或全形；
# 用 (?:...)$ 錨定在字串尾端取「最後一組括號」，團體名本身帶括號時才不會錯拆。
# 括號內可能不只一位作者，用頓號／逗號分隔（如「和泉、冷泉」），數量不限。
_CIRCLE_AUTHOR_RE = re.compile(
    r'^\[?\s*(?P<circle>.+?)\s*[(（]\s*(?P<authors>[^()（）]+?)\s*[)）]\s*\]?$'
)
_AUTHOR_SPLIT_RE = re.compile(r'[、,，]\s*')


def parse_circle_author(text):
    """把「團體 (作者[、作者…])」或「[…]」拆成 (團體名, [作者名, …])；不符合格式回傳 None。"""
    match = _CIRCLE_AUTHOR_RE.match(text.strip())
    if not match:
        return None
    circle = match.group('circle').strip()
    authors = [a.strip() for a in _AUTHOR_SPLIT_RE.split(match.group('authors')) if a.strip()]
    if not circle or not authors:
        return None
    return circle, authors


# 半形可列印 ASCII 之外的字元。全形空白、日文、中文都算「不是拉丁字母」。
_NON_LATIN_RE = re.compile(r'[^ -~]')
_HAS_LETTER_RE = re.compile(r'[A-Za-z]')


def is_latin_name(name):
    """名稱本身是否就是一個能直接查詢的英文名字。

    判準刻意保守——只認半形可列印 ASCII，而且至少要有一個英文字母：

    - `MAFIC`、`blue soda`、`Panda Boxing`、`I'm moralist` → 是
    - `南浜よりこ`、`低空MSコンボ` → 否（名字裡有非 ASCII）
    - `123`、空字串 → 否（沒有字母，當 tag 查不到東西）

    帶重音的拉丁字母（`Café`）判為否：它會留在「還沒填英文名稱」的清單裡等人
    確認，而不是被程式猜一個查不到的 tag 出去。寧可多問一句，不要默默漏掉。
    """
    name = (name or '').strip()
    if not name or _NON_LATIN_RE.search(name):
        return False
    return bool(_HAS_LETTER_RE.search(name))
