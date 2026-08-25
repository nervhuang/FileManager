"""設定層的特徵測試：鎖住 config.ini 目前的讀寫行為。

這些測試寫在拆分**之前**，用途是確認拆分沒有改變任何行為。條文編號見
docs/spec/settings.md。

刻意走完整的 FileManager 而不是直接測 load_config／save_config：現在讀設定與
套用設定混在同一個方法裡，只有從外面觀察「寫進去的值下次會不會回來」才問得出
真正的行為。拆分之後這些測試不必改，正好證明外部行為沒變。
"""
import configparser

import pytest

pytestmark = pytest.mark.gui


def _write_config(home, text):
    home.mkdir(parents=True, exist_ok=True)
    (home / 'config.ini').write_text(text, encoding='utf-8')


def _read_config(home):
    cfg = configparser.ConfigParser()
    cfg.read(home / 'config.ini', encoding='utf-8')
    return cfg


@pytest.fixture
def home(tmp_path, monkeypatch):
    """一個空的執行期目錄，測試自己決定要不要放 config.ini 進去。"""
    path = tmp_path / 'home'
    path.mkdir()
    monkeypatch.setenv('FILEMANAGER_HOME', str(path))
    return path


@pytest.fixture
def make_window(qapp, home):
    """建立主視窗；同一個測試可以建立多次，模擬關掉再開。"""
    windows = []

    def factory():
        from app.file_manager import FileManager
        window = FileManager()
        window.show()
        qapp.processEvents()
        windows.append(window)
        return window

    yield factory

    for window in windows:
        window.close()
    qapp.processEvents()


def _close(window, qapp):
    """關閉視窗，觸發 closeEvent 把設定寫出去。"""
    window.close()
    qapp.processEvents()


# ── 啟動容錯 ──────────────────────────────────────────────────────────────

def test_set_5_first_launch_without_config_uses_defaults(home, make_window, qapp):
    """SET-5：沒有 config.ini 是正常狀態，以內建預設值執行，關閉時寫出檔案。"""
    assert not (home / 'config.ini').exists()

    window = make_window()
    assert window._current_font_size() == 10        # General/font_size 的 fallback
    assert window._exclude_enabled is False

    _close(window, qapp)
    assert (home / 'config.ini').exists()


def test_set_13_corrupt_values_do_not_prevent_startup(home, make_window):
    """SET-13：任何一個鍵解析失敗只影響該鍵，不得讓程式無法啟動。

    每一個鍵都塞進格式錯誤的值——不是空字串，是型別對不上的垃圾。
    """
    _write_config(home, """
[General]
font_size = 不是數字
search_history = {這不是 JSON

[Layout]
window_geometry = ****不是 base64****
window_state = 亂寫
authors_panel_visible = 也不是布林
authors_panel_width = abc
checker_panel_width = -
checker_split_sizes = x,y,z
checker_col_widths = 1,2,三
right_splitter_sizes = 一,二
right_splitter_vertical_sizes = ,,,
right_splitter_orientation = 斜的

[Columns]
mid_col_widths = 100,壞掉,300
mid_col_hidden = 一
mid_col_order = 9999,0

[Sort]
mid_sort_column = 壞
mid_sort_order = 掉

[Tabs]
mid_tabs = [不是 JSON
mid_tabs_current = 很多
""".lstrip())

    window = make_window()     # 建得起來就是通過；建不起來會在這裡拋例外
    assert window.isVisible()
    # 壞掉的字級應退回 fallback，而不是套用垃圾值
    assert 6 <= window._current_font_size() <= 72


# ── 往返 ──────────────────────────────────────────────────────────────────

def test_set_config_round_trips_across_restarts(home, make_window, qapp):
    """改狀態 → 關閉 → 重開，狀態要回來。涵蓋字級、排除設定、面板寬度與顯隱。"""
    first = make_window()
    first._apply_font_size(17)
    first._exclude_enabled = True
    first._exclude_dirs = ['D:\\NAS', 'E:\\暫存']
    first._apply_exclude_settings()
    first._set_authors_panel_visible(False)
    first._set_checker_panel_visible(True)
    _close(first, qapp)

    cfg = _read_config(home)
    assert cfg.getint('General', 'font_size') == 17
    assert cfg.getboolean('Exclude', 'enabled') is True
    assert cfg.getboolean('Layout', 'authors_panel_visible') is False
    assert cfg.getboolean('Layout', 'checker_panel_visible') is True

    second = make_window()
    assert second._current_font_size() == 17
    assert second._exclude_enabled is True
    assert second._exclude_dirs == ['D:\\NAS', 'E:\\暫存']
    assert second._authors_panel_visible is False
    assert second._checker_panel_visible is True


def test_set_6_horizontal_and_vertical_splitter_sizes_are_independent(
        home, make_window, qapp):
    """SET-6：兩種配置的分割尺寸各自保存，切過去再切回來尺寸不變。"""
    from PyQt5.QtCore import Qt

    window = make_window()
    window._set_right_panel_layout(Qt.Orientation.Horizontal)
    qapp.processEvents()
    window.right_splitter.setSizes([300, 700])
    qapp.processEvents()

    window._set_right_panel_layout(Qt.Orientation.Vertical)
    qapp.processEvents()
    window.right_splitter.setSizes([200, 500])
    qapp.processEvents()

    window._set_right_panel_layout(Qt.Orientation.Horizontal)
    qapp.processEvents()
    horizontal = window._right_splitter_sizes_by_orientation[Qt.Orientation.Horizontal]
    vertical = window._right_splitter_sizes_by_orientation[Qt.Orientation.Vertical]
    assert horizontal != vertical, '兩種配置的尺寸不應互相覆蓋'

    _close(window, qapp)
    cfg = _read_config(home)
    assert cfg.get('Layout', 'right_splitter_orientation') == 'horizontal'
    assert cfg.get('Layout', 'right_splitter_sizes')
    assert cfg.get('Layout', 'right_splitter_vertical_sizes')


def test_set_12_restored_tabs_still_load_their_content(home, make_window, qapp):
    """SET-12：restore_tabs 不觸發 tab_switched，啟動時必須主動補上。"""
    _write_config(home, """
[Tabs]
mid_tabs = [["C:\\\\", "C:"], ["D:\\\\", "D:"]]
mid_tabs_current = 1
""".lstrip())

    window = make_window()
    tabs, current = window.mid_tab_bar.get_all_tabs()
    assert [d for d, _ in tabs] == ['C:\\', 'D:\\']
    assert current == 1
    # 還原後麵包屑要指向當前分頁，而不是停在預設值
    assert window.mid_tab_bar.current_data() == 'D:\\'


# ── 欄位 ──────────────────────────────────────────────────────────────────

def test_set_10_empty_hidden_key_means_all_visible(home, make_window):
    """SET-10：鍵存在但為空字串＝全部顯示，與鍵不存在（採預設隱藏欄）不同。"""
    from app.file_manager import FileManager

    default_hidden = set(FileManager.DEFAULT_HIDDEN_COLUMNS.get('mid', ()))
    assert default_hidden, '這個測試的前提是 mid 面板本來有預設隱藏欄'

    _write_config(home, '[Columns]\nmid_col_hidden = \n')
    window = make_window()
    header = window.listView.header()
    hidden_now = {i for i in range(header.count()) if window.listView.isColumnHidden(i)}
    assert hidden_now == set(), f'空字串應代表全部顯示，實際隱藏了 {hidden_now}'


def test_set_9_zero_width_falls_back_to_default(home, make_window):
    """SET-9：舊版把隱藏欄寬度存成 0，讀到 0 要改用預設欄寬。"""
    from app.file_manager import FileManager

    _write_config(home, '[Columns]\nmid_col_widths = 0,0,0,0\nmid_col_hidden = \n')
    window = make_window()
    for i in range(4):
        assert window.listView.columnWidth(i) == FileManager.DEFAULT_COLUMN_WIDTH


def test_set_7_two_panels_keep_separate_column_settings(home, make_window, qapp):
    """SET-7：兩個面板的欄位設定彼此獨立。"""
    window = make_window()
    window.listView.setColumnWidth(0, 123)
    window.listView2.setColumnWidth(0, 456)
    _close(window, qapp)

    cfg = _read_config(home)
    assert cfg.get('Columns', 'mid_col_widths').split(',')[0] == '123'
    assert cfg.get('Columns', 'right_col_widths').split(',')[0] == '456'


# ── 舊鍵清理 ──────────────────────────────────────────────────────────────

def test_legacy_three_panel_keys_are_removed_on_save(home, make_window, qapp):
    """三面板時代的遺留鍵在寫出時清掉，不會一直跟著設定檔跑。"""
    _write_config(home, """
[General]
left_dir = C:\\舊的

[Layout]
splitter_sizes = 1,2,3

[Columns]
left_col_widths = 100,200

[Tabs]
left_tabs = []
left_tabs_current = 0
""".lstrip())

    _close(make_window(), qapp)

    cfg = _read_config(home)
    for section, option in (('General', 'left_dir'), ('Layout', 'splitter_sizes'),
                            ('Columns', 'left_col_widths'), ('Tabs', 'left_tabs'),
                            ('Tabs', 'left_tabs_current')):
        assert not cfg.has_option(section, option), f'{section}/{option} 應已被清除'
