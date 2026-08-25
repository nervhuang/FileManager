"""`config.ini` 的讀寫。不依賴 Qt。

這一層只回答兩件事：**檔案裡寫了什麼**，以及**拿不到時該用什麼**。
把值套到 widget 上不屬於這裡——那是各功能域自己的事。

會把 configparser 藏在這裡，是因為它的行為有幾個容易踩到的地方：
`fallback=` 只在鍵不存在時生效、寫入前必須先 `add_section`、值一律得是字串。
這些細節散在 129 行的 `load_config` 裡時，每加一個設定就要重新踩一次。
"""

import base64
import configparser
import json
import os

from .. import paths
from .config import cfg_bool, cfg_int, cfg_int_list

# 三面板時代遺留的鍵。留著不會壞事，但會一直跟著設定檔跑，
# 讓人以為它們還有作用。寫出時一併清掉。
LEGACY_KEYS = (
    ('General', 'left_dir'),
    ('Layout', 'splitter_sizes'),
    ('Columns', 'left_col_widths'),
    ('Tabs', 'left_tabs'),
    ('Tabs', 'left_tabs_current'),
)

# 寫入前必須存在的段落。configparser 對不存在的段落是直接拋例外，不是自動建。
SECTIONS = ('General', 'Layout', 'Columns', 'Sort', 'Tabs', 'Exclude')


class ConfigStore:
    """一份 `config.ini` 的內容。

    `load()` 讀進來，用 `get_*` 取值，用 `set_*` 改，最後 `save()` 寫回。
    不認得的鍵原樣保留——這個程式不是設定檔的唯一寫入者。
    """

    def __init__(self, path, parser=None):
        self.path = path
        self._cfg = parser if parser is not None else configparser.ConfigParser()

    @classmethod
    def load(cls, path=None):
        if path is None:
            path = paths.config_path()
        cfg = configparser.ConfigParser()
        # read() 對不存在的檔案是安靜略過，正好就是「首次啟動」該有的行為。
        cfg.read(path, encoding='utf-8')
        # 缺的段落在讀進來時就補齊，寫出的檔案才維持固定的段落順序：
        # 檔案裡原有的照原順序，缺的依 SECTIONS 附在後面。
        for section in SECTIONS:
            if not cfg.has_section(section):
                cfg.add_section(section)
        return cls(path, cfg)

    # ── 讀 ────────────────────────────────────────────────────────────────

    def get_str(self, section, option, fallback=''):
        return self._cfg.get(section, option, fallback=fallback)

    def get_int(self, section, option, fallback, minimum=None, maximum=None):
        value = cfg_int(self._cfg, section, option, fallback)
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    def get_bool(self, section, option, fallback):
        return cfg_bool(self._cfg, section, option, fallback)

    def get_int_list(self, section, option):
        """回整數清單；沒有這個鍵或有任一項解析失敗都回空清單。"""
        return cfg_int_list(self.get_str(section, option))

    def get_json(self, section, option, fallback):
        """回解析後的 JSON；沒有這個鍵或內容壞掉都回 fallback。"""
        raw = self.get_str(section, option)
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return fallback

    def get_bytes(self, section, option):
        """回 base64 解出的位元組；沒有這個鍵或不是合法 base64 都回 None。

        用於 Qt 的視窗幾何：`saveGeometry()` 給的是不透明的位元組，
        塞進 ini 得先編碼。
        """
        raw = self.get_str(section, option)
        if not raw:
            return None
        try:
            return base64.b64decode(raw.encode('ascii'))
        except Exception:
            return None

    def has(self, section, option):
        """鍵是否存在。

        「鍵存在但為空字串」與「鍵不存在」是不同的兩件事，欄位顯示設定就靠這個
        分辨（docs/spec/settings.md 的 SET-10），所以得問得出來。
        """
        return self._cfg.has_option(section, option)

    # ── 寫 ────────────────────────────────────────────────────────────────

    def set(self, section, option, value):
        """寫入一個值。段落不存在會自動建立，值一律轉成字串。"""
        if not self._cfg.has_section(section):
            self._cfg.add_section(section)
        self._cfg.set(section, option, str(value))

    def set_bool(self, section, option, value):
        self.set(section, option, 'true' if value else 'false')

    def set_json(self, section, option, value):
        self.set(section, option, json.dumps(value, ensure_ascii=False))

    def set_int_list(self, section, option, values):
        self.set(section, option, ','.join(str(v) for v in values))

    def set_bytes(self, section, option, value):
        self.set(section, option, base64.b64encode(bytes(value)).decode('ascii'))

    def drop_legacy_keys(self):
        for section, option in LEGACY_KEYS:
            if self._cfg.has_option(section, option):
                self._cfg.remove_option(section, option)

    def save(self):
        self.drop_legacy_keys()
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            self._cfg.write(f)
