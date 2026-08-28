"""縮圖快取：把站上的縮圖抓下來存本機，由 Web UI 從本機供應。

**不可改成讓頁面直接引用 `s.exhentai.org` 的網址。** 那會讓瀏覽器對站方發出
幾百個外連請求，很容易被判成盜連而拒絕服務，圖全部破掉；而且瀏覽器沒有登入
cookie，本來就未必拿得到。

快取視同網際網路暫存檔：可以隨時整個刪掉，下次看的時候會自己補回來。
超過容量上限時汰換最久沒被讀取的檔案。

**下載有節流。** 縮圖牆是瀏覽器捲到才觸發下載，一次捲動可能同時打出幾十個
請求，而 `ThreadingHTTPServer` 每個請求一條執行緒，等於同時併發往站方灌。
掃描器那邊小心翼翼地 4 秒一次請求，這裡卻毫無節制，是整個程式對站方最不禮貌
的地方。節流器是模組層級的單一份，所有執行緒共用。
"""

import os
import re
import threading
import time
import urllib.error
import urllib.request

from .. import paths

CACHE_DIRNAME = 'checker_cache'
MAX_BYTES = 512 * 1024 * 1024      # 512MB，約兩萬張縮圖

# 下載之間的最小間隔。比掃描器的 4 秒短得多是有理由的：那邊打的是要動用資料庫
# 的搜尋頁，這裡是靜態圖片 CDN，站上一頁 gallery 本來就會一口氣載入四十幾張。
# 0.5 秒（2 req/s）大致等於一般瀏覽器開一頁的速度，一百張沒快取的牆約 50 秒填滿。
MIN_INTERVAL = 0.5

# 被站方擋下（429／503）之後停手多久。期間所有下載直接放棄、顯示佔位圖——
# 被擋的時候繼續重試正是最糟的反應。
COOLDOWN_SECONDS = 60.0
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

_EXT_RE = re.compile(r'\.(jpg|jpeg|png|webp|gif)(?:\?|$)', re.IGNORECASE)
_CONTENT_TYPE = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.webp': 'image/webp', '.gif': 'image/gif',
}

_lock = threading.Lock()

# 節流用的狀態。與 _lock 分開：汰換會在持鎖時刪好幾百個檔案，
# 沒理由讓下載佇列跟著卡住。
_throttle_lock = threading.Lock()
_last_download = 0.0
_cooldown_until = 0.0


def _acquire_slot():
    """排隊等一個下載名額。回 False 代表站方剛擋過我們，現在該停手。

    等待是在持鎖時進行的——這正是重點：所有執行緒因此排成一列，
    而不是各自睡完 0.5 秒再一起衝出去。
    """
    global _last_download
    with _throttle_lock:
        now = time.monotonic()
        if now < _cooldown_until:
            return False
        wait = _last_download + MIN_INTERVAL - now
        if wait > 0:
            time.sleep(wait)
        _last_download = time.monotonic()
        return True


def _start_cooldown(seconds=None):
    global _cooldown_until
    with _throttle_lock:
        _cooldown_until = time.monotonic() + (
            COOLDOWN_SECONDS if seconds is None else seconds)


def cooling_down():
    """目前是否還在被擋之後的停手期。"""
    with _throttle_lock:
        return time.monotonic() < _cooldown_until


def reset_throttle():
    """清掉節流狀態。測試用，也給「使用者手動重試」留一個入口。"""
    global _last_download, _cooldown_until
    with _throttle_lock:
        _last_download = 0.0
        _cooldown_until = 0.0


def cache_dir():
    path = os.path.join(paths.runtime_root(), CACHE_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


def _extension_for(url):
    match = _EXT_RE.search(url or '')
    return ('.' + match.group(1).lower()) if match else '.jpg'


def cached_path(gid, url):
    """這個 gid 的縮圖該存在哪。不保證檔案已存在。"""
    return os.path.join(cache_dir(), f'{gid}{_extension_for(url)}')


def content_type(path):
    return _CONTENT_TYPE.get(os.path.splitext(path)[1].lower(), 'image/jpeg')


def fetch(gid, url, cookie_header=None, timeout=20.0):
    """取得縮圖的本機路徑；沒有就下載。失敗回 None（頁面自己顯示佔位圖）。

    縮圖抓不到不是錯誤——它只是好看而已，不該讓整個頁面掛掉，
    更不該讓一張圖的逾時卡住其他幾百張。
    """
    if not url or not gid:
        return None
    path = cached_path(gid, url)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        # 記下最近使用時間，汰換時才知道誰該先走。
        try:
            os.utime(path, None)
        except OSError:
            pass
        return path

    # 快取命中的路徑在上面就回去了，節流只擋真的要出門的請求。
    if not _acquire_slot():
        return None

    headers = {'User-Agent': _UA, 'Referer': 'https://exhentai.org/'}
    if cookie_header:
        headers['Cookie'] = cookie_header
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        # 被擋就停手一分鐘。這是唯一一個站方明確說「你太快了」的訊號，
        # 收到之後繼續重試等於把警告當成沒看到。
        if exc.code in (429, 503):
            _start_cooldown()
        return None
    except (OSError, ValueError):
        return None
    if not data:
        return None

    try:
        tmp = path + '.part'
        with open(tmp, 'wb') as handle:
            handle.write(data)
        os.replace(tmp, path)
    except OSError:
        return None

    evict_if_needed()
    return path


def total_bytes():
    total = 0
    for name in os.listdir(cache_dir()):
        try:
            total += os.path.getsize(os.path.join(cache_dir(), name))
        except OSError:
            continue
    return total


def evict_if_needed(max_bytes=MAX_BYTES):
    """超過上限就從最久沒被讀取的開始刪，回傳刪掉的檔案數。"""
    with _lock:
        directory = cache_dir()
        entries = []
        for name in os.listdir(directory):
            full = os.path.join(directory, name)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            entries.append((stat.st_atime, stat.st_size, full))

        total = sum(size for _atime, size, _path in entries)
        if total <= max_bytes:
            return 0

        entries.sort()                      # 最久沒讀的排前面
        removed = 0
        for _atime, size, full in entries:
            if total <= max_bytes:
                break
            try:
                os.remove(full)
            except OSError:
                continue
            total -= size
            removed += 1
        return removed


def clear():
    """整個清空。使用者想釋放空間時用，下次瀏覽會自動補回來。"""
    with _lock:
        directory = cache_dir()
        removed = 0
        for name in os.listdir(directory):
            try:
                os.remove(os.path.join(directory, name))
                removed += 1
            except OSError:
                continue
        return removed
