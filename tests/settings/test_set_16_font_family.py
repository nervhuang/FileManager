"""SET-16：字型種類（`[General] font_family`）由 app/font_family.py 自己讀寫。

與 SET-15 的筆數上限同一套作法：即讀即存，不經過主視窗的 save_config。
不依賴 Qt——這一層只回答「檔案裡寫了什麼、拿不到時該用什麼」。
"""
import pytest

from app import font_family
from app.settings import ConfigStore

pytestmark = pytest.mark.logic


def _store(tmp_path):
    return ConfigStore.load(str(tmp_path / 'config.ini'))


def test_set_16_default_is_system_font(tmp_path):
    """沒有這個鍵＝用系統預設，回空字串。"""
    assert font_family.load(_store(tmp_path)) == ''


def test_set_16_round_trip(tmp_path):
    path = str(tmp_path / 'config.ini')
    font_family.save('Meiryo', ConfigStore.load(path))
    assert font_family.load(ConfigStore.load(path)) == 'Meiryo'


def test_set_16_save_keeps_other_keys(tmp_path):
    """自己讀寫不得洗掉別人的鍵，否則主視窗與對話框會互相覆蓋。"""
    path = str(tmp_path / 'config.ini')
    store = ConfigStore.load(path)
    store.set('General', 'font_size', 18)
    store.save()

    font_family.save('Meiryo', ConfigStore.load(path))

    after = ConfigStore.load(path)
    assert after.get_int('General', 'font_size', 10) == 18
    assert font_family.load(after) == 'Meiryo'


def test_set_16_blank_means_system_default(tmp_path):
    """存空字串是「還原成系統預設」，不是壞值。"""
    path = str(tmp_path / 'config.ini')
    font_family.save('Meiryo', ConfigStore.load(path))
    font_family.save('', ConfigStore.load(path))
    assert font_family.load(ConfigStore.load(path)) == ''


def test_set_16_does_not_need_qt():
    """設定層不得依賴 Qt：MCP server 與 CLI 沒有 QApplication。"""
    import subprocess
    import sys
    code = ('import app.font_family, sys; '
            "sys.exit(0 if 'PyQt5' not in sys.modules else 1)")
    assert subprocess.call([sys.executable, '-c', code]) == 0
