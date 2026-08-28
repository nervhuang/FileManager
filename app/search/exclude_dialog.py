"""排除設定對話框。

排除清單是搜尋域的規則（docs/spec/search.md 的 SRCH-10），對話框跟著它走。
原本住在 `app/file_manager.py` 裡——外殼只該建面板、接訊號、管版面，
一個自成一格的對話框放在那裡沒有理由，也讓外殼的行數棘輪擋住新功能。

只負責收集使用者的選擇，`result_values()` 交出去；套用與存檔是呼叫端的事。
"""

import os

from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QPushButton, QVBoxLayout,
)


class ExcludeSettingsDialog(QDialog):
    """排除設定對話框：勾選是否啟用排除清單，並維護「不列出的目錄」清單。

    被排除的目錄（及其子路徑）不會在中間檔案面板與右側搜尋結果中列出。"""

    def __init__(self, enabled, dirs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("排除設定")
        self.resize(560, 420)

        layout = QVBoxLayout(self)

        self.enable_checkbox = QCheckBox("啟用排除清單", self)
        self.enable_checkbox.setChecked(bool(enabled))
        layout.addWidget(self.enable_checkbox)

        layout.addWidget(QLabel("排除的目錄（這些目錄及其內容不會列出）：", self))

        body = QHBoxLayout()
        self.dir_list = QListWidget(self)
        self.dir_list.addItems(list(dirs))
        body.addWidget(self.dir_list, 1)

        button_col = QVBoxLayout()
        self.add_button = QPushButton("新增資料夾...", self)
        self.remove_button = QPushButton("移除", self)
        self.add_button.clicked.connect(self._on_add_folder)
        self.remove_button.clicked.connect(self._on_remove)
        button_col.addWidget(self.add_button)
        button_col.addWidget(self.remove_button)
        button_col.addStretch(1)
        body.addLayout(button_col)
        layout.addLayout(body)

        self.dir_list.currentRowChanged.connect(self._update_buttons)
        self._update_buttons()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_buttons(self, *args):
        self.remove_button.setEnabled(self.dir_list.currentRow() >= 0)

    def _on_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "選擇要排除的資料夾")
        if not folder:
            return
        folder = os.path.normpath(folder)
        existing = {os.path.normcase(self.dir_list.item(i).text())
                    for i in range(self.dir_list.count())}
        if os.path.normcase(folder) not in existing:
            self.dir_list.addItem(folder)

    def _on_remove(self):
        row = self.dir_list.currentRow()
        if row >= 0:
            self.dir_list.takeItem(row)

    def result_values(self):
        dirs = [self.dir_list.item(i).text() for i in range(self.dir_list.count())]
        return self.enable_checkbox.isChecked(), dirs
