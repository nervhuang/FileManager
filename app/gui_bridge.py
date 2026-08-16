"""FileManager GUI 與 Hermes MCP server 之間的本機管道。

GUI 端是 `QLocalServer`（在 Windows 底層即命名管道，跑在 Qt 主執行緒事件圈，
不開 TCP port、不會跳防火牆提示）。MCP 端不依賴 Qt，直接以檔案 I/O 連同名管道。

協定：一行一個 JSON（NDJSON）。用戶端送出一行請求，伺服器回一行結果。
    {"cmd": "ping"}                          -> {"ok": true, "pid": 1234}
    {"cmd": "open_search_tab", "query": "…"} -> {"ok": true}
    {"cmd": "authors_changed"}               -> {"ok": true}
"""

import json
import os
import queue
import threading

SERVER_NAME = 'FileManagerHermesBridge'
PIPE_PATH = r'\\.\pipe' + '\\' + SERVER_NAME


# ── 用戶端（MCP server 進程，無 Qt） ────────────────────────────────────

def gui_is_running():
    """檢查管道是否存在，藉此判斷 GUI 有沒有在跑（不需實際連線）。"""
    try:
        return SERVER_NAME in os.listdir(r'\\.\pipe')
    except OSError:
        return False


def _pipe_roundtrip(payload, out_queue):
    try:
        with open(PIPE_PATH, 'r+b', buffering=0) as pipe:
            pipe.write(json.dumps(payload, ensure_ascii=False).encode('utf-8') + b'\n')
            data = b''
            while not data.endswith(b'\n'):
                chunk = pipe.read(1)
                if not chunk:
                    break
                data += chunk
        out_queue.put(json.loads(data.decode('utf-8').strip() or '{}'))
    except Exception as exc:  # 管道不存在、被關閉、回應不是 JSON…
        out_queue.put({'ok': False, 'reason': 'bridge_error', 'error': str(exc)})


def send_command(payload, timeout=3.0):
    """送一個指令給 GUI。GUI 沒開回 {'ok': False, 'reason': 'gui_not_running'}。

    管道 I/O 放在背景執行緒並以 timeout 收斂，避免 GUI 卡住時把 MCP server 一起拖死。
    """
    if not gui_is_running():
        return {'ok': False, 'reason': 'gui_not_running'}

    result_queue = queue.Queue(maxsize=1)
    worker = threading.Thread(target=_pipe_roundtrip, args=(payload, result_queue), daemon=True)
    worker.start()
    try:
        return result_queue.get(timeout=timeout)
    except queue.Empty:
        return {'ok': False, 'reason': 'timeout'}


def notify_authors_changed():
    """通知 GUI 清單已變更；GUI 沒開就靜默跳過（不是錯誤）。"""
    if not gui_is_running():
        return
    try:
        send_command({'cmd': 'authors_changed'}, timeout=1.5)
    except Exception:
        pass


# ── 伺服器端（GUI 進程，需要 Qt） ──────────────────────────────────────

def create_server(handler, parent=None):
    """建立並啟動 QLocalServer。

    handler(dict) -> dict，在 Qt 主執行緒被呼叫，可直接操作 UI。
    已有另一個實例佔用管道名稱時回 None（多開時只有第一個實例接受指令）。
    """
    from PyQt5.QtNetwork import QLocalServer

    server = QLocalServer(parent)
    # 不呼叫 removeServer()：那會把正在執行的另一個實例踢掉。
    if not server.listen(SERVER_NAME):
        server.deleteLater()
        return None

    def _on_new_connection():
        socket = server.nextPendingConnection()
        if socket is None:
            return
        buffer = {'data': b''}

        def _on_ready_read():
            buffer['data'] += bytes(socket.readAll())
            while b'\n' in buffer['data']:
                line, _, rest = buffer['data'].partition(b'\n')
                buffer['data'] = rest
                try:
                    request = json.loads(line.decode('utf-8').strip() or '{}')
                except Exception as exc:
                    response = {'ok': False, 'reason': 'bad_request', 'error': str(exc)}
                else:
                    try:
                        response = handler(request) or {'ok': True}
                    except Exception as exc:
                        response = {'ok': False, 'reason': 'handler_error', 'error': str(exc)}
                socket.write(json.dumps(response, ensure_ascii=False).encode('utf-8') + b'\n')
                socket.flush()

        socket.readyRead.connect(_on_ready_read)
        socket.disconnected.connect(socket.deleteLater)

    server.newConnection.connect(_on_new_connection)
    return server
