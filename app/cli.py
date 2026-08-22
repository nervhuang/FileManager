"""給 Hermes 以外的程式呼叫的 CLI，功能與 MCP server（app/hermes_mcp.py）完全相同。

直接呼叫 hermes_mcp.py 裡的工具函式——@server.tool() 只是註冊用的裝飾器，
回傳原函式不變，因此這裡不重複寫一份邏輯，行為（含 GUI 未開一律拒絕的授權
閘門）保證與 MCP 端一致。

用法（與 Hermes 的 MCP server 走同一支直譯器，需要同一份 FILEMANAGER_HOME）：
    .venv\\Scripts\\python.exe -m app.cli <command> [options]

每個指令輸出一行 JSON 到 stdout；ok 為 false 時 exit code 為 1，方便 shell 判斷。
"""

import argparse
import json
import sys

from . import hermes_mcp

# Windows 主控台預設用系統 codepage（繁中環境常是 cp950），印不出日文／罕見漢字
# 會直接炸掉；作者名稱本來就常是日文，這裡固定用 UTF-8 輸出，不看主控台設定。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _print_result(result):
    print(json.dumps(result, ensure_ascii=False))
    if isinstance(result, dict) and result.get('ok') is False:
        sys.exit(1)


def _read_entries(args):
    """entries 陣列：優先吃 --json，沒給就從 stdin 讀（方便大批貼上，不用跟殼層引號搏鬥）。"""
    raw = args.json if args.json is not None else sys.stdin.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        _print_result({'ok': False, 'error': f'JSON 解析失敗：{exc}'})
        raise SystemExit(1)


def _cmd_search(args):
    _print_result(hermes_mcp.fm_search(
        args.query, args.match, args.limit, args.under_dir, args.ext))


def _cmd_search_all(args):
    _print_result(hermes_mcp.fm_search_all(
        args.query, args.match, args.limit, args.offset, args.under_dir, args.ext))


def _cmd_open_search_tab(args):
    _print_result(hermes_mcp.fm_open_search_tab(args.query))


def _cmd_authors_list(args):
    _print_result(hermes_mcp.fm_authors_list(args.type, args.keyword, args.limit))


def _cmd_authors_upsert(args):
    _print_result(hermes_mcp.fm_authors_upsert(_read_entries(args)))


def _cmd_authors_link(args):
    _print_result(hermes_mcp.fm_authors_link(args.author, args.circle, args.unlink))


def _cmd_authors_delete(args):
    _print_result(hermes_mcp.fm_authors_delete(args.ids, args.name, args.type))


def _cmd_match_author(args):
    _print_result(hermes_mcp.fm_match_author(args.name, args.type, args.id, args.limit))


def _cmd_authors_stats(args):
    _print_result(hermes_mcp.fm_authors_stats(args.type, args.limit))


def build_parser():
    parser = argparse.ArgumentParser(
        prog='python -m app.cli',
        description='FileManager CLI——功能與 Hermes MCP server 相同，供其他程式呼叫。',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('search', help='搜尋本機檔案')
    p.add_argument('query')
    p.add_argument('--match', choices=('any', 'all'), default='any')
    p.add_argument('--limit', type=int, default=200)
    p.add_argument('--under-dir', dest='under_dir', default='')
    p.add_argument('--ext', default='')
    p.set_defaults(func=_cmd_search)

    p = sub.add_parser('search-all', help='大量搜尋，可分頁取回全部符合的檔案')
    p.add_argument('query')
    p.add_argument('--match', choices=('any', 'all'), default='any')
    p.add_argument('--limit', type=int, default=200)
    p.add_argument('--offset', type=int, default=0)
    p.add_argument('--under-dir', dest='under_dir', default='')
    p.add_argument('--ext', default='')
    p.set_defaults(func=_cmd_search_all)

    p = sub.add_parser('open-search-tab', help='在 FileManager GUI 開一個搜尋分頁')
    p.add_argument('query')
    p.set_defaults(func=_cmd_open_search_tab)

    p = sub.add_parser('authors-list', help='列出作者／團體清單')
    p.add_argument('--type', choices=('author', 'circle'), default='')
    p.add_argument('--keyword', default='')
    p.add_argument('--limit', type=int, default=500)
    p.set_defaults(func=_cmd_authors_list)

    p = sub.add_parser(
        'authors-upsert', help='新增或更新作者／團體；entries JSON 陣列用 --json 或 stdin 餵入')
    p.add_argument('--json', default=None, help='entries 的 JSON 陣列字串；不給則從 stdin 讀')
    p.set_defaults(func=_cmd_authors_upsert)

    p = sub.add_parser('authors-link', help='建立（或用 --unlink 解除）作者⇄團體關聯')
    p.add_argument('author')
    p.add_argument('circle')
    p.add_argument('--unlink', action='store_true')
    p.set_defaults(func=_cmd_authors_link)

    p = sub.add_parser('authors-delete', help='刪除作者／團體（軟刪除，可在 GUI 還原）')
    p.add_argument('--ids', nargs='*', type=int, default=[])
    p.add_argument('--name', default='')
    p.add_argument('--type', choices=('author', 'circle'), default='')
    p.set_defaults(func=_cmd_authors_delete)

    p = sub.add_parser('match-author', help='找出屬於某作者／團體的本機檔案')
    p.add_argument('--name', default='')
    p.add_argument('--type', choices=('author', 'circle'), default='')
    p.add_argument('--id', type=int, default=0)
    p.add_argument('--limit', type=int, default=200)
    p.set_defaults(func=_cmd_match_author)

    p = sub.add_parser('authors-stats', help='統計每個作者／團體各有幾個本機檔案')
    p.add_argument('--type', choices=('author', 'circle'), default='')
    p.add_argument('--limit', type=int, default=100)
    p.set_defaults(func=_cmd_authors_stats)

    return parser


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
