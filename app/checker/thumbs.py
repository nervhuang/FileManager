"""縮圖快取：把站上的縮圖抓下來存本機，由 Web UI 從本機供應。

**不可改成讓頁面直接引用 `s.exhentai.org` 的網址。** 那會讓瀏覽器對站方發出
幾百個外連請求，很容易被判成盜連而拒絕服務，圖全部破掉；而且瀏覽器沒有登入
cookie，本來就未必拿得到。

快取視同網際網路暫存檔：可以隨時整個刪掉，下次看的時候會自己補回來。
超過容量上限時汰換最久沒被讀取的檔案。
"""

import os
import re
import threading
import urllib.error
import urllib.request

from .. import paths

CACHE_DIRNAME = 'checker_cache'
MAX_BYTES = 512 * 1024 * 1024      # 512MB，約兩萬張縮圖
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

_EXT_RE = re.compile(r'\.(jpg|jpeg|png|webp|gif)(?:\?|$)', re.IGNORECASE)
_CONTENT_TYPE = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.webp': 'image/webp', '.gif': 'image/gif',
}

_lock = threading.Lock()


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

    headers = {'User-Agent': _UA, 'Referer': 'https://exhentai.org/'}
    if cookie_header:
        headers['Cookie'] = cookie_header
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except (urllib.error.URLError, OSError, ValueError):
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
