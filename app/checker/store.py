"""檢查器的狀態儲存：掃描進度、使用者決定、最近一次的比對結果。

資料表建在 `authors.db` 內，但 schema 由本模組自己套用（`ensure_schema`），
`authors_db.py` 因此一行都不必改。新表對舊版 FileManager 是純增加，
舊版開同一個 db 照常運作，只是看不到這些表。

**為什麼把「上次掃描時間」存成站上的發布時間而非本機時鐘**：
分頁要靠「這筆比上次看到的舊了嗎」決定何時停，兩邊時間必須同源。
本機時鐘與站方時區有時差，拿來當基準會在邊界少抓或多抓幾筆。
存站上看到的最新一筆發布時間，比較的兩個值就都來自同一個來源。
"""

import datetime
import json
from contextlib import closing

from . import matcher

STATE_IGNORED = 'ignored'        # 使用者明說不要，永遠不再出現
STATE_DOWNLOADED = 'downloaded'  # 已下載待驗，等本機檔案出現後自動轉為已有

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checker_state (
  entity_id INTEGER PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
  last_scan_at TEXT NOT NULL,
  last_posted TEXT NOT NULL DEFAULT '',
  truncated INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS checker_decisions (
  gid TEXT PRIMARY KEY,
  state TEXT NOT NULL CHECK(state IN ('ignored','downloaded')),
  entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
  title TEXT NOT NULL DEFAULT '',
  decided_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checker_findings (
  gid TEXT PRIMARY KEY,
  entity_id INTEGER REFERENCES entities(id) ON DELETE CASCADE,
  token TEXT NOT NULL DEFAULT '',
  core TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  title_jpn TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  pages INTEGER,
  thumb TEXT NOT NULL DEFAULT '',
  posted INTEGER,
  markers TEXT NOT NULL DEFAULT '[]',
  verdict TEXT NOT NULL,
  score REAL NOT NULL DEFAULT 0,
  missing_markers TEXT NOT NULL DEFAULT '[]',
  matched_local TEXT NOT NULL DEFAULT '',
  found_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_checker_findings_entity
  ON checker_findings(entity_id);
CREATE INDEX IF NOT EXISTS ix_checker_findings_verdict
  ON checker_findings(verdict);
"""

_POSTED_FORMAT = '%Y-%m-%d %H:%M'


def _now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def ensure_schema(conn):
    """建立檢查器用的資料表。每次連線都可安全呼叫。"""
    conn.executescript(_SCHEMA)
    conn.commit()


def connect():
    """開一條已套用兩邊 schema 的連線。呼叫端負責關閉。"""
    from .. import authors_db

    conn = authors_db.connect()
    ensure_schema(conn)
    return conn


# ── 掃描進度 ────────────────────────────────────────────────────────────

def last_posted(conn, entity_id):
    """上次掃描時看到的最新發布時間；沒掃過回 None（代表首次掃描）。"""
    row = conn.execute(
        'SELECT last_posted FROM checker_state WHERE entity_id = ?',
        (entity_id,)).fetchone()
    if not row or not row['last_posted']:
        return None
    try:
        return datetime.datetime.strptime(row['last_posted'], _POSTED_FORMAT)
    except ValueError:
        return None


def record_scan(conn, entity_id, *, newest_posted='', truncated=False, error=''):
    """記下這個實體剛掃完的狀態。

    `newest_posted` 是本輪看到的最新一筆發布時間（tag 頁上的 'YYYY-MM-DD HH:MM'）。
    留空時保留原值——抓取失敗不該把進度往前推，否則下次會跳過這段沒掃到的區間。
    """
    existing = conn.execute(
        'SELECT last_posted FROM checker_state WHERE entity_id = ?',
        (entity_id,)).fetchone()
    keep = existing['last_posted'] if existing else ''
    conn.execute(
        'INSERT INTO checker_state (entity_id, last_scan_at, last_posted, truncated, error) '
        'VALUES (?, ?, ?, ?, ?) '
        'ON CONFLICT(entity_id) DO UPDATE SET '
        '  last_scan_at = excluded.last_scan_at,'
        '  last_posted = excluded.last_posted,'
        '  truncated = excluded.truncated,'
        '  error = excluded.error',
        (entity_id, _now(), newest_posted or keep, 1 if truncated else 0, error or ''))
    conn.commit()


def scan_states(conn):
    """回傳 entity_id -> {last_scan_at, last_posted, truncated, error}。"""
    return {row['entity_id']: dict(row)
            for row in conn.execute('SELECT * FROM checker_state')}


# ── 使用者決定 ──────────────────────────────────────────────────────────

def decisions(conn):
    """回傳 gid -> state。"""
    return {row['gid']: row['state']
            for row in conn.execute('SELECT gid, state FROM checker_decisions')}


def set_decision(conn, gid, state, *, entity_id=None, title=''):
    if state not in (STATE_IGNORED, STATE_DOWNLOADED):
        raise ValueError(f'未知的狀態：{state}')
    conn.execute(
        'INSERT INTO checker_decisions (gid, state, entity_id, title, decided_at) '
        'VALUES (?, ?, ?, ?, ?) '
        'ON CONFLICT(gid) DO UPDATE SET '
        '  state = excluded.state, entity_id = excluded.entity_id,'
        '  title = excluded.title, decided_at = excluded.decided_at',
        (str(gid), state, entity_id, title or '', _now()))
    conn.commit()


def clear_decision(conn, gid):
    conn.execute('DELETE FROM checker_decisions WHERE gid = ?', (str(gid),))
    conn.commit()


def reconcile_downloads(conn, entity_id=None):
    """本機檔案出現後，把「已下載待驗」轉正，回傳被轉正的 gid。

    使用者按下「已下載」時檔案還沒落地，比對仍判成新書；等 `refresh_verdicts()`
    以新的本機索引把該 gid 重評成已有，就代表檔案真的進來了，此時清掉標記讓它
    回歸一般的已有項目。沒下載成功的維持待驗，繼續被記著——這是不靜默漏書的關鍵。

    直接查資料庫而非接收呼叫端的清單：`load_findings()` 會濾掉所有已有決定的項目，
    待驗中的 gid 正好都在被濾掉的那一批裡，接它的輸出會讓轉正永遠不發生。
    """
    sql = ('SELECT f.gid FROM checker_findings f '
           'JOIN checker_decisions d ON d.gid = f.gid '
           'WHERE d.state = ? AND f.verdict IN (?, ?)')
    params = [STATE_DOWNLOADED, matcher.VERDICT_HAVE, matcher.VERDICT_UPGRADE]
    if entity_id is not None:
        sql += ' AND f.entity_id = ?'
        params.append(entity_id)

    confirmed = [row['gid'] for row in conn.execute(sql, params)]
    if confirmed:
        conn.executemany('DELETE FROM checker_decisions WHERE gid = ?',
                         [(gid,) for gid in confirmed])
        conn.commit()
    return confirmed


# ── 比對結果 ────────────────────────────────────────────────────────────

def save_findings(conn, entity_id, items):
    """把本輪結果併進該實體的比對結果。

    **不可改成先 DELETE 再插入。** 增量掃描只取回上次之後的新增項目，若先清空
    舊資料，使用者還沒處理完的項目會在下一次掃描時整批消失——實測第二輪只取回
    1 筆，就把前一輪 19 筆待處理的書洗掉了。

    既有項目的判定改由 `refresh_verdicts()` 用當前本機索引重新評定，
    因此不需要靠重掃來更新，也就不需要清空。
    """
    conn.executemany(
        'INSERT OR REPLACE INTO checker_findings '
        '(gid, entity_id, token, core, title, title_jpn, category, pages, thumb,'
        ' posted, markers, verdict, score, missing_markers, matched_local, found_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        [(str(i['gid']), entity_id, i.get('token', ''), i.get('core', ''),
          i.get('title', ''), i.get('title_jpn', ''), i.get('category', ''),
          int(i['pages']) if str(i.get('pages') or '').isdigit() else None,
          i.get('thumb', ''),
          int(i['posted']) if str(i.get('posted') or '').isdigit() else None,
          json.dumps(i.get('markers') or [], ensure_ascii=False),
          i['verdict'], float(i.get('score') or 0.0),
          json.dumps(i.get('missing_markers') or [], ensure_ascii=False),
          i.get('matched_local', ''), _now())
         for i in items])
    conn.commit()


def refresh_verdicts(conn, entity_id, local_items,
                     threshold=matcher.DEFAULT_THRESHOLD):
    """用當前的本機索引重新評定該實體已存的比對結果，回傳判定有變的筆數。

    為什麼需要這步：增量掃描只會抓回上次之後的新增項目，早先被判成新書的項目
    不會再被抓一次。使用者把那本書下載下來之後，若沒有這步，它會永遠停在
    「新書」——明明檔案已經在本機了。這裡不花任何網路成本，只是拿當前的本機
    檔案清單把舊判定重算一次。
    """
    from . import titles

    rows = conn.execute(
        'SELECT gid, title, title_jpn, verdict, score FROM checker_findings '
        'WHERE entity_id = ?', (entity_id,)).fetchall()

    updates = []
    for row in rows:
        parsed = titles.parse(row['title_jpn'] or row['title'])
        verdict = matcher.classify(parsed, local_items, threshold)
        new_verdict = verdict['verdict']
        if new_verdict == row['verdict']:
            continue
        updates.append((
            new_verdict, round(verdict['score'], 4),
            json.dumps(verdict['missing_markers'], ensure_ascii=False),
            ('' if new_verdict == matcher.VERDICT_NEW
             else (verdict['matched'] or {}).get('raw', '')),
            row['gid']))

    if updates:
        conn.executemany(
            'UPDATE checker_findings SET verdict = ?, score = ?, '
            'missing_markers = ?, matched_local = ? WHERE gid = ?', updates)
        conn.commit()
    return len(updates)


def load_findings(conn, *, verdicts=None, entity_id=None):
    """讀回比對結果，已套用使用者決定（忽略與已下載待驗都不再出現）。"""
    sql = ('SELECT f.*, e.name AS entity_name, e.type AS entity_type, d.state AS decision '
           'FROM checker_findings f '
           'LEFT JOIN entities e ON e.id = f.entity_id '
           'LEFT JOIN checker_decisions d ON d.gid = f.gid '
           'WHERE d.state IS NULL')
    params = []
    if verdicts:
        sql += ' AND f.verdict IN (%s)' % ','.join('?' * len(verdicts))
        params.extend(verdicts)
    if entity_id is not None:
        sql += ' AND f.entity_id = ?'
        params.append(entity_id)
    sql += ' ORDER BY f.posted DESC'

    out = []
    for row in conn.execute(sql, params):
        item = dict(row)
        item['markers'] = json.loads(item['markers'] or '[]')
        item['missing_markers'] = json.loads(item['missing_markers'] or '[]')
        item['url'] = f"https://exhentai.org/g/{item['gid']}/{item['token']}/"
        out.append(item)
    return out


def counts(conn):
    """四區塊計數，已排除使用者已處理的項目。"""
    rows = conn.execute(
        'SELECT f.verdict, COUNT(*) AS n FROM checker_findings f '
        'LEFT JOIN checker_decisions d ON d.gid = f.gid '
        'WHERE d.state IS NULL GROUP BY f.verdict')
    result = {matcher.VERDICT_NEW: 0, matcher.VERDICT_UPGRADE: 0,
              matcher.VERDICT_MAYBE: 0, matcher.VERDICT_HAVE: 0,
              matcher.VERDICT_SUPPRESSED: 0}
    for row in rows:
        result[row['verdict']] = row['n']
    return result
