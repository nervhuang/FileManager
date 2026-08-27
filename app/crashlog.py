"""崩潰記錄器：把原生崩潰、Qt 致命訊息與未捕捉例外都留在 crash.log。

原本是 `app/file_manager.py` 的模組層函式。它與外殼的職責（建面板、接訊號、
管版面）無關，是與 `app/font_scaling.py`、`app/icons.py` 同一類的橫切關注點。

模組層**不匯入 Qt**：Qt 訊息處理器的安裝寫在函式裡並包在 try 內，沒有
`QApplication` 的行程（MCP server、CLI）照樣可以匯入這支模組。
"""

import os
import sys
import traceback

from .paths import runtime_root


def install():
    """安裝崩潰記錄器：把原生崩潰（存取違規）、Qt 致命訊息與未捕捉的 Python
    例外都寫進 crash.log，讓「無聲消失」的原生崩潰留下可診斷的呼叫堆疊。

    回傳開啟中的 log 檔物件——必須在整個行程生命週期保持開啟，faulthandler
    才能在崩潰當下寫入。"""
    import faulthandler
    from datetime import datetime as _dt

    log_path = os.path.join(runtime_root(), 'crash.log')
    try:
        log_file = open(log_path, 'a', buffering=1, encoding='utf-8')
    except Exception:
        return None

    log_file.write(f"\n===== session start {_dt.now():%Y-%m-%d %H:%M:%S} =====\n")
    log_file.flush()

    # faulthandler：在 SIGSEGV / Windows 存取違規等致命錯誤時 dump 所有執行緒的
    # Python 堆疊到 log_file（含造成崩潰的那一行）。
    try:
        faulthandler.enable(file=log_file, all_threads=True)
    except Exception:
        pass

    # 未捕捉的 Python 例外也寫入 log（保留原本的主控台輸出）。
    _prev_excepthook = sys.excepthook

    def _excepthook(exc_type, exc_value, exc_tb):
        try:
            log_file.write(f"\n----- uncaught exception {_dt.now():%Y-%m-%d %H:%M:%S} -----\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=log_file)
            log_file.flush()
        except Exception:
            pass
        _prev_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    # Qt 端的警告/致命訊息（QSortFilterProxyModel 索引越界常以 qWarning 先示警）。
    try:
        from PyQt5.QtCore import qInstallMessageHandler, QtMsgType

        def _qt_message_handler(mode, context, message):
            label = {
                QtMsgType.QtDebugMsg: 'DEBUG',
                QtMsgType.QtInfoMsg: 'INFO',
                QtMsgType.QtWarningMsg: 'WARNING',
                QtMsgType.QtCriticalMsg: 'CRITICAL',
                QtMsgType.QtFatalMsg: 'FATAL',
            }.get(mode, 'MSG')
            try:
                log_file.write(f"[Qt {label}] {message}\n")
                log_file.flush()
            except Exception:
                pass

        qInstallMessageHandler(_qt_message_handler)
    except Exception:
        pass

    return log_file
