"""Web UI 的頁面模板是資源檔，三份打包設定都得收它。

模板從 webui.py 搬到 app/checker/page.html 之後，打包設定成了一條沒有編譯器
把關的線：漏收的話程式照常啟動、掃描照常跑，直到有人按下「詳細清單」才炸。
這支測試就是那個把關——CI 上不需要真的打包，只要三份設定裡都提得到這個檔。
"""
import io
import os

import pytest

from app.checker import webui

pytestmark = pytest.mark.logic

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _text(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as handle:
        return handle.read()


def test_template_ships_next_to_the_module():
    assert os.path.isfile(webui._PAGE_PATH), 'page.html 要跟 webui.py 同目錄'
    assert '<!doctype html>' in webui._read_page()


@pytest.mark.parametrize('config', [
    'scripts/build_nuitka.ps1',
    'BUILD.md',
    'FileManager.spec',
])
def test_build_configs_include_the_template(config):
    assert 'page.html' in _text(config), f'{config} 沒有收 app/checker/page.html'


def test_missing_template_raises_instead_of_degrading(monkeypatch):
    """找不到就炸，不回殘缺頁面：默默降級只會變成「新版面沒生效」這種難認的症狀。"""
    monkeypatch.setattr(webui, '_PAGE_PATH',
                        os.path.join(ROOT, 'app', 'checker', 'no-such-page.html'))
    with pytest.raises(OSError):
        webui._render_page('tok-en')
