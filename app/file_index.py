import os
import ctypes
import marshal
import threading


# Windows file attribute for junctions / symlinks; skipped to avoid scan loops.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_DRIVE_FIXED = 3


def _fixed_drive_roots():
    """列舉所有本機固定磁碟（C:\\、D:\\…），排除卸除式/網路/光碟機。"""
    roots = []
    try:
        kernel32 = ctypes.windll.kernel32
        bitmask = kernel32.GetLogicalDrives()
    except Exception:
        return roots
    for i in range(26):
        if not (bitmask & (1 << i)):
            continue
        root = f"{chr(ord('A') + i)}:\\"
        try:
            if kernel32.GetDriveTypeW(root) == _DRIVE_FIXED:
                roots.append(root)
        except Exception:
            pass
    return roots


class FileMetadataCache:
    """開啟時於背景執行緒掃描固定磁碟，預載每個檔案的 is_dir/size/mtime。

    搜尋結果渲染時改讀此快取，省去對每個結果逐一 os.stat 的磁碟 I/O。
    快取未命中（尚未掃到或新檔案）時，呼叫端自行 fallback 到 os.stat。

    執行緒安全：背景執行緒只對 dict 做逐筆寫入，GUI 執行緒只做 .get 讀取；
    在 CPython GIL 下兩者皆為原子操作，讀到的不是舊值就是新值，不會崩潰。
    """

    def __init__(self, cache_path=None):
        self._entries = {}
        self._thread = None
        self._stop = threading.Event()
        self._cache_path = cache_path
        self.ready = False

    @staticmethod
    def _key(path):
        return os.path.normcase(os.path.normpath(path))

    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._build, name="FileMetadataCache", daemon=True
        )
        self._thread.start()

    def stop(self, wait_timeout=None):
        """請求停止；可選擇等待背景執行緒收尾存檔（關閉程式時用）。"""
        self._stop.set()
        if wait_timeout is not None and self._thread is not None:
            self._thread.join(wait_timeout)

    def _build(self):
        """背景流程：先載入上次存檔（秒級，立即可用），再全碟重掃更新，最後存檔。

        重掃只會往已載入的集合「新增」項目、不刪除，所以即使中途被中止，
        存回去的索引也不會比上次少，可安全保存部分進度。"""
        self._load_persisted()
        self._scan_all()
        if self._entries:
            self._save_persisted()

    def _load_persisted(self):
        """載入上次存到磁碟的索引；成功即標記 ready，讓開啟後馬上有資料可用。"""
        if not self._cache_path or not os.path.exists(self._cache_path):
            return
        try:
            with open(self._cache_path, 'rb') as f:
                data = marshal.load(f)
            if isinstance(data, dict):
                self._entries = data
                self.ready = True
        except Exception:
            pass

    def _save_persisted(self):
        """以 marshal 將索引寫到磁碟（原子取代），供下次開啟快速載入。"""
        if not self._cache_path:
            return
        tmp = self._cache_path + '.tmp'
        try:
            with open(tmp, 'wb') as f:
                marshal.dump(self._entries, f)
            os.replace(tmp, self._cache_path)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    @property
    def count(self):
        return len(self._entries)

    def lookup(self, path):
        """回傳 (is_dir, size, mtime)；未命中回傳 None。"""
        return self._entries.get(self._key(path))

    def update(self, path):
        """單一路徑刷新（檔案操作後可選用），抓不到就移除舊項。"""
        key = self._key(path)
        try:
            st = os.stat(path)
            self._entries[key] = (os.path.isdir(path), st.st_size, st.st_mtime)
        except OSError:
            self._entries.pop(key, None)

    def _scan_all(self):
        for root in _fixed_drive_roots():
            if self._stop.is_set():
                break
            self._scan_tree(root)
        self.ready = True

    def _scan_tree(self, root):
        """以明確堆疊迭代掃描，避免深層目錄遞迴爆掉，並跳過接合點避免迴圈。"""
        entries = self._entries
        stack = [root]
        while stack:
            if self._stop.is_set():
                return
            current = stack.pop()
            try:
                scandir_it = os.scandir(current)
            except OSError:
                continue
            with scandir_it:
                for entry in scandir_it:
                    if self._stop.is_set():
                        return
                    try:
                        st = entry.stat(follow_symlinks=False)
                        attrs = getattr(st, 'st_file_attributes', 0)
                        if attrs & _FILE_ATTRIBUTE_REPARSE_POINT:
                            # 接合點/符號連結：記錄但不深入，避免循環掃描
                            is_dir = entry.is_dir(follow_symlinks=False)
                            entries[self._key(entry.path)] = (is_dir, st.st_size, st.st_mtime)
                            continue
                        is_dir = entry.is_dir(follow_symlinks=False)
                        entries[self._key(entry.path)] = (is_dir, st.st_size, st.st_mtime)
                        if is_dir:
                            stack.append(entry.path)
                    except OSError:
                        continue
