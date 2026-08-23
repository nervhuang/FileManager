"""同人誌標題的解析與正規化（純函式，不依賴 Qt、不碰網路）。

本機檔名與站上的 `title_jpn` 遵循同一套慣例：

    (活動) [社團 (作者)] 標題 (作品系列) [標記1] [標記2].副檔名

比對時只有「標題」與「作品系列」有意義，其餘都是雜訊：同一本書在不同來源
會掛不同的漢化組、語言與版本標記，若不剝掉就永遠比不中。

站上的英文 `title` 是羅馬拼音，與本機的日文檔名對不起來，因此一律以
`title_jpn` 為比對依據，僅在缺 `title_jpn` 時才退回英文標題。
"""

import os
import re
import unicodedata

# 一組完整的方括號或圓括號，允許內層再巢狀一層（如 [40010壱号 (40010試作型)]）。
_BRACKET = r'\[(?:[^\[\]]|\[[^\[\]]*\])*\]'
_PAREN = r'\((?:[^()]|\([^()]*\))*\)'

_LEADING_PAREN = re.compile(r'^\s*(' + _PAREN + r')\s*')
_LEADING_BRACKET = re.compile(r'^\s*(' + _BRACKET + r')\s*')
_TRAILING_BRACKET = re.compile(r'\s*(' + _BRACKET + r')\s*$')
_TRAILING_PAREN = re.compile(r'\s*(' + _PAREN + r')\s*$')

# [社團 (作者)]；沒有內層括號時整串就是社團名。
_CIRCLE_ARTIST = re.compile(r'^\[\s*(?P<circle>.*?)\s*(?:\(\s*(?P<artist>[^()]*?)\s*\))?\s*\]$')

_ARCHIVE_EXTS = {'.zip', '.rar', '.7z', '.cbz', '.cbr', '.pdf', '.epub', '.tar'}

# 語言標記。以子字串比對，因此 [萌の空漢化社] 這種漢化組名稱也能判成中文版。
_LANGUAGE_KEYWORDS = {
    'chinese': ('中国翻訳', '中國翻訳', '中国語', '漢化', '汉化', '中文', '中譯', '中译',
                'chinese'),
    'english': ('英訳', '英語', 'english'),
    'korean': ('韓国翻訳', '韓国語', 'korean'),
    'spanish': ('スペイン翻訳', 'スペイン語', 'spanish'),
    'portuguese': ('ポルトガル翻訳', 'ポルトガル語', 'portuguese'),
    'russian': ('ロシア翻訳', 'ロシア語', 'russian'),
    'french': ('フランス翻訳', 'フランス語', 'french'),
    'german': ('ドイツ翻訳', 'ドイツ語', 'german'),
    'italian': ('イタリア翻訳', 'イタリア語', 'italian'),
    'thai': ('タイ翻訳', 'タイ語', 'thai'),
    'vietnamese': ('ベトナム翻訳', 'ベトナム語', 'vietnamese'),
    'indonesian': ('インドネシア翻訳', 'インドネシア語', 'indonesian'),
    'polish': ('ポーランド翻訳', 'polish'),
    'turkish': ('トルコ翻訳', 'turkish'),
}

# 品質／載體標記，與語言正交。
_QUALITY_KEYWORDS = {
    'decensored': ('無修正', '无修正', '無修', 'decensored', 'uncensored'),
    'digital': ('dl版', 'digital', 'デジタル', 'dlsite'),
    'translated': ('翻訳', 'translated'),
}

_MARKER_KEYWORDS = dict(_LANGUAGE_KEYWORDS, **_QUALITY_KEYWORDS)

LANGUAGE_MARKERS = frozenset(_LANGUAGE_KEYWORDS)

# 語言白名單：只有這些語言（以及完全沒有語言標記的日文原版）值得通知。
# 實測本機藏書中譯 ≥2000 本、英譯 1 本，黑名單列不完，白名單才對得上實際分佈。
WANTED_LANGUAGES = frozenset({'chinese'})

# 判定「版本升級」時視為值得通知的標記，依偏好排序。
PREFERRED_MARKERS = ('chinese', 'decensored')


def languages(markers):
    """從標記集合中取出語言標記。空集合代表日文原版。"""
    return set(markers or ()) & LANGUAGE_MARKERS


def is_wanted_language(markers):
    """這個版本的語言值不值得通知：中譯或無語言標記的原版為真。"""
    found = languages(markers)
    return not found or bool(found & WANTED_LANGUAGES)


def _nfkc(text):
    """全形轉半形、統一相容字元。日文假名本身不受影響。"""
    return unicodedata.normalize('NFKC', text or '')


def strip_extension(name):
    """去掉壓縮檔／電子書副檔名；資料夾名稱或無副檔名時原樣回傳。"""
    stem, ext = os.path.splitext(name or '')
    return stem if ext.lower() in _ARCHIVE_EXTS else (name or '')


def detect_markers(*texts):
    """從任意段文字（標記、漢化組名、站上 tag）判出版本標記集合。"""
    haystack = _nfkc(' '.join(t for t in texts if t)).lower()
    found = set()
    for marker, keywords in _MARKER_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            found.add(marker)
    return found


def core_key(title):
    """把標題壓成比對用的鍵：去空白、去標點、統一大小寫與全半形。

    留下日文假名與漢字本身，只抹掉排版差異——檔名裡的空白與標點在不同來源
    幾乎必定不同，納入比對只會製造假性差異。
    """
    text = _nfkc(title).lower()
    return ''.join(ch for ch in text if ch.isalnum())


def parse(raw, *, is_filename=False):
    """拆解一個標題，回傳各欄位與比對用的 `core`。

    `is_filename` 為真時會先去掉副檔名。解析失敗不丟例外——來源格式五花八門，
    拆不乾淨時退化成「整串當標題」仍然可以比對，總比整批掃描中斷好。
    """
    text = (raw or '').strip()
    if is_filename:
        text = strip_extension(text)

    event = ''
    circle = ''
    artist = ''
    markers_raw = []

    # 開頭的圓括號是活動名（(C77)、(COMIC1☆3)…），可能不只一組。
    while True:
        match = _LEADING_PAREN.match(text)
        if not match:
            break
        event = event or match.group(1)[1:-1].strip()
        text = text[match.end():]

    # 接著的方括號是 [社團 (作者)]。
    match = _LEADING_BRACKET.match(text)
    if match:
        inner = match.group(1)
        text = text[match.end():]
        parts = _CIRCLE_ARTIST.match(inner)
        if parts:
            circle = (parts.group('circle') or '').strip()
            artist = (parts.group('artist') or '').strip()
        else:
            circle = inner[1:-1].strip()

    # 結尾的方括號全是版本／漢化組標記，由後往前剝。
    while True:
        match = _TRAILING_BRACKET.search(text)
        if not match:
            break
        markers_raw.append(match.group(1)[1:-1].strip())
        text = text[:match.start()]

    # 最後一組圓括號是作品系列。剝完標記才剝，因為標記通常排在系列之後。
    series = ''
    match = _TRAILING_PAREN.search(text)
    if match:
        series = match.group(1)[1:-1].strip()
        text = text[:match.start()]

    title = text.strip(' -_.')
    if not title:
        # 整串都被剝光（例如檔名只有 [社團] 沒有標題），退回原字串保底。
        title = strip_extension(raw or '').strip() if is_filename else (raw or '').strip()

    markers_raw.reverse()
    return {
        'raw': raw or '',
        'event': event,
        'circle': circle,
        'artist': artist,
        'title': title,
        'series': series,
        'markers_raw': markers_raw,
        'markers': detect_markers(*markers_raw, circle),
        'core': core_key(title),
    }
