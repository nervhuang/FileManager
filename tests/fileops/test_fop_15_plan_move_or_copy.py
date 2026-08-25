"""FOP-15a：交給 shell 之前要挑出哪些來源真的要動，並把路徑正規化。

這是檔案操作域裡少數 CI 驗得到的部分——沒有 shell 呼叫、沒有 Qt，
只有路徑判斷。域裡其餘的（原生右鍵選單、右鍵拖放、回收筒）都得人工驗收，
所以能算成純函式的就盡量算出來。
"""
import os

import pytest

from app.fileops.shell import plan_move_or_copy

pytestmark = pytest.mark.logic


@pytest.fixture
def tree(tmp_path):
    src_dir = tmp_path / 'src'
    dst_dir = tmp_path / 'dst'
    src_dir.mkdir()
    dst_dir.mkdir()
    for name in ('a.txt', 'b.txt'):
        (src_dir / name).write_text('x', encoding='utf-8')
    return src_dir, dst_dir


def test_fop_15a_normalises_forward_slashes(tree):
    """Qt 給的路徑是正斜線，shell API 不吃——這裡就要換掉。"""
    src_dir, dst_dir = tree
    qt_src = str(src_dir / 'a.txt').replace(os.sep, '/')
    qt_dst = str(dst_dir).replace(os.sep, '/')

    target, sources = plan_move_or_copy([qt_src], qt_dst)

    assert '/' not in target.replace(':/', '')  # 磁碟機後的斜線已是 os.sep
    assert sources == [os.path.normpath(qt_src)]
    assert target == os.path.normpath(qt_dst)


def test_fop_15a_normalises_dot_dot(tree):
    src_dir, dst_dir = tree
    weird = str(src_dir / '..' / 'src' / 'a.txt')
    _, sources = plan_move_or_copy([weird], str(dst_dir))
    assert sources == [str(src_dir / 'a.txt')]


def test_fop_15a_drops_sources_that_no_longer_exist(tree):
    """多選拖放時其中一個檔案剛好被別的程式刪掉，不該讓整批失敗。"""
    src_dir, dst_dir = tree
    _, sources = plan_move_or_copy(
        [str(src_dir / 'a.txt'), str(src_dir / '不存在.txt')], str(dst_dir))
    assert sources == [str(src_dir / 'a.txt')]


def test_fop_15a_drops_sources_already_at_the_target(tree):
    """拖回原地不該送進 shell——它會跳出沒有意義的「取代檔案？」對話框。"""
    src_dir, _ = tree
    _, sources = plan_move_or_copy([str(src_dir / 'a.txt')], str(src_dir))
    assert sources == []


def test_fop_15a_keeps_the_order_of_the_remaining_sources(tree):
    src_dir, dst_dir = tree
    _, sources = plan_move_or_copy(
        [str(src_dir / 'b.txt'), str(src_dir / 'a.txt')], str(dst_dir))
    assert [os.path.basename(s) for s in sources] == ['b.txt', 'a.txt']


def test_fop_15a_empty_input_yields_nothing_to_do(tmp_path):
    target, sources = plan_move_or_copy([], str(tmp_path))
    assert sources == []
    assert target == str(tmp_path)
