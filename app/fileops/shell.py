"""Windows shell 的檔案操作。不依賴 Qt。

只認路徑與視窗代號（hwnd），成功與否用回傳值表達，錯誤訊息的呈現留給呼叫端
——同一個操作在主視窗與在拖放時要顯示的措辭不同。

**所有交給 shell API 的路徑都必須先 `os.path.normpath`。** Qt 給的路徑是正斜線
（`QUrl.toLocalFile()` 回 `D:/a/b.txt`），shell API 不吃，實測會回錯誤碼 183
並且什麼都不做。見 docs/spec/fileops.md 的 FOP-15a。
"""

import os


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
