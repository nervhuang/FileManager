"""三級比對：站上一本書對上本機藏書後，判定它是新書、版本升級、疑似已有或已有。

（純函式，不依賴 Qt、不碰網路。）

為什麼不做兩級：本機檔名常有錯字。實測同一本書在本機是「美柑はパンツはさくらいろ」，
站上是「美柑はパンツもさくらいろ」，只差一個假名；用完全比對會判成新書，用模糊比對
又會把真正的新書吃掉——同一位作者的「美柑のパンツはさくらいろ」是另一本書，字串同樣
只差一個假名。兩者無法用單一門檻分開，所以中間那段交給人判斷。

作品系列（series）用來擋掉跨作品的假陽性：標題再像，系列不同就幾乎不可能是同一本。
"""

import difflib

from . import titles

# 判定為「疑似已有」的相似度下限。低於此值視為新書。
DEFAULT_THRESHOLD = 0.85

VERDICT_NEW = 'new'                # 🆕 新書
VERDICT_UPGRADE = 'upgrade'        # ⬆️ 版本升級
VERDICT_MAYBE = 'maybe'            # ❓ 疑似已有
VERDICT_HAVE = 'have'              # ✅ 已有
VERDICT_SUPPRESSED = 'suppressed'  # 靜音，不進任何清單


def similarity(a, b):
    """兩個 core 鍵的相似度，0.0–1.0。空字串一律回 0。"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _series_conflict(site, local):
    """兩邊都標了系列而且對不起來時為真——這是跨作品假陽性的主要來源。"""
    site_series = titles.core_key(site.get('series'))
    local_series = titles.core_key(local.get('series'))
    if not site_series or not local_series:
        return False
    if site_series == local_series:
        return False
    # 系列名寫法常有長短差異（「To LOVEる」對「To LOVEる -とらぶる-」），
    # 互為子字串就當同一個系列。
    if site_series in local_series or local_series in site_series:
        return False
    return similarity(site_series, local_series) < 0.7


def best_match(site, locals_, threshold=DEFAULT_THRESHOLD):
    """在本機清單中找出最像的一本，回傳 (項目, 相似度)；找不到回 (None, 0.0)。"""
    best, best_score = None, 0.0
    for local in locals_:
        if _series_conflict(site, local):
            continue
        score = similarity(site['core'], local['core'])
        if score > best_score:
            best, best_score = local, score
    if best_score <= 0.0:
        return None, 0.0
    return best, best_score


def classify(site, locals_, threshold=DEFAULT_THRESHOLD,
             preferred=titles.PREFERRED_MARKERS):
    """判定站上這一本相對於本機藏書的處置。

    回傳 dict：verdict、score、matched（對到的本機項目）、missing_markers
    （站上有、本機該本沒有的偏好標記，即「版本升級」的理由）。
    """
    match, score = best_match(site, locals_, threshold)
    result = {'verdict': VERDICT_NEW, 'score': score, 'matched': match,
              'missing_markers': []}

    if match is None or score < threshold:
        return result

    # 標題對上了，再看版本。本機同名的所有版本一起算，因為同一本書的中譯版與
    # 原版常是分開的兩個檔案，只看比中的那一個會誤報升級。
    same_title = [l for l in locals_
                  if l['core'] == match['core'] or similarity(l['core'], match['core']) >= threshold]
    local_markers = set()
    for local in same_title:
        local_markers |= local['markers']

    site_markers = site.get('markers') or set()

    # 非白名單語言（英、韓、西、葡…）且本機已有這本：使用者不收這些語言，靜音不打擾。
    # 本機沒有這本時不靜音——那是一本沒收過的作品，仍該讓使用者知道它存在。
    if same_title and not titles.is_wanted_language(site_markers):
        result['verdict'] = VERDICT_SUPPRESSED
        return result

    missing = [m for m in preferred if m in site_markers and m not in local_markers]
    if missing:
        result['verdict'] = VERDICT_UPGRADE
        result['missing_markers'] = missing
        return result

    result['verdict'] = VERDICT_HAVE if score >= 1.0 else VERDICT_MAYBE
    return result
