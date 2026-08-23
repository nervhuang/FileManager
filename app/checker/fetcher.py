"""exhentai 抓取層：tag 頁清單與 E-Hentai JSON API 的中繼資料。

為什麼要兩段抓：tag 頁只給得到 gid、token 與羅馬拼音標題，而本機檔名是日文，
拿羅馬拼音比對會全數落空。`api.e-hentai.org` 的 gdata 方法會回 `title_jpn`，
格式與本機檔名幾乎一致，是比對能不能成立的關鍵。

安全規則（不可放寬）：cookie 值永不出現在 log、例外訊息或任何回傳結構中。
找不到 cookie 檔就明確報錯，**不退回匿名請求**——否則使用者會以為有登入，
實際上抓到的是空清單，然後把整櫃藏書誤判成「站上沒有」。
"""

import json
import os
import random
import re
import time
import urllib.error
import urllib.request

from .. import paths

COOKIE_FILENAME = 'exhentai.txt'
REQUIRED_COOKIES = ('ipb_member_id', 'ipb_pass_hash')

TAG_URL = 'https://exhentai.org/tag/{tag}'
API_URL = 'https://api.e-hentai.org/api.php'
API_BATCH = 25  # gdata 單次上限

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

_GALLERY_RE = re.compile(r'https://exhentai\.org/g/(\d+)/([0-9a-f]+)/')
_POSTED_RE = re.compile(r'id="posted_(\d+)"[^>]*>([^<]+)<')


class CheckerError(Exception):
    """可直接顯示給使用者的錯誤。訊息保證不含 cookie 值。"""


class CookieExpired(CheckerError):
    """cookie 失效（sad panda）。整輪掃描應立即中止，不要繼續空轉。"""


def cookie_path():
    return os.path.join(paths.runtime_root(), COOKIE_FILENAME)


def load_cookie_header():
    """讀 cookie 檔並組成 Cookie 標頭字串。

    回傳的字串含憑證，呼叫端只能拿去送出，不得寫入任何輸出。
    """
    path = cookie_path()
    try:
        with open(path, 'r', encoding='utf-8-sig') as handle:
            raw = handle.read()
    except OSError:
        raise CheckerError(
            f'找不到登入憑證檔：{path}\n'
            '請放入含 ipb_member_id、ipb_pass_hash、igneous 的文字檔（一行一組 key=value）。')

    jar = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if key and value:
            jar[key] = value

    missing = [k for k in REQUIRED_COOKIES if k not in jar]
    if missing:
        # 只列出缺少的欄位名稱，不回報任何既有欄位的值。
        raise CheckerError(f'登入憑證檔缺少必要欄位：{"、".join(missing)}（{path}）')

    return '; '.join(f'{k}={v}' for k, v in jar.items())


def tag_for(entity):
    """把 authors.db 的實體轉成 exhentai 的 tag。無 english_name 時回 None。"""
    english = (entity.get('english_name') or '').strip()
    if not english:
        return None
    namespace = 'group' if entity.get('type') == 'circle' else 'artist'
    return f'{namespace}:{english.lower()}'


class Fetcher:
    """帶速率控制與退避的抓取器。單執行緒使用，不可跨執行緒共用。"""

    def __init__(self, cookie_header, *, delay=4.0, jitter=1.0, timeout=30.0,
                 max_consecutive_failures=3, sleeper=time.sleep):
        self._cookie = cookie_header
        self._delay = delay
        self._jitter = jitter
        self._timeout = timeout
        self._max_failures = max_consecutive_failures
        self._sleep = sleeper          # 可注入，方便測試不必真的等
        self._last_request = 0.0
        self._failures = 0
        self.cancelled = False

    # ── 內部 ────────────────────────────────────────────────────────────

    def _throttle(self):
        """站方會擋密集請求，每次請求之間拉開間隔並加抖動。"""
        elapsed = time.monotonic() - self._last_request
        wait = self._delay + random.uniform(-self._jitter, self._jitter) - elapsed
        if wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()

    def _open(self, request):
        self._throttle()
        if self.cancelled:
            raise CheckerError('已取消')
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = response.read().decode('utf-8', 'replace')
            self._failures = 0
            return body
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                self._failures += 1
                if self._failures >= self._max_failures:
                    raise CheckerError(
                        f'連續 {self._failures} 次被站方限流（HTTP {exc.code}），已中止本輪掃描。'
                        '稍後再試即可，已掃描的部分都保留了。')
                # 指數退避：4、8、16 秒。
                self._sleep(self._delay * (2 ** self._failures))
                return self._open(request)
            raise CheckerError(f'請求失敗：HTTP {exc.code}')
        except urllib.error.URLError as exc:
            self._failures += 1
            if self._failures >= self._max_failures:
                raise CheckerError(f'連續 {self._failures} 次連線失敗，已中止本輪掃描。')
            self._sleep(self._delay * (2 ** self._failures))
            return self._open(request)

    # ── 對外 ────────────────────────────────────────────────────────────

    def fetch_tag_page(self, tag, page=0):
        """抓一頁 tag 清單，回傳 [(gid, token, posted_text)]，依發布時間新→舊。

        exhentai 未登入時會回一張極小的 sad panda 圖片而非 HTTP 錯誤，
        因此以「頁面過短且沒有任何 gallery 連結」判定 cookie 失效。
        """
        url = TAG_URL.format(tag=urllib.request.quote(tag, safe=':+'))
        if page:
            url += f'?page={page}'
        body = self._open(urllib.request.Request(url, headers={
            'User-Agent': _UA, 'Cookie': self._cookie,
            'Accept': 'text/html,application/xhtml+xml',
        }))

        posted = dict(_POSTED_RE.findall(body))
        seen, items = set(), []
        for gid, token in _GALLERY_RE.findall(body):
            if gid in seen:
                continue
            seen.add(gid)
            items.append((gid, token, posted.get(gid, '')))

        if not items and len(body) < 2000:
            raise CookieExpired(
                '登入憑證已失效（站方回了未登入頁面）。'
                f'請更新 {cookie_path()} 後重試。')
        return items

    def fetch_metadata(self, gid_token_pairs):
        """以 gdata 批次取中繼資料，回傳 gid -> dict。含 title_jpn。"""
        results = {}
        pairs = list(gid_token_pairs)
        for start in range(0, len(pairs), API_BATCH):
            if self.cancelled:
                break
            batch = pairs[start:start + API_BATCH]
            payload = {'method': 'gdata',
                       'gidlist': [[int(g), t] for g, t in batch],
                       'namespace': 1}
            body = self._open(urllib.request.Request(
                API_URL, data=json.dumps(payload).encode('utf-8'),
                headers={'User-Agent': _UA, 'Content-Type': 'application/json'}))
            try:
                data = json.loads(body)
            except ValueError:
                raise CheckerError('中繼資料 API 回傳格式無法解析。')
            if 'error' in data:
                raise CheckerError(f'中繼資料 API 回報錯誤：{data["error"]}')
            for entry in data.get('gmetadata', []):
                if 'error' in entry:
                    continue
                results[str(entry.get('gid'))] = entry
        return results
