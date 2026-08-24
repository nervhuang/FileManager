"""單檔行數上限檢查（棘輪式）。

規則：
  - `app/` 底下每個 .py 上限 600 行。
  - 既有超標檔記在 .line-limit-baseline.json，只禁止它們「變得更長」。
  - 檔案拆小之後跑 `--update` 把基準線降下來；降了就不能再升回去。

為什麼要機械式的檢查：app/file_manager.py 長到 2808 行、一個 initUI 佔 548 行，
不是某次疏忽，是每次「順手再加一個方法」的累積。人不會在第 601 行停手，
CI 會。

用法：
    python scripts/check_line_limits.py            # 檢查，超標回 exit 1
    python scripts/check_line_limits.py --update   # 依現況重寫基準線
"""
import json
import os
import sys

# 主控台預設用系統 codepage（開發機的繁中 Windows 是 cp950，GitHub Actions 的
# windows runner 是 cp1252），印不出中文就直接拋 UnicodeEncodeError，讓「檢查
# 通過」的訊息把整支腳本弄成非零 exit code——檢查其實過了，死在印結果。
# 與 app/cli.py、tests/conftest.py 同一套處理。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except Exception:
        pass

LIMIT = 600
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SCAN_DIR = os.path.join(ROOT, 'app')
BASELINE_PATH = os.path.join(ROOT, '.line-limit-baseline.json')


def count_lines(path):
    with open(path, 'rb') as f:
        return sum(1 for _ in f)


def collect():
    """回傳 {相對路徑: 行數}，路徑一律用正斜線，Windows 與 CI 上結果才一致。"""
    counts = {}
    for dirpath, dirnames, filenames in os.walk(SCAN_DIR):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for name in filenames:
            if not name.endswith('.py'):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, ROOT).replace(os.sep, '/')
            counts[rel] = count_lines(full)
    return counts


def load_baseline():
    if not os.path.exists(BASELINE_PATH):
        return {}
    with open(BASELINE_PATH, encoding='utf-8') as f:
        return json.load(f).get('files', {})


def write_baseline(counts):
    over = {path: n for path, n in sorted(counts.items()) if n > LIMIT}
    payload = {
        '_comment': (
            f'單檔上限 {LIMIT} 行。這裡列的是既有超標檔，只擋它們變得更長；'
            '拆小之後跑 scripts/check_line_limits.py --update 把數字降下來。'
            '降了就不能再升回去。'),
        'limit': LIMIT,
        'files': over,
    }
    with open(BASELINE_PATH, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return over


def main():
    counts = collect()

    if '--update' in sys.argv:
        over = write_baseline(counts)
        print(f'基準線已更新：{len(over)} 個檔案超過 {LIMIT} 行')
        for path, n in sorted(over.items(), key=lambda kv: -kv[1]):
            print(f'  {n:5}  {path}')
        return 0

    baseline = load_baseline()
    failures, shrunk = [], []

    for path, n in sorted(counts.items()):
        allowed = baseline.get(path, LIMIT)
        if n > allowed:
            if path in baseline:
                failures.append(
                    f'{path}：{n} 行，超過它自己的基準線 {allowed} 行。'
                    f'這個檔案只准變短。')
            else:
                failures.append(
                    f'{path}：{n} 行，超過上限 {LIMIT} 行。'
                    f'拆成功能域套件，不要加進基準線。')
        elif path in baseline and n < allowed:
            shrunk.append(f'  {path}：{allowed} → {n}')

    if shrunk:
        print(f'以下檔案已比基準線短，跑 --update 把基準線降下來：')
        print('\n'.join(shrunk))
        print()

    if failures:
        print('行數檢查失敗：')
        for line in failures:
            print(f'  {line}')
        return 1

    print(f'行數檢查通過（{len(counts)} 個檔案，上限 {LIMIT} 行，'
          f'{len(baseline)} 個既有超標檔在基準線內）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
