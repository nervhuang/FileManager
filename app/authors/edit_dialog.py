"""新增／編輯單一作者或團體的對話框。規格見 docs/spec/authors.md 的 AUT-15 到 AUT-21。

從 panel.py 拆出來：那個檔案原本一份裝著面板、樹與兩個對話框，已經逼近 600 行
上限。對話框與面板之間只有「開啟它、讀 result_entry()」這一條線，是最好切的地方。
"""

from PyQt5.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMessageBox, QPushButton, QVBoxLayout,
)

from .. import font_scaling
from . import db as authors_db
from .labels import TYPE_LABEL
from .names import parse_circle_author


class EntityEditDialog(QDialog):
    """新增／編輯單一作者或團體：名稱、類型、別名、關聯對象、備註。"""

    def __init__(self, conn, entity=None, default_type=authors_db.AUTHOR, parent=None):
        super().__init__(parent)
        font_scaling.inherit(self, parent)
        self._conn = conn
        self._entity = entity
        self.setWindowTitle('編輯項目' if entity else '新增項目')
        self.resize(520, 480)

        # 每個「清單＋輸入框」欄位的提交函式，按確定時一併沖出未按 Enter 的殘留文字
        self._list_committers = []

        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel('名稱：', self))
        self.name_edit = QLineEdit(entity['name'] if entity else '', self)
        if entity is None:
            # 只在「新增」時攔截：貼上「團體 (作者)」格式就自動拆成兩筆並建立關聯。
            # 編輯既有項目時名稱本來就可能含括號，不應該被這條規則誤拆。
            self.name_edit.editingFinished.connect(self._maybe_split_pasted_name)
        row.addWidget(self.name_edit, 1)
        row.addWidget(QLabel('類型：', self))
        self.type_combo = QComboBox(self)
        self.type_combo.addItem(TYPE_LABEL[authors_db.AUTHOR], authors_db.AUTHOR)
        self.type_combo.addItem(TYPE_LABEL[authors_db.CIRCLE], authors_db.CIRCLE)
        current_type = entity['type'] if entity else default_type
        self.type_combo.setCurrentIndex(self.type_combo.findData(current_type))
        self.type_combo.currentIndexChanged.connect(self._refresh_link_hint)
        row.addWidget(self.type_combo)
        layout.addLayout(row)

        layout.addWidget(QLabel('別名（搜尋時會與名稱一起以 OR 查詢）：', self))
        self.alias_list, alias_input, alias_row = self._make_list_editor('新增別名後按 Enter')
        if entity:
            self.alias_list.addItems(entity['aliases'])
        layout.addLayout(alias_row)

        self.link_label = QLabel('', self)
        layout.addWidget(self.link_label)
        self.link_list, link_input, link_row = self._make_list_editor('輸入名稱後按 Enter；不存在會自動建立')
        if entity:
            self.link_list.addItems([item['name'] for item in entity['linked']])
        layout.addLayout(link_row)
        self._refresh_link_hint()

        english_row = QHBoxLayout()
        english_row.addWidget(QLabel('英文名稱：', self))
        self.english_name_edit = QLineEdit(entity['english_name'] if entity else '', self)
        self.english_name_edit.setPlaceholderText('網站查詢用，與本機檔案搜尋無關（可留空）')
        english_row.addWidget(self.english_name_edit, 1)
        layout.addLayout(english_row)

        note_row = QHBoxLayout()
        note_row.addWidget(QLabel('備註：', self))
        self.note_edit = QLineEdit(entity['note'] if entity else '', self)
        note_row.addWidget(self.note_edit, 1)
        layout.addLayout(note_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.name_edit.setFocus()

    def _make_list_editor(self, placeholder):
        """回傳 (清單, 輸入框, 版面)：輸入框按 Enter 加入，右側按鈕移除選取項。"""
        container = QVBoxLayout()
        list_widget = QListWidget(self)

        body = QHBoxLayout()
        body.addWidget(list_widget, 1)
        remove_button = QPushButton('移除', self)
        column = QVBoxLayout()
        column.addWidget(remove_button)
        column.addStretch(1)
        body.addLayout(column)
        container.addLayout(body)

        line = QLineEdit(self)
        line.setPlaceholderText(placeholder)
        container.addWidget(line)

        def _add():
            text = line.text().strip()
            existing = {list_widget.item(i).text() for i in range(list_widget.count())}
            if text and text not in existing:
                list_widget.addItem(text)
            line.clear()

        def _remove():
            row = list_widget.currentRow()
            if row >= 0:
                list_widget.takeItem(row)

        line.returnPressed.connect(_add)
        remove_button.clicked.connect(_remove)
        self._list_committers.append(_add)
        return list_widget, line, container

    def _refresh_link_hint(self):
        if self.type_combo.currentData() == authors_db.AUTHOR:
            self.link_label.setText('所屬團體：')
        else:
            self.link_label.setText('旗下作者：')

    def _maybe_split_pasted_name(self):
        """名稱欄符合「團體 (作者[、作者…])」格式時，自動拆成團體名 + 旗下作者關聯。"""
        parsed = parse_circle_author(self.name_edit.text())
        if parsed is None:
            return
        circle_name, author_names = parsed
        self.name_edit.setText(circle_name)
        self.type_combo.setCurrentIndex(self.type_combo.findData(authors_db.CIRCLE))
        existing = {self.link_list.item(i).text() for i in range(self.link_list.count())}
        for author_name in author_names:
            if author_name not in existing:
                self.link_list.addItem(author_name)
                existing.add(author_name)

    def _on_accept(self):
        # 使用者常在別名／關聯欄打完字就直接按確定，沒按 Enter。先把殘留文字
        # 收進清單，否則那行字會被無聲丟掉（關聯漏掉時，項目就會變成孤立實體）。
        for commit in self._list_committers:
            commit()
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, '名稱不可空白', '請輸入名稱。')
            return
        self.accept()

    def result_entry(self):
        def _items(widget):
            return [widget.item(i).text() for i in range(widget.count())]

        entry = {
            'name': self.name_edit.text().strip(),
            'type': self.type_combo.currentData(),
            'aliases': _items(self.alias_list),
            'linked_names': _items(self.link_list),
            'note': self.note_edit.text().strip(),
            'english_name': self.english_name_edit.text().strip(),
        }
        if self._entity:
            entry['id'] = self._entity['id']
        return entry
