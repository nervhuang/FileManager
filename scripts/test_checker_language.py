"""更新檢查器語系限縮的純函式測試。不碰網路、不需要憑證、不需要 Qt。

跑法：.venv/Scripts/python.exe scripts/test_checker_language.py

站上 tag 的格式（扁平字串陣列 'language:korean'）已用公開的 gdata API 實測確認，
這裡的樣本直接照那個格式寫。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.checker import matcher, titles

FAILED = []


def check(label, got, want):
    if got == want:
        print(f'  ok   {label}')
    else:
        print(f'  FAIL {label}\n       got  {got!r}\n       want {want!r}')
        FAILED.append(label)


def site_markers(tags, title=''):
    """照 scanner.scan_entity 的做法組出站上那本書的標記集合。"""
    parsed = titles.parse(title) if title else {'markers': set()}
    quality = {m for m in titles.detect_markers(*tags)
               if not m.startswith(titles.LANGUAGE_PREFIX)}
    return parsed['markers'] | titles.site_language_markers(tags) | quality


print('\n── site_language_markers：只讀 language namespace ──')
check('韓譯', titles.site_language_markers(
    ['language:korean', 'language:translated', 'parody:blue archive']),
    {'lang:korean'})
check('translated 單獨出現視為無語言',
      titles.site_language_markers(['language:translated']), set())
check('rewrite 忽略',
      titles.site_language_markers(['language:chinese', 'language:rewrite']),
      {'lang:chinese'})
check('textless narrative 不是忽略項，照樣是語言值',
      titles.site_language_markers(['language:textless narrative']),
      {'lang:textless narrative'})
check('字典裡沒有的語言也認得（舊版關鍵字比對認不出來）',
      titles.site_language_markers(['language:ukrainian']), {'lang:ukrainian'})
check('大小寫與空白',
      titles.site_language_markers([' Language:Korean ']), {'lang:korean'})
check('非 language namespace 不算',
      titles.site_language_markers(['other:chinese dress', 'female:glasses']), set())
check('沒有 language tag',
      titles.site_language_markers(['artist:as109', 'female:sole female']), set())


print('\n── is_wanted_language：嚴格白名單 ──')
check('無語言標記＝日文原版', titles.is_wanted_language(set()), True)
check('日文', titles.is_wanted_language({'lang:japanese'}), True)
check('中文', titles.is_wanted_language({'lang:chinese'}), True)
check('中日並列', titles.is_wanted_language({'lang:chinese', 'lang:japanese'}), True)
check('韓文', titles.is_wanted_language({'lang:korean'}), False)
check('嚴格：日文＋韓文一起出現也排除',
      titles.is_wanted_language({'lang:japanese', 'lang:korean'}), False)
check('textless narrative 排除',
      titles.is_wanted_language({'lang:textless narrative'}), False)
check('品質標記不影響語言判定',
      titles.is_wanted_language({'decensored', 'digital'}), True)


print('\n── 聯集：站上 namespace ∪ 檔名關鍵字 ──')
check('tag 說日文、標題寫英譯 → 排除（嚴格規則的重點）',
      titles.is_wanted_language(
          site_markers(['language:japanese'], '[社團 (作者)] 標題 [English]')),
      False)
check('tag 沒掛語言、標題寫漢化 → 中文，收',
      titles.languages(site_markers(['artist:x'], '[社團] 標題 [萌の空漢化社]')),
      {'chinese'})
check('無修正從站上 tag 認得出來',
      'decensored' in site_markers(['language:japanese', 'other:uncensored']),
      True)


print('\n── classify：排除與本機有沒有這本無關 ──')
local = [titles.parse('[社團 (作者)] とある標題.zip', is_filename=True)]
korean = {'core': titles.core_key('とある標題'), 'series': '',
          'markers': {'lang:korean'}}
korean_unknown = {'core': titles.core_key('全新的書'), 'series': '',
                  'markers': {'lang:korean'}}
japanese_new = {'core': titles.core_key('全新的書'), 'series': '', 'markers': set()}

check('本機已有 → 排除',
      matcher.classify(korean, local)['verdict'], matcher.VERDICT_SUPPRESSED)
check('本機沒有 → 一樣排除（舊版會判成新書）',
      matcher.classify(korean_unknown, local)['verdict'], matcher.VERDICT_SUPPRESSED)
check('日文新書照樣是新書',
      matcher.classify(japanese_new, local)['verdict'], matcher.VERDICT_NEW)
check('本機日文原版、站上中文版 → 版本升級',
      matcher.classify({'core': titles.core_key('とある標題'), 'series': '',
                        'markers': {'lang:chinese'}}, local)['verdict'],
      matcher.VERDICT_UPGRADE)
check('本機日文原版、站上日文原版 → 已有',
      matcher.classify({'core': titles.core_key('とある標題'), 'series': '',
                        'markers': set()}, local)['verdict'],
      matcher.VERDICT_HAVE)


print('\n' + ('全部通過' if not FAILED else f'失敗 {len(FAILED)} 項：' + '、'.join(FAILED)))
sys.exit(1 if FAILED else 0)
