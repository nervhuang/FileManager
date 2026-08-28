"""掃描編排：把實體清單、抓取層與比對層串成一次完整檢查。

本機檔案的取得方式以可注入的 `local_lookup` 傳入，理由有二：純比對邏輯得以在
沒有 Everything、沒有 GUI 的情況下測試；真正跑起來時則由 `everything_lookup()`
接上與 `authors-stats` 完全相同的搜尋管線，確保兩邊算出來的檔案集合一致。

錯誤在這層收斂：單一實體失敗只記在該實體的 `error` 欄位，不中斷整輪；
只有限流與 cookie 失效才會中止全部——那兩種情況繼續跑下去也只是空轉。
"""

import datetime
import html
import os

from . import fetcher, limits as limits_settings, matcher, titles

# 預設值住在 limits.py，因為使用者調得動它（選項 → 更新檢查筆數）。
# 這兩個名字留著當函式預設值，呼叫端沒特別指定時行為與以前一致。
FIRST_RUN_LIMIT = limits_settings.FIRST_RUN_DEFAULT
MAX_ITEMS = limits_settings.MAX_ITEMS_DEFAULT
PAGE_SIZE = 25


def _parse_posted(text):
    """把 tag 頁的 '2026-08-21 20:04' 轉成 datetime；解析不了回 None。"""
    try:
        return datetime.datetime.strptime((text or '').strip(), '%Y-%m-%d %H:%M')
    except ValueError:
        return None


def everything_lookup(everything, exclude_norm=()):
    """回傳一個 local_lookup 函式，走與 authors-stats 相同的搜尋管線。"""
    from ..authors import db as authors_db
    from ..search import query as search_query

    def lookup(entity):
        terms = authors_db.search_terms_for(entity)
        if not terms:
            return []
        results, _info = search_query.run_search(
            everything, terms, exclude_norm, limit=None, limit_scale=1)

        # 藏書是以作者名分資料夾的，搜尋一併撈到那層資料夾本身（如 E:\コミック\As109）。
        # 那不是一本書，留在索引裡會讓低分項目對到一個純作者名，報告上看起來像有對到
        # 卻毫無意義。以名稱是否等於實體的搜尋詞來排除，這樣解壓縮成資料夾的單行本
        # （名稱是書名）仍會保留。
        own_names = {t.strip().casefold() for t in terms.split('|') if t.strip()}
        names = []
        for result in results:
            name = os.path.basename(result.path)
            if result.is_dir and name.strip().casefold() in own_names:
                continue
            names.append(name)
        return names

    return lookup


def scan_entity(entity, fetch, local_lookup, *, last_scan_at=None,
                threshold=matcher.DEFAULT_THRESHOLD,
                first_run_limit=FIRST_RUN_LIMIT, max_items=MAX_ITEMS):
    """掃描單一作者／團體，回傳該實體的完整比對結果。

    `last_scan_at` 為 None 代表首次掃描：只取 `first_run_limit` 筆建立基準，
    不追溯歷史。有值時往回取到發布時間早於它為止，最多 `max_items` 筆。
    兩個上限由使用者設定（見 limits.py），這裡只收數字。
    """
    tag = fetcher.tag_for(entity)
    result = {
        'entity_id': entity.get('id'), 'name': entity.get('name'),
        'type': entity.get('type'), 'tag': tag,
        'items': [], 'works': [], 'error': None, 'skipped': None, 'truncated': False,
        'newest_posted': '', 'excluded': 0,
    }
    if not tag:
        result['skipped'] = 'no_english_name'
        return result

    # ── 決定要取幾筆 ────────────────────────────────────────────────────
    first_run = last_scan_at is None
    wanted = first_run_limit if first_run else max_items
    # reached_cutoff 只回答「有沒有翻到頭」。首次掃描沒有上次掃描時間可追，
    # 但仍然要照 wanted 翻頁——以前這裡預設 True，等於首次掃描永遠只翻一頁，
    # 筆數寫死 25（＝一頁）時看不出來，一旦可調就會發現設 100 只拿到 25。
    collected, reached_cutoff = [], False
    for page in range((wanted + PAGE_SIZE - 1) // PAGE_SIZE):
        rows = fetch.fetch_tag_page(tag, page=page)
        if not rows:
            reached_cutoff = True
            break
        # tag 頁依發布時間新→舊排序，第一頁第一筆就是本輪的最新一筆。
        # 記下它當作下次掃描的分頁基準——與站上時間同源，不受本機時區影響。
        if page == 0 and rows[0][2]:
            result['newest_posted'] = rows[0][2]
        for gid, token, posted_text in rows:
            posted = _parse_posted(posted_text)
            if not first_run and posted and posted < last_scan_at:
                reached_cutoff = True
                break
            collected.append((gid, token))
            if len(collected) >= wanted:
                break
        if reached_cutoff or len(collected) >= wanted or len(rows) < PAGE_SIZE:
            if len(rows) < PAGE_SIZE:
                reached_cutoff = True
            break

    # 追到上限還沒接上上次掃描時間，代表這段期間的發布量超過 max_items，
    # 中間可能有漏。明白標示出來，不靜默吞掉。調大上限就是使用者對這件事的回應。
    # 首次掃描不算：那是在建基準，沒有「上次掃到哪」可以追，取滿就是取滿。
    result['truncated'] = (not first_run and not reached_cutoff
                           and len(collected) >= wanted)

    if not collected:
        return result

    metadata = fetch.fetch_metadata(collected)

    # ── 本機藏書 ────────────────────────────────────────────────────────
    local_items = [titles.parse(name, is_filename=True)
                   for name in local_lookup(entity)]

    # ── 逐本判定 ────────────────────────────────────────────────────────
    for gid, token in collected:
        meta = metadata.get(gid)
        if not meta:
            continue
        # API 回傳的標題是 HTML 跳脫過的（撇號會變成 &#039;），先還原再解析，
        # 否則跳脫字元會被當成標題的一部分拿去比對。
        japanese = html.unescape(meta.get('title_jpn') or '').strip()
        english = html.unescape(meta.get('title') or '').strip()
        # title_jpn 有時是空的（純英文投稿），此時只能退回英文標題。
        parsed = titles.parse(japanese or english)
        # 標記有三個來源，聯集起來判斷：
        #   1. 標題括號裡的文字（關鍵字比對）——已在 parse() 裡做完
        #   2. 站上 language: namespace 的值（直接讀，不猜）
        #   3. 站上其他 tag 的關鍵字（無修正之類的品質標記）
        # 語言只認 2 與 1，不從 3 猜：那會被 female:／other: 裡剛好含語言名稱的
        # tag 誤判。品質標記則相反，只有 3 認得出來。
        tags = meta.get('tags') or []
        quality = {m for m in titles.detect_markers(*tags)
                   if not m.startswith(titles.LANGUAGE_PREFIX)}
        parsed['markers'] = (parsed['markers']
                             | titles.site_language_markers(tags)
                             | quality)

        verdict = matcher.classify(parsed, local_items, threshold)
        if verdict['verdict'] == matcher.VERDICT_SUPPRESSED:
            result['excluded'] += 1
        result['items'].append({
            'gid': gid, 'token': token,
            'url': f'https://exhentai.org/g/{gid}/{token}/',
            'title': english, 'title_jpn': japanese,
            'display_title': japanese or english,
            'core': parsed['core'],
            'category': meta.get('category', ''),
            'pages': meta.get('filecount', ''),
            'thumb': meta.get('thumb', ''),
            'posted': meta.get('posted', ''),
            'markers': sorted(parsed['markers']),
            'verdict': verdict['verdict'],
            'score': round(verdict['score'], 4),
            'missing_markers': verdict['missing_markers'],
            # 判定為新書時不填對照檔名：那只是分數最高的候選，可能低到毫無關係，
            # 寫進報告會讓使用者以為真的對到了什麼。
            'matched_local': ('' if verdict['verdict'] == matcher.VERDICT_NEW
                              else (verdict['matched'] or {}).get('raw', '')),
        })

    result['works'] = aggregate(result['items'])
    return result


# 聚合後決定整部作品該落在哪一格：越前面越優先顯示。
_VERDICT_PRIORITY = (matcher.VERDICT_UPGRADE, matcher.VERDICT_NEW,
                     matcher.VERDICT_MAYBE, matcher.VERDICT_HAVE,
                     matcher.VERDICT_SUPPRESSED)


def _version_rank(item):
    """挑代表版本用的排序鍵：偏好語言優先，其次無修正，再次頁數多。"""
    markers = set(item['markers'])
    return (
        0 if titles.is_wanted_language(markers) else 1,
        0 if 'decensored' in markers else 1,
        -int(item['pages'] or 0),
    )


def aggregate(items):
    """把同一部作品的多個版本收成一列。

    站上同一本書常有多次上傳與多語版本，各自是不同的 gid，用 gid 去重擋不住。
    實測一位作者的同一本書可以同時出現韓譯、西譯、葡譯三筆，全都對到同一個本機
    檔案、全都說「缺無修正」——使用者只需要看到一次。
    """
    groups = {}
    for item in items:
        groups.setdefault(item['core'] or item['gid'], []).append(item)

    works = []
    for versions in groups.values():
        versions.sort(key=_version_rank)
        verdicts = {v['verdict'] for v in versions}
        verdict = next((v for v in _VERDICT_PRIORITY if v in verdicts),
                       matcher.VERDICT_SUPPRESSED)
        # 代表版本要能解釋這一格的判定，因此從同判定的版本裡挑。
        primary = next(v for v in versions if v['verdict'] == verdict)
        works.append({
            'verdict': verdict,
            'primary': primary,
            'versions': versions,
            'version_count': len(versions),
            'languages': sorted({lang for v in versions
                                 for lang in titles.languages(v['markers'])}),
        })

    works.sort(key=lambda w: (_VERDICT_PRIORITY.index(w['verdict']),
                              -int(w['primary']['posted'] or 0)))
    return works


def scan_all(conn, entities, fetch, local_lookup, *,
             threshold=matcher.DEFAULT_THRESHOLD, progress=None, on_result=None,
             limits=None):
    """依序掃描多個實體並把結果寫進資料庫，回傳每個實體的結果。

    錯誤分兩級：單一實體的抓取或解析失敗只記在該實體上、繼續掃下一個；
    cookie 失效與連續限流會往上拋，因為那兩種情況繼續跑也只是空轉，
    而且會讓後面幾百個實體全部記上假的失敗紀錄。

    `limits` 是 `limits.Limits`；沒給就在這裡讀一次設定檔。**只讀一次**——
    幾百個實體逐一去讀同一個檔案，讀到的還是同一份。

    `progress(index, total, entity)` 在每個實體開始前呼叫，
    `on_result(index, total, result)` 在該實體寫入資料庫後呼叫——前者讓呼叫端知道
    正在跑誰，後者讓它知道跑出了什麼。中止由 `fetch.cancelled` 控制，
    已掃完的實體都已經寫入資料庫，下次接著跑。
    """
    from . import store

    store.ensure_schema(conn)
    if limits is None:
        limits = limits_settings.load()
    entities = list(entities)
    results = []

    for index, entity in enumerate(entities):
        if fetch.cancelled:
            break
        if progress:
            progress(index, len(entities), entity)

        entity_id = entity.get('id')
        try:
            result = scan_entity(entity, fetch, local_lookup,
                                 last_scan_at=store.last_posted(conn, entity_id),
                                 threshold=threshold,
                                 first_run_limit=limits.first_run,
                                 max_items=limits.max_items)
        except fetcher.ScanAborted:
            # 中止類的錯誤（憑證失效、連續限流、連續連線失敗）往上拋。
            # 走下面那條「記在這位身上、換下一位」只會讓剩下的幾百位
            # 全部記上同一個假的失敗。
            raise
        except fetcher.CheckerError as exc:
            result = {'entity_id': entity_id, 'name': entity.get('name'),
                      'type': entity.get('type'), 'tag': fetcher.tag_for(entity),
                      'items': [], 'works': [], 'skipped': None,
                      'truncated': False, 'newest_posted': '', 'excluded': 0,
                      'error': str(exc)}
            store.record_scan(conn, entity_id, error=str(exc))
            results.append(result)
            if on_result:
                on_result(index, len(entities), result)
            continue

        if not result['skipped']:
            store.save_findings(conn, entity_id, result['items'])
            # 用當前本機索引重評既有結果：使用者下載完的書會自動從新書轉成已有，
            # 增量掃描不會再抓到它們，沒有這步就會永遠停在新書。
            local_items = [titles.parse(name, is_filename=True)
                           for name in local_lookup(entity)]
            store.refresh_verdicts(conn, entity_id, local_items, threshold)
            store.reconcile_downloads(conn, entity_id)
            store.record_scan(conn, entity_id,
                              newest_posted=result['newest_posted'],
                              truncated=result['truncated'])
        results.append(result)
        if on_result:
            on_result(index, len(entities), result)

    return results


def summarize(results):
    """把多個實體的結果彙總成四區塊計數。

    以聚合後的「作品」計數而非原始筆數——同一本書的多語版本算一部作品，
    否則計數會被重複上傳灌水，使用者看到的數字跟實際要處理的量對不上。
    """
    counts = {matcher.VERDICT_NEW: 0, matcher.VERDICT_UPGRADE: 0,
              matcher.VERDICT_MAYBE: 0, matcher.VERDICT_HAVE: 0,
              matcher.VERDICT_SUPPRESSED: 0}
    for result in results:
        for work in result.get('works') or ():
            counts[work['verdict']] = counts.get(work['verdict'], 0) + 1
    return {
        'entities': len(results),
        'scanned': sum(1 for r in results if not r['skipped'] and not r['error']),
        'skipped': [r['name'] for r in results if r['skipped']],
        'errors': [(r['name'], r['error']) for r in results if r['error']],
        'truncated': [r['name'] for r in results if r['truncated']],
        'counts': counts,
    }
