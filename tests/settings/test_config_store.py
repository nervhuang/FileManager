"""ConfigStore 的純邏輯測試：不需要 QApplication，也不碰主視窗。

設定層抽出來的主要好處就在這裡——設定檔的格式、預設值與容錯本來就是純資料
問題，不必為了測它建一個 1400×900 的視窗。這些測試進 pre-commit 的快跑集合。
"""
import configparser

import pytest

from app.settings import ConfigStore
from app.settings.store import LEGACY_KEYS, SECTIONS

pytestmark = pytest.mark.logic


@pytest.fixture
def store(tmp_path):
    return ConfigStore.load(tmp_path / 'config.ini')


def _written(store):
    cfg = configparser.ConfigParser()
    cfg.read(store.path, encoding='utf-8')
    return cfg


# ── 讀不到就用預設 ────────────────────────────────────────────────────────

def test_missing_file_is_not_an_error(tmp_path):
    """SET-5：首次啟動沒有 config.ini 是正常狀態。"""
    store = ConfigStore.load(tmp_path / 'nope.ini')
    assert store.get_int('General', 'font_size', 10) == 10
    assert store.get_bool('Exclude', 'enabled', False) is False
    assert store.get_str('Layout', 'window_state', 'normal') == 'normal'


@pytest.mark.parametrize("raw", ['', '不是數字', '3.5', 'true', '  '])
def test_set_13_get_int_falls_back_on_any_bad_value(store, raw):
    """SET-13：鍵存在但值壞掉時退回預設，不得拋例外。

    這正是 configparser 原生 getint 做不到的：它的 fallback 只在鍵不存在時生效。
    """
    store.set('General', 'font_size', raw)
    assert store.get_int('General', 'font_size', 10) == 10


@pytest.mark.parametrize("raw", ['', '也不是布林', '2', '是'])
def test_set_13_get_bool_falls_back_on_any_bad_value(store, raw):
    store.set('Exclude', 'enabled', raw)
    assert store.get_bool('Exclude', 'enabled', False) is False


@pytest.mark.parametrize("raw, expected", [
    ('1,2,3', [1, 2, 3]),
    (' 4 , 5 ', [4, 5]),
    ('', []),
    ('1,,2', [1, 2]),
    ('1,壞,3', []),          # 有一項壞掉就整組放棄
    ('abc', []),
])
def test_get_int_list(store, raw, expected):
    """整組回空而不是逐項略過：少一項的尺寸清單套下去會讓版面錯位。"""
    store.set('Layout', 'right_splitter_sizes', raw)
    assert store.get_int_list('Layout', 'right_splitter_sizes') == expected


def test_get_json_falls_back_on_broken_content(store):
    store.set('Exclude', 'dirs', '[這不是 JSON')
    assert store.get_json('Exclude', 'dirs', ['預設']) == ['預設']


def test_get_bytes_falls_back_on_broken_base64(store):
    store.set('Layout', 'window_geometry', '****不是 base64****')
    assert store.get_bytes('Layout', 'window_geometry') is None


def test_int_is_clamped_to_range(store):
    store.set('General', 'font_size', 999)
    assert store.get_int('General', 'font_size', 10, minimum=6, maximum=72) == 72
    store.set('General', 'font_size', 1)
    assert store.get_int('General', 'font_size', 10, minimum=6, maximum=72) == 6


# ── 「鍵不存在」與「鍵是空字串」是兩件事 ──────────────────────────────────

def test_set_10_has_distinguishes_absent_from_empty(store):
    """SET-10：欄位顯示設定靠這個分辨「全部顯示」與「採用預設隱藏欄」。"""
    assert store.has('Columns', 'mid_col_hidden') is False
    store.set('Columns', 'mid_col_hidden', '')
    assert store.has('Columns', 'mid_col_hidden') is True
    assert store.get_str('Columns', 'mid_col_hidden') == ''


# ── 寫 ────────────────────────────────────────────────────────────────────

def test_set_creates_missing_section(tmp_path):
    """configparser 對不存在的段落是拋例外，不是自動建。"""
    store = ConfigStore.load(tmp_path / 'config.ini')
    store.set('沒見過的段落', 'k', 'v')
    store.save()
    assert _written(store).get('沒見過的段落', 'k') == 'v'


def test_values_round_trip_through_the_file(tmp_path):
    store = ConfigStore.load(tmp_path / 'config.ini')
    store.set('General', 'font_size', 17)
    store.set_bool('Layout', 'authors_panel_visible', False)
    store.set_json('Exclude', 'dirs', ['D:\\NAS', '中文路徑'])
    store.set_int_list('Layout', 'right_splitter_sizes', [401, 402])
    store.set_bytes('Layout', 'window_geometry', b'\x00\x01\xfe\xff')
    store.save()

    again = ConfigStore.load(tmp_path / 'config.ini')
    assert again.get_int('General', 'font_size', 0) == 17
    assert again.get_bool('Layout', 'authors_panel_visible', True) is False
    assert again.get_json('Exclude', 'dirs', []) == ['D:\\NAS', '中文路徑']
    assert again.get_int_list('Layout', 'right_splitter_sizes') == [401, 402]
    assert again.get_bytes('Layout', 'window_geometry') == b'\x00\x01\xfe\xff'


def test_json_keeps_non_ascii_readable(tmp_path):
    """中文與日文路徑不要被寫成 \\uXXXX，設定檔是使用者看得到的東西。"""
    store = ConfigStore.load(tmp_path / 'config.ini')
    store.set_json('Exclude', 'dirs', ['D:\\同人誌'])
    store.save()
    assert '同人誌' in (tmp_path / 'config.ini').read_text(encoding='utf-8')


def test_unknown_keys_survive_a_save(tmp_path):
    """這個程式不是設定檔的唯一寫入者，不認得的鍵要原樣留著。"""
    path = tmp_path / 'config.ini'
    path.write_text('[General]\nsomeone_elses_key = 保留我\n', encoding='utf-8')
    store = ConfigStore.load(path)
    store.set('General', 'font_size', 12)
    store.save()
    assert _written(store).get('General', 'someone_elses_key') == '保留我'


def test_legacy_three_panel_keys_are_dropped_on_save(tmp_path):
    path = tmp_path / 'config.ini'
    by_section = {}
    for section, option in LEGACY_KEYS:
        by_section.setdefault(section, []).append(option)

    lines = []
    for section, options in by_section.items():
        lines.append(f'[{section}]')
        lines.extend(f'{option} = 舊值' for option in options)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    store = ConfigStore.load(path)
    store.save()

    cfg = _written(store)
    for section, option in LEGACY_KEYS:
        assert not cfg.has_option(section, option)


def test_all_expected_sections_exist_after_save(tmp_path):
    store = ConfigStore.load(tmp_path / 'config.ini')
    store.save()
    cfg = _written(store)
    for section in SECTIONS:
        assert cfg.has_section(section), f'{section} 應該存在'
