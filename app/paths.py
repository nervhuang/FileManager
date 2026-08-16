"""執行期路徑解析（不依賴 Qt，GUI 與 Hermes MCP server 共用）。"""

import os
import sys


def bundle_root():
    """打包資源（icon 等）所在目錄。"""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def runtime_root():
    """可寫入的執行期目錄：config.ini 與 authors.db 都放這裡。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def config_path():
    return os.path.join(runtime_root(), 'config.ini')


def authors_db_path():
    return os.path.join(runtime_root(), 'authors.db')
