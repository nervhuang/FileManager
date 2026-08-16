"""搜尋關鍵字的解析與查詢組裝（純函式，不依賴 Qt）。

原本這些邏輯都是 `FileManager(QMainWindow)` 的方法，只有 GUI 進程用得到。
Hermes MCP server 是獨立進程、沒有 Qt 視窗，卻必須跟 GUI 搜出完全一樣的結果，
因此抽成模組級函式讓兩邊共用；`file_manager.py` 端保留同名薄包裝方法。
"""

import os
import re
import unicodedata


def normalize_search_command(search_command):
    """將以 | 分隔的關鍵詞個別正規化，避免含空白詞組被 Everything 拆散。"""
    normalized_terms = []
    for raw_term in search_command.split('|'):
        term = raw_term.strip()
        if not term:
            continue
        if any(ch.isspace() for ch in term) and not (term.startswith('"') and term.endswith('"')):
            term = f'"{term}"'
        normalized_terms.append(term)
    return '|'.join(normalized_terms)


def split_terms(search_command):
    return [term.strip() for term in search_command.split('|') if term.strip()]


def strip_term_quotes(term):
    candidate = term.strip()
    if candidate.startswith('"') and candidate.endswith('"') and len(candidate) >= 2:
        return candidate[1:-1]
    return candidate


def normalize_text(text):
    normalized = unicodedata.normalize('NFKC', text or '').casefold()
    # 連字號（-）與點（.）不視為分隔符：像「A-10」「ver.2」「a.b.c」這類關鍵字
    # 需整體保留，不可被拆開。NFKC 已把全形 －／．正規化為半形 -／.。
    collapsed = re.sub(r'[^\w.-]+', ' ', normalized, flags=re.UNICODE)
    return ' '.join(collapsed.split())


def keyword_tokens(term):
    normalized = normalize_text(strip_term_quotes(term))
    # 過濾只剩連字號／點的孤立 token（如「tsf - saeki」中間的 -），避免污染查詢。
    return [token for token in normalized.split(' ') if token.strip('.-')]


def build_queries(term):
    raw_term = strip_term_quotes(term)
    queries = []
    seen = set()

    def add_query(query_text, normalize=True):
        query_text = query_text.strip()
        if not query_text or query_text in seen:
            return
        seen.add(query_text)
        # normalize=False：保留原樣送出（用於空白分隔的 AND 查詢，
        # 不可被 normalize_search_command 加引號變成片語比對）。
        queries.append(normalize_search_command(query_text) if normalize else query_text)

    add_query(raw_term)
    add_query(f'[{raw_term}]')

    # 全形括弧等符號（（）【】「」『』〔〕…）與連字號在檔名/關鍵字中通常只是
    # 標註或分隔，使用者真正想搜的是「符號之間的文字」。但原本只把含符號的原字串
    # 交給 Everything，實際檔名不含那些符號時就查無結果（如搜「（重要）」找不到
    # 「重要.txt」、搜「【tsf-saeki】」找不到「tsf-saeki」）。這裡改以去符號後的
    # tokens（NFKC 正規化＋去標點，已涵蓋全形/半形括弧與連字號）組查詢：
    #   單一詞 → 直接查該詞；
    #   多個詞 → 以空白分隔（Everything 原生 AND，不加引號、不需開 regex 旗標、
    #            也不要求詞序）查詢，最穩健；另保留 regex 依序串接作為輔助。
    tokens = keyword_tokens(term)
    if len(tokens) == 1:
        add_query(tokens[0])
    elif len(tokens) >= 2:
        add_query(' '.join(tokens), normalize=False)
        add_query('regex:' + '.*'.join(re.escape(token) for token in tokens))

    return queries


def path_matches(path, term):
    tokens = keyword_tokens(term)
    if not tokens:
        return False

    normalized_path = normalize_text(os.path.basename(path))
    # 以「去符號後的各詞是否都出現在檔名」為準，與查詢端一致：括弧會被正規化成
    # 空白，若仍要求整個 normalized_term 為連續子字串，會因括弧造成的空白差異
    # （如關鍵字「重要（報告）」對檔名「重要報告」）而誤判不符。改為各詞皆需命中。
    return all(token in normalized_path for token in tokens)


def is_plain_keyword_term(term):
    candidate = strip_term_quotes(term)
    if not candidate:
        return False
    return not any(token in candidate for token in (':', '<', '>', '!', '*', '?'))


# GUI 逐個查詢變體向 Everything 索取的筆數上限。這兩個值決定了「一次搜尋最多
# 看得到幾筆」，GUI 沿用至今；需要完整結果集的呼叫端（例如 Hermes 的大量搜尋）
# 可用 scale 參數等比放大。
PRIMARY_QUERY_LIMIT = 2000
VARIANT_QUERY_LIMIT = 800
# 帶 Everything 原生語法（: < > ! * ?）的查詢整串原樣送出，沿用 SDK 的預設筆數。
RAW_QUERY_LIMIT = 200


def search_plain_keyword_terms(everything, terms, limit_scale=1):
    """逐個關鍵詞查詢並聯集去重（| 在此語意為 OR）。

    回傳 (results, capped)。capped 表示至少有一個查詢變體撈滿了上限，也就是
    Everything 可能還有更多符合的項目沒被取回——呼叫端要據此回報結果不完整。
    """
    results = []
    seen = set()
    capped = False
    for term in terms:
        for query_text in build_queries(term):
            base = (PRIMARY_QUERY_LIMIT
                    if query_text.startswith('regex:') or query_text == strip_term_quotes(term)
                    else VARIANT_QUERY_LIMIT)
            max_results = base * limit_scale
            items = everything.query(query_text, max_results=max_results)
            if len(items) >= max_results:
                capped = True
            for item in items:
                if item.path in seen or not path_matches(item.path, term):
                    continue
                seen.add(item.path)
                results.append(item)
    return results, capped


# ── 排除目錄 ────────────────────────────────────────────────────────────

def normalize_exclude_dirs(dirs):
    return tuple(os.path.normcase(os.path.normpath(d)) for d in (dirs or []) if d)


def is_path_excluded(path, exclude_norm):
    if not exclude_norm:
        return False
    norm = os.path.normcase(os.path.normpath(path))
    for ex in exclude_norm:
        if norm == ex:
            return True
        # 磁碟根目錄（如 C:\）normpath 後已帶尾端分隔符，避免補成雙分隔符。
        base = ex if ex.endswith(os.sep) else ex + os.sep
        if norm.startswith(base):
            return True
    return False


def query_everything(everything, search_command, limit_scale=1):
    """執行一次完整搜尋，回傳 (SearchResult 清單, 是否撈滿上限)。不套排除設定。

    與 GUI 的 `_do_search` 判斷一致：所有關鍵詞都是純關鍵字時走多重查詢＋比對
    過濾；只要有一個帶 Everything 語法符號（: < > ! * ?）就整串原樣送出。
    """
    terms = split_terms(search_command)
    if terms and all(is_plain_keyword_term(term) for term in terms):
        return search_plain_keyword_terms(everything, terms, limit_scale)
    max_results = RAW_QUERY_LIMIT * limit_scale
    items = everything.query(normalize_search_command(search_command), max_results=max_results)
    return items, len(items) >= max_results


def run_search(everything, search_command, exclude_norm=(), under_dir=None, ext=None,
               limit=None, offset=0, limit_scale=1):
    """MCP 端用的搜尋入口：查詢＋排除過濾＋路徑/副檔名限縮＋分頁。

    回傳 (results, info)。info 內含：
      total     過濾後的總筆數（不受 limit/offset 影響）
      offset    實際起始位置
      returned  本次回傳筆數
      has_more  offset+returned 之後還有沒有資料
      capped    Everything 端撈滿了上限，代表 total 本身可能仍是低估

    capped 與 has_more 是兩回事：前者是「索引裡可能還有更多沒取回」，後者是
    「這次分頁沒給完」。舊版只回一個 truncated 且只反映 limit 的裁切，撞到
    Everything 上限時會謊報未截斷。
    """
    results, capped = query_everything(everything, search_command, limit_scale)

    if exclude_norm:
        results = [r for r in results if not is_path_excluded(r.path, exclude_norm)]

    if under_dir:
        base = os.path.normcase(os.path.normpath(under_dir))
        if not base.endswith(os.sep):
            base += os.sep
        results = [
            r for r in results
            if os.path.normcase(os.path.normpath(r.path)).startswith(base)
        ]

    if ext:
        wanted = {e.lower().lstrip('.') for e in ([ext] if isinstance(ext, str) else ext) if e}
        if wanted:
            results = [
                r for r in results
                if not r.is_dir and os.path.splitext(r.path)[1].lower().lstrip('.') in wanted
            ]

    total = len(results)
    offset = max(0, int(offset or 0))
    page = results[offset:offset + limit] if limit else results[offset:]
    info = {
        'total': total,
        'offset': offset,
        'returned': len(page),
        'has_more': offset + len(page) < total,
        'capped': capped,
    }
    return page, info
