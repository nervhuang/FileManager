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

# 檔名用的語言關鍵字。以子字串比對，因此 [萌の空漢化社] 這種漢化組名稱也能判成中文版。
#
# 這份字典**只**用在本機檔名與標題括號——檔名沒有 namespace 可讀，只能認關鍵字。
# 站上那側改讀 `language:` namespace 的值本身（見 `site_language_markers`），
# 不再依賴這份字典：它只列得出 14 種語言，而站上超過 30 種，認不出來的會被
# 當成「無語言標記」放行，白名單就變成了黑名單。
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

# 語言標記在標記集合裡一律帶 `lang:` 前綴，與品質標記（decensored、digital…）分開。
# 之所以要前綴而不是列舉：站上的語言值不受我們控制，`language:ukrainian` 這種
# 沒列進字典的值也必須認得出「這是一個語言」，否則又會退回「認不出＝日文原版」。
LANGUAGE_PREFIX = 'lang:'

# 站上 `language:` namespace 裡不是語言的值。
#   translated / rewrite  伴隨真正的語言 tag 出現，由那個 tag 自己判，這裡忽略。
# 其餘沒列到的值（textless narrative、text cleaned…）不在白名單內，一律排除。
LANGUAGE_NAMESPACE_IGNORE = frozenset({'translated', 'rewrite'})

# 語言白名單。實測 5 位作者最新各 25 本共 103 本：無語言標記 53、中文 19、
# 中日並列 4，其餘 27 本散在英、韓、西、越、法、烏克蘭、土耳其與 text cleaned——
# 黑名單列不完，白名單才對得上實際分佈。
WANTED_LANGUAGES = frozenset({'japanese', 'chinese'})

# 判定「版本升級」時視為值得通知的標記，依偏好排序。
PREFERRED_MARKERS = (LANGUAGE_PREFIX + 'chinese', 'decensored')


def language_marker(value):
    """把一個語言值（'korean'）轉成標記（'lang:korean'）。"""
    return LANGUAGE_PREFIX + (value or '').strip().lower()


def site_language_markers(tags):
    """從站上的 tag 陣列取語言標記。

    gdata API 帶 `namespace=1` 時回的是 `['language:korean', 'language:translated',
    'artist:xxx', ...]` 這種扁平字串陣列（已實測確認）。直接讀 namespace 而非
    關鍵字比對，好處有二：站上有三十幾種語言，字典列不完；而且不會被
    `female:` / `other:` 裡剛好含有語言名稱的 tag 誤判。
    """
    found = set()
    for tag in tags or ():
        namespace, sep, value = str(tag).partition(':')
        if not sep or namespace.strip().lower() != 'language':
            continue
        value = value.strip().lower()
        if value and value not in LANGUAGE_NAMESPACE_IGNORE:
            found.add(language_marker(value))
    return found


def languages(markers):
    """從標記集合中取出語言值（不含前綴）。空集合代表日文原版。"""
    return {m[len(LANGUAGE_PREFIX):] for m in (markers or ())
            if str(m).startswith(LANGUAGE_PREFIX)}


def is_wanted_language(markers):
    """這個版本的語言值不值得通知。

    嚴格白名單：**只要出現任何一個白名單外的語言就為假**，即使同時掛著日文或
    中文也一樣。站上的 language tag 常常沒跟上——日文 tag 掛著沒改、標題卻已經
    寫明是英譯本；寬鬆規則會被「japanese 在白名單裡」拖著放行，等於沒過濾。

    完全沒有語言標記代表日文原版，為真。
    """
    found = languages(markers)
    return not (found - WANTED_LANGUAGES)


def _nfkc(text):
    """全形轉半形、統一相容字元。日文假名本身不受影響。"""
    return unicodedata.normalize('NFKC', text or '')


def strip_extension(name):
    """去掉壓縮檔／電子書副檔名；資料夾名稱或無副檔名時原樣回傳。"""
    stem, ext = os.path.splitext(name or '')
    return stem if ext.lower() in _ARCHIVE_EXTS else (name or '')


def detect_markers(*texts):
    """從檔名或標題括號裡的文字判出版本標記集合。

    語言結果帶 `lang:` 前綴，與 `site_language_markers()` 的輸出同一套詞彙，
    兩邊可以直接聯集。
    """
    haystack = _nfkc(' '.join(t for t in texts if t)).lower()
    found = set()
    for marker, keywords in _MARKER_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            found.add(language_marker(marker) if marker in _LANGUAGE_KEYWORDS
                      else marker)
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
