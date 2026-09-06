"""第二個來源 wnacg：關鍵字搜尋與列表剖析。見 docs/spec/checker.md「第二個來源」。

HTML 片段取自實站（2026-09-06 `?q=南浜よりこ`），只留兩個項目並縮短屬性。
站方改版時這支測試會紅——那正是它的用途：剖析壞掉必須有人知道，
不能靜靜地回 0 筆，看起來像「這位作者在 wnacg 沒有書」。
"""
import pytest

from app.checker import wnacg

pytestmark = pytest.mark.logic


PAGE = '''
<div class="gallary_wrap"><ul class="cc">
<li class="li gallary_item">
<div class="pic_box cate-12">
<a href="/photos-index-aid-377256.html" title="[<em>南浜</em>屋 (<em>南浜よりこ</em>)] 種付ライセンス〜女上司わからせ編〜"><img alt="x" src="//t4.qy0.ru/data/t/3772/56/1786735479134369.webp" /></a>
</div>
<div class="info"><div class="title">
<a href="/photos-index-aid-377256.html" title="x">[<em>南浜</em>屋 (<em>南浜よりこ</em>)] 種付ライセンス〜女上司わからせ編〜</a>
</div>
<div class="info_col">
109張圖片，
創建於2026-08-15 03:24:39</div>
</div></li>
<li class="li gallary_item">
<div class="pic_box cate-1">
<a href="/photos-index-aid-360688.html" title="[南浜屋 (南浜よりこ)] 種付ライセンス&#12316;非モテ&#65372;播种资格证书 [白杨汉化组]"><img alt="x" src="//t4.qy0.ru/data/t/3606/88/17789254038659.png" /></a>
</div>
<div class="info"><div class="title">
<a href="/photos-index-aid-360688.html" title="x">y</a>
</div>
<div class="info_col">
176張圖片，
創建於2026-05-16 17:52:17</div>
</div></li>
</ul></div>
'''


def test_listing_gives_everything_a_finding_needs():
    rows = wnacg.parse_listing(PAGE)
    assert len(rows) == 2
    first = rows[0]
    assert first['gid'] == 'wn-377256'
    assert first['url'] == 'https://www.wnacg.com/photos-index-aid-377256.html'
    assert first['pages'] == 109
    assert first['thumb'] == 'https://t4.qy0.ru/data/t/3772/56/1786735479134369.webp'
    # 站上的時間是 UTC+8，存的是 epoch（與 exhentai 的 API 同單位）。
    assert first['posted'] == 1786735479 - 0  # 2026-08-15 03:24:39 +08:00
    import datetime
    assert datetime.datetime.fromtimestamp(
        first['posted'], datetime.timezone(datetime.timedelta(hours=8))
    ).strftime('%Y-%m-%d %H:%M:%S') == '2026-08-15 03:24:39'


def test_highlight_tags_are_not_part_of_the_title():
    """搜尋結果把命中的關鍵字包在 <em> 裡，那是排版不是標題。"""
    title = wnacg.parse_listing(PAGE)[0]['title']
    assert title == '[南浜屋 (南浜よりこ)] 種付ライセンス〜女上司わからせ編〜'
    assert '<em>' not in title


def test_html_entities_in_titles_are_decoded():
    assert '｜播种资格证书' in wnacg.parse_listing(PAGE)[1]['title']


def test_a_block_without_an_id_is_skipped_not_fatal():
    """站方偶爾在項目裡多塞一塊東西；缺 aid 的跳過，其餘照樣解析。"""
    broken = PAGE.replace('<li class="li gallary_item">',
                          '<li class="li gallary_item">\n<div class="ad"></div>', 1)
    assert len(wnacg.parse_listing(broken)) == 2
    assert wnacg.parse_listing('<li class="li gallary_item">垃圾') == []


def test_ids_are_prefixed_so_they_cannot_collide_with_exhentai():
    """findings 表的主鍵兩個來源共用：沒有前綴的話 wnacg 的 377256 會蓋掉站方的。"""
    assert wnacg.parse_listing(PAGE)[0]['gid'].startswith(wnacg.GID_PREFIX)
    assert wnacg.is_wnacg('wn-377256') and not wnacg.is_wnacg('377256')
    assert wnacg.url_for('wn-377256').endswith('aid-377256.html')


# ── 搜尋與翻頁 ──────────────────────────────────────────────────────────

def _pages(count):
    """做出 count 個項目的假頁面產生器，時間一路往舊走。"""
    def fetch_html(url):
        page = int(url.split('&p=')[1]) if '&p=' in url else 1
        base = (page - 1) * wnacg.PAGE_SIZE
        if base >= count:
            return ''
        blocks = []
        for i in range(base, min(base + wnacg.PAGE_SIZE, count)):
            posted = f'2026-01-{(31 - i % 28):02d} 00:00:00'
            blocks.append(
                f'<li class="li gallary_item"><a href="/photos-index-aid-{1000 + i}.html" '
                f'title="第{i}本"><img src="//x/y{i}.jpg" /></a>'
                f'<div class="info_col">10張圖片，創建於{posted}</div></li>')
        return ''.join(blocks)
    return fetch_html


def test_search_stops_at_the_wanted_count():
    rows = wnacg.search(_pages(200), '某作者', wanted=30)
    assert len(rows) == 30


def test_search_stops_when_the_results_run_out():
    rows = wnacg.search(_pages(5), '某作者', wanted=100)
    assert len(rows) == 5


def test_search_stops_at_the_cutoff():
    """增量掃描只要走到上次掃過的時間就夠，不必翻完整個作者。"""
    import datetime
    cutoff = int(datetime.datetime(
        2026, 1, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=8))).timestamp())
    rows = wnacg.search(_pages(200), '某作者', wanted=100, cutoff_epoch=cutoff)
    assert 0 < len(rows) < 100, '翻到比上次舊的就該停'
    assert all(r['posted'] >= cutoff for r in rows)
