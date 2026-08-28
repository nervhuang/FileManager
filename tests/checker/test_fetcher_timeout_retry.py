"""抓取層對連線類錯誤的重試。見 docs/spec/checker.md「速率控制」。

真實事故：跑到第 244／440 位時 `The read operation timed out` 直接打死整輪。
`read()` 逾時拋的是 `TimeoutError`，不是 `urllib.error.URLError`，於是它穿過
抓取層的退避、穿過 `scan_all` 的錯誤收斂，撞上工作執行緒最外層的
「未預期的錯誤」——一次逾時就報銷 20 分鐘。

不碰網路：`urlopen` 由測試換掉。
"""
import urllib.error
import urllib.request

import pytest

from app.checker import fetcher

pytestmark = pytest.mark.logic


class _Response:
    def __init__(self, body):
        self._body = body.encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fetcher(monkeypatch, outcomes):
    """每次呼叫 urlopen 就吐出 outcomes 的下一項：例外就 raise，字串就當成回應。"""
    calls = []

    def fake_urlopen(request, timeout=None):
        outcome = outcomes[len(calls)]
        calls.append(request)
        if isinstance(outcome, BaseException):
            raise outcome
        return _Response(outcome)

    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    # delay/jitter 歸零、sleeper 換掉：測退避邏輯，不測時鐘。
    instance = fetcher.Fetcher('ipb_member_id=x', delay=0, jitter=0,
                               sleeper=lambda seconds: None)
    return instance, calls


def test_read_timeout_is_retried(monkeypatch):
    """一次讀取逾時要退避重試，不是往上炸。"""
    instance, calls = _fetcher(monkeypatch, [TimeoutError('The read operation timed out'), 'ok'])
    assert instance._open(urllib.request.Request('https://example.invalid/')) == 'ok'
    assert len(calls) == 2


def test_connection_reset_is_retried(monkeypatch):
    """連線被重置與逾時同一類：都是 OSError，都該重試。"""
    instance, calls = _fetcher(monkeypatch, [ConnectionResetError('reset'), 'ok'])
    assert instance._open(urllib.request.Request('https://example.invalid/')) == 'ok'
    assert len(calls) == 2


def test_repeated_timeouts_abort_the_whole_run(monkeypatch):
    """連續 3 次就中止整輪——而且要是 ScanAborted，scan_all 才不會把它當單一實體的失敗吞掉。"""
    instance, _calls = _fetcher(monkeypatch, [TimeoutError('timed out')] * 3)
    with pytest.raises(fetcher.ScanAborted):
        instance._open(urllib.request.Request('https://example.invalid/'))


def test_success_resets_the_failure_counter(monkeypatch):
    """撐過一次逾時之後，計數要歸零，不然下一位作者出一次錯就被當成連續失敗。"""
    instance, _calls = _fetcher(
        monkeypatch, [TimeoutError('t'), 'ok', TimeoutError('t'), 'ok'])
    request = urllib.request.Request('https://example.invalid/')
    assert instance._open(request) == 'ok'
    assert instance._open(request) == 'ok'


def test_rate_limit_still_backs_off_then_aborts(monkeypatch):
    """429 的處理不變：退避重試，連續 3 次中止整輪。"""
    error = urllib.error.HTTPError('u', 429, 'Too Many Requests', {}, None)
    instance, calls = _fetcher(monkeypatch, [error, error, error])
    with pytest.raises(fetcher.ScanAborted):
        instance._open(urllib.request.Request('https://example.invalid/'))
    assert len(calls) == 3


def test_cookie_expired_aborts_the_run_too():
    """CookieExpired 是 ScanAborted 的一種：兩者都該中止整輪。"""
    assert issubclass(fetcher.CookieExpired, fetcher.ScanAborted)
