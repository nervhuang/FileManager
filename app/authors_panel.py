"""左側「作者／團體」面板與其編輯對話框。

清單資料存在 authors.db（見 app/authors_db.py），與 Hermes MCP server 共用同一份。
單擊清單項目即以「名稱＋所有別名」組成 OR 查詢，在右側面板開一個搜尋分頁。
"""

import re

from PyQt5.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QTreeView, QToolBar,
    QDialog, QDialogButtonBox, QLabel, QComboBox, QListWidget, QPushButton,
    QMessageBox, QMenu, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QFrame,
)
from PyQt5.QtWidgets import QApplication, QStyle
from PyQt5.QtGui import (
    QColor, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap,
    QStandardItem, QStandardItemModel,
)

from . import authors_db
from .widgets import make_refresh_icon

ENTITY_ID_ROLE = Qt.UserRole + 1
ENTITY_TYPE_ROLE = Qt.UserRole + 2

_TYPE_LABEL = {authors_db.AUTHOR: '作者', authors_db.CIRCLE: '團體'}

# 同人圈慣用的「團體 (作者)」標記，外層方括號可有可無，括號可半形或全形；
# 用 (?:...)$ 錨定在字串尾端取「最後一組括號」，團體名本身帶括號時才不會錯拆。
# 括號內可能不只一位作者，用頓號／逗號分隔（如「和泉、冷泉」），數量不限。
_CIRCLE_AUTHOR_RE = re.compile(
    r'^\[?\s*(?P<circle>.+?)\s*[(（]\s*(?P<authors>[^()（）]+?)\s*[)）]\s*\]?$'
)
_AUTHOR_SPLIT_RE = re.compile(r'[、,，]\s*')


def _parse_circle_author(text):
    """把「團體 (作者[、作者…])」或「[…]」拆成 (團體名, [作者名, …])；不符合格式回傳 None。"""
    match = _CIRCLE_AUTHOR_RE.match(text.strip())
    if not match:
        return None
    circle = match.group('circle').strip()
    authors = [a.strip() for a in _AUTHOR_SPLIT_RE.split(match.group('authors')) if a.strip()]
    if not circle or not authors:
        return None
    return circle, authors


# 與中間檔案面板工具列共用的色盤：實心填色 + 深色描邊 + 高光，
# 而非單純的線稿，這樣兩條工具列擺在一起才是同一種視覺語彙。
_INK = QColor("#4a4a4a")
_BODY = QColor("#7aa8dc")          # 人形主體
_BODY_DARK = QColor("#4d7cb0")
_BODY_BACK = QColor("#b8cfe8")     # 後排人形（較淡，製造前後層次）
_EDGE = QColor("#37567a")          # 人形描邊
_SKIN = QColor("#f5cfa4")
_SKIN_EDGE = QColor("#b3844f")
_GREEN = QColor("#2fb24a")         # 新增徽章
_GREEN_DARK = QColor("#1d7a33")
_WOOD_LIGHT = QColor("#fff1a8")    # 鉛筆木身，沿用資料夾圖示的黃
_WOOD = QColor("#f2c23f")
_WOOD_EDGE = QColor("#8f5c00")
_METAL = QColor("#c9ccd1")
_FACE = QColor("#fbfbfb")          # 時鐘面
_RIM = QColor("#6b6b6b")
_ACCENT = QColor("#2f66d0")


def _make_glyph_icon(kind):
    """畫出工具列圖示（64×64 畫布，由 QToolButton 縮到實際大小）。

    風格對齊中間檔案面板的 make_up_folder_icon／make_glyph_icon：實心填色、
    深色描邊、局部高光，不是純線稿。
    """
    canvas = 64
    pix = QPixmap(canvas, canvas)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    def pt(fx, fy):
        return QPoint(int(canvas * fx), int(canvas * fy))

    def px(f):
        return int(canvas * f)

    def filled(brush, edge, width=1.6):
        p.setBrush(brush)
        p.setPen(QPen(edge, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def person(cx, cy_head, scale, body, edge, skin=_SKIN, skin_edge=_SKIN_EDGE):
        """一個人形：頭 + 肩胸。cx 為中心、scale 控制大小。"""
        head_r = 0.115 * scale
        filled(skin, skin_edge)
        p.drawEllipse(px(cx - head_r), px(cy_head - head_r),
                      px(head_r * 2), px(head_r * 2))
        # 肩胸：上緣為半圓，下緣切平
        grad = QLinearGradient(pt(cx, cy_head + head_r), pt(cx, cy_head + 0.46 * scale))
        grad.setColorAt(0.0, body.lighter(112))
        grad.setColorAt(1.0, body)
        filled(grad, edge)
        left, right = cx - 0.20 * scale, cx + 0.20 * scale
        top, bottom = cy_head + head_r * 1.15, cy_head + 0.44 * scale
        p.drawChord(px(left), px(top), px(right - left), px((bottom - top) * 2), 0, 180 * 16)
        p.setPen(QPen(body.lighter(150), 1.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pt(cx - 0.10 * scale, top + 0.05 * scale),
                   pt(cx - 0.13 * scale, bottom - 0.02 * scale))

    def plus_badge(cx, cy, r=0.19):
        filled(_GREEN, _GREEN_DARK, 1.8)
        p.drawEllipse(px(cx - r), px(cy - r), px(r * 2), px(r * 2))
        p.setPen(QPen(QColor("#ffffff"), 3.4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pt(cx - r * 0.52, cy), pt(cx + r * 0.52, cy))
        p.drawLine(pt(cx, cy - r * 0.52), pt(cx, cy + r * 0.52))

    if kind == 'add_author':
        person(0.42, 0.32, 1.15, _BODY, _EDGE)
        plus_badge(0.76, 0.76)

    elif kind == 'add_circle':
        person(0.30, 0.30, 0.88, _BODY_BACK, _EDGE.lighter(135))
        person(0.58, 0.28, 0.88, _BODY_BACK, _EDGE.lighter(135))
        person(0.44, 0.42, 1.00, _BODY, _EDGE)
        plus_badge(0.78, 0.78, 0.17)

    elif kind == 'edit':
        # 鉛筆：木身 + 金屬套環 + 筆尖，斜置由左下指向右上
        body_pts = [pt(0.30, 0.86), pt(0.22, 0.70), pt(0.66, 0.26), pt(0.78, 0.40)]
        grad = QLinearGradient(pt(0.22, 0.70), pt(0.40, 0.90))
        grad.setColorAt(0.0, _WOOD_LIGHT)
        grad.setColorAt(1.0, _WOOD)
        filled(grad, _WOOD_EDGE)
        p.drawPolygon(*body_pts)
        filled(_METAL, _WOOD_EDGE, 1.3)
        p.drawPolygon(pt(0.62, 0.22), pt(0.74, 0.36), pt(0.80, 0.30), pt(0.68, 0.16))
        # 筆尖與石墨
        filled(_WOOD_LIGHT, _WOOD_EDGE, 1.3)
        p.drawPolygon(pt(0.14, 0.92), pt(0.22, 0.70), pt(0.30, 0.86))
        filled(_INK, _INK, 1.0)
        p.drawPolygon(pt(0.14, 0.92), pt(0.185, 0.80), pt(0.235, 0.865))
        p.setPen(QPen(QColor("#ffffff"), 1.4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pt(0.29, 0.68), pt(0.68, 0.30))

    elif kind == 'history':
        # 時鐘 + 逆時針箭頭（還原的意象）
        margin = 0.20
        filled(_FACE, _RIM, 3.0)
        p.drawEllipse(px(margin), px(margin), px(1 - margin * 2), px(1 - margin * 2))
        p.setPen(QPen(_INK, 3.0, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pt(0.50, 0.50), pt(0.50, 0.32))
        p.drawLine(pt(0.50, 0.50), pt(0.65, 0.57))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_ACCENT, 3.4, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(px(0.07), px(0.07), px(0.52), px(0.52), 30 * 16, 200 * 16)
        filled(_ACCENT, _ACCENT, 1.0)
        p.drawPolygon(pt(0.04, 0.26), pt(0.22, 0.24), pt(0.11, 0.40))

    p.end()
    return QIcon(pix)


def _standard_icon(pixmap_enum):
    """刪除與重新整理直接沿用系統圖示，與檔案面板工具列同一顆。"""
    return QApplication.style().standardIcon(pixmap_enum)


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
        if entity is None:
            # 只在「新增」時攔截：貼上「團體 (作者)」格式就自動拆成兩筆並建立關聯。
            # 編輯既有項目時名稱本來就可能含括號，不應該被這條規則誤拆。
            self.name_edit.editingFinished.connect(self._maybe_split_pasted_name)
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

    def _maybe_split_pasted_name(self):
        """名稱欄符合「團體 (作者[、作者…])」格式時，自動拆成團體名 + 旗下作者關聯。"""
        parsed = _parse_circle_author(self.name_edit.text())
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
            (_make_glyph_icon('add_author'), '新增作者', '新增作者',
             lambda: self._add_entity(authors_db.AUTHOR), False),
            (_make_glyph_icon('add_circle'), '新增團體', '新增團體',
             lambda: self._add_entity(authors_db.CIRCLE), False),
            (None, None, None, None, None),
            (_make_glyph_icon('edit'), '編輯', '編輯選取項目', self._edit_selected, True),
            (_standard_icon(QStyle.StandardPixmap.SP_TrashIcon), '刪除',
             '刪除選取項目（可還原）', self._delete_selected, True),
            (None, None, None, None, None),
            (make_refresh_icon(self._toolbar_icon_size.width()), '重新整理',
             '重新整理', self.reload, False),
            (_make_glyph_icon('history'), '變更', '最近變更／還原', self._open_changes, False),
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
