"""更新檢查器的本機 Web UI：縮圖牆、四區塊、標記已下載／忽略。

面板只放摘要，逐本判斷「這本我到底有沒有」要看縮圖與並排的本機檔名，
那需要瀏覽器的排版能力，所以另開一個頁面。

安全邊界（不可放寬）：

* 只綁 `127.0.0.1`，埠號由系統指派，不對外開放。
* 每一個請求都要帶對 token，否則回 403。token 每次啟動重新產生。
* **頁面與 API 永不輸出 cookie 值。** 縮圖由本機快取供應，
  瀏覽器不會、也不需要對站方發出任何請求。
"""

import html
import json
import os
import secrets
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import matcher, store, thumbs

VERDICT_ORDER = (matcher.VERDICT_NEW, matcher.VERDICT_UPGRADE,
                 matcher.VERDICT_MAYBE, matcher.VERDICT_HAVE)
VERDICT_LABEL = {
    matcher.VERDICT_NEW: '🆕 新書',
    matcher.VERDICT_UPGRADE: '⬆️ 版本升級',
    matcher.VERDICT_MAYBE: '❓ 疑似已有',
    matcher.VERDICT_HAVE: '✅ 已有',
}


class _Handler(BaseHTTPRequestHandler):
    server_version = 'FileManagerChecker/1.0'

    # ── 基礎 ────────────────────────────────────────────────────────────

    def log_message(self, *args):
        """關掉預設的 stderr 存取紀錄：網址帶著 token，寫進 log 等於外洩。"""

    def _authorized(self, query):
        token = (query.get('t') or [''])[0]
        return secrets.compare_digest(token, self.server.token)

    def _send(self, code, content_type, body, *, extra_headers=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        # 頁面完全自足，不連任何外部主機；順手把瀏覽器也鎖住。
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; img-src 'self' data:; "
                         "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
        self.send_header('Referrer-Policy', 'no-referrer')
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, code=200):
        self._send(code, 'application/json; charset=utf-8',
                   json.dumps(payload, ensure_ascii=False))

    # ── 路由 ────────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._authorized(query):
            self._send(403, 'text/plain; charset=utf-8', '403 需要有效的存取權杖')
            return

        if parsed.path in ('/', '/index.html'):
            self._send(200, 'text/html; charset=utf-8', _render_page(self.server.token))
        elif parsed.path == '/api/findings':
            self._json(self._findings())
        elif parsed.path.startswith('/thumb/'):
            self._thumb(parsed.path[len('/thumb/'):])
        else:
            self._send(404, 'text/plain; charset=utf-8', '404')

    def do_POST(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._authorized(query):
            self._send(403, 'text/plain; charset=utf-8', '403 需要有效的存取權杖')
            return
        if parsed.path != '/api/decision':
            self._send(404, 'text/plain; charset=utf-8', '404')
            return

        length = int(self.headers.get('Content-Length') or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode('utf-8') or '{}')
        except ValueError:
            self._json({'ok': False, 'error': '請求格式錯誤'}, 400)
            return

        gid = str(payload.get('gid') or '')
        state = payload.get('state') or ''
        if not gid:
            self._json({'ok': False, 'error': '缺少 gid'}, 400)
            return
        try:
            with closing(store.connect()) as conn:
                if state == 'clear':
                    store.clear_decision(conn, gid)
                else:
                    store.set_decision(conn, gid, state,
                                       entity_id=payload.get('entity_id'),
                                       title=payload.get('title') or '')
                self._json({'ok': True, 'counts': store.counts(conn)})
        except Exception as exc:
            self._json({'ok': False, 'error': str(exc)}, 500)

    # ── 資料 ────────────────────────────────────────────────────────────

    def _findings(self):
        with closing(store.connect()) as conn:
            items = store.load_findings(conn)
            counts = store.counts(conn)
        for item in items:
            item['label'] = VERDICT_LABEL.get(item['verdict'], item['verdict'])
            item['has_thumb'] = bool(item.get('thumb'))
            item.pop('found_at', None)
        return {'items': items, 'counts': counts,
                'order': list(VERDICT_ORDER), 'labels': VERDICT_LABEL}

    def _thumb(self, gid):
        gid = ''.join(ch for ch in gid if ch.isdigit())
        if not gid:
            self._send(404, 'text/plain', '404')
            return
        with closing(store.connect()) as conn:
            row = conn.execute(
                'SELECT thumb FROM checker_findings WHERE gid = ?', (gid,)).fetchone()
        url = row['thumb'] if row else ''
        path = thumbs.fetch(gid, url, self.server.cookie_header) if url else None
        if not path or not os.path.isfile(path):
            # 佔位圖：1×1 透明 GIF。缺圖不該讓版面塌掉，也不值得再往站方要一次。
            self._send(200, 'image/gif',
                       b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00'
                       b'!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01'
                       b'\x00\x00\x02\x02D\x01\x00;')
            return
        try:
            with open(path, 'rb') as handle:
                data = handle.read()
        except OSError:
            self._send(404, 'text/plain', '404')
            return
        self._send(200, thumbs.content_type(path), data,
                   extra_headers={'Cache-Control': 'max-age=86400'})


class WebUI:
    """本機 Web UI 的生命週期管理。與主視窗同生共死。"""

    def __init__(self):
        self._server = None
        self._thread = None
        self.token = ''

    @property
    def running(self):
        return self._server is not None

    def start(self, cookie_header=None):
        """啟動伺服器，回傳基底網址。已啟動時直接回傳現有網址。"""
        if self._server is not None:
            return self.url()

        self.token = secrets.token_urlsafe(24)
        # 埠號交給系統指派（port 0）：寫死埠號會在被別的程式佔用時直接啟動失敗。
        server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        server.token = self.token
        server.cookie_header = cookie_header
        server.daemon_threads = True

        self._server = server
        self._thread = threading.Thread(target=server.serve_forever,
                                        name='checker-webui', daemon=True)
        self._thread.start()
        return self.url()

    def url(self, gid=''):
        if self._server is None:
            return ''
        host, port = self._server.server_address[:2]
        base = f'http://{host}:{port}/?t={self.token}'
        return f'{base}#g{gid}' if gid else base

    def stop(self):
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._server = None
        self._thread = None
        self.token = ''


def _render_page(token):
    """整頁自足：CSS 與 JS 全部內嵌，不引用任何外部主機。"""
    return _PAGE.replace('__TOKEN__', html.escape(token, quote=True))


_PAGE = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>更新檢查器</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c1f23;--dim:#6b7280;--line:#e3e6ea;--accent:#2f66d0}
@media(prefers-color-scheme:dark){:root{--bg:#16181c;--card:#1f2228;--ink:#e8eaed;--dim:#9aa1ab;--line:#31353c;--accent:#7aa8dc}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15px/1.55 "Segoe UI","Microsoft JhengHei",system-ui,sans-serif}
header{position:sticky;top:0;z-index:10;background:var(--bg);
 border-bottom:1px solid var(--line);padding:12px 20px}
h1{margin:0 0 10px;font-size:19px}
.tabs{display:flex;gap:8px;flex-wrap:wrap}
.tab{border:1px solid var(--line);background:var(--card);color:var(--ink);
 padding:6px 14px;border-radius:999px;cursor:pointer;font-size:14px}
.tab.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.filters{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input,select{background:var(--card);color:var(--ink);border:1px solid var(--line);
 border-radius:6px;padding:6px 10px;font:inherit}
main{padding:18px 20px;display:grid;gap:14px;
 grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
 overflow:hidden;display:flex;flex-direction:column}
.card img{width:100%;height:190px;object-fit:cover;background:var(--line);display:block}
.body{padding:10px 12px;display:flex;flex-direction:column;gap:6px;flex:1}
.title{font-weight:600;font-size:14px;word-break:break-word}
.meta{color:var(--dim);font-size:12.5px;word-break:break-word}
.tagrow{display:flex;gap:5px;flex-wrap:wrap}
.tag{font-size:11.5px;border:1px solid var(--line);border-radius:4px;padding:1px 6px;color:var(--dim)}
.match{font-size:12px;color:var(--dim);border-left:3px solid var(--accent);
 padding-left:8px;word-break:break-all}
.acts{display:flex;gap:6px;padding:10px 12px;border-top:1px solid var(--line);flex-wrap:wrap}
button.act{flex:1;min-width:74px;border:1px solid var(--line);background:transparent;
 color:var(--ink);border-radius:6px;padding:6px 8px;cursor:pointer;font:inherit;font-size:13px}
button.act:hover{border-color:var(--accent);color:var(--accent)}
.empty{grid-column:1/-1;text-align:center;color:var(--dim);padding:50px 0}
a{color:var(--accent)}
</style></head><body>
<header>
  <h1>更新檢查器</h1>
  <div class="tabs" id="tabs"></div>
  <div class="filters">
    <input id="q" placeholder="搜尋標題或作者…" size="26">
    <select id="cat"><option value="">全部分類</option></select>
    <span class="meta" id="shown"></span>
  </div>
</header>
<main id="grid"><div class="empty">載入中…</div></main>
<script>
const T = "__TOKEN__";
let DATA = {items:[], counts:{}, order:[], labels:{}};
let tab = "new";

const esc = s => String(s==null?"":s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

async function load(){
  const r = await fetch("/api/findings?t="+encodeURIComponent(T));
  DATA = await r.json();
  drawTabs(); draw();
}

function drawTabs(){
  document.getElementById("tabs").innerHTML = DATA.order.map(v =>
    `<button class="tab${v===tab?" on":""}" data-v="${v}">${esc(DATA.labels[v])} ${DATA.counts[v]||0}</button>`
  ).join("");
  document.querySelectorAll(".tab").forEach(b =>
    b.onclick = () => { tab = b.dataset.v; drawTabs(); draw(); });

  const cats = [...new Set(DATA.items.map(i => i.category).filter(Boolean))].sort();
  const sel = document.getElementById("cat"), keep = sel.value;
  sel.innerHTML = '<option value="">全部分類</option>' +
    cats.map(c => `<option${c===keep?" selected":""}>${esc(c)}</option>`).join("");
}

function draw(){
  const q = document.getElementById("q").value.trim().toLowerCase();
  const cat = document.getElementById("cat").value;
  const rows = DATA.items.filter(i => i.verdict === tab
    && (!cat || i.category === cat)
    && (!q || ((i.title_jpn||"")+(i.title||"")+(i.entity_name||"")).toLowerCase().includes(q)));

  document.getElementById("shown").textContent = `顯示 ${rows.length} 筆`;
  document.getElementById("grid").innerHTML = rows.length ? rows.map(card).join("")
    : '<div class="empty">這一區沒有項目。</div>';
}

function card(i){
  const date = i.posted ? new Date(i.posted*1000).toISOString().slice(0,10) : "";
  const tags = (i.markers||[]).map(m => `<span class="tag">${esc(m)}</span>`).join("");
  const miss = (i.missing_markers||[]).length
    ? `<div class="meta">缺少版本：${esc(i.missing_markers.join("、"))}</div>` : "";
  const match = i.matched_local
    ? `<div class="match">本機：${esc(i.matched_local)}</div>` : "";
  return `<article class="card" id="g${esc(i.gid)}">
    <img loading="lazy" src="/thumb/${esc(i.gid)}?t=${encodeURIComponent(T)}" alt="">
    <div class="body">
      <div class="title">${esc(i.title_jpn || i.title)}</div>
      <div class="meta">${esc(i.entity_name||"")} · ${esc(i.category||"")} · ${esc(i.pages||"?")}頁 · ${date}</div>
      <div class="tagrow">${tags}</div>${miss}${match}
    </div>
    <div class="acts">
      <button class="act" onclick="decide('${esc(i.gid)}','downloaded',${i.entity_id||"null"})">已下載</button>
      <button class="act" onclick="decide('${esc(i.gid)}','ignored',${i.entity_id||"null"})">忽略</button>
      <button class="act" onclick="window.open('${esc(i.url)}','_blank','noopener')">開啟</button>
    </div></article>`;
}

async function decide(gid, state, entity_id){
  const r = await fetch("/api/decision?t="+encodeURIComponent(T), {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({gid, state, entity_id})});
  const res = await r.json();
  if(!res.ok){ alert("失敗：" + (res.error||"")); return; }
  DATA.items = DATA.items.filter(i => i.gid !== gid);
  DATA.counts = res.counts;
  drawTabs(); draw();
}

document.getElementById("q").oninput = draw;
document.getElementById("cat").onchange = draw;
load();
</script></body></html>
"""
