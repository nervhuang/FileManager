"""作者／團體名稱的解析。不依賴 Qt。

同人圈的清單標記法是「團體 (作者)」，貼進名稱欄時自動拆開，
省去手動建兩筆再拉關聯。規格見 docs/spec/authors.md 的 AUT-17 到 AUT-21。
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
