"""更新檢查器的語系限縮。純函式：不碰網路、不需憑證、不需 Qt。

規則見 docs/spec/checker.md：語言集合為空（日文原版）或完全落在
{japanese, chinese} 之內才通知，出現任何白名單外的值即排除。

站上 tag 的扁平字串格式（'language:korean'）已用公開的 gdata API 實測確認，
這裡的樣本直接照那個格式寫。

原 scripts/test_checker_language.py。
"""
import pytest

from app.checker import matcher, titles

pytestmark = pytest.mark.logic


def _site_markers(tags, title=''):
    """照 scanner.scan_entity 的做法組出站上那本書的標記集合。"""
    parsed = titles.parse(title) if title else {'markers': set()}
    quality = {m for m in titles.detect_markers(*tags)
               if not m.startswith(titles.LANGUAGE_PREFIX)}
    return parsed['markers'] | titles.site_language_markers(tags) | quality


# ── site_language_markers：只讀 language namespace ────────────────────────
# 舊版拿關鍵字字典比對，字典只列得出 14 種語言而站上超過 30 種，
# 認不出來的又被當成日文原版，於是白名單實際上是黑名單。

@pytest.mark.parametrize("tags, expected", [
    pytest.param(['language:korean', 'language:translated', 'parody:blue archive'],
                 {'lang:korean'}, id="韓譯"),
    pytest.param(['language:translated'], set(), id="translated單獨出現視為無語言"),
    pytest.param(['language:chinese', 'language:rewrite'],
                 {'lang:chinese'}, id="rewrite忽略"),
    pytest.param(['language:textless narrative'],
                 {'lang:textless narrative'}, id="textless_narrative不是忽略項"),
    pytest.param(['language:ukrainian'], {'lang:ukrainian'},
                 id="字典裡沒有的語言也認得"),
    pytest.param([' Language:Korean '], {'lang:korean'}, id="大小寫與空白"),
    pytest.param(['other:chinese dress', 'female:glasses'], set(),
                 id="非language_namespace不算"),
    pytest.param(['artist:as109', 'female:sole female'], set(), id="沒有language_tag"),
])
def test_site_language_markers_reads_only_the_language_namespace(tags, expected):
    assert titles.site_language_markers(tags) == expected


# ── is_wanted_language：嚴格白名單 ────────────────────────────────────────
# 嚴格而非寬鬆：站上的語言 tag 常常沒跟上，日文 tag 掛著沒改、標題卻已寫明是
# 英譯本；寬鬆規則會被「japanese 在白名單裡」拖著放行。

@pytest.mark.parametrize("markers, wanted", [
    pytest.param(set(), True, id="無語言標記即日文原版"),
    pytest.param({'lang:japanese'}, True, id="日文"),
    pytest.param({'lang:chinese'}, True, id="中文"),
    pytest.param({'lang:chinese', 'lang:japanese'}, True, id="中日並列"),
    pytest.param({'lang:korean'}, False, id="韓文"),
    pytest.param({'lang:japanese', 'lang:korean'}, False, id="嚴格_日韓並列也排除"),
    pytest.param({'lang:textless narrative'}, False, id="textless_narrative排除"),
    pytest.param({'decensored', 'digital'}, True, id="品質標記不影響語言判定"),
])
def test_is_wanted_language_is_a_strict_whitelist(markers, wanted):
    assert titles.is_wanted_language(markers) is wanted


# ── 聯集：站上 namespace ∪ 檔名關鍵字 ─────────────────────────────────────

def test_site_tag_says_japanese_but_title_says_english_is_excluded():
    """嚴格規則的重點：tag 沒跟上時，標題說了算。"""
    markers = _site_markers(['language:japanese'], '[社團 (作者)] 標題 [English]')
    assert titles.is_wanted_language(markers) is False


def test_language_from_filename_keyword_when_site_has_no_language_tag():
    markers = _site_markers(['artist:x'], '[社團] 標題 [萌の空漢化社]')
    assert titles.languages(markers) == {'chinese'}


def test_decensored_is_detected_from_site_tags():
    assert 'decensored' in _site_markers(['language:japanese', 'other:uncensored'])


# ── classify：排除與本機有沒有這本無關 ─────────────────────────────────────
# 舊版只在本機已有同名書時才靜音，理由是沒收過的作品仍該讓使用者知道；
# 實際上只有韓譯英譯版存在的書本來就不會收。

@pytest.fixture
def local_collection():
    return [titles.parse('[社團 (作者)] とある標題.zip', is_filename=True)]


def _remote(core_title, markers):
    return {'core': titles.core_key(core_title), 'series': '', 'markers': markers}


@pytest.mark.parametrize("remote, expected_verdict", [
    pytest.param(_remote('とある標題', {'lang:korean'}),
                 matcher.VERDICT_SUPPRESSED, id="韓譯_本機已有則排除"),
    pytest.param(_remote('全新的書', {'lang:korean'}),
                 matcher.VERDICT_SUPPRESSED, id="韓譯_本機沒有一樣排除"),
    pytest.param(_remote('全新的書', set()),
                 matcher.VERDICT_NEW, id="日文新書照樣是新書"),
    pytest.param(_remote('とある標題', {'lang:chinese'}),
                 matcher.VERDICT_UPGRADE, id="本機日文原版_站上中文版為版本升級"),
    pytest.param(_remote('とある標題', set()),
                 matcher.VERDICT_HAVE, id="本機日文原版_站上日文原版為已有"),
])
def test_classify_verdicts(local_collection, remote, expected_verdict):
    assert matcher.classify(remote, local_collection)['verdict'] == expected_verdict
