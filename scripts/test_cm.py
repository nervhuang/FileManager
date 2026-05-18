from win32com.shell import shell, shellcon
import pythoncom

pythoncom.CoInitialize()
try:
    desktop = shell.SHGetDesktopFolder()
    parent_pidl = shell.SHParseDisplayName(r'C:\Windows', 0)[0]
    parent_sf = desktop.BindToObject(parent_pidl, None, shell.IID_IShellFolder)
    pd_result = parent_sf.ParseDisplayName(0, None, 'notepad.exe')
    print('ParseDisplayName len:', len(pd_result), 'types:', [type(x).__name__ for x in pd_result])
    child_pidl = pd_result[1]

    icm_raw = parent_sf.GetUIObjectOf(0, [child_pidl], shell.IID_IContextMenu, 0)
    print('GetUIObjectOf type:', type(icm_raw).__name__)
    print('GetUIObjectOf value:', repr(icm_raw)[:200])
    if isinstance(icm_raw, tuple):
        for i, v in enumerate(icm_raw):
            print(f'  [{i}] type={type(v).__name__}', 'hasQCM=', hasattr(v, 'QueryContextMenu'), 'hasQI=', hasattr(v, 'QueryInterface'))
            if hasattr(v, 'QueryInterface'):
                try:
                    icm2 = v.QueryInterface(shell.IID_IContextMenu)
                    print('       QI(IContextMenu) ->', type(icm2).__name__, 'hasQCM=', hasattr(icm2, 'QueryContextMenu'))
                except Exception as e:
                    print('       QI error:', e)
    else:
        print('Not a tuple - has QueryContextMenu:', hasattr(icm_raw, 'QueryContextMenu'))

    # Also try IContextMenu2/3
    try:
        IID_ICM2 = pythoncom.MakeIID('{000214F4-0000-0000-C000-000000000046}')
        icm2 = parent_sf.GetUIObjectOf(0, [child_pidl], IID_ICM2, 0)
        print('IContextMenu2 type:', type(icm2).__name__)
    except Exception as e:
        print('IContextMenu2 error:', e)

finally:
    pythoncom.CoUninitialize()
