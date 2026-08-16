"""Hermes 用的 MCP stdio server。

以獨立進程執行（不需要 FileManager GUI 開著）：清單讀寫直接對 authors.db，
檔案搜尋直接走 Everything IPC。只有「叫 GUI 開搜尋分頁」這件事需要 GUI，
會透過 app/gui_bridge.py 的本機管道轉發，GUI 沒開就回 gui_not_running。

啟動方式（寫進 Hermes 設定檔的 mcp_servers；Windows 上實際位置是
%LOCALAPPDATA%\\hermes\\config.yaml，不是文件寫的 ~/.hermes/config.yaml）：
    command: '<專案>\\.venv\\Scripts\\python.exe'   # 用單引號，雙引號會讓 YAML 誤判逸出序列
    args:    ['-m', 'app.hermes_mcp']
"""

import configparser
import json
import os
import subprocess
import sys
import time
from contextlib import closing

from mcp.server import MCPServer

from . import authors_db, gui_bridge, paths, search_query
from .everything_sdk import EverythingSDK

server = MCPServer(
    name='filemanager',
    instructions=(
        '本機 FileManager 的作者／團體清單與檔案搜尋。清單是這台電腦上同人檔案的'
        '權威名單，包含作者、團體、各自的別名，以及作者與團體的關聯。'
        '搜尋透過 Everything 索引，只涵蓋 FileManager 排除設定允許的路徑。'
    ),
)

_everything = None


def _get_everything():
    global _everything
    if _everything is None:
        _everything = EverythingSDK()
    return _everything


def _exclude_norm():
    """讀 config.ini 的 [Exclude] 設定，與 GUI 套用同一份排除規則。"""
    cfg = configparser.ConfigParser()
    cfg.read(paths.config_path(), encoding='utf-8')
    if not cfg.getboolean('Exclude', 'enabled', fallback=False):
        return ()
    raw = cfg.get('Exclude', 'dirs', fallback='')
    try:
        dirs = json.loads(raw) if raw else []
    except Exception:
        dirs = []
    return search_query.normalize_exclude_dirs(dirs)


def _serialize(result):
    return {
        'path': result.path,
        'name': os.path.basename(result.path),
        'dir': os.path.dirname(result.path),
        'is_dir': bool(result.is_dir),
        'size': result.size,
        'mtime': result.mtime,
    }


def _run_search(query, match='any', limit=200, under_dir=None, ext=None):
    everything = _get_everything()
    if not everything.is_available():
        return {'ok': False, 'reason': 'everything_unavailable',
                'error': 'Everything 沒有在執行，或找不到它的 IPC 視窗。'}

    terms = search_query.split_terms(query)
    if match == 'all' and len(terms) > 1:
        # | 在搜尋管線裡是 OR；要 AND 就逐詞搜完取交集。
        sets = []
        for term in terms:
            partial, _ = search_query.run_search(
                everything, term, _exclude_norm(), under_dir=under_dir, ext=ext)
            sets.append({r.path: r for r in partial})
        common = set.intersection(*[set(s) for s in sets]) if sets else set()
        merged = [sets[0][p] for p in common]
        merged.sort(key=lambda r: r.path)
        truncated = bool(limit) and len(merged) > limit
        results = merged[:limit] if truncated else merged
    else:
        results, truncated = search_query.run_search(
            everything, query, _exclude_norm(), under_dir=under_dir, ext=ext, limit=limit)

    return {
        'ok': True,
        'query': query,
        'count': len(results),
        'truncated': truncated,
        'results': [_serialize(r) for r in results],
    }


# ── 搜尋 ────────────────────────────────────────────────────────────────

@server.tool()
def fm_search(query: str, match: str = 'any', limit: int = 200,
              under_dir: str = '', ext: str = '') -> dict:
    """搜尋本機檔案。

    query: 關鍵字；以 | 分隔多個關鍵字。也接受 Everything 原生語法
           （含 : < > ! * ? 時整串原樣送出，例如 "ext:zip path:D:\\NAS"）。
    match: 'any'（預設，任一關鍵字命中即列出）或 'all'（所有關鍵字都要命中）。
    limit: 最多回傳幾筆，預設 200。
    under_dir: 只回傳此目錄底下的結果（可留空）。
    ext: 只回傳此副檔名的檔案，例如 "zip"（可留空）。
    """
    return _run_search(query, match, limit, under_dir or None, ext or None)


@server.tool()
def fm_open_search_tab(query: str, launch_if_needed: bool = False) -> dict:
    """在 FileManager GUI 的右面板開一個新分頁顯示這個關鍵字的搜尋結果。

    GUI 沒開著時回 {"ok": false, "reason": "gui_not_running"}；
    launch_if_needed=true 才會自動把 GUI 啟動起來再送指令。
    """
    response = gui_bridge.send_command({'cmd': 'open_search_tab', 'query': query})
    if response.get('reason') != 'gui_not_running' or not launch_if_needed:
        return response

    exe = os.path.join(paths.runtime_root(), 'FileManager.exe')
    if os.path.exists(exe):
        command = [exe]
    else:
        command = [sys.executable, os.path.join(paths.runtime_root(), 'main.py')]
    try:
        subprocess.Popen(command, cwd=paths.runtime_root())
    except Exception as exc:
        return {'ok': False, 'reason': 'launch_failed', 'error': str(exc)}

    for _ in range(30):  # 最多等 15 秒讓 GUI 起來並開好管道
        time.sleep(0.5)
        if gui_bridge.gui_is_running():
            return gui_bridge.send_command({'cmd': 'open_search_tab', 'query': query})
    return {'ok': False, 'reason': 'launch_timeout'}


# ── 清單讀寫 ────────────────────────────────────────────────────────────

@server.tool()
def fm_authors_list(type: str = '', keyword: str = '', limit: int = 500) -> dict:
    """列出作者／團體清單。

    type: 'author'、'circle'，留空代表兩者都列。
    keyword: 以子字串比對名稱與別名（可留空）。
    """
    if type and type not in authors_db.TYPES:
        return {'ok': False, 'error': "type 必須是 'author' 或 'circle'"}
    with closing(authors_db.connect()) as conn:
        entities = authors_db.list_entities(
            conn, type_=type or None, keyword=keyword or None, limit=limit)
    return {'ok': True, 'count': len(entities), 'entities': entities}


@server.tool()
def fm_authors_upsert(entries: list) -> dict:
    """新增或更新作者／團體。

    每筆 entry：
      name (必填，除非給了 id)、type ('author' 或 'circle'，必填除非給了 id)、
      id (要改既有項目時給)、aliases (字串陣列，會整組取代)、
      linked_names (相對類型的名稱陣列：作者填團體名、團體填作者名；
                    對方不存在會自動建檔)、note。
    以 (type, name) 找得到現有項目時會更新它，不會重複新增。
    所有變更都會寫入變更紀錄，使用者可在 GUI 一鍵還原。

    重要：當你同時知道某個作者與其所屬團體時，**必須**用 linked_names 把兩者
    關聯起來，不要送成兩筆彼此無關的 entry。少了關聯，它們在使用者的清單裡會
    變成兩個孤立項目，而不是團體底下掛著作者。
    只送一筆帶 linked_names 的 entry 即可，另一邊會自動建檔並雙向關聯：
        [{"name": "南浜屋", "type": "circle", "linked_names": ["南浜よりこ"]}]
    若兩者已經各自存在、只是還沒關聯，改用 fm_authors_link 補上就好。
    """
    if not isinstance(entries, list) or not entries:
        return {'ok': False, 'error': 'entries 必須是非空陣列'}
    try:
        with closing(authors_db.connect()) as conn:
            result = authors_db.upsert(conn, entries, source=authors_db.SOURCE_HERMES)
            entities = [authors_db.get_entity(conn, i)
                        for i in result['created'] + result['updated']]
    except authors_db.AuthorsDbError as exc:
        return {'ok': False, 'error': str(exc)}
    gui_bridge.notify_authors_changed()
    return {'ok': True, 'created': result['created'], 'updated': result['updated'],
            'entities': entities}


@server.tool()
def fm_authors_link(author: str, circle: str, unlink: bool = False) -> dict:
    """把一個作者掛到一個團體底下，或解除該關聯。

    作者與團體是多對多：一個作者可屬於多個團體，一個團體可有多個作者，
    重複呼叫同一組不會產生重複資料。任一邊不存在時會自動建檔，因此這也是
    「發現某作者屬於某團體」時最省事的寫法。
    unlink=true 則是解除關聯（兩個項目本身都保留）。
    """
    try:
        with closing(authors_db.connect()) as conn:
            if unlink:
                author_entity = _resolve_entity(conn, author, authors_db.AUTHOR, 0)
                circle_entity = _resolve_entity(conn, circle, authors_db.CIRCLE, 0)
                if author_entity is None or circle_entity is None:
                    return {'ok': False, 'reason': 'not_found',
                            'error': f'清單中找不到 {author!r} 或 {circle!r}'}
                result = authors_db.unlink(conn, author_entity['id'], circle_entity['id'],
                                           source=authors_db.SOURCE_HERMES)
                payload = {'author': result}
            else:
                author_entity, circle_entity = authors_db.link(
                    conn, author, circle, source=authors_db.SOURCE_HERMES)
                payload = {'author': author_entity, 'circle': circle_entity}
    except authors_db.AuthorsDbError as exc:
        return {'ok': False, 'error': str(exc)}
    gui_bridge.notify_authors_changed()
    return {'ok': True, **payload}


@server.tool()
def fm_authors_delete(ids: list = [], name: str = '', type: str = '') -> dict:
    """刪除作者／團體（軟刪除，使用者可在 GUI 還原）。

    給 ids 陣列，或給 name + type 二擇一。
    """
    with closing(authors_db.connect()) as conn:
        if ids:
            deleted = authors_db.soft_delete(conn, ids, source=authors_db.SOURCE_HERMES)
        elif name and type:
            deleted = authors_db.delete_by_name(conn, name, type, source=authors_db.SOURCE_HERMES)
        else:
            return {'ok': False, 'error': '請給 ids，或同時給 name 與 type'}
    if deleted:
        gui_bridge.notify_authors_changed()
    return {'ok': True, 'deleted': deleted}


# ── 檔名比對 ────────────────────────────────────────────────────────────

def _resolve_entity(conn, name, type_, entity_id):
    if entity_id:
        return authors_db.get_entity(conn, entity_id)
    if not name:
        return None
    candidates = [e for e in authors_db.list_entities(conn, type_=type_ or None, keyword=name)
                  if e['name'] == name or name in e['aliases']]
    return candidates[0] if candidates else None


@server.tool()
def fm_match_author(name: str = '', type: str = '', id: int = 0, limit: int = 200) -> dict:
    """找出屬於某個作者／團體的本機檔案。

    作法是把該實體的名稱與所有別名組成 OR 查詢丟進同一套搜尋管線，
    因此結果與使用者在 GUI 點該項目看到的完全一致。
    給 name（可加 type 消歧義）或 id。
    """
    with closing(authors_db.connect()) as conn:
        entity = _resolve_entity(conn, name, type or None, id)
    if entity is None:
        return {'ok': False, 'reason': 'not_found',
                'error': f'清單中找不到 {name or id!r}'}

    query = authors_db.search_terms_for(entity)
    result = _run_search(query, 'any', limit)
    result['entity'] = {'id': entity['id'], 'name': entity['name'], 'type': entity['type'],
                        'aliases': entity['aliases']}
    return result


@server.tool()
def fm_authors_stats(type: str = '', limit: int = 100) -> dict:
    """統計清單中每個作者／團體在本機各有幾個檔案。

    每個實體都會跑一次搜尋，項目多時會很慢；建議搭配 type 或 limit 縮小範圍。
    """
    with closing(authors_db.connect()) as conn:
        entities = authors_db.list_entities(conn, type_=type or None, limit=limit)

    stats = []
    for entity in entities:
        result = _run_search(authors_db.search_terms_for(entity), 'any', limit=100000)
        stats.append({
            'id': entity['id'], 'name': entity['name'], 'type': entity['type'],
            'file_count': result.get('count', 0) if result.get('ok') else None,
        })
    stats.sort(key=lambda s: (s['file_count'] is None, -(s['file_count'] or 0)))
    return {'ok': True, 'count': len(stats), 'stats': stats}


def main():
    # authors.db 不存在時先建好 schema，讓第一個工具呼叫就能用。
    authors_db.connect().close()
    server.run('stdio')


if __name__ == '__main__':
    main()
