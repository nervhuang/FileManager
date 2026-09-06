"""SHL-5a：位址列的下拉選單也要跟著字型走。

QMenu 是彈出視窗，不從按鈕繼承字型——分頁列的「全部分頁」選單踩過同一個坑
（app/tabs/bar.py 有明確的 setFont）。位址列的 chevron 與 overflow 選單則一直
漏著：字型放大到 21pt，點開來的資料夾清單仍然是預設大小。

這是 offscreen 量得到的（字型級數），不是外觀。
"""
import os

import pytest
from PyQt5.QtWidgets import QMenu, QToolButton

from app import font_scaling

pytestmark = pytest.mark.gui


def _menus(breadcrumb):
    menus = []
    for btn in breadcrumb.findChildren(QToolButton):
        menu = btn.menu()
        if isinstance(menu, QMenu):
            menus.append((btn, menu))
    return menus


def test_shl_05a_breadcrumb_menus_follow_the_font(main_window, qapp):
    breadcrumb = main_window.path_bar
    breadcrumb.set_path(os.path.abspath(os.sep))
    font_scaling.apply_to_window(main_window, 21)
    qapp.processEvents()

    pairs = _menus(breadcrumb)
    assert pairs, '位址列應該有帶下拉選單的按鈕（chevron／overflow）'
    stale = [f'{btn.text()}: {menu.font().pointSize()}pt'
             for btn, menu in pairs if menu.font().pointSize() != btn.font().pointSize()]
    assert not stale, ('以下下拉選單沒跟上按鈕的字型（SHL-5a）：\n  '
                       + '\n  '.join(stale))
