"""SET-1 到 SET-4、SET-8、SET-11：路徑解析與「不依賴 Qt」這條界線。

SET-3 那支是架構守門測試：它在**子進程**裡匯入服務層，然後問 PyQt5 有沒有被
拉進來。在本進程裡問沒有意義——pytest 早就把 Qt 載進來了。
"""
import configparser
import os
import subprocess
import sys
import textwrap

import pytest

from app import paths

pytestmark = pytest.mark.logic

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 這些必須能在沒有 QApplication 的進程裡使用：MCP server 與 CLI 都是那樣跑的。
QT_FREE_MODULES = [
    'app.paths',
    'app.settings',
    'app.settings.config',
    'app.settings.store',
    'app.search.query',
    'app.search.everything',
    'app.search.results',
    'app.authors.db',
    'app.authors.names',
    'app.fileops.shell',
    'app.fileops.rename',
    'app.fileops.clipboard',
    'app.tabs.history',
    'app.checker.titles',
    'app.checker.matcher',
    'app.checker.store',
]


def _run_in_subprocess(code):
    result = subprocess.run(
        [sys.executable, '-c', textwrap.dedent(code)],
        cwd=PROJECT_ROOT, capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


# ── SET-1：執行期目錄的解析順序 ─────────────────────────────────────────

def test_set_1_filemanager_home_wins(tmp_path, monkeypatch):
    monkeypatch.setenv('FILEMANAGER_HOME', str(tmp_path))
    assert paths.runtime_root() == str(tmp_path)


def test_set_1_blank_filemanager_home_is_ignored(monkeypatch):
    """空字串或只有空白不算設定，否則會解析到一個不存在的目錄。"""
    monkeypatch.setenv('FILEMANAGER_HOME', '   ')
    assert paths.runtime_root() == os.path.abspath(PROJECT_ROOT)


def test_set_1_config_and_db_live_in_the_runtime_root(tmp_path, monkeypatch):
    monkeypatch.setenv('FILEMANAGER_HOME', str(tmp_path))
    assert paths.config_path() == os.path.join(str(tmp_path), 'config.ini')
    assert paths.authors_db_path() == os.path.join(str(tmp_path), 'authors.db')


# ── SET-2：打包資源目錄與執行期目錄是兩件事 ────────────────────────────

def test_set_2_bundle_root_is_not_redirected_by_filemanager_home(tmp_path, monkeypatch):
    """混用會造成「寫進 _internal 但執行期讀不到」。"""
    monkeypatch.setenv('FILEMANAGER_HOME', str(tmp_path))
    assert paths.bundle_root() != paths.runtime_root()
    assert paths.bundle_root() == os.path.abspath(PROJECT_ROOT)


# ── SET-3：服務層不得依賴 Qt ────────────────────────────────────────────

def test_set_3_service_layers_import_without_qt():
    """一次全部匯入，然後問 PyQt5 在不在 sys.modules 裡。

    這條界線一旦破掉，MCP server 與 CLI 會在使用者的機器上直接 ImportError，
    而 GUI 這邊完全看不出來。
    """
    output = _run_in_subprocess(f'''
        import sys
        for name in {QT_FREE_MODULES!r}:
            __import__(name)
        print('PyQt5' in sys.modules)
    ''')
    assert output == 'False', '有服務層模組把 PyQt5 拉進來了'


def test_set_3_the_cli_entry_point_imports_without_qt():
    output = _run_in_subprocess('''
        import sys
        import app.cli
        print('PyQt5' in sys.modules)
    ''')
    assert output == 'False'


def test_set_3_the_mcp_server_imports_without_qt():
    output = _run_in_subprocess('''
        import sys
        import app.hermes_mcp
        print('PyQt5' in sys.modules)
    ''')
    assert output == 'False'


def test_set_3_this_test_would_notice_a_qt_import():
    """證明上面那三支不是恆真：故意匯入 Qt 的話要看得到 True。"""
    output = _run_in_subprocess('''
        import sys
        import PyQt5.QtCore
        print('PyQt5' in sys.modules)
    ''')
    assert output == 'True'


# ── SET-4：config.ini 不得被打包 ────────────────────────────────────────

def test_set_4_config_ini_is_not_bundled():
    """打包進去的那份會落在 _internal/，執行期永遠讀不到，只會洩漏建置機器的
    搜尋歷史與私人路徑。"""
    spec = open(os.path.join(PROJECT_ROOT, 'FileManager.spec'), encoding='utf-8').read()
    datas_line = next(line for line in spec.split('\n') if 'datas=' in line)
    assert 'config.ini' not in datas_line


# ── SET-8／SET-11：欄位與排除設定的鍵 ──────────────────────────────────

def test_set_8_column_keys_are_namespaced_per_panel(tmp_path):
    """兩個面板各自一組鍵，設定才不會互相影響（SET-7）。"""
    from app.settings import ConfigStore

    store = ConfigStore.load(tmp_path / 'config.ini')
    store.set('Columns', 'mid_col_widths', '1,2')
    store.set('Columns', 'right_col_widths', '3,4')
    store.save()

    again = ConfigStore.load(tmp_path / 'config.ini')
    assert again.get_int_list('Columns', 'mid_col_widths') == [1, 2]
    assert again.get_int_list('Columns', 'right_col_widths') == [3, 4]


def test_set_11_exclude_settings_round_trip(tmp_path):
    """同一份排除設定要給 GUI、MCP、CLI 三個進程共用，所以得存得回來。"""
    from app.search.query import is_path_excluded, normalize_exclude_dirs
    from app.settings import ConfigStore

    store = ConfigStore.load(tmp_path / 'config.ini')
    store.set_bool('Exclude', 'enabled', True)
    store.set_json('Exclude', 'dirs', [r'D:\排除'])
    store.save()

    again = ConfigStore.load(tmp_path / 'config.ini')
    assert again.get_bool('Exclude', 'enabled', False) is True
    exclude = normalize_exclude_dirs(again.get_json('Exclude', 'dirs', []))
    assert is_path_excluded(r'D:\排除\a.txt', exclude) is True


def test_set_11_the_written_file_is_readable_by_plain_configparser(tmp_path):
    """設定檔不是這個程式的私有格式，別的進程要讀得懂。"""
    from app.settings import ConfigStore

    store = ConfigStore.load(tmp_path / 'config.ini')
    store.set('General', 'font_size', 14)
    store.save()

    cfg = configparser.ConfigParser()
    cfg.read(tmp_path / 'config.ini', encoding='utf-8')
    assert cfg.getint('General', 'font_size') == 14
