"""變更紀錄對話框：列出誰在什麼時候改了什麼，選一列可還原（AUT-3）。

與 edit_dialog.py 一起從 panel.py 拆出來，理由見那個檔案。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .. import font_scaling
from . import db as authors_db
from .labels import TYPE_LABEL


class RecentChangesDialog(QDialog):
    """變更紀錄：列出誰在什麼時候改了什麼，選一列可還原。"""

    _HEADERS = ('時間', '來源', '動作', '項目', '變更後')

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        font_scaling.inherit(self, parent)
        self._conn = conn
        self.setWindowTitle('最近變更')
        self.resize(760, 460)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('選一列按「還原」，即可把該筆變更退回到它發生前的狀態。', self))

        self.table = QTableWidget(0, len(self._HEADERS), self)
        self.table.setHorizontalHeaderLabels(self._HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        self.revert_button = QPushButton('還原', self)
        buttons.addButton(self.revert_button, QDialogButtonBox.ActionRole)
        self.revert_button.clicked.connect(self._on_revert)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.reverted = False
        self.reload()

    def reload(self):
        changes = authors_db.recent_changes(self._conn, 200)
        self.table.setRowCount(len(changes))
        for row, change in enumerate(changes):
            after = change['after'] or {}
            before = change['before'] or {}
            name = after.get('name') or before.get('name') or ''
            summary = ''
            if after:
                summary = f"{name}（{TYPE_LABEL.get(after.get('type'), '')}）"
                if after.get('aliases'):
                    summary += ' 別名：' + '、'.join(after['aliases'])
                if after.get('deleted'):
                    summary += ' [已刪除]'
            values = (change['ts'], change['source'], change['op'], name, summary)
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(Qt.UserRole, change['id'])
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)

    def _on_revert(self):
        row = self.table.currentRow()
        if row < 0:
            return
        change_id = self.table.item(row, 0).data(Qt.UserRole)
        try:
            authors_db.revert_change(self._conn, change_id)
        except authors_db.AuthorsDbError as exc:
            QMessageBox.warning(self, '還原失敗', str(exc))
            return
        self.reverted = True
        self.reload()
