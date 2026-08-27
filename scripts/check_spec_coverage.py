"""規格條文的測試覆蓋檢查。

規則：`docs/spec/` 裡每一條編號條文，要嘛被某支測試引用（檔案內容出現該編號），
要嘛在條文段落裡標著 `[手動]`。兩者都沒有就是漏了。

為什麼要機械式檢查：條文與測試是靠「測試檔名／docstring 引用編號」串起來的，
那是一條沒有編譯器把關的線。新增條文時忘了補測試，或刪測試時忘了改條文，
都不會有任何提示——正是這個專案原本「功能默默消失」的同一種失效方式。

引用只需要「內容裡出現該編號」，不要求特定寫法：測試檔名、docstring、
assert 訊息都算。這是刻意放寬的——重點是「有人負責這條」，不是格式。

用法：
    python scripts/check_spec_coverage.py            # 有漏就 exit 1
    python scripts/check_spec_coverage.py --list     # 印出完整對照表
"""
import io
import os
import re
import sys

# 主控台預設用系統 codepage（開發機 cp950、CI 的 windows runner cp1252），
# 印不出中文會直接拋 UnicodeEncodeError——檢查其實過了，死在印結果。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SPEC_DIR = os.path.join(ROOT, 'docs', 'spec')
TESTS_DIR = os.path.join(ROOT, 'tests')

PREFIXES = 'SET|SRCH|FOP|TAB|AUT|INT|SHL'
ANY_ID = re.compile(rf'\b({PREFIXES})-(\d+[a-z]?)\b')
CLAUSE_HEAD = re.compile(rf'^\*\*((?:{PREFIXES})-\d+[a-z]?)\*\*')
MANUAL = '[手動]'


def _sort_key(clause_id):
    match = ANY_ID.match(clause_id)
    return (match.group(1), int(re.sub(r'[a-z]', '', match.group(2))), match.group(2))


def collect_clauses():
    """回傳 {條文編號: (規格檔名, 是否標記手動)}。

    `[手動]` 可能寫在條文的第一行，也可能寫在同段落的後續行——條文常常要換行，
    只看第一行會誤判成沒標。段落以空行結束。
    """
    clauses = {}
    for name in sorted(os.listdir(SPEC_DIR)):
        if not name.endswith('.md') or name == 'README.md':
            continue
        current = None
        for line in io.open(os.path.join(SPEC_DIR, name), encoding='utf-8'):
            head = CLAUSE_HEAD.match(line.strip())
            if head:
                current = head.group(1)
                clauses[current] = [name, MANUAL in line]
            elif current and not line.strip():
                current = None
            elif current and MANUAL in line:
                clauses[current][1] = True
    return {cid: tuple(value) for cid, value in clauses.items()}


def collect_referenced():
    """測試裡出現過的條文編號。"""
    referenced = set()
    for root, dirs, files in os.walk(TESTS_DIR):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for name in files:
            if not name.endswith('.py'):
                continue
            text = io.open(os.path.join(root, name), encoding='utf-8').read()
            referenced |= {f'{a}-{b}' for a, b in ANY_ID.findall(text)}
            referenced |= {f'{a}-{b}' for a, b in ANY_ID.findall(name.upper())}
    return referenced


def main():
    clauses = collect_clauses()
    referenced = collect_referenced()

    covered = {c for c in clauses if c in referenced}
    manual = {c for c, (_f, m) in clauses.items() if m}
    missing = sorted(set(clauses) - covered - manual, key=_sort_key)

    by_file = {}
    for cid, (fname, is_manual) in clauses.items():
        by_file.setdefault(fname, []).append((cid, cid in covered, is_manual))

    print(f'規格 {len(clauses)} 條｜測試涵蓋 {len(covered)}｜'
          f'標記 {MANUAL} {len(manual)}｜未覆蓋 {len(missing)}')
    for fname in sorted(by_file):
        rows = by_file[fname]
        gaps = sorted([c for c, cov, man in rows if not cov and not man], key=_sort_key)
        print(f'  {fname:16} {sum(1 for _c, cov, _m in rows if cov):2}/{len(rows):2}'
              f'  手動 {sum(1 for _c, _cov, m in rows if m)}'
              + (f'  未覆蓋：{" ".join(gaps)}' if gaps else ''))

    if '--list' in sys.argv:
        print()
        for cid in sorted(clauses, key=_sort_key):
            state = '手動' if cid in manual else ('覆蓋' if cid in covered else '未覆蓋')
            print(f'  {state}  {cid:10} {clauses[cid][0]}')

    if missing:
        print(f'\n以下條文既沒有測試引用，也沒有標記 {MANUAL}：')
        for cid in missing:
            print(f'  {cid:10} {clauses[cid][0]}')
        print('\n補一支測試（檔名或 docstring 帶上編號），'
              f'或在條文段落裡標 {MANUAL} 並寫明為什麼只能人工驗收。')
        return 1

    print('\n每一條規格都有測試或已標記為人工驗收。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
