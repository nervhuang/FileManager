"""進度條高度隨字型重算。見 docs/spec/checker.md「執行紀錄區」。

原本是 `setFixedHeight(18)`。18pt 字型下「待命」這行字需要約 30px，於是文字
被裁掉一半——與工具列高度踩過的是同一個坑（ui-shell.md 的 SHL-10a）：
釘死的尺寸在文字開始跟著字型長大之後就會裁掉內容。

offscreen 量得到高度與 fontMetrics，量不到「看起來有沒有被裁」——所以判準
寫成「高度必須容得下一行字」，那是量得到的部分。
"""
import pytest
from PyQt5.QtGui import QFontMetrics

pytestmark = pytest.mark.gui


@pytest.fixture
def panel(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv('FILEMANAGER_HOME', str(tmp_path))
    from app.checker.panel import CheckerPanel
    widget = CheckerPanel()
    yield widget
    widget.close()


@pytest.mark.parametrize('size', [8, 12, 18, 24])
def test_the_bar_always_fits_its_own_text(panel, qapp, size):
    panel.apply_font_size(size)
    qapp.processEvents()

    bar = panel.progress_bar
    needed = QFontMetrics(bar.font()).height()
    assert bar.minimumHeight() >= needed, (
        f'{size}pt：進度條 {bar.minimumHeight()}px 容不下 {needed}px 的文字')


def test_the_bar_grows_with_the_font(panel, qapp):
    panel.apply_font_size(9)
    small = panel.progress_bar.minimumHeight()
    panel.apply_font_size(20)
    qapp.processEvents()
    assert panel.progress_bar.minimumHeight() > small, '放大字型後高度必須跟著長'


def test_it_never_shrinks_below_the_original_look(panel, qapp):
    """小字型時維持原本的 18px，不要變成一條細線。"""
    panel.apply_font_size(6)
    qapp.processEvents()
    assert panel.progress_bar.minimumHeight() >= 18


def test_the_log_box_minimum_follows_the_font_too(panel, qapp):
    """紀錄區整格的最小高度也不能釘死，否則字型放大後標題會壓到進度條上。"""
    box = panel._log_box
    panel.apply_font_size(10)
    small = box.minimumHeight()
    panel.apply_font_size(20)
    qapp.processEvents()
    assert box.minimumHeight() > small
    # 標題 ＋ 進度條 ＋ 兩行紀錄都要放得下。
    title = QFontMetrics(panel.log_title_label.font()).height()
    log_line = QFontMetrics(panel.log_view.font()).height()
    assert box.minimumHeight() >= title + panel.progress_bar.minimumHeight() + log_line * 2


def test_small_fonts_keep_the_original_size(panel, qapp):
    """10pt 時算出來要和原本釘死的 110px 差不多，不然舊版面會突然變樣。"""
    panel.apply_font_size(10)
    qapp.processEvents()
    assert panel._log_box.minimumHeight() == 110
