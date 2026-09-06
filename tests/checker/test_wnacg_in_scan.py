"""掃描時兩個來源一起跑。見 docs/spec/checker.md「第二個來源」。

wnacg 的結果與 exhentai 的併進同一份 items，判定走同一套 matcher——
使用者要的是「這本我有沒有」，不是「這本在哪個站」。來源以 markers 裡的
`wnacg` 標籤呈現，卡片上看得到。

不碰網路：頁面與 metadata 都由測試提供。
"""
import pytest

from app.checker import matcher, scanner, titles, wnacg

pytestmark = pytest.mark.logic


def _wn_page(*titles_):
    blocks = []
    for i, title in enumerate(titles_):
        blocks.append(
            f'<li class="li gallary_item"><a href="/photos-index-aid-{500 + i}.html" '
            f'title="{title}"><img src="//t4.qy0.ru/x{i}.jpg" /></a>'
            f'<div class="info_col">100張圖片，創建於2026-08-0{i + 1} 00:00:00</div></li>')
    return ''.join(blocks)


class _NoExhentai:
    """站方那邊什麼也沒有：wnacg 仍然要跑。"""

    cancelled = False

    def fetch_tag_page(self, tag, after_gid=None):
        return []

    def fetch_search_page(self, keyword, after_gid=None):
        return []

    def fetch_metadata(self, pairs):
        return {}


def test_wnacg_items_are_added_to_the_same_result():
    calls = []

    def wn_fetch(url):
        calls.append(url)
        return _wn_page('[南浜屋 (南浜よりこ)] 種付ライセンス [中国翻訳]')

    result = scanner.scan_entity(
        {'id': 1, 'name': '南浜よりこ', 'type': 'author', 'english_name': 'Minamihama'},
        _NoExhentai(), lambda e: [], wnacg_fetch=wn_fetch)

    assert calls, 'wnacg 沒被查'
    # 一律用日文名稱做關鍵字，不管有沒有英文名稱。
    from urllib.parse import quote
    assert quote('南浜よりこ', safe='') in calls[0]

    assert len(result['items']) == 1
    item = result['items'][0]
    assert item['gid'] == 'wn-500'
    assert item['url'] == 'https://www.wnacg.com/photos-index-aid-500.html'
    assert wnacg.MARKER in item['markers'], '卡片要看得出這本來自哪裡'
    assert item['verdict'] == matcher.VERDICT_NEW
    assert result['wnacg_count'] == 1


def test_the_source_tag_does_not_fake_a_version_upgrade():
    """`wnacg` 只是來源標籤，不得被當成本機缺少的偏好版本。"""
    local = [titles.parse('[南浜屋 (南浜よりこ)] 種付ライセンス [中国翻訳].zip',
                          is_filename=True)]
    result = scanner.scan_entity(
        {'id': 1, 'name': '南浜よりこ', 'type': 'author'},
        _NoExhentai(), lambda e: [l['raw'] for l in local],
        wnacg_fetch=lambda url: _wn_page('[南浜屋 (南浜よりこ)] 種付ライセンス [中国翻訳]'))

    assert result['items'][0]['verdict'] != matcher.VERDICT_UPGRADE
    assert result['items'][0]['missing_markers'] == []


def test_wnacg_runs_even_when_the_entity_has_no_english_name():
    result = scanner.scan_entity(
        {'id': 1, 'name': '低空MSコンボ', 'type': 'circle'},
        _NoExhentai(), lambda e: [],
        wnacg_fetch=lambda url: _wn_page('[低空MSコンボ (えちひろ)] 星梨花'))
    assert result['wnacg_count'] == 1


def test_without_a_wnacg_fetcher_nothing_changes():
    result = scanner.scan_entity({'id': 1, 'name': 'X', 'english_name': 'X'},
                                 _NoExhentai(), lambda e: [])
    assert result['items'] == [] and result['wnacg_count'] == 0


def test_the_newest_wnacg_time_is_recorded_for_the_next_scan():
    result = scanner.scan_entity(
        {'id': 1, 'name': '某作者', 'type': 'author'}, _NoExhentai(), lambda e: [],
        wnacg_fetch=lambda url: _wn_page('甲', '乙', '丙'))
    # 第一筆是最新的（站上依建立時間新→舊）。
    assert result['wnacg_posted'] == result['items'][0]['posted']
    assert result['wnacg_posted']
