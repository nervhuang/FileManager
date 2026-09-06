"""SHL-18、SHL-18a、SHL-18b、SHL-18c：字型種類可從系統已安裝字型中挑。

判準與 SHL-2a 的字級一樣是「每一個 widget 都要跟上」，只是這裡比的是 family。
唯一的例外是刻意指定等寬的 widget（SHL-18c），判準用 styleHint，不列舉 widget。

長相不驗：字型好不好看、有沒有缺字，offscreen 量不到，標在 SHL-18d [手動]。
"""
import pytest
from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from app import font_family, font_scaling

pytestmark = pytest.mark.gui


# 刻意不從 QFontDatabase 挑：offscreen 平台回報的已安裝字型是空的（實測 0 筆），
# 挑不到就只能整批跳過，等於什麼都沒驗。`QFont.family()` 回的是「要求的名字」，
# 系統裝沒裝那套字型是描繪時才解析的，換句話說這裡驗得到的正是這一層。
# 清單真的來自系統這件事由 QFontComboBox 負責，見下面的對話框測試。
TARGET = 'Fake Test Gothic'


def _some_installed_family(current):
    assert TARGET != current
    return TARGET


def test_shl_18b_family_goes_through_the_same_recursion(qapp):
    """種類與級數同一支 font_scaling.apply，不另開一條路徑。"""
    root = QWidget()
    root.setFont(QFont('Arial', 10))
    layout = QVBoxLayout(root)
    child = QLabel('x', root)
    child.setFont(QFont('Arial', 12))       # 刻意比父層大兩級
    layout.addWidget(child)

    target = _some_installed_family('Arial')
    font_scaling.apply(root, 10, 14, family=target)

    assert root.font().family() == target
    assert child.font().family() == target
    assert root.font().pointSize() == 14
    assert child.font().pointSize() == 16, '相對差距要保留（SHL-2a）'


def test_shl_18c_monospace_widgets_keep_their_family(qapp):
    """執行紀錄靠欄位對齊才讀得快，換成比例字型就對不齊。"""
    root = QWidget()
    root.setFont(QFont('Arial', 10))
    layout = QVBoxLayout(root)
    log = QLabel('x', root)
    mono = QFont('Consolas', 9)
    mono.setStyleHint(QFont.Monospace)
    log.setFont(mono)
    layout.addWidget(log)

    font_scaling.apply(root, 10, 14, family=_some_installed_family('Arial'))

    assert log.font().family() == 'Consolas', '等寬是刻意的，不得被換掉'
    assert log.font().pointSize() == 13, '級數照舊要跟上'


def test_shl_18_every_widget_tracks_the_family(main_window, qapp):
    target = _some_installed_family(main_window.font().family())
    font_scaling.apply_to_window(main_window, font_scaling.current_size(main_window),
                                 family=target)
    qapp.processEvents()

    stale = []
    for widget in [main_window] + main_window.findChildren(QWidget):
        font = widget.font()
        if font.styleHint() == QFont.Monospace:
            continue
        if font.family() != target:
            stale.append(f'{widget.__class__.__name__}: {font.family()}')
    assert not stale, ('以下 widget 沒有跟上字型種類（SHL-18）：\n  '
                       + '\n  '.join(sorted(set(stale))))


def test_shl_18_dialog_offers_installed_fonts_and_a_way_back(main_window, qapp):
    """SHL-18a：選到看不清楚的字型時，只靠一個按鈕就能還原成系統預設。"""
    from PyQt5.QtWidgets import QFontComboBox

    from app import font_dialog

    dialog = font_dialog.FontDialog('', main_window)
    assert dialog.findChildren(QFontComboBox), '清單要來自系統已安裝字型'

    target = _some_installed_family(main_window.font().family())
    dialog.set_family(target)
    assert dialog.selected_family() == target

    dialog.reset_to_system_default()
    assert dialog.selected_family() == '', '空字串＝系統預設'
    dialog.deleteLater()


def test_shl_18_saved_family_is_restored_on_startup(qapp, tmp_path, monkeypatch):
    """存進 config.ini 的字型，下次啟動就是這個字型。"""
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('FILEMANAGER_HOME', str(home))

    from app.settings import ConfigStore
    target = _some_installed_family(qapp.font().family())
    font_family.save(target, ConfigStore.load(str(home / 'config.ini')))

    from app.file_manager import FileManager
    window = FileManager()
    try:
        assert window.font().family() == target
        assert window.listView.font().family() == target
    finally:
        window.close()
        qapp.processEvents()
