import ctypes
import ctypes.wintypes as wt
import struct
import time


class EverythingSDK:
    """Everything IPC client supporting both 1.5a (pure IPC2) and 1.4 (DLL)."""

    WM_COPYDATA = 0x004A
    EVERYTHING_IPC_COPYDATA_QUERY2W = 18
    EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME = 0x00000004

    # Window class names for different Everything versions
    _IPC_WNDCLASS_15A = "EVERYTHING_TASKBAR_NOTIFICATION_(1.5a)"
    _IPC_WNDCLASS_14 = "EVERYTHING_TASKBAR_NOTIFICATION"

    def __init__(self):
        self._setup_winapi()
        self._ipc_results = []
        self._ipc_got_reply = False
        self._wndproc_ref = self._WNDPROCTYPE(self._wnd_proc)

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
        """Parse EVERYTHING_IPC_LIST2 response data."""
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
            if str_start + str_bytes <= len(data):
                full_path = data[str_start:str_start + str_bytes].decode('utf-16-le', errors='replace')
                self._ipc_results.append(full_path)

    def _find_everything_hwnd(self):
        """Find Everything IPC window (1.5a or 1.4)."""
        hwnd = self._user32.FindWindowW(self._IPC_WNDCLASS_15A, None)
        if hwnd:
            return hwnd
        hwnd = self._user32.FindWindowW(self._IPC_WNDCLASS_14, None)
        return hwnd

    def is_available(self):
        return bool(self._find_everything_hwnd())

    def query(self, search_text, max_results=200):
        """Query Everything via IPC2 (WM_COPYDATA)."""
        self._ipc_results = []
        self._ipc_got_reply = False

        everything_hwnd = self._find_everything_hwnd()
        if not everything_hwnd:
            return []

        hInst = self._kernel32.GetModuleHandleW(None)
        cls_name = f"EvIPC{time.time_ns()}"

        wc = self._WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(self._WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hInst
        wc.lpszClassName = cls_name
        self._user32.RegisterClassExW(ctypes.byref(wc))

        reply_hwnd = self._user32.CreateWindowExW(
            0, cls_name, "R", 0, 0, 0, 0, 0, None, None, hInst, None
        )
        if not reply_hwnd:
            try:
                self._user32.UnregisterClassW(cls_name, hInst)
            except Exception:
                pass
            return []

        # Build EVERYTHING_IPC_QUERY2: reply_hwnd, reply_msg, search_flags, offset, max, req_flags, sort
        search_bytes = search_text.encode('utf-16-le') + b'\x00\x00'
        reply_hwnd_32 = reply_hwnd & 0xFFFFFFFF
        header = struct.pack('<IIIIIII', reply_hwnd_32, 0, 0, 0, max_results,
                             self.EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME, 1)
        query_data = header + search_bytes
        data_buf = ctypes.create_string_buffer(query_data)

        cds = self._COPYDATASTRUCT()
        cds.dwData = self.EVERYTHING_IPC_COPYDATA_QUERY2W
        cds.cbData = len(query_data)
        cds.lpData = ctypes.cast(data_buf, ctypes.c_void_p)

        result = self._user32.SendMessageW(
            everything_hwnd, self.WM_COPYDATA, reply_hwnd, ctypes.addressof(cds)
        )

        if result:
            msg = wt.MSG()
            end_time = time.time() + 5
            while time.time() < end_time and not self._ipc_got_reply:
                ret = self._user32.PeekMessageW(ctypes.byref(msg), reply_hwnd, 0, 0, 1)
                if ret:
                    self._user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.01)

        self._user32.DestroyWindow(reply_hwnd)
        try:
            self._user32.UnregisterClassW(cls_name, hInst)
        except Exception:
            pass

        return list(self._ipc_results)
