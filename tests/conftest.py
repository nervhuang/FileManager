"""全域測試設定。

這個檔案在任何 app.* 模組被匯入之前執行，因為隔離必須先於匯入生效。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ── 與開發者的個人設定隔離 ────────────────────────────────────────────────
# FileManager 會讀 runtime_root() 底下的 config.ini（docs/spec/settings.md 的 SET-1）。
# 開發機上那份是真實設定：[Exclude] 可能排除整個磁碟，把測試資料整批濾光，
# 於是測試在 CI 上綠、在開發機上紅。指向一個空的暫存目錄，程式就以內建預設值
# 執行（SET-5），寫出的設定也只落在那裡。
os.environ['FILEMANAGER_HOME'] = tempfile.mkdtemp(prefix='fm_test_home_')

# ── 無頭執行 ──────────────────────────────────────────────────────────────
# offscreen 平台讓 Qt 在沒有桌面的環境（CI）也能建立 widget。
# 注意：它量得到 widget 的尺寸、字型、選取狀態，但不會真的畫出文字——
# 「看起來對不對」一律標成 manual，不要試圖用 offscreen 判定外觀。
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

# 主控台編碼：繁中 Windows 是 cp950，測試輸出含日文檔名或勾號會直接拋
# UnicodeEncodeError，讓斷言全過的測試以非零 exit code 收場。與 app/cli.py 同一套處理。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except Exception:
        pass

import pytest  # noqa: E402


@pytest.fixture
def main_window(qapp, tmp_path, monkeypatch):
    """真實的 FileManager 主視窗，測試結束後關閉。

    建立成本不低（會載入設定、建立三條工具列與兩個面板），需要它的測試才用。
    只驗 model/proxy 的測試請直接建立該類別，不要拉整個主視窗進來。

    每個測試各自一份 FILEMANAGER_HOME：`closeEvent` 會把字級、版面、分頁
    寫回 config.ini（SET-14），共用一個目錄的話前一個測試的結束狀態就成了
    下一個測試的起始狀態，字型相關的測試會因此互相污染。
    """
    monkeypatch.setenv('FILEMANAGER_HOME', str(tmp_path / 'home'))
    (tmp_path / 'home').mkdir()

    from app.file_manager import FileManager
    window = FileManager()
    window.show()
    qapp.processEvents()
    yield window
    window.close()
    qapp.processEvents()
