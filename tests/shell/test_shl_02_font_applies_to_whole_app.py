"""SHL-2、SHL-3、SHL-4：字型設定套用於整個應用程式。

判定方式是**相對追蹤**而不是絕對相等：字級加 8pt，每一個 widget 的字級都應該
跟著加 8pt。這樣寫才容得下刻意的相對差距——更新檢查器的計數列比內文大一級、
執行紀錄用等寬且小一級——同時仍然抓得到「某個 widget 完全沒跟上」。

這支測試存在的理由是 SHL-3：`_apply_font_size` 曾經是一份逐一列舉全 app widget
的手寫白名單。作者面板漏過一次、更新檢查器是第二次補登記。第三次不該再靠人記得。
"""
import pytest
from PyQt5.QtWidgets import QWidget

pytestmark = pytest.mark.gui

STEP = 8


def _describe(widget):
    name = widget.objectName() or ''
    text = ''
    for attr in ('text', 'title', 'toolTip'):
        getter = getattr(widget, attr, None)
        if callable(getter):
            try:
                text = getter() or ''
            except TypeError:      # 需要參數的同名方法（如 QTabBar.text(index)）
                text = ''
            if text:
                break
    label = ' / '.join(part for part in (name, text) if part)
    return f'{widget.__class__.__name__}({label})' if label else widget.__class__.__name__


def _font_sizes(window):
    """回傳 {widget: 字級}，涵蓋主視窗與它底下每一個 widget。

    字級為 -1 的（以 pixel 而非 point 指定字型）跳過：那是另一套單位，
    比較 point 沒有意義。
    """
    sizes = {}
    for widget in [window] + window.findChildren(QWidget):
        size = widget.font().pointSize()
        if size > 0:
            sizes[widget] = size
    return sizes


def test_shl_04_every_widget_tracks_the_font_size(main_window, qapp):
    base = main_window._current_font_size()
    before = _font_sizes(main_window)
    assert before, "沒有量到任何 widget，測試本身可能失效了"

    main_window._apply_font_size(base + STEP)
    qapp.processEvents()

    stale = []
    for widget, old_size in before.items():
        try:
            new_size = widget.font().pointSize()
        except RuntimeError:       # widget 已在套用過程中被重建
            continue
        if new_size != old_size + STEP:
            stale.append(f'{_describe(widget)}：{old_size} → {new_size}'
                         f'（應為 {old_size + STEP}）')

    assert not stale, (
        f"字級加 {STEP}pt 後，以下 widget 沒有跟上。"
        "橫切關注點不要寫成手寫清單，改成遞迴套用：\n  "
        + '\n  '.join(sorted(stale)))


def test_shl_02_menu_status_and_toolbars_follow_the_font(main_window, qapp):
    """單獨點名這幾個，因為它們是原本整片漏掉的部分。

    判準同樣是相對追蹤而非絕對相等：工具列的文字刻意比內文大兩級
    （`file_manager` 與 `authors_panel` 都把按鈕字級釘在 14pt，為的是圖示與
    文字的比例），要求它等於基準字級是錯的判準。
    """
    from PyQt5.QtWidgets import QToolBar

    named = {
        '功能表列': main_window.menuBar(),
        '狀態列': main_window.statusBar(),
        '主視窗': main_window,
    }
    for index, toolbar in enumerate(main_window.findChildren(QToolBar), 1):
        named[f'工具列#{index}'] = toolbar
    named = {name: w for name, w in named.items() if w is not None}

    before = {name: w.font().pointSize() for name, w in named.items()}
    main_window._apply_font_size(main_window._current_font_size() + STEP)
    qapp.processEvents()

    wrong = {
        name: f'{before[name]} → {w.font().pointSize()}（應為 {before[name] + STEP}）'
        for name, w in named.items()
        if w.font().pointSize() != before[name] + STEP
    }
    assert not wrong, f'字級加 {STEP}pt 後沒跟上：{wrong}'


def test_shl_01_font_scaling_is_reversible(main_window, qapp):
    """來回縮放必須回到原樣，包含撞到 6pt 下限與拉到大字級之後。

    以偏移量套用字型的作法，最容易壞在下限：一旦有 widget 被鉗到 6pt，
    它與基準的偏移就丟失了，放大回來時會與鄰居錯開一級。
    """
    from PyQt5.QtWidgets import QToolBar

    named = {
        '主視窗': main_window,
        '功能表列': main_window.menuBar(),
        '狀態列': main_window.statusBar(),
        '檔案清單': main_window.listView,
        '搜尋清單': main_window.listView2,
        '作者面板': main_window.authors_panel,
        '作者樹': main_window.authors_panel.tree,
        '檢查器計數列': main_window.checker_panel.counts_label,
        '檢查器紀錄區': main_window.checker_panel.log_view,
    }
    for index, toolbar in enumerate(main_window.findChildren(QToolBar), 1):
        named[f'工具列#{index}'] = toolbar
    named = {name: w for name, w in named.items() if w is not None}

    base = main_window._current_font_size()
    before = {name: w.font().pointSize() for name, w in named.items()}

    for target in (base + 9, base, 6, base, 40, base):
        main_window._apply_font_size(target)
        qapp.processEvents()

    after = {name: w.font().pointSize() for name, w in named.items()}
    drifted = {name: (before[name], after[name])
               for name in before if before[name] != after[name]}
    assert not drifted, f'來回縮放後與原始不同（原始, 現在）：{drifted}'
