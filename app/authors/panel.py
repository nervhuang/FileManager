"""左側「作者／團體」面板。

清單資料存在 authors.db（見 app/authors/db.py），與 Hermes MCP server 共用同一份。
單擊清單項目即以「名稱＋所有別名」組成 OR 查詢，在右側面板開一個搜尋分頁。

兩個對話框在 edit_dialog.py 與 changes_dialog.py。
"""


from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLineEdit, QTreeView, QToolBar, QDialog,
    QMessageBox, QMenu, QFrame,
)
from PyQt5.QtGui import QFont, QStandardItem, QStandardItemModel

from . import db as authors_db
from ..icons import make_refresh_icon, make_trash_icon   # 外殼共用的那兩顆
from .changes_dialog import RecentChangesDialog
from .edit_dialog import EntityEditDialog
from .icons import make_glyph_icon
from .labels import TYPE_LABEL

ENTITY_ID_ROLE = Qt.UserRole + 1
ENTITY_TYPE_ROLE = Qt.UserRole + 2


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

        # 「僅顯示無英文名稱」檢視。刻意不寫進設定檔（AUT-24）：開機看到清單
        # 默默少一半，第一個反應會是資料庫壞了，不是「喔我上次切過」。
        self._missing_english_only = False

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
        # 檔案面板的操作鈕是「圖示＋文字」；這裡改成文字在圖示下方，因為側邊
        # 面板寬度有限，文字並排會讓六顆鈕要近 900px 才排得下。
        bar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        bar.setFloatable(False)
        bar.setMovable(False)
        # 不搶走樹的焦點，否則按下編輯/刪除時 currentIndex 會失去視覺提示
        bar.setFocusPolicy(Qt.NoFocus)
        # 與檔案面板操作鈕相同的文字級數，避免頭大身小
        font = bar.font()
        font.setPointSize(14)
        bar.setFont(font)

        self._actions = []
        self._selection_actions = []
        specs = (
            (make_glyph_icon('add_author'), '新增作者', '新增作者',
             lambda: self._add_entity(authors_db.AUTHOR), False),
            (make_glyph_icon('add_circle'), '新增團體', '新增團體',
             lambda: self._add_entity(authors_db.CIRCLE), False),
            (None, None, None, None, None),
            (make_glyph_icon('edit'), '編輯', '編輯選取項目', self._edit_selected, True),
            (make_trash_icon(self._toolbar_icon_size), '刪除',
             '刪除選取項目（可還原）', self._delete_selected, True),
            (None, None, None, None, None),
            (make_refresh_icon(self._toolbar_icon_size), '重新整理',
             '重新整理', self.reload, False),
            (make_glyph_icon('history'), '變更', '最近變更／還原', self._open_changes, False),
        )
        for icon, text, tooltip, slot, needs_selection in specs:
            if icon is None:
                bar.addSeparator()
                continue
            action = bar.addAction(icon, text)
            action.setToolTip(tooltip)
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

        entities = authors_db.list_entities(
            self._conn, keyword=keyword,
            missing_english_only=self._missing_english_only)
        circles = [e for e in entities if e['type'] == authors_db.CIRCLE]
        authors = [e for e in entities if e['type'] == authors_db.AUTHOR]

        self.model.clear()
        root = self.model.invisibleRootItem()

        # 篩選開著時，團體底下的作者也各自判斷（AUT-22b）。`authors` 這時剛好
        # 就是「沒填英文名的作者」那一份清單，用它的 id 過濾，不必為每個團體
        # 再查一次資料庫。
        listed_ids = ({a['id'] for a in authors} if self._missing_english_only
                      else None)

        circle_group = self._make_group_item(self._group_title('團體', len(circles)))
        for circle in circles:
            circle_item = self._make_entity_item(circle)
            for author in circle['linked']:
                if listed_ids is not None and author['id'] not in listed_ids:
                    continue
                child = QStandardItem(author['name'])
                child.setEditable(False)
                child.setData(author['id'], ENTITY_ID_ROLE)
                child.setData(author['type'], ENTITY_TYPE_ROLE)
                circle_item.appendRow(child)
            circle_group.appendRow(circle_item)
        root.appendRow(circle_group)

        # 作者一律全列（含已歸屬團體者），標題數字才與實際列出的筆數相符，
        # 也讓任何作者都能不展開團體就直接找到。已歸屬者同時出現在團體底下。
        author_group = self._make_group_item(self._group_title('作者', len(authors)))
        for author in authors:
            author_group.appendRow(self._make_entity_item(author))
        root.appendRow(author_group)

        # 有過濾字串時全展開，方便直接看到命中的項目。
        if keyword or not expanded_before:
            self.tree.expandAll()
        else:
            self.tree.expandToDepth(0)
        self._update_toolbar_state()

    def _group_title(self, label, count):
        """群組標題。篩選開著時必須說出來（AUT-23）——少了這個提示，清單少一半
        看起來就是資料掉了。"""
        suffix = '，僅無英文' if self._missing_english_only else ''
        return f'{label}（{count}{suffix}）'

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
        tooltip = [f"{TYPE_LABEL[entity['type']]}：{entity['name']}"]
        if entity['aliases']:
            tooltip.append('別名：' + '、'.join(entity['aliases']))
        if entity['english_name']:
            tooltip.append('英文名稱：' + entity['english_name'])
        if entity['note']:
            tooltip.append('備註：' + entity['note'])
        tooltip.append('來源：' + entity['source'])
        item.setToolTip('\n'.join(tooltip))
        return item

    # ── 檢視 ────────────────────────────────────────────────────────────

    def missing_english_only(self):
        return self._missing_english_only

    def set_missing_english_only(self, value):
        """切換「僅顯示無英文名稱」。整個面板一個狀態（AUT-22a）。"""
        value = bool(value)
        if value == self._missing_english_only:
            return
        self._missing_english_only = value
        self.reload()

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
        self._build_context_menu(pos).exec_(self.tree.viewport().mapToGlobal(pos))

    def _build_context_menu(self, pos):
        """組出 `pos` 位置的右鍵選單。分開一支是為了測得到選單內容——
        `exec_()` 會卡住不返回，測試沒辦法在它跳出來之後再去讀。"""
        index = self.tree.indexAt(pos)
        if index.isValid():
            self.tree.setCurrentIndex(index)
        entity_id = self._selected_entity_id()

        menu = QMenu(self)
        if self._is_group_index(index):
            # 檢視切換掛在最上層節點上（AUT-22）：那裡是「這一整群」的位置，
            # 而這個開關影響的正是一整群。
            for text, value in (('全部', False), ('僅顯示無英文名稱', True)):
                action = menu.addAction(text)
                action.setCheckable(True)
                action.setChecked(self._missing_english_only == value)
                action.triggered.connect(
                    lambda _checked, v=value: self.set_missing_english_only(v))
            menu.addSeparator()
        menu.addAction('新增作者', lambda: self._add_entity(authors_db.AUTHOR))
        menu.addAction('新增團體', lambda: self._add_entity(authors_db.CIRCLE))
        if entity_id is not None:
            menu.addSeparator()
            menu.addAction('在搜尋面板開分頁', lambda: self._on_clicked(self.tree.currentIndex()))
            menu.addAction('編輯…', self._edit_selected)
            menu.addAction('刪除', self._delete_selected)
        menu.addSeparator()
        menu.addAction('最近變更…', self._open_changes)
        return menu

    def _is_group_index(self, index):
        """是不是「團體」「作者」那兩個最上層節點。"""
        if not index.isValid() or index.parent().isValid():
            return False
        item = self.model.itemFromIndex(index)
        return item is not None and item.data(ENTITY_ID_ROLE) is None

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
