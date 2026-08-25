"""Windows shell 的檔案操作。不依賴 Qt。

只認路徑與視窗代號（hwnd），成功與否用回傳值表達，錯誤訊息的呈現留給呼叫端
——同一個操作在主視窗與在拖放時要顯示的措辭不同。

**交給 shell API 的路徑都要先 `os.path.normpath`。** Qt 給的是正斜線
（`QUrl.toLocalFile()` 與 `QFileSystemModel.filePath()` 都回 `D:/a/b.txt`）。
實測：關鍵是 `pTo`——目標目錄帶正斜線時回錯誤碼 183 且什麼都不做；`pFrom`
反而容忍。`FO_DELETE` 因為 `pTo` 是 None，不受影響。見 docs/spec/fileops.md
的 FOP-15a。
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


FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_WANTNUKEWARNING = 0x4000


def delete_to_recycle_bin(hwnd, paths):
    """把 paths 送進回收筒。回傳 Outcome(ran, code, aborted)。

    `FOF_ALLOWUNDO` 是「送回收筒」而不是永久刪除；`FOF_WANTNUKEWARNING` 讓
    無法送回收筒的情況（容量不足、網路磁碟）由系統跳警告，而不是靜默永久刪除
    （docs/spec/fileops.md 的 FOP-7、FOP-9）。

    這裡刻意沒有 normpath：`FO_DELETE` 的 `pTo` 是 None，實測對正斜線沒有問題
    （見 FOP-15a 的對照表），維持搬過來之前的行為。
    """
    existing = [p for p in paths if os.path.exists(p)]
    if not existing:
        return NOTHING_TO_DO

    path_buf = ctypes.create_unicode_buffer('\0'.join(existing) + '\0')
    op = SHFILEOPSTRUCTW()
    op.hwnd = hwnd
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(path_buf, ctypes.c_wchar_p)
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_WANTNUKEWARNING

    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return Outcome(True, code, bool(op.fAnyOperationsAborted))


# show_context_menu 的三種結果。
NOTHING_CHOSEN = None
CHOSE_RENAME = 'rename'          # 使用者選了「重新命名」，但**沒有**執行
INVOKED = 'invoked'              # 已執行使用者選的命令


def show_context_menu(hwnd, paths, x, y):
    """顯示 Windows 原生的右鍵選單（與檔案總管完全相同的那一份）。

    回傳 NOTHING_CHOSEN / CHOSE_RENAME / INVOKED。Qt 端的後續動作（重新命名、
    延遲刷新）留給呼叫端——這一層不認得 Qt。

    **rename 不由這裡執行。** Shell 的 InvokeCommand("rename") 會送 WM_CLOSE 給
    hwnd，把 Qt 主視窗關掉。所以偵測到 rename verb 就回報，讓呼叫端改用自己的
    F2 重新命名流程（docs/spec/fileops.md 的 FOP-20）。
    """
    from win32com.shell import shell, shellcon
    import win32con
    import win32gui
    import pythoncom

    pythoncom.CoInitialize()
    try:
        # GetUIObjectOf 要求所有項目同一個父目錄，因此依第一個路徑的父目錄分組。
        parent_dir = os.path.normpath(os.path.dirname(os.path.abspath(paths[0])))
        norm_parent = os.path.normcase(parent_dir)
        same_parent = [
            p for p in paths
            if os.path.normcase(
                os.path.normpath(os.path.dirname(os.path.abspath(p)))
            ) == norm_parent
        ]

        desktop = shell.SHGetDesktopFolder()
        # SHParseDisplayName 在這個 pywin32 版本只接受兩個參數：(name, sfgaoMask)
        parent_pidl = shell.SHParseDisplayName(parent_dir, 0)[0]
        # BindToObject 的 pbc 傳 None 代表 NULL
        parent_sf = desktop.BindToObject(parent_pidl, None, shell.IID_IShellFolder)

        # ParseDisplayName 回傳 (eaten, pidl, attrs)，取 index 1
        child_pidls = [parent_sf.ParseDisplayName(hwnd, None, os.path.basename(p))[1]
                       for p in same_parent]

        # GetUIObjectOf 回傳 (reserved, IContextMenu)，取 index 1
        icm = parent_sf.GetUIObjectOf(hwnd, child_pidls, shell.IID_IContextMenu, 0)[1]

        hmenu = win32gui.CreatePopupMenu()
        icm.QueryContextMenu(hmenu, 0, 1, 0x7FFF,
                             shellcon.CMF_EXPLORE | shellcon.CMF_CANRENAME)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass

        cmd = win32gui.TrackPopupMenu(
            hmenu,
            win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON | win32con.TPM_RETURNCMD,
            x, y, 0, hwnd, None)
        win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(hmenu)

        if cmd <= 0:
            return NOTHING_CHOSEN

        try:
            verb = icm.GetCommandString(cmd - 1, shellcon.GCS_VERBW)
        except Exception:
            verb = ''
        if verb.lower() == 'rename':
            return CHOSE_RENAME

        icm.InvokeCommand((0, hwnd, cmd - 1, None, None, win32con.SW_SHOWNORMAL, 0, None))
        return INVOKED
    finally:
        pythoncom.CoUninitialize()


# IDropTarget::Drop 用的滑鼠鍵與拖放效果旗標。
MK_RBUTTON = 2
DROPEFFECT_NONE = 0
DROPEFFECT_ALL = 7


def right_drag_drop(hwnd, src_paths, target_dir, screen_x, screen_y):
    """以 Shell 的 `IDropTarget::Drop(MK_RBUTTON)` 模擬右鍵拖放。

    Shell 會自己跳出原生選單（移動／複製／建立捷徑／取消）並執行使用者選的動作，
    我們不必自己畫那個選單，也不必自己判斷該做什麼。

    回傳 True 代表已完成，False 代表使用者取消。失敗時直接拋出——呼叫端各自有
    自己的後備 Qt 選單（docs/spec/fileops.md 的 FOP-16、FOP-17）。

    座標要的是**螢幕座標**，不是 viewport 座標。呼叫端各自的 viewport 不同，
    換算留在那一側。
    """
    from win32com.shell import shell
    import pythoncom

    pythoncom.CoInitialize()
    try:
        desktop = shell.SHGetDesktopFolder()

        # 來源 IDataObject
        src_parent = os.path.normpath(os.path.dirname(os.path.abspath(src_paths[0])))
        src_parent_pidl = shell.SHParseDisplayName(src_parent, 0)[0]
        src_sf = desktop.BindToObject(src_parent_pidl, None, shell.IID_IShellFolder)
        child_pidls = [src_sf.ParseDisplayName(hwnd, None, os.path.basename(p))[1]
                       for p in src_paths]
        data_obj = src_sf.GetUIObjectOf(
            hwnd, child_pidls, pythoncom.IID_IDataObject, 0)[1]

        # 目標資料夾的 IDropTarget
        tdir = os.path.normpath(target_dir)
        tparent_pidl = shell.SHParseDisplayName(os.path.dirname(tdir), 0)[0]
        tparent_sf = desktop.BindToObject(tparent_pidl, None, shell.IID_IShellFolder)
        tdir_pidl = tparent_sf.ParseDisplayName(hwnd, None, os.path.basename(tdir))[1]
        drop_target = tparent_sf.GetUIObjectOf(
            hwnd, [tdir_pidl], pythoncom.IID_IDropTarget, 0)[1]

        point = (screen_x, screen_y)
        drop_target.DragEnter(data_obj, MK_RBUTTON, point, DROPEFFECT_ALL)
        return drop_target.Drop(data_obj, MK_RBUTTON, point, DROPEFFECT_ALL) != DROPEFFECT_NONE
    finally:
        pythoncom.CoUninitialize()
