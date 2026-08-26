"""剪貼簿的判定。不依賴 Qt。

實際存取 `QApplication.clipboard()` 留在呼叫端；這裡只做「拿到路徑之後怎麼算」。

規格見 docs/spec/fileops.md 的 FOP-5、FOP-6。
"""

import os

COPY = 'copy'
MOVE = 'move'


def normalise(paths):
    """把路徑正規化成可比較的形式（大小寫、分隔符、`..` 都統一）。

    只用來**比對**，不用來做檔案操作——實際操作要用原本的路徑，
    正規化過的形式在某些網路路徑上不等價。
    """
    return tuple(os.path.normcase(os.path.normpath(path)) for path in paths if path)


def unique_paths(paths):
    """去掉重複但保留順序。

    同一個檔案在剪貼簿裡出現兩次（多選時跨面板重複）不該被搬兩次。
    """
    seen = set()
    result = []
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def decide_paste_op(remembered_op, remembered_paths, pasted_paths):
    """貼上時該搬還是該複製。

    只有在**剪貼簿內容仍然是我們剪下的那一批**時才搬移。中間只要有別的程式
    寫過剪貼簿（在檔案總管複製了別的東西），就退回複製。

    這條規則的代價不對稱：判成複製最多是多一份檔案，判成搬移卻會動到使用者
    只想複製的東西。不確定時一律複製。
    """
    if remembered_op != MOVE:
        return COPY
    if normalise(pasted_paths) != tuple(remembered_paths):
        return COPY
    return MOVE
