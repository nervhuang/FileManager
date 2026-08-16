"""左側「作者／團體」面板與其編輯對話框。

清單資料存在 authors.db（見 app/authors_db.py），與 Hermes MCP server 共用同一份。
單擊清單項目即以「名稱＋所有別名」組成 OR 查詢，在右側面板開一個搜尋分頁。
"""

from PyQt5.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QTreeView, QToolBar,
    QDialog, QDialogButtonBox, QLabel, QComboBox, QListWidget, QPushButton,
    QMessageBox, QMenu, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QFrame,
)
from PyQt5.QtGui import (
    QColor, QFont, QIcon, QPainter, QPen, QPixmap, QStandardItem, QStandardItemModel,
)

from . import authors_db

ENTITY_ID_ROLE = Qt.UserRole + 1
ENTITY_TYPE_ROLE = Qt.UserRole + 2

_TYPE_LABEL = {authors_db.AUTHOR: '作者', authors_db.CIRCLE: '團體'}


def _make_glyph_icon(kind):
    """畫出工具列圖示。

    一律畫在 64×64 的畫布上再由 QToolButton 縮到實際大小，高 DPI 下才不會糊。
    筆觸與主工具列的 make_glyph_icon 一致（同樣的墨色與線寬）。
    """
    canvas = 64
    pix = QPixmap(canvas, canvas)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    ink = QColor("#4a4a4a")
    painter.setPen(QPen(ink, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)

    def pt(fx, fy):
        return QPoint(int(canvas * fx), int(canvas * fy))

    def person(cx, scale=1.0):
        """一個人：頭加肩線。"""
        head = int(canvas * 0.15 * scale)
        painter.drawEllipse(int(canvas * cx) - head // 2, int(canvas * (0.30 - 0.07 * scale)),
                            head, head)
        painter.drawArc(int(canvas * (cx - 0.17 * scale)), int(canvas * 0.50),
                        int(canvas * 0.34 * scale), int(canvas * 0.40 * scale), 0, 180 * 16)

    def plus(cx, cy, half=0.11):
        painter.drawLine(pt(cx - half, cy), pt(cx + half, cy))
        painter.drawLine(pt(cx, cy - half), pt(cx, cy + half))

    if kind == 'add_author':
        person(0.40)
        plus(0.78, 0.30)
    elif kind == 'add_circle':
        person(0.30, 0.85)
        person(0.55, 0.85)
        plus(0.82, 0.30, 0.10)
    elif kind == 'edit':
        painter.drawLine(pt(0.22, 0.78), pt(0.68, 0.32))
        painter.setBrush(ink)
        painter.drawPolygon(pt(0.15, 0.85), pt(0.31, 0.79), pt(0.23, 0.68))
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(pt(0.60, 0.22), pt(0.78, 0.40))
    elif kind == 'delete':
        painter.drawLine(pt(0.18, 0.30), pt(0.82, 0.30))
        painter.drawLine(pt(0.40, 0.30), pt(0.42, 0.20))
        painter.drawLine(pt(0.60, 0.30), pt(0.58, 0.20))
        painter.drawLine(pt(0.42, 0.20), pt(0.58, 0.20))
        painter.drawLine(pt(0.26, 0.30), pt(0.32, 0.84))
        painter.drawLine(pt(0.74, 0.30), pt(0.68, 0.84))
        painter.drawLine(pt(0.32, 0.84), pt(0.68, 0.84))
    elif kind == 'refresh':
        rect_margin = int(canvas * 0.22)
        painter.drawArc(rect_margin, rect_margin, canvas - 2 * rect_margin,
                        canvas - 2 * rect_margin, 40 * 16, 280 * 16)
        painter.setBrush(ink)
        painter.drawPolygon(pt(0.70, 0.16), pt(0.86, 0.30), pt(0.66, 0.36))
    elif kind == 'history':
        margin = int(canvas * 0.18)
        painter.drawEllipse(margin, margin, canvas - 2 * margin, canvas - 2 * margin)
        painter.drawLine(pt(0.50, 0.50), pt(0.50, 0.30))
        painter.drawLine(pt(0.50, 0.50), pt(0.66, 0.58))

    painter.end()
    return QIcon(pix)


def _inherit_font(dialog, parent):
    """讓對話框沿用開啟它的面板字型。

    Qt 的字型傳遞在頂層視窗邊界就停了：對話框即使有 parent，也只會拿到應用程式
    預設字型，不會跟著使用者 Ctrl+= 調整過的大小走。"""
    if parent is not None:
        dialog.setFont(parent.font())


class EntityEditDialog(QDialog):
    """新增／編輯單一作者或團體：名稱、類型、別名、關聯對象、備註。"""

    def __init__(self, conn, entity=None, default_type=authors_db.AUTHOR, parent=None):
        super().__init__(parent)
        _inherit_font(self, parent)
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
        row.addWidget(self.name_edit, 1)
        row.addWidget(QLabel('類型：', self))
        self.type_combo = QComboBox(self)
        self.type_combo.addItem(_TYPE_LABEL[authors_db.AUTHOR], authors_db.AUTHOR)
        self.type_combo.addItem(_TYPE_LABEL[authors_db.CIRCLE], authors_db.CIRCLE)
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
        }
        if self._entity:
            entry['id'] = self._entity['id']
        return entry


class RecentChangesDialog(QDialog):
    """變更紀錄：列出誰在什麼時候改了什麼，選一列可還原。"""

    _HEADERS = ('時間', '來源', '動作', '項目', '變更後')

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        _inherit_font(self, parent)
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
                summary = f"{name}（{_TYPE_LABEL.get(after.get('type'), '')}）"
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


class AuthorsPanel(QWidget):
    """左側常駐面板：樹狀顯示團體與作者，單擊即開搜尋分頁。"""

    search_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._conn = authors_db.connect()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 預設與 FileManager 的 _toolbar_icon_size 相同；主視窗建立面板後會再
        # 呼叫 set_toolbar_icon_size 覆寫，確保兩邊永遠一致。
        self._toolbar_icon_size = QSize(64, 64)
        self.toolbar = None
        self.toolbar = self._build_toolbar()
        layout.addWidget(self.toolbar)
        layout.addWidget(self._make_hline())

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText('過濾名稱或別名…')
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self.reload)
        layout.addWidget(self.filter_edit)

        self.tree = QTreeView(self)
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QTreeView.NoEditTriggers)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.clicked.connect(self._on_clicked)
        self.model = QStandardItemModel(self)
        self.tree.setModel(self.model)
        self.tree.selectionModel().selectionChanged.connect(
            lambda *args: self._update_toolbar_state())
        layout.addWidget(self.tree, 1)

        self.reload()

    def _make_hline(self):
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setStyleSheet("color: rgba(127, 127, 127, 0.30);")
        line.setFixedHeight(1)
        return line

    def _build_toolbar(self):
        """面板頂端的圖示工具列，尺寸與中間檔案面板的工具列一致。

        用 QToolBar 而非自排的 QHBoxLayout：面板可以被拉窄（也可整個關閉），
        大圖示排不下時 QToolBar 會自動收成溢位選單，不會把面板的最小寬度撐開。
        """
        bar = QToolBar(self)
        bar.setIconSize(self._toolbar_icon_size)
        bar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        bar.setFloatable(False)
        bar.setMovable(False)
        # 不搶走樹的焦點，否則按下編輯/刪除時 currentIndex 會失去視覺提示
        bar.setFocusPolicy(Qt.NoFocus)

        self._actions = []
        self._selection_actions = []
        specs = (
            ('add_author', '新增作者', lambda: self._add_entity(authors_db.AUTHOR), False),
            ('add_circle', '新增團體', lambda: self._add_entity(authors_db.CIRCLE), False),
            (None, None, None, None),
            ('edit', '編輯選取項目', self._edit_selected, True),
            ('delete', '刪除選取項目（可還原）', self._delete_selected, True),
            (None, None, None, None),
            ('refresh', '重新整理', self.reload, False),
            ('history', '最近變更／還原', self._open_changes, False),
        )
        for kind, text, slot, needs_selection in specs:
            if kind is None:
                bar.addSeparator()
                continue
            action = bar.addAction(_make_glyph_icon(kind), text)
            action.setToolTip(text)
            action.triggered.connect(slot)
            self._actions.append(action)
            if needs_selection:
                self._selection_actions.append(action)
        return bar

    def set_toolbar_icon_size(self, size):
        """與主視窗共用同一個工具列圖示尺寸，不必在兩處各寫一份數字。"""
        self._toolbar_icon_size = size
        if self.toolbar is not None:
            self.toolbar.setIconSize(size)

    def _update_toolbar_state(self):
        """沒選到任何實體時，編輯與刪除停用。"""
        has_selection = self._selected_entity_id() is not None
        for action in self._selection_actions:
            action.setEnabled(has_selection)

    def apply_font_size(self, size):
        """跟隨主視窗的字型大小（Ctrl+= / Ctrl+-）。

        子元件都沒有自己設過字型，理論上會從面板繼承；但明確設一次才能保證
        QTreeView 立刻重算列高、QToolButton 重算寬度，不會等到下次重繪。
        """
        font = QFont(self.font().family(), size)
        self.setFont(font)
        for widget in (self.filter_edit, self.tree):
            widget.setFont(font)
        # 工具列圖示不跟著字型縮放，與中間檔案面板的工具列保持同一尺寸
        self.tree.doItemsLayout()

    # ── 資料 ────────────────────────────────────────────────────────────

    def reload(self, *args):
        """從資料庫重建樹。Hermes 寫入後也是走這裡刷新。"""
        keyword = self.filter_edit.text().strip() or None
        expanded_before = self.model.rowCount() > 0

        entities = authors_db.list_entities(self._conn, keyword=keyword)
        circles = [e for e in entities if e['type'] == authors_db.CIRCLE]
        authors = [e for e in entities if e['type'] == authors_db.AUTHOR]

        self.model.clear()
        root = self.model.invisibleRootItem()

        circle_group = self._make_group_item(f'團體（{len(circles)}）')
        for circle in circles:
            circle_item = self._make_entity_item(circle)
            for author in circle['linked']:
                child = QStandardItem(author['name'])
                child.setEditable(False)
                child.setData(author['id'], ENTITY_ID_ROLE)
                child.setData(author['type'], ENTITY_TYPE_ROLE)
                circle_item.appendRow(child)
            circle_group.appendRow(circle_item)
        root.appendRow(circle_group)

        # 作者一律全列（含已歸屬團體者），標題數字才與實際列出的筆數相符，
        # 也讓任何作者都能不展開團體就直接找到。已歸屬者同時出現在團體底下。
        author_group = self._make_group_item(f'作者（{len(authors)}）')
        for author in authors:
            author_group.appendRow(self._make_entity_item(author))
        root.appendRow(author_group)

        # 有過濾字串時全展開，方便直接看到命中的項目。
        if keyword or not expanded_before:
            self.tree.expandAll()
        else:
            self.tree.expandToDepth(0)
        self._update_toolbar_state()

    def _make_group_item(self, text):
        item = QStandardItem(text)
        item.setEditable(False)
        item.setSelectable(False)
        return item

    def _make_entity_item(self, entity):
        label = entity['name']
        if entity['aliases']:
            label += f"  ({len(entity['aliases'])} 別名)"
        item = QStandardItem(label)
        item.setEditable(False)
        item.setData(entity['id'], ENTITY_ID_ROLE)
        item.setData(entity['type'], ENTITY_TYPE_ROLE)
        tooltip = [f"{_TYPE_LABEL[entity['type']]}：{entity['name']}"]
        if entity['aliases']:
            tooltip.append('別名：' + '、'.join(entity['aliases']))
        if entity['note']:
            tooltip.append('備註：' + entity['note'])
        tooltip.append('來源：' + entity['source'])
        item.setToolTip('\n'.join(tooltip))
        return item

    def _selected_entity_id(self):
        index = self.tree.currentIndex()
        if not index.isValid():
            return None
        return self.model.itemFromIndex(index).data(ENTITY_ID_ROLE)

    # ── 互動 ────────────────────────────────────────────────────────────

    def _on_clicked(self, index):
        item = self.model.itemFromIndex(index)
        entity_id = item.data(ENTITY_ID_ROLE) if item else None
        if entity_id is None:
            return
        entity = authors_db.get_entity(self._conn, entity_id)
        if entity:
            self.search_requested.emit(authors_db.search_terms_for(entity))

    def _show_context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if index.isValid():
            self.tree.setCurrentIndex(index)
        entity_id = self._selected_entity_id()

        menu = QMenu(self)
        menu.addAction('新增作者', lambda: self._add_entity(authors_db.AUTHOR))
        menu.addAction('新增團體', lambda: self._add_entity(authors_db.CIRCLE))
        if entity_id is not None:
            menu.addSeparator()
            menu.addAction('在搜尋面板開分頁', lambda: self._on_clicked(self.tree.currentIndex()))
            menu.addAction('編輯…', self._edit_selected)
            menu.addAction('刪除', self._delete_selected)
        menu.addSeparator()
        menu.addAction('最近變更…', self._open_changes)
        menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def _add_entity(self, type_):
        dialog = EntityEditDialog(self._conn, None, type_, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self._apply_upsert([dialog.result_entry()])

    def _edit_selected(self):
        entity_id = self._selected_entity_id()
        if entity_id is None:
            return
        entity = authors_db.get_entity(self._conn, entity_id)
        if entity is None:
            return
        dialog = EntityEditDialog(self._conn, entity, entity['type'], self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self._apply_upsert([dialog.result_entry()])

    def _apply_upsert(self, entries):
        try:
            authors_db.upsert(self._conn, entries, source=authors_db.SOURCE_LOCAL)
        except authors_db.AuthorsDbError as exc:
            QMessageBox.warning(self, '儲存失敗', str(exc))
            return
        self.reload()

    def _delete_selected(self):
        entity_id = self._selected_entity_id()
        if entity_id is None:
            return
        entity = authors_db.get_entity(self._conn, entity_id)
        if entity is None:
            return
        answer = QMessageBox.question(
            self, '刪除項目',
            f"要刪除「{entity['name']}」嗎？\n（軟刪除，可從「最近變更」還原）",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        authors_db.soft_delete(self._conn, [entity_id], source=authors_db.SOURCE_LOCAL)
        self.reload()

    def _open_changes(self):
        dialog = RecentChangesDialog(self._conn, self)
        dialog.exec_()
        if dialog.reverted:
            self.reload()

    def close_db(self):
        try:
            self._conn.close()
        except Exception:
            pass
