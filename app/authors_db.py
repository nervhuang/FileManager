"""作者／團體清單的 SQLite 存取層（不依賴 Qt）。

GUI 與 Hermes MCP server 是兩個獨立進程，共用同一個 authors.db；因此開啟時
一律啟用 WAL 與 busy_timeout，讓兩邊可以同時讀、輪流寫。

所有寫入都會在同一個 transaction 內附帶寫入 `changes` 表（含變更前後的完整
實體快照），刪除一律為軟刪除，因此 Hermes 寫錯的任何一筆都救得回來。
"""

import json
import os
import sqlite3
from datetime import datetime

from . import paths

AUTHOR = 'author'
CIRCLE = 'circle'
TYPES = (AUTHOR, CIRCLE)

SOURCE_LOCAL = 'local'
SOURCE_HERMES = 'hermes'

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('author','circle')),
  note TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'local',
  deleted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_entities_live
  ON entities(type, name) WHERE deleted = 0;

CREATE TABLE IF NOT EXISTS aliases (
  id INTEGER PRIMARY KEY,
  entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  alias TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_aliases ON aliases(entity_id, alias);

CREATE TABLE IF NOT EXISTS links (
  author_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  circle_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  PRIMARY KEY (author_id, circle_id)
);

CREATE TABLE IF NOT EXISTS changes (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  source TEXT NOT NULL,
  op TEXT NOT NULL,
  entity_id INTEGER,
  before_json TEXT,
  after_json TEXT
);
"""


class AuthorsDbError(Exception):
    pass


def _now():
    return datetime.now().isoformat(timespec='seconds')


def db_path():
    return paths.authors_db_path()


def connect(path=None):
    """開啟（必要時建立）資料庫，回傳已套用 schema 的連線。"""
    target = path or db_path()
    directory = os.path.dirname(target)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(target, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=8000')
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


# ── 讀取 ────────────────────────────────────────────────────────────────

def _row_to_entity(conn, row, with_relations=True):
    entity = {
        'id': row['id'],
        'name': row['name'],
        'type': row['type'],
        'note': row['note'],
        'source': row['source'],
        'deleted': bool(row['deleted']),
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
        'aliases': [],
        'linked': [],
    }
    if not with_relations:
        return entity

    entity['aliases'] = [
        r['alias'] for r in conn.execute(
            'SELECT alias FROM aliases WHERE entity_id = ? ORDER BY alias', (row['id'],)
        )
    ]
    if row['type'] == AUTHOR:
        sql = ('SELECT e.id, e.name, e.type FROM links l JOIN entities e ON e.id = l.circle_id '
               'WHERE l.author_id = ? AND e.deleted = 0 ORDER BY e.name')
    else:
        sql = ('SELECT e.id, e.name, e.type FROM links l JOIN entities e ON e.id = l.author_id '
               'WHERE l.circle_id = ? AND e.deleted = 0 ORDER BY e.name')
    entity['linked'] = [dict(r) for r in conn.execute(sql, (row['id'],))]
    return entity


def get_entity(conn, entity_id, with_relations=True):
    row = conn.execute('SELECT * FROM entities WHERE id = ?', (entity_id,)).fetchone()
    if row is None:
        return None
    return _row_to_entity(conn, row, with_relations)


def find_entity(conn, name, type_):
    """依 (type, name) 找未刪除的實體。"""
    row = conn.execute(
        'SELECT * FROM entities WHERE type = ? AND name = ? AND deleted = 0', (type_, name)
    ).fetchone()
    return _row_to_entity(conn, row) if row else None


def list_entities(conn, type_=None, keyword=None, include_deleted=False, limit=None):
    """列出實體。keyword 會同時比對名稱與別名（子字串，不分大小寫）。"""
    sql = 'SELECT DISTINCT e.* FROM entities e LEFT JOIN aliases a ON a.entity_id = e.id WHERE 1=1'
    args = []
    if not include_deleted:
        sql += ' AND e.deleted = 0'
    if type_:
        sql += ' AND e.type = ?'
        args.append(type_)
    if keyword:
        sql += ' AND (e.name LIKE ? COLLATE NOCASE OR a.alias LIKE ? COLLATE NOCASE)'
        like = f'%{keyword}%'
        args.extend([like, like])
    sql += ' ORDER BY e.type, e.name'
    if limit:
        sql += ' LIMIT ?'
        args.append(int(limit))
    return [_row_to_entity(conn, row) for row in conn.execute(sql, args)]


def search_terms_for(entity):
    """組出該實體的 OR 搜尋字串：名稱與所有別名。"""
    terms = [entity['name']] + list(entity.get('aliases') or [])
    seen, out = set(), []
    for term in terms:
        term = (term or '').strip()
        if term and term not in seen:
            seen.add(term)
            out.append(term)
    return '|'.join(out)


# ── 寫入 ────────────────────────────────────────────────────────────────

def _log_change(conn, source, op, entity_id, before, after):
    conn.execute(
        'INSERT INTO changes (ts, source, op, entity_id, before_json, after_json) VALUES (?,?,?,?,?,?)',
        (
            _now(), source, op, entity_id,
            json.dumps(before, ensure_ascii=False) if before is not None else None,
            json.dumps(after, ensure_ascii=False) if after is not None else None,
        ),
    )


def _set_aliases(conn, entity_id, aliases):
    conn.execute('DELETE FROM aliases WHERE entity_id = ?', (entity_id,))
    for alias in aliases:
        alias = (alias or '').strip()
        if alias:
            conn.execute(
                'INSERT OR IGNORE INTO aliases (entity_id, alias) VALUES (?, ?)',
                (entity_id, alias),
            )


def _link(conn, author_id, circle_id):
    conn.execute(
        'INSERT OR IGNORE INTO links (author_id, circle_id) VALUES (?, ?)',
        (author_id, circle_id),
    )


def _set_links(conn, entity_id, entity_type, counterpart_ids):
    if entity_type == AUTHOR:
        conn.execute('DELETE FROM links WHERE author_id = ?', (entity_id,))
        for cid in counterpart_ids:
            _link(conn, entity_id, cid)
    else:
        conn.execute('DELETE FROM links WHERE circle_id = ?', (entity_id,))
        for aid in counterpart_ids:
            _link(conn, aid, entity_id)


def _ensure_entity(conn, name, type_, source, now):
    """取得（必要時建立）指定名稱的實體，回傳 id。用於 linked_names 自動建檔。"""
    row = conn.execute(
        'SELECT id FROM entities WHERE type = ? AND name = ? AND deleted = 0', (type_, name)
    ).fetchone()
    if row:
        return row['id']
    cur = conn.execute(
        'INSERT INTO entities (name, type, note, source, deleted, created_at, updated_at) '
        'VALUES (?,?,?,?,0,?,?)',
        (name, type_, '', source, now, now),
    )
    new_id = cur.lastrowid
    _log_change(conn, source, 'insert', new_id, None, get_entity(conn, new_id))
    return new_id


def upsert(conn, entries, source=SOURCE_LOCAL):
    """新增或更新實體。

    每筆 entry 支援：id、name、type、aliases、linked_names、note。
    - 有 id 走更新；否則以 (type, name) 找現有未刪除實體，找不到才新增。
    - aliases / linked_names 有給才動（給空陣列＝清空），沒給則保持原狀。
    - linked_names 指的是「相對類型」的名稱；不存在時自動建檔。

    回傳 {'created': [id...], 'updated': [id...]}。
    """
    created, updated = [], []
    now = _now()
    try:
        with conn:
            for entry in entries:
                name = (entry.get('name') or '').strip()
                type_ = (entry.get('type') or '').strip()
                entity_id = entry.get('id')

                if type_ and type_ not in TYPES:
                    raise AuthorsDbError(f'type 必須是 author 或 circle，收到 {type_!r}')

                before = None
                if entity_id:
                    before = get_entity(conn, entity_id)
                    if before is None:
                        raise AuthorsDbError(f'找不到 id={entity_id} 的項目')
                    type_ = type_ or before['type']
                    name = name or before['name']
                else:
                    if not name or not type_:
                        raise AuthorsDbError('新增項目必須同時提供 name 與 type')
                    existing = find_entity(conn, name, type_)
                    if existing:
                        entity_id = existing['id']
                        before = existing

                if entity_id:
                    conn.execute(
                        'UPDATE entities SET name = ?, type = ?, note = ?, source = ?, updated_at = ? '
                        'WHERE id = ?',
                        (name, type_, entry.get('note', before['note']), source, now, entity_id),
                    )
                    updated.append(entity_id)
                else:
                    cur = conn.execute(
                        'INSERT INTO entities (name, type, note, source, deleted, created_at, updated_at) '
                        'VALUES (?,?,?,?,0,?,?)',
                        (name, type_, entry.get('note', ''), source, now, now),
                    )
                    entity_id = cur.lastrowid
                    created.append(entity_id)

                if 'aliases' in entry:
                    _set_aliases(conn, entity_id, entry.get('aliases') or [])

                if 'linked_names' in entry:
                    other_type = CIRCLE if type_ == AUTHOR else AUTHOR
                    counterpart_ids = [
                        _ensure_entity(conn, n.strip(), other_type, source, now)
                        for n in (entry.get('linked_names') or []) if (n or '').strip()
                    ]
                    _set_links(conn, entity_id, type_, counterpart_ids)

                _log_change(
                    conn, source,
                    'update' if before else 'insert',
                    entity_id, before, get_entity(conn, entity_id),
                )
    except sqlite3.IntegrityError as exc:
        raise AuthorsDbError(f'違反唯一性限制（同類型下名稱重複？）：{exc}') from exc

    return {'created': created, 'updated': updated}


def soft_delete(conn, ids, source=SOURCE_LOCAL):
    """軟刪除：標記 deleted=1，保留別名與關聯，可從變更紀錄還原。"""
    deleted = []
    now = _now()
    with conn:
        for entity_id in ids:
            before = get_entity(conn, entity_id)
            if before is None or before['deleted']:
                continue
            conn.execute(
                'UPDATE entities SET deleted = 1, updated_at = ? WHERE id = ?', (now, entity_id)
            )
            _log_change(conn, source, 'delete', entity_id, before, get_entity(conn, entity_id))
            deleted.append(entity_id)
    return deleted


def delete_by_name(conn, name, type_, source=SOURCE_LOCAL):
    entity = find_entity(conn, name, type_)
    return soft_delete(conn, [entity['id']], source) if entity else []


# ── 變更紀錄與還原 ──────────────────────────────────────────────────────

def recent_changes(conn, limit=100):
    rows = conn.execute(
        'SELECT * FROM changes ORDER BY id DESC LIMIT ?', (int(limit),)
    ).fetchall()
    out = []
    for row in rows:
        out.append({
            'id': row['id'],
            'ts': row['ts'],
            'source': row['source'],
            'op': row['op'],
            'entity_id': row['entity_id'],
            'before': json.loads(row['before_json']) if row['before_json'] else None,
            'after': json.loads(row['after_json']) if row['after_json'] else None,
        })
    return out


def revert_change(conn, change_id, source=SOURCE_LOCAL):
    """把某筆變更還原回它發生前的狀態，並把這次還原本身也記為一筆變更。"""
    row = conn.execute('SELECT * FROM changes WHERE id = ?', (change_id,)).fetchone()
    if row is None:
        raise AuthorsDbError(f'找不到變更紀錄 id={change_id}')

    before = json.loads(row['before_json']) if row['before_json'] else None
    entity_id = row['entity_id']
    now = _now()
    current = get_entity(conn, entity_id)

    with conn:
        if before is None:
            # 原本是新增 → 還原＝軟刪除
            conn.execute(
                'UPDATE entities SET deleted = 1, updated_at = ? WHERE id = ?', (now, entity_id)
            )
        else:
            conn.execute(
                'UPDATE entities SET name = ?, type = ?, note = ?, source = ?, deleted = ?, '
                'updated_at = ? WHERE id = ?',
                (
                    before['name'], before['type'], before['note'], before['source'],
                    1 if before['deleted'] else 0, now, entity_id,
                ),
            )
            _set_aliases(conn, entity_id, before.get('aliases') or [])
            counterpart_ids = [
                _ensure_entity(conn, item['name'], item['type'], source, now)
                for item in (before.get('linked') or [])
            ]
            _set_links(conn, entity_id, before['type'], counterpart_ids)

        _log_change(conn, source, 'restore', entity_id, current, get_entity(conn, entity_id))

    return get_entity(conn, entity_id)
