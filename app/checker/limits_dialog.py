"""「更新檢查筆數」對話框：調整每輪要抓最新幾筆。

兩個數字分開設，因為它們的成本不同：首次掃描是每位作者都要付的固定開銷
（427 位 × 每多一頁 ≈ 多跑一輪 25–35 分鐘），回溯上限只有在該作者真的發了
那麼多本時才會用到。合成一個數字會讓「想追回久違的作者」直接把首掃時間翻倍。

自己讀檔、自己存檔，不經過主視窗：`ConfigStore.save()` 保留不認得的鍵，
主視窗稍後存自己那批鍵時不會互相覆蓋（docs/spec/settings.md 的 SET-15）。
"""

from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QSpinBox,
)

from . import limits as limits_settings


class LimitsDialog(QDialog):
    def __init__(self, limits, parent=None):
        super().__init__(parent)
        self.setWindowTitle('更新檢查筆數')

        layout = QFormLayout(self)
        self.first_run_spin = self._make_spin(limits.first_run)
        self.max_items_spin = self._make_spin(limits.max_items)
        layout.addRow('首次掃描取樣筆數：', self.first_run_spin)
        layout.addRow('每輪最多回溯筆數：', self.max_items_spin)

        # 站方一頁 25 筆，數字不是 25 的倍數也只是最後一頁少收幾筆，不會出錯，
        # 但使用者該知道每加 25 就多一次請求——那是整輪時間的來源。
        note = QLabel(
            f'每 {limits_settings.MINIMUM} 筆為一頁請求，範圍 '
            f'{limits_settings.MINIMUM}–{limits_settings.MAXIMUM}。\n'
            '首次掃描的筆數每位作者都會付，調大會等比拉長整輪時間；\n'
            '回溯筆數只有在該作者真的發了那麼多本時才會用到。', self)
        note.setWordWrap(True)
        layout.addRow(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _make_spin(self, value):
        spin = QSpinBox(self)
        spin.setRange(limits_settings.MINIMUM, limits_settings.MAXIMUM)
        spin.setSingleStep(limits_settings.MINIMUM)
        spin.setValue(value)
        spin.setSuffix(' 筆')
        return spin

    def result_values(self):
        return limits_settings.Limits(self.first_run_spin.value(),
                                      self.max_items_spin.value())


def open_dialog(parent=None):
    """開對話框，按確定就存檔。回傳存下來的值；取消回 None。"""
    dialog = LimitsDialog(limits_settings.load(), parent)
    if dialog.exec_() != QDialog.Accepted:
        return None
    return limits_settings.save(dialog.result_values())
