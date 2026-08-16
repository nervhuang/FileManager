"""執行期路徑解析（不依賴 Qt，GUI 與 Hermes MCP server 共用）。"""

import os
import sys


def bundle_root():
    """打包資源（icon 等）所在目錄。"""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def runtime_root():
    """可寫入的執行期目錄：config.ini 與 authors.db 都放這裡。

    環境變數 FILEMANAGER_HOME 可覆寫。這是給 Hermes MCP server 用的：它以專案
    venv 的 python 執行（未凍結），預設會解析到專案目錄，但使用者實際在跑的是
    打包後的 exe（凍結，解析到 exe 所在資料夾），兩個進程於是各自讀寫一份
    authors.db 與 config.ini。把這個變數指向 exe 所在資料夾，兩邊才是同一份。
    """
    override = os.environ.get('FILEMANAGER_HOME', '').strip()
    if override:
        return os.path.abspath(override)
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def config_path():
    return os.path.join(runtime_root(), 'config.ini')


def authors_db_path():
    return os.path.join(runtime_root(), 'authors.db')
