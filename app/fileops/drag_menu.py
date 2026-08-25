"""右鍵拖放的後備選單。

Shell 的 `IDropTarget` 不可用時才會走到這裡（`fileops.shell.right_drag_drop`
拋出例外）。選單刻意做得跟檔案總管一樣：移動是預設動作所以是粗體，取消放在
分隔線之後（docs/spec/fileops.md 的 FOP-17）。

只負責問「要做哪一種」，不負責做。動作留給呼叫端——搜尋面板與檔案面板事後要
刷新的東西不同。
"""

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QMenu

MOVE = 'move'
COPY = 'copy'
LINK = 'link'
CANCELLED = None


def ask_right_drag_action(parent, global_pos):
    """在 global_pos 顯示選單，回傳 MOVE / COPY / LINK / CANCELLED。"""
    menu = QMenu(parent)
    font_bold = QFont(menu.font())
    font_bold.setBold(True)

    act_move = menu.addAction('移動到這裡(&M)')
    act_move.setFont(font_bold)          # 移動是預設動作，與檔案總管一致
    act_copy = menu.addAction('複製到這裡(&C)')
    act_link = menu.addAction('建立捷徑到這裡(&S)')
    menu.addSeparator()
    menu.addAction('取消')

    chosen = menu.exec_(global_pos)
    if chosen == act_move:
        return MOVE
    if chosen == act_copy:
        return COPY
    if chosen == act_link:
        return LINK
    return CANCELLED
