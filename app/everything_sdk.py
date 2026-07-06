import ctypes
import ctypes.wintypes as wt
import os
import struct
import time
from collections import namedtuple


# 單筆搜尋結果：路徑與 Everything 索引中既有的中繼資料。
# 直接由 IPC 回覆取得，免去對每筆結果逐一 os.stat 的磁碟 I/O。
SearchResult = namedtuple('SearchResult', ('path', 'is_dir', 'size', 'mtime'))

# FILETIME（1601-01-01 起算的 100ns）轉 Unix epoch 的偏移量
_FILETIME_EPOCH_DELTA = 116444736000000000
_FILETIME_UNKNOWN = 0xFFFFFFFFFFFFFFFF


class EverythingSDK:
    """Everything IPC client supporting both 1.5a (pure IPC2) and 1.4 (DLL)."""

    WM_COPYDATA = 0x004A
    EVERYTHING_IPC_COPYDATA_QUERY2W = 18
    EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME = 0x00000004
    EVERYTHING_REQUEST_SIZE = 0x00000010
    EVERYTHING_REQUEST_DATE_MODIFIED = 0x00000040
    EVERYTHING_IPC_FOLDER = 0x00000001

    # Window class names for different Everything versions
    _IPC_WNDCLASS_15A = "EVERYTHING_TASKBAR_NOTIFICATION_(1.5a)"
    _IPC_WNDCLASS_14 = "EVERYTHING_TASKBAR_NOTIFICATION"

    def __init__(self):
        self._setup_winapi()
        self._ipc_results = []
        self._ipc_got_reply = False
        self._wndproc_ref = self._WNDPROCTYPE(self._wnd_proc)
        self._reply_hwnd = None
        self._cls_name = None
        self._create_reply_window()

    def _setup_winapi(self):
        """Configure ctypes signatures for Windows API calls."""
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32

        self._kernel32.GetModuleHandleW.restype = wt.HMODULE
        self._kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        self._user32.FindWindowW.restype = wt.HWND
        self._user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
        self._user32.DefWindowProcW.restype = ctypes.c_longlong
        self._user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong]
        self._user32.SendMessageW.restype = ctypes.c_longlong
        self._user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong]
        self._user32.PeekMessageW.restype = wt.BOOL
        self._user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
        self._user32.CreateWindowExW.argtypes = [
            wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p
        ]
        self._user32.CreateWindowExW.restype = wt.HWND
        self._user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]

    class _COPYDATASTRUCT(ctypes.Structure):
        _fields_ = [
            ("dwData", ctypes.c_ulonglong),
            ("cbData", wt.DWORD),
            ("lpData", ctypes.c_void_p),
        ]

    _WNDPROCTYPE = ctypes.CFUNCTYPE(ctypes.c_longlong, wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong)

    class _WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wt.UINT), ("style", wt.UINT),
            ("lpfnWndProc", ctypes.CFUNCTYPE(ctypes.c_longlong, wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong)),
            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
            ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
            ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
            ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON),
        ]

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """Window procedure to receive IPC2 reply from Everything."""
        if msg == self.WM_COPYDATA:
            pCds = ctypes.cast(lparam, ctypes.POINTER(self._COPYDATASTRUCT))
            cds = pCds.contents
            if cds.cbData > 0 and cds.lpData:
                raw = (ctypes.c_ubyte * cds.cbData).from_address(cds.lpData)
                data = bytes(raw)
                self._parse_ipc2_response(data)
            self._ipc_got_reply = True
            return 1
        return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _parse_ipc2_response(self, data):
        """Parse EVERYTHING_IPC_LIST2 response data.

        每筆 item 的資料區依 request flags 的位元順序排列：
        full_path 字串區塊（DWORD 字元數不含結尾 null，後接含 null 的 WCHAR 陣列）、
        size（8 bytes LARGE_INTEGER）、date_modified（8 bytes FILETIME）。"""
        if len(data) < 20:
            return
        totitems, numitems, offset, req_flags, sort_type = struct.unpack_from('<IIIII', data, 0)
        items_start = 20
        for i in range(numitems):
            item_off = items_start + i * 8
            if item_off + 8 > len(data):
                break
            flags, data_offset = struct.unpack_from('<II', data, item_off)
            if data_offset + 4 > len(data):
                continue
            str_len_chars = struct.unpack_from('<I', data, data_offset)[0]
            str_start = data_offset + 4
            str_bytes = str_len_chars * 2
            if str_start + str_bytes > len(data):
                continue
            full_path = data[str_start:str_start + str_bytes].decode('utf-16-le', errors='replace')

            size = 0
            mtime = 0
            meta_off = str_start + str_bytes + 2  # 跳過字串的 null 結尾
            if meta_off + 16 <= len(data):
                size, filetime = struct.unpack_from('<qQ', data, meta_off)
                if size < 0:  # 資料夾大小未索引時 Everything 回傳 -1
                    size = 0
                if 0 < filetime < _FILETIME_UNKNOWN and filetime > _FILETIME_EPOCH_DELTA:
                    mtime = (filetime - _FILETIME_EPOCH_DELTA) / 10000000
            is_dir = bool(flags & self.EVERYTHING_IPC_FOLDER)
            self._ipc_results.append(SearchResult(full_path, is_dir, size, mtime))

    def _find_everything_hwnd(self):
        """Find Everything IPC window (1.5a or 1.4)."""
        hwnd = self._user32.FindWindowW(self._IPC_WNDCLASS_15A, None)
        if hwnd:
            return hwnd
        hwnd = self._user32.FindWindowW(self._IPC_WNDCLASS_14, None)
        return hwnd

    def _create_reply_window(self):
        """建立持久化的 IPC 回覆視窗，整個生命週期共用。"""
        hInst = self._kernel32.GetModuleHandleW(None)
        self._cls_name = f"EvIPC_{os.getpid()}"
        wc = self._WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(self._WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hInst
        wc.lpszClassName = self._cls_name
        self._user32.RegisterClassExW(ctypes.byref(wc))
        self._reply_hwnd = self._user32.CreateWindowExW(
            0, self._cls_name, "R", 0, 0, 0, 0, 0, None, None, hInst, None
        )

    def __del__(self):
        try:
            if self._reply_hwnd:
                self._user32.DestroyWindow(self._reply_hwnd)
                self._reply_hwnd = None
            if self._cls_name:
                hInst = self._kernel32.GetModuleHandleW(None)
                self._user32.UnregisterClassW(self._cls_name, hInst)
                self._cls_name = None
        except Exception:
            pass

    def is_available(self):
        return bool(self._find_everything_hwnd())

    def query(self, search_text, max_results=200):
        """Query Everything via IPC2 (WM_COPYDATA)。回傳 SearchResult 清單。"""
        self._ipc_results = []
        self._ipc_got_reply = False

        everything_hwnd = self._find_everything_hwnd()
        if not everything_hwnd:
            return []

        if not self._reply_hwnd:
            self._create_reply_window()
        if not self._reply_hwnd:
            return []

        # Build EVERYTHING_IPC_QUERY2: reply_hwnd, reply_msg, search_flags, offset, max, req_flags, sort
        search_bytes = search_text.encode('utf-16-le') + b'\x00\x00'
        reply_hwnd_32 = self._reply_hwnd & 0xFFFFFFFF
        request_flags = (self.EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME
                         | self.EVERYTHING_REQUEST_SIZE
                         | self.EVERYTHING_REQUEST_DATE_MODIFIED)
        header = struct.pack('<IIIIIII', reply_hwnd_32, 0, 0, 0, max_results,
                             request_flags, 1)
        query_data = header + search_bytes
        data_buf = ctypes.create_string_buffer(query_data)

        cds = self._COPYDATASTRUCT()
        cds.dwData = self.EVERYTHING_IPC_COPYDATA_QUERY2W
        cds.cbData = len(query_data)
        cds.lpData = ctypes.cast(data_buf, ctypes.c_void_p)

        result = self._user32.SendMessageW(
            everything_hwnd, self.WM_COPYDATA, self._reply_hwnd, ctypes.addressof(cds)
        )

        if result:
            msg = wt.MSG()
            end_time = time.time() + 5
            while time.time() < end_time and not self._ipc_got_reply:
                ret = self._user32.PeekMessageW(ctypes.byref(msg), self._reply_hwnd, 0, 0, 1)
                if ret:
                    self._user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.01)

        return list(self._ipc_results)
