"""Windows shell 的檔案操作。不依賴 Qt。

只認路徑與視窗代號（hwnd），成功與否用回傳值表達，錯誤訊息的呈現留給呼叫端
——同一個操作在主視窗與在拖放時要顯示的措辭不同。

**所有交給 shell API 的路徑都必須先 `os.path.normpath`。** Qt 給的路徑是正斜線
（`QUrl.toLocalFile()` 回 `D:/a/b.txt`），shell API 不吃，實測會回錯誤碼 183
並且什麼都不做。見 docs/spec/fileops.md 的 FOP-15a。
"""

import ctypes
import ctypes.wintypes as wt
import os
from collections import namedtuple


def create_shortcuts(src_paths, target_dir):
    """在 target_dir 建立 src_paths 的 Windows 捷徑（.lnk）。

    失敗時直接拋出，由呼叫端決定怎麼告訴使用者。不存在的來源安靜略過——
    多選拖放時其中一個檔案剛好被別的程式刪掉，不該讓整批都失敗。

    **[未驗]** 這裡刻意沒有 normpath，維持搬過來之前的行為。
    `IShellLink.SetPath` 收到正斜線會怎樣還沒實測；要改的話得先寫一支會失敗的
    測試，不能順手加。
    """
    import pythoncom
    from win32com.shell import shell

    pythoncom.CoInitialize()
    try:
        for src in src_paths:
            if not os.path.exists(src):
                continue
            base = os.path.splitext(os.path.basename(src))[0]
            lnk_path = os.path.join(target_dir, f"{base} - 捷徑.lnk")
            link = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink, None,
                pythoncom.CLSCTX_INPROC_SERVER,
                shell.IID_IShellLink,
            )
            link.SetPath(src)
            link.SetWorkingDirectory(os.path.dirname(src))
            persist = link.QueryInterface(pythoncom.IID_IPersistFile)
            persist.Save(lnk_path, True)
    finally:
        pythoncom.CoUninitialize()


# SHFileOperationW 的參數結構與旗標。原本在三個地方各定義一次
# （回收筒、主視窗的檔案操作、拖放），三份一模一樣。
class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ('hwnd', wt.HWND),
        ('wFunc', wt.UINT),
        ('pFrom', ctypes.c_wchar_p),
        ('pTo', ctypes.c_wchar_p),
        ('fFlags', ctypes.c_ushort),
        ('fAnyOperationsAborted', wt.BOOL),
        ('hNameMappings', ctypes.c_void_p),
        ('lpszProgressTitle', ctypes.c_wchar_p),
    ]


FO_MOVE = 0x0001
FO_COPY = 0x0002
FOF_SIMPLEPROGRESS = 0x0100

# 沒有任何有效來源時的結果：什麼都沒做，也就談不上成功或失敗。
Outcome = namedtuple('Outcome', ('ran', 'code', 'aborted'))
NOTHING_TO_DO = Outcome(False, 0, False)


def plan_move_or_copy(src_paths, target_dir):
    """挑出真正要動的來源，回傳 (正規化後的目標目錄, 來源清單)。

    純函式，沒有 shell 呼叫，因此測得到。兩種來源會被剔除：已經不存在的
    （多選時其中一個剛好被別的程式刪掉），以及目標與來源是同一個位置的
    （拖回原地，shell 會跳出沒有意義的「取代檔案？」對話框）。
    """
    target_dir = os.path.normpath(target_dir)
    sources = []
    for src in src_paths:
        src = os.path.normpath(src)
        if not os.path.exists(src):
            continue
        dest = os.path.join(target_dir, os.path.basename(src))
        if os.path.abspath(src) == os.path.abspath(dest):
            continue
        sources.append(src)
    return target_dir, sources


def move_or_copy(hwnd, src_paths, target_dir, op):
    """以 SHFileOperationW 搬移或複製。回傳 Outcome(ran, code, aborted)。

    不顯示任何訊息——呈現留給呼叫端，同一個操作在主視窗與在拖放時的措辭不同。
    """
    target_dir, sources = plan_move_or_copy(src_paths, target_dir)
    if not sources:
        return NOTHING_TO_DO

    from_buf = ctypes.create_unicode_buffer('\0'.join(sources) + '\0\0')
    to_buf = ctypes.create_unicode_buffer(target_dir + '\0')

    op_struct = SHFILEOPSTRUCTW()
    op_struct.hwnd = hwnd
    op_struct.wFunc = FO_MOVE if op == 'move' else FO_COPY
    op_struct.pFrom = ctypes.cast(from_buf, ctypes.c_wchar_p)
    op_struct.pTo = ctypes.cast(to_buf, ctypes.c_wchar_p)
    op_struct.fFlags = FOF_SIMPLEPROGRESS
    op_struct.lpszProgressTitle = '正在處理檔案...'

    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op_struct))
    return Outcome(True, code, bool(op_struct.fAnyOperationsAborted))
