"""「選項 → 更新檢查筆數…」的對話框與選單入口。見 docs/spec/settings.md 的 SET-15。

offscreen 量得到選單項目在不在、spinbox 的範圍與交出來的值；
版面好不好看量不到，那是 [手動]。
"""
import pytest

from PyQt5.QtWidgets import QApplication

from app.checker import limits, limits_dialog

pytestmark = pytest.mark.gui


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_spins_are_clamped_to_the_allowed_range(app):
    dialog = limits_dialog.LimitsDialog(limits.DEFAULTS)
    for spin in (dialog.first_run_spin, dialog.max_items_spin):
        assert spin.minimum() == limits.MINIMUM
        assert spin.maximum() == limits.MAXIMUM
    assert dialog.result_values() == limits.DEFAULTS


def test_two_separate_numbers(app):
    """首掃與回溯分開設：兩者成本不同，合成一個數字會讓首掃時間平白翻倍。"""
    dialog = limits_dialog.LimitsDialog(limits.Limits(50, 200))
    assert dialog.first_run_spin.value() == 50
    assert dialog.max_items_spin.value() == 200
    dialog.first_run_spin.setValue(75)
    assert dialog.result_values() == limits.Limits(75, 200)


def test_option_menu_has_the_entry(app):
    """入口在「選項」下拉功能表，與排除設定並列。"""
    from app.file_manager import FileManager

    window = FileManager()
    try:
        texts = [action.text() for action in window.action_checker_limits.parent().actions()]
        assert '更新檢查筆數(&C)…' in texts
        assert '排除設定(&E)…' in texts
    finally:
        window.close()
