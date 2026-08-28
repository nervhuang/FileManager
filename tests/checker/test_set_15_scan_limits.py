"""更新檢查筆數的設定與套用。見 docs/spec/settings.md 的 SET-15、
docs/spec/checker.md 的「取幾筆」。

原本 25／50 寫死在 scanner.py。這裡守三件事：值壞掉要退回預設、
存檔只碰自己的兩個鍵、掃描真的照設定的筆數抓。
"""
import configparser

import pytest

from app.checker import limits, scanner
from app.settings import ConfigStore

pytestmark = pytest.mark.logic


def _store(tmp_path, **checker_keys):
    cfg = configparser.ConfigParser()
    if checker_keys:
        cfg.add_section(limits.SECTION)
        for key, value in checker_keys.items():
            cfg.set(limits.SECTION, key, str(value))
    return ConfigStore(str(tmp_path / 'config.ini'), cfg)


def test_defaults_when_key_missing(tmp_path):
    assert limits.load(_store(tmp_path)) == limits.DEFAULTS


@pytest.mark.parametrize('raw', ['', 'abc', '  ', '12.5'])
def test_broken_value_falls_back_to_default(tmp_path, raw):
    """SET-15：值壞掉的代價是失去這個設定，不是掃描炸掉。"""
    loaded = limits.load(_store(tmp_path, first_run_limit=raw, max_items=raw))
    assert loaded == limits.DEFAULTS


def test_out_of_range_is_clamped(tmp_path):
    loaded = limits.load(_store(tmp_path, first_run_limit=1, max_items=99999))
    assert loaded == limits.Limits(limits.MINIMUM, limits.MAXIMUM)


def test_save_keeps_foreign_keys(tmp_path):
    """SET-15：只改自己的兩個鍵，別人的鍵原樣留著。"""
    store = _store(tmp_path)
    store.set('General', 'font_size', 13)
    store.save()

    limits.save(limits.Limits(75, 150), ConfigStore.load(str(tmp_path / 'config.ini')))

    reloaded = ConfigStore.load(str(tmp_path / 'config.ini'))
    assert limits.load(reloaded) == limits.Limits(75, 150)
    assert reloaded.get_str('General', 'font_size') == '13'


def test_save_clamps_before_writing(tmp_path):
    written = limits.save(limits.Limits(0, 99999), _store(tmp_path))
    assert written == limits.Limits(limits.MINIMUM, limits.MAXIMUM)


# ── 掃描真的照設定的筆數抓 ────────────────────────────────────────────────

class _Fetch:
    """只回頁面，不碰網路。每頁 25 筆，發布時間一路往回退。"""

    cancelled = False

    def __init__(self):
        self.pages = []

    def fetch_tag_page(self, tag, page=0):
        self.pages.append(page)
        base = page * scanner.PAGE_SIZE
        return [(str(1000 + base + i), f'tok{base + i}', '2026-01-01 00:00')
                for i in range(scanner.PAGE_SIZE)]

    def fetch_metadata(self, pairs):
        return {}


def test_first_run_limit_controls_how_many_are_fetched():
    fetch = _Fetch()
    result = scanner.scan_entity({'id': 1, 'name': 'X', 'english_name': 'X'},
                                 fetch, lambda e: [], last_scan_at=None,
                                 first_run_limit=100)
    assert len(fetch.pages) == 4, '100 筆＝4 頁'
    assert result['items'] == []


def test_max_items_caps_the_walk_back():
    import datetime

    fetch = _Fetch()
    scanner.scan_entity({'id': 1, 'name': 'X', 'english_name': 'X'},
                        fetch, lambda e: [],
                        last_scan_at=datetime.datetime(2020, 1, 1),
                        max_items=75)
    assert len(fetch.pages) == 3, '75 筆＝3 頁，追不到 2020 也要停'
