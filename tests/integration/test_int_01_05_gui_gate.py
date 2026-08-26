"""INT-1 到 INT-5：Hermes MCP 的授權閘門與工具清單。

**這是安全條文，不是便利性設計。** 使用者的授權方式就是「把 FileManager 打開」；
關著的時候 Hermes 讀不到硬碟內容，也讀不到作者清單。

閘門必須套用在**每一個**工具上。只擋一部分的話，模型改叫另一個工具就繞過去了。
所以這裡是遍歷全部工具逐一驗證，不是抽查——新增第十個工具而忘了加閘門時，
測試要立刻紅。

不需要 QApplication、不需要 Everything、不需要真的管道。
"""
import argparse
import inspect

import pytest

from app import cli, hermes_mcp

pytestmark = pytest.mark.logic


def _tool_functions():
    """從模組裡撈出所有 MCP 工具。

    `@server.tool()` 回傳原函式不變，所以工具就是模組層那些 fm_ 開頭的函式。
    用「掃模組」而不是「寫死清單」：寫死的清單正是這條規則會被繞過的方式。
    """
    return {
        name: obj for name, obj in vars(hermes_mcp).items()
        if name.startswith('fm_') and inspect.isfunction(obj)
    }


@pytest.fixture
def gui_closed(monkeypatch):
    monkeypatch.setattr(hermes_mcp.gui_bridge, 'gui_is_running', lambda: False)


def _minimal_args(fn):
    """給每個必填參數一個型別上說得過去的值。

    閘門必須在參數處理**之前**就擋下來，所以這些值長什麼樣不重要——
    重要的是不要因為缺參數而拋 TypeError，那樣就測不到閘門了。
    """
    args = {}
    for name, param in inspect.signature(fn).parameters.items():
        if param.default is not inspect.Parameter.empty:
            continue
        annotation = param.annotation
        args[name] = {str: '', int: 0, list: [], bool: False}.get(annotation, '')
    return args


def test_there_are_tools_to_check():
    """這支測試的前提：真的撈得到工具。撈不到的話下面全部都是空轉。"""
    assert len(_tool_functions()) >= 9


@pytest.mark.parametrize('name', sorted(_tool_functions()))
def test_int_1_every_tool_refuses_when_the_gui_is_closed(name, gui_closed):
    """INT-1／INT-2：九個工具一律回 gui_not_running，一個都不能漏。"""
    fn = _tool_functions()[name]
    result = fn(**_minimal_args(fn))

    assert isinstance(result, dict), f'{name} 沒有回 dict'
    assert result.get('ok') is False, f'{name} 在主程式關閉時回了 ok=True'
    assert result.get('reason') == 'gui_not_running', (
        f'{name} 的拒絕理由不是 gui_not_running：{result.get("reason")!r}')


def test_int_3_open_search_tab_cannot_launch_the_app():
    """INT-3：能啟動主程式的工具，等於可以自己授予這道閘門要擋下的存取權。

    所以 fm_open_search_tab 不得有 launch_if_needed 之類的參數。
    """
    params = set(inspect.signature(hermes_mcp.fm_open_search_tab).parameters)
    assert params == {'query'}, f'多出了參數：{params - {"query"}}'


def test_int_5_cli_mirrors_every_mcp_tool():
    """INT-5：MCP 與 CLI 功能等價。新增工具時兩邊要一起加。

    只認 `_SubParsersAction`，不掃全部帶 choices 的參數——那樣連 `--match` 的
    ('any', 'all') 都會被算成子指令。
    """
    subparsers = next(
        action for action in cli.build_parser()._actions
        if isinstance(action, argparse._SubParsersAction))
    subcommands = set(subparsers.choices)

    expected = {name[len('fm_'):].replace('_', '-') for name in _tool_functions()}
    assert subcommands, 'CLI 沒有任何子指令，比對本身失效了'
    assert subcommands == expected, (
        f'只在 MCP：{sorted(expected - subcommands)}；'
        f'只在 CLI：{sorted(subcommands - expected)}')
