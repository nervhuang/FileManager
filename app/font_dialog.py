"""「字型」對話框：從系統已安裝的字型裡挑一種給整個應用程式用。

清單交給 `QFontComboBox`——它直接向系統要已安裝的字型，這個程式不自備清單，
也就不會有「清單與系統不同步」這種只在別人機器上發生的問題。

自己讀檔、自己存檔，不經過主視窗（docs/spec/settings.md 的 SET-16）。
"""

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QFontComboBox, QFormLayout, QLabel,
)

from . import font_family, font_scaling

# 預覽刻意中日英數混排（SHL-18d）：藏書檔名多是日文，選到缺 CJK 字的字型會滿
# 畫面豆腐框，而只看 "AaBbCc" 完全看不出來。
PREVIEW_TEXT = '同人誌 コミック 作者名 Doujinshi 0123'


class FontDialog(QDialog):
    def __init__(self, current_family='', parent=None):
        super().__init__(parent)
        self.setWindowTitle('字型')
        # Qt 在頂層視窗邊界停止字型傳播，對話框得自己套一次（AUT-14）。
        if parent is not None:
            self.setFont(parent.font())

        self._family = ''
        layout = QFormLayout(self)

        self.combo = QFontComboBox(self)
        self.combo.currentFontChanged.connect(self._on_font_picked)
        layout.addRow('字型：', self.combo)

        self.preview = QLabel(PREVIEW_TEXT, self)
        self.preview.setMinimumHeight(48)
        layout.addRow('預覽：', self.preview)

        note = QLabel('只換字型種類；大小仍由 Ctrl+= / Ctrl+- 調整。\n'
                      '「系統預設」還原成程式啟動時系統給的那一套。', self)
        note.setWordWrap(True)
        layout.addRow(note)

        # 「系統預設」給的是一條退路：選到缺字或難讀的字型時，畫面正處於看不清楚
        # 的狀態，此時要能只按一個鈕還原，而不是去手改 config.ini（SHL-18a）。
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Reset,
            self)
        buttons.button(QDialogButtonBox.Reset).setText('系統預設')
        buttons.button(QDialogButtonBox.Reset).clicked.connect(self.reset_to_system_default)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.set_family(current_family)

    # ── 狀態 ────────────────────────────────────────────────────────────

    def selected_family(self):
        """目前選的字型；空字串代表系統預設。"""
        return self._family

    def set_family(self, family):
        """`family` 為空字串時選回系統預設。

        `_family` 是這個對話框的狀態，不是向 combo 問來的：combo 只認得系統
        真的裝了的字型，設定檔裡可能留著一個這台機器沒有的名字（換機器、
        字型被移除），那個名字仍然該原樣顯示並保留，直到使用者自己改掉。
        """
        family = (family or '').strip()
        self.combo.setCurrentFont(QFont(family or font_scaling.system_default_family()))
        self._family = family
        self._update_preview()

    def reset_to_system_default(self):
        self.set_family('')

    # ── 內部 ────────────────────────────────────────────────────────────

    def _on_font_picked(self, font):
        self._family = font.family()
        self._update_preview()

    def _update_preview(self):
        family = self._family or font_scaling.system_default_family()
        # 預覽比內文大幾級才看得出字面差異，級數不影響任何設定。
        self.preview.setFont(QFont(family, max(font_scaling.MIN_POINT_SIZE,
                                               self.font().pointSize() + 4)))


def open_dialog(window):
    """開啟對話框；按下確定就存檔並立刻套用到整個應用程式。

    回傳實際套用的字型（取消時回 None），供測試與呼叫端判斷。
    """
    dialog = FontDialog(font_family.load(), window)
    if dialog.exec_() != QDialog.Accepted:
        return None
    family = font_family.save(dialog.selected_family())
    font_scaling.apply_to_window(window, font_scaling.current_size(window), family)
    return family
