"""第二個來源：wnacg（紳士漫畫）。不依賴 Qt。

exhentai 靠 `artist:`／`group:` tag 查詢，wnacg 沒有這種東西——它連英文名稱都
沒定義過，所以**一律拿作者的日文名稱跑站上的關鍵字搜尋**。也不需要登入：
沒有 cookie、沒有憑證，這個模組完全不碰 `exhentai.txt`。

比 exhentai 省一趟：列表頁本身就帶了標題、頁數、建立時間與縮圖，
不必再打一次 metadata API。

同一本書在兩個站是不同的識別碼，findings 表的主鍵是共用的，所以這裡的 id
一律加上 `wn-` 前綴（`GID_PREFIX`）——沒有前綴的話，wnacg 的 377256 會蓋掉
exhentai 的 377256。
"""

import datetime
import html
import re
import urllib.parse

BASE = 'https://www.wnacg.com'
SEARCH_URL = BASE + '/search/?q={q}&f=_all&s=create_time_DESC&syn=yes'
GALLERY_URL = BASE + '/photos-index-aid-{aid}.html'

GID_PREFIX = 'wn-'
MARKER = 'wnacg'          # 卡片上的來源標籤，與語言／品質標記併排
PAGE_SIZE = 24            # 實測一頁 24 筆
DELAY = 2.0               # 請求間隔。這個站沒有 exhentai 那麼嚴，但也不該狂打

# 站上時間沒有標時區，實測是 UTC+8。存進資料庫的一律是 epoch（與 exhentai 的
# API 同一個單位），顯示時才轉回當地時間。
_SITE_TZ = datetime.timezone(datetime.timedelta(hours=8))

_ITEM_SPLIT = '<li class="li gallary_item">'
_AID_RE = re.compile(r'/photos-index-aid-(\d+)\.html')
_TITLE_RE = re.compile(r'title="([^"]*)"')
_THUMB_RE = re.compile(r'src="([^"]+)"')
_PAGES_RE = re.compile(r'(\d+)\s*張圖片')
_POSTED_RE = re.compile(r'創建於\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
_EM_RE = re.compile(r'</?em>')


def is_wnacg(gid):
    return str(gid or '').startswith(GID_PREFIX)


def url_for(gid):
    """從 findings 的 gid 還原這本書的網址。"""
    return GALLERY_URL.format(aid=str(gid)[len(GID_PREFIX):])


def search_url(keyword, page=1):
    url = SEARCH_URL.format(q=urllib.parse.quote(keyword, safe=''))
    return url if page <= 1 else f'{url}&p={page}'


def _clean_title(raw):
    """搜尋結果會把命中的關鍵字包在 <em> 裡，那是排版不是標題。"""
    return html.unescape(_EM_RE.sub('', raw)).strip()


def _posted_epoch(text):
    try:
        naive = datetime.datetime.strptime(text, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None
    return int(naive.replace(tzinfo=_SITE_TZ).timestamp())


def parse_listing(body):
    """把一頁搜尋結果剖析成 [{gid, url, title, pages, posted, thumb}]。

    逐個 `<li class="li gallary_item">` 區塊各自解析，不用一條橫跨整個項目的
    大正則：站方偶爾會在某些項目多塞一塊廣告或少一個欄位，一條大正則會整項
    比對失敗而**整批消失**，逐欄解析頂多缺那一欄。

    缺 aid 的區塊直接跳過——沒有識別碼的項目存不進 findings 表。
    """
    items = []
    seen = set()
    for block in body.split(_ITEM_SPLIT)[1:]:
        aid_match = _AID_RE.search(block)
        if not aid_match:
            continue
        aid = aid_match.group(1)
        if aid in seen:
            continue
        seen.add(aid)

        title_match = _TITLE_RE.search(block)
        thumb_match = _THUMB_RE.search(block)
        pages_match = _PAGES_RE.search(block)
        posted_match = _POSTED_RE.search(block)
        thumb = thumb_match.group(1) if thumb_match else ''
        if thumb.startswith('//'):            # 站上給的是 protocol-relative
            thumb = 'https:' + thumb

        items.append({
            'gid': GID_PREFIX + aid,
            'url': GALLERY_URL.format(aid=aid),
            'title': _clean_title(title_match.group(1)) if title_match else '',
            'pages': int(pages_match.group(1)) if pages_match else None,
            'posted': _posted_epoch(posted_match.group(1)) if posted_match else None,
            'thumb': thumb,
        })
    return items


def search(fetch_html, keyword, *, wanted, cutoff_epoch=None):
    """關鍵字搜尋，回傳最多 `wanted` 筆，新→舊。

    `cutoff_epoch` 是上次掃到的最新一筆時間：翻到比它舊的就停，這樣增量掃描
    只會走一頁。`fetch_html(url)` 由呼叫端注入——測試餵假頁面，實際跑時是
    `Fetcher.fetch_html`，節流與退避都在那裡。
    """
    items = []
    for page in range(1, (wanted + PAGE_SIZE - 1) // PAGE_SIZE + 1):
        rows = parse_listing(fetch_html(search_url(keyword, page)))
        if not rows:
            break
        for row in rows:
            if cutoff_epoch and row['posted'] and row['posted'] < cutoff_epoch:
                return items
            items.append(row)
            if len(items) >= wanted:
                return items
        if len(rows) < PAGE_SIZE:
            break
    return items
