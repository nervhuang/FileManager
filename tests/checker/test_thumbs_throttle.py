"""縮圖下載的節流與停手。見 docs/spec/checker.md「縮圖 → 下載節流」。

縮圖牆是瀏覽器捲到才觸發下載，一次捲動可能同時打出幾十個請求，而
ThreadingHTTPServer 每個請求一條執行緒——掃描器那邊 4 秒一次，這裡卻毫無節制。

不碰網路、不寫真的快取：urlopen 與 time 都由測試換掉。
"""
import threading
import urllib.error
import urllib.request

import pytest

from app.checker import thumbs

pytestmark = pytest.mark.logic


@pytest.fixture(autouse=True)
def clean_throttle():
    thumbs.reset_throttle()
    yield
    thumbs.reset_throttle()


class _Clock:
    """假時鐘：sleep 只是把指針往前撥，測得到等了多久而不必真的等。"""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(thumbs.time, 'monotonic', fake.monotonic)
    monkeypatch.setattr(thumbs.time, 'sleep', fake.sleep)
    return fake


def test_downloads_are_spaced_out(clock):
    assert thumbs._acquire_slot() is True
    assert clock.slept == [], '第一個不必等'
    assert thumbs._acquire_slot() is True
    assert clock.slept == [pytest.approx(thumbs.MIN_INTERVAL)], '第二個要等一個間隔'


def test_time_already_passed_costs_no_wait(clock):
    assert thumbs._acquire_slot() is True
    clock.now += thumbs.MIN_INTERVAL * 3
    assert thumbs._acquire_slot() is True
    assert clock.slept == [], '已經隔夠久就不必再等'


def test_rate_limit_starts_a_cooldown(clock, monkeypatch, tmp_path):
    """429 是站方唯一一次明說「你太快了」，收到之後要停手，不是繼續重試。"""
    monkeypatch.setattr(thumbs, 'cache_dir', lambda: str(tmp_path))

    def blocked(request, timeout=None):
        raise urllib.error.HTTPError('u', 429, 'Too Many Requests', {}, None)

    monkeypatch.setattr(urllib.request, 'urlopen', blocked)
    assert thumbs.fetch('123', 'https://ehgt.org/x.webp') is None
    assert thumbs.cooling_down() is True

    # 停手期間連出門都不出門：urlopen 換成會爆的版本，證明它沒被呼叫。
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: pytest.fail('停手期間仍在請求'))
    assert thumbs.fetch('124', 'https://ehgt.org/y.webp') is None

    clock.now += thumbs.COOLDOWN_SECONDS + 1
    assert thumbs.cooling_down() is False


def test_cache_hit_skips_the_throttle(clock, monkeypatch, tmp_path):
    """已經在快取裡的圖不必排隊——節流只擋真的要出門的請求。"""
    monkeypatch.setattr(thumbs, 'cache_dir', lambda: str(tmp_path))
    cached = tmp_path / '999.webp'
    cached.write_bytes(b'image-bytes')
    monkeypatch.setattr(urllib.request, 'urlopen',
                        lambda *a, **k: pytest.fail('快取命中不該連線'))

    assert thumbs.fetch('999', 'https://ehgt.org/z.webp') == str(cached)
    assert clock.slept == []


def test_threads_queue_up_instead_of_bursting(clock):
    """節流器是模組層級的單一份，等待在持鎖時進行，所以執行緒排成一列。"""
    results = []

    def worker():
        results.append(thumbs._acquire_slot())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [True] * 4
    assert len(clock.slept) == 3, '四個請求＝三段等待'
