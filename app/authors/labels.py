"""作者／團體的顯示用字串。不依賴 Qt。

只有一份 `TYPE_LABEL`，但它同時被面板、編輯對話框與變更紀錄用到。放在其中
任何一邊，另外兩邊就得反過來 import 那一邊——三個檔案於是繞成一圈。
"""

from . import db as authors_db

TYPE_LABEL = {authors_db.AUTHOR: '作者', authors_db.CIRCLE: '團體'}
