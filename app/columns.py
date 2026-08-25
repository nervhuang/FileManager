"""表頭欄位：顯示切換選單，以及欄寬／欄序／隱藏欄的持久化。

兩個面板（檔案與搜尋）的表頭共用這一套，各自用不同的 `key` 存設定。
屬於檔案／搜尋面板的 UI，等那些域拆出來時應該一起搬走——放在這裡至少
不必再擠在外殼裡。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMenu

DEFAULT_WIDTH = 120

# 檔名欄不准隱藏：隱藏了就沒有東西可以點、可以改名，整個面板等於失效。
LOCKED_COLUMNS = (0,)

# 預設隱藏哪些欄：檔案面板藏「類型」，搜尋面板全顯示。
DEFAULT_HIDDEN = {'mid': (2,), 'right': ()}


def restore(cfg, key, view, cache, *, default_width=DEFAULT_WIDTH,
            default_hidden=DEFAULT_HIDDEN, locked=LOCKED_COLUMNS):
    """還原單一面板的欄寬、隱藏欄與欄序。

    順序固定為「寬度 → 隱藏 → 欄序」：先把寬度套到所有欄位（含隨後要隱藏的），
    QHeaderView 才會記住隱藏欄的原始寬度，使用者日後勾回來時寬度才正確
    （docs/spec/settings.md 的 SET-8）。

    `cache` 是呼叫端持有的 {欄位索引: 最後一次的可見寬度}，會被就地更新。
    """
    header = view.header()
    if header is None:
        return

    raw_widths = cfg.get_str('Columns', f'{key}_col_widths')
    if raw_widths:
        try:
            for index, raw in enumerate(raw_widths.split(',')):
                # 舊版 config 把隱藏欄的寬度存成 0，直接沿用會讓欄位勾回來仍是 0 寬
                # （SET-9）。
                width = int(raw) or default_width
                cache[index] = width
                view.setColumnWidth(index, width)
        except ValueError:
            pass

    hidden = set(default_hidden.get(key, ()))
    # 鍵存在但為空字串代表「全部顯示」，與鍵不存在（採用預設值）不同，
    # 所以要問 has() 而不是看值是不是空的（SET-10）。
    if cfg.has('Columns', f'{key}_col_hidden'):
        try:
            hidden = {int(x) for x in
                      cfg.get_str('Columns', f'{key}_col_hidden').split(',') if x.strip()}
        except ValueError:
            pass
    hidden -= set(locked)
    for index in range(header.count()):
        view.setColumnHidden(index, index in hidden)

    raw_order = cfg.get_str('Columns', f'{key}_col_order')
    if raw_order:
        try:
            for visual, logical in enumerate(int(x) for x in raw_order.split(',')):
                current = header.visualIndex(logical)
                if current != visual:
                    header.moveSection(current, visual)
        except ValueError:
            pass


def save(cfg, key, view, cache, *, default_width=DEFAULT_WIDTH):
    """寫出單一面板的欄寬、欄序與隱藏欄。

    隱藏欄的 `columnWidth()` 恆為 0，改寫入快取中最後一次的可見寬度，
    下次啟動勾回來才有合理寬度。
    """
    header = view.header()
    if header is None:
        return

    widths = []
    hidden = []
    for index in range(header.count()):
        if view.isColumnHidden(index):
            hidden.append(str(index))
            width = cache.get(index, default_width)
        else:
            width = view.columnWidth(index) or cache.get(index, default_width)
            cache[index] = width
        widths.append(str(width))

    cfg.set('Columns', f'{key}_col_widths', ','.join(widths))
    cfg.set('Columns', f'{key}_col_order',
            ','.join(str(header.logicalIndex(i)) for i in range(header.count())))
    cfg.set('Columns', f'{key}_col_hidden', ','.join(hidden))

class KeepOpenMenu(QMenu):
    """勾選 checkable 項目後不關閉的選單，可一次連續切換多個選項。

    QMenu 預設觸發任何動作即關閉。此處攔截滑鼠放開與 Enter/Space：若當前項目是
    啟用中的 checkable 動作，就自行 trigger() 並吞掉事件，選單保持開啟；其餘情形
    （點在分隔線、停用項目或選單外）一律交回原生處理，Esc 與點外面仍可關閉。"""

    def _toggle_active(self):
        action = self.activeAction()
        if action is not None and action.isEnabled() and action.isCheckable():
            action.trigger()
            return True
        return False

    def mouseReleaseEvent(self, event):
        if self._toggle_active():
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self._toggle_active():
            event.accept()
            return
        super().keyPressEvent(event)


def build_column_visibility_menu(view, locked_columns=(), on_toggled=None, parent=None):
    """建立「欄位顯示」切換選單：每個欄位一個 checkbox，勾選狀態即該欄目前是否顯示。

    項目依表頭的視覺順序排列，與畫面上看到的欄位順序一致。locked_columns 內的欄位
    以已勾選但停用的樣子呈現（恆顯示、點不動）。實際的顯示/隱藏動作交由 on_toggled
    (column, visible) 執行，讓呼叫端得以一併處理欄寬記憶。"""
    menu = KeepOpenMenu(parent if parent is not None else view)
    model = view.model()
    header = view.header()
    if model is None or header is None:
        return menu

    for visual in range(header.count()):
        logical = header.logicalIndex(visual)
        label = model.headerData(logical, Qt.Horizontal, Qt.DisplayRole)
        action = menu.addAction(str(label) if label else str(logical))
        action.setCheckable(True)
        action.setChecked(not view.isColumnHidden(logical))
        if logical in locked_columns:
            action.setEnabled(False)
        elif on_toggled is not None:
            action.toggled.connect(
                lambda checked, col=logical: on_toggled(col, checked))
    return menu
