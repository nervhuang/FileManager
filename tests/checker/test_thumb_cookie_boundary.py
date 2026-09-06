"""縮圖只對 exhentai 帶登入 cookie，其他主機一律不帶。

見 docs/spec/checker.md「安全邊界」的「不外洩憑證」。原本 `thumbs.fetch()` 把
cookie 與 Referer 無條件掛上去——縮圖網址指到哪裡就送到哪裡。之前所有縮圖都在
站方的 CDN，看不出問題；一旦有第二個來源（wnacg 的縮圖在 t4.qy0.ru），
那條 cookie 就會被送給一個完全無關的第三方主機。

不碰網路：`urlopen` 由測試換掉。
"""
import urllib.request

import pytest

from app.checker import thumbs

pytestmark = pytest.mark.logic


class _Response:
    def read(self):
        return b'\x89PNG\r\n\x1a\n' + b'0' * 64

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def captured(monkeypatch, tmp_path):
    monkeypatch.setenv('FILEMANAGER_HOME', str(tmp_path))
    monkeypatch.setattr(thumbs, '_acquire_slot', lambda: True)
    seen = []

    def fake_urlopen(request, timeout=None):
        seen.append(request)
        return _Response()

    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    return seen


def test_exhentai_thumbs_still_carry_the_cookie(captured):
    thumbs.fetch('123', 'https://s.exhentai.org/t/ab/cd.jpg', 'ipb_member_id=1')
    assert captured[0].get_header('Cookie') == 'ipb_member_id=1'
    assert 'exhentai.org' in captured[0].get_header('Referer')


def test_other_hosts_never_see_the_cookie(captured):
    thumbs.fetch('wn-377256', 'https://t4.qy0.ru/data/t/3772/56/17867.webp',
                 'ipb_member_id=1')
    assert captured[0].get_header('Cookie') is None, '憑證不得送給站方以外的主機'
    assert captured[0].get_header('Referer') is None
