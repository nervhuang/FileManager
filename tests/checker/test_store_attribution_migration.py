"""舊資料庫升級時，`attribution` 必須真的算過一次。
見 docs/spec/checker.md「決定的作用範圍」。

`ALTER TABLE ... ADD COLUMN` 只會把既有的列填成預設值，而這一欄的預設值是空字串
——空字串本身是合法值（商業誌沒有社團括號），跨作者共用決定就是靠「核心標題與
掛名都相同」。不補算的話，一整批空掛名會讓所有同名的舊資料互相認親。

這條路自動測試容易漏：其他測試都是在全新的 schema 上跑，走不到 migration。
"""
import sqlite3

import pytest

from app.checker import store

pytestmark = pytest.mark.logic


# 加上 attribution 之前的 checker_findings，只留這支測試真的會用到的欄位。
_OLD_SCHEMA = """
CREATE TABLE checker_findings (
  gid TEXT PRIMARY KEY,
  entity_id INTEGER,
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
"""


def test_upgrading_an_old_database_computes_the_attribution():
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute('CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT, type TEXT)')
    con.execute('CREATE TABLE links (author_id INTEGER, circle_id INTEGER,'
                ' PRIMARY KEY (author_id, circle_id))')
    con.executescript(_OLD_SCHEMA)
    con.execute("INSERT INTO checker_findings (gid, core, title, title_jpn, verdict,"
                " found_at) VALUES ('111', 'x', 'en', "
                "'[リンゴヤ (あるぷ)] C108 おまけ本', 'new', '')")
    con.execute("INSERT INTO checker_findings (gid, core, title, title_jpn, verdict,"
                " found_at) VALUES ('222', 'x', 'コミック エグゼ 69 [DL版]', '',"
                " 'new', '')")
    con.commit()

    store.ensure_schema(con)

    rows = {r['gid']: r['attribution']
            for r in con.execute('SELECT gid, attribution FROM checker_findings')}
    assert rows['111'] == 'リンゴヤあるぷ'   # 掛名算得出來
    assert rows['222'] == ''                # 商業誌沒有社團括號，空字串是正確答案
    con.close()
