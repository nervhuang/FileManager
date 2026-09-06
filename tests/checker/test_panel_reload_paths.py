"""面板讀取資料庫的三條路徑真的跑得起來。

2026-09-06 的 regression：把 `ScanWorker` 拆出去時，`from contextlib import closing`
被一併刪掉，但面板自己還有三處在用。三處都包在 `try/except Exception` 裡，
所以症狀不是崩潰，是畫面上一行「讀取結果失敗：name 'closing' is not defined」
——測試裡沒有任何東西會踩到它。

這支測試存在的理由就是踩它：不驗內容，只驗「呼叫下去不會拋 NameError」。
"""
import pytest

pytestmark = pytest.mark.gui


@pytest.fixture
def panel(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv('FILEMANAGER_HOME', str(tmp_path))
    from app.checker.panel import CheckerPanel
    widget = CheckerPanel()
    yield widget
    widget.close()


def test_refresh_reads_the_database_without_blowing_up(panel, qapp):
    errors = []
    panel.status_message.connect(errors.append)
    panel.refresh()
    qapp.processEvents()
    assert not [e for e in errors if '失敗' in e], errors
    assert '失敗' not in panel.counts_label.text()


def test_every_database_helper_of_the_panel_is_callable(panel):
    """三處 `with closing(store.connect())` 各叫一次。

    它們的例外處理會把 NameError 吞成一行訊息，所以這裡直接查函式用到的
    全域名字都存在，而不是等它在畫面上變成一行字。
    """
    import app.checker.panel as module

    missing = []
    for name in ('closing', 'store', 'fetcher', 'matcher', 'webui', 'ScanWorker'):
        if not hasattr(module, name):
            missing.append(name)
    assert not missing, f'panel.py 少了這些名字：{missing}'
