"""SHL-12：不使用 Qt 內建圖示。

尺寸問題（`SP_BrowserReload`、`SP_MediaStop` 只出到 32×32，在 64px 工具列裡
會小一半）已由 test_shl_11 的實際渲染尺寸把關。這一支管的是另一半——**外觀**：
Windows 的立體光澤風格與自繪的實心填色語彙擺在同一條工具列上，一眼就看得出
是兩套東西，而那不是渲染尺寸量得出來的。

作法是掃原始碼。這是少數適合這樣做的規則：它講的是「不准用哪個 API」，
而不是「跑起來要有什麼行為」。
"""
import os
import re

import pytest

pytestmark = pytest.mark.logic

APP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'app')

# QStyle.standardIcon(...) 與 SP_ 系列常數就是 Qt 內建圖示的入口。
FORBIDDEN = re.compile(r'\bstandardIcon\s*\(|\bSP_[A-Za-z]')

# 註解與 docstring 裡提到它們是可以的——那正是在說明「為什麼不用」。
CODE_ONLY = re.compile(r'^\s*#')


def _python_files():
    for root, dirs, files in os.walk(APP_DIR):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for name in files:
            if name.endswith('.py'):
                yield os.path.join(root, name)


def _offending_lines(path):
    """回傳 (行號, 內容)。只看程式碼，略過註解與 docstring。"""
    hits = []
    in_docstring = False
    for number, line in enumerate(open(path, encoding='utf-8'), 1):
        triple = line.count('"""') + line.count("'''")
        if triple:
            # 奇數個＝跨行 docstring 的開頭或結尾，切換狀態；
            # 偶數個＝單行 docstring，狀態不變。兩種情況這一行都略過。
            if triple % 2:
                in_docstring = not in_docstring
            continue
        if in_docstring or CODE_ONLY.match(line):
            continue
        if FORBIDDEN.search(line):
            hits.append((number, line.strip()))
    return hits


def test_shl_12_no_module_uses_qt_system_icons():
    """全部工具列圖示自繪，集中在 app/icons.py 與各域自己的 icons 模組。"""
    offenders = {}
    for path in _python_files():
        hits = _offending_lines(path)
        if hits:
            offenders[os.path.relpath(path, APP_DIR)] = hits

    assert not offenders, (
        '以下地方用了 Qt 內建圖示（見 docs/spec/ui-shell.md 的 SHL-12）：\n' +
        '\n'.join(f'  {f}:{n}  {text}'
                  for f, hits in offenders.items() for n, text in hits))


def test_shl_12_this_check_would_notice_a_system_icon(tmp_path):
    """證明上面那支不是恆真。"""
    sample = tmp_path / 'sample.py'
    sample.write_text(
        'from PyQt5.QtWidgets import QStyle\n'
        'icon = self.style().standardIcon(QStyle.SP_TrashIcon)\n',
        encoding='utf-8')
    assert _offending_lines(str(sample))


def test_shl_12_mentions_in_comments_and_docstrings_are_allowed(tmp_path):
    """規格與註解裡要講得出「為什麼不用 SP_MediaStop」，不能因此被誤判。"""
    sample = tmp_path / 'sample.py'
    sample.write_text(
        '"""不能用 SP_BrowserReload：它只出到 32x32。"""\n'
        '# 也不要用 standardIcon(SP_MediaStop)\n'
        'x = 1\n',
        encoding='utf-8')
    assert _offending_lines(str(sample)) == []
