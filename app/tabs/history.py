"""導覽歷史：瀏覽器式的上一頁／下一頁。不依賴 Qt。

規格見 docs/spec/tabs.md 的 TAB-22 到 TAB-25。

只管一串路徑與一個游標，不碰檔案系統——「這個目錄還在不在」是呼叫端的事，
歷史本身不該因為某個目錄被刪掉就自己改寫。
"""

import os


class NavigationHistory:
    """一串走過的路徑，加上目前位在第幾個。

    行為與瀏覽器一致：往回走之後再導覽到新的地方，前方的紀錄會被截掉——
    分支出去就回不到原來那條線了。
    """

    def __init__(self):
        self._entries = []
        self._index = -1

    def __len__(self):
        return len(self._entries)

    @property
    def entries(self):
        return tuple(self._entries)

    @property
    def current(self):
        if 0 <= self._index < len(self._entries):
            return self._entries[self._index]
        return None

    @property
    def can_go_back(self):
        return self._index > 0

    @property
    def can_go_forward(self):
        return 0 <= self._index < len(self._entries) - 1

    def record(self, path):
        """記下一次導覽。回傳是否真的有記（重複目前位置時不記）。

        往回走之後再記新的地方，會先截掉前方的紀錄（TAB-24 的另一半：
        `back()` / `forward()` 本身不呼叫這裡，所以走歷史不會污染歷史）。
        """
        if not path:
            return False
        if self.current == path:
            return False
        if self._index < len(self._entries) - 1:
            del self._entries[self._index + 1:]
        self._entries.append(path)
        self._index = len(self._entries) - 1
        return True

    def go_back(self):
        """往回一步並回傳該路徑；已經在最前面則回 None。"""
        if not self.can_go_back:
            return None
        self._index -= 1
        return self._entries[self._index]

    def go_forward(self):
        """往前一步並回傳該路徑；已經在最後面則回 None。"""
        if not self.can_go_forward:
            return None
        self._index += 1
        return self._entries[self._index]


def parent_of(path):
    """回傳上一層目錄；已經在根目錄或路徑為空時回 None。

    `os.path.dirname` 對 `C:\\` 回的是 `C:\\` 自己，不是空字串——這就是判斷
    「已經到頂」的方式（TAB-22）。
    """
    if not path:
        return None
    normalised = os.path.normpath(path)
    parent = os.path.dirname(normalised)
    if not parent or parent == normalised:
        return None
    return parent
