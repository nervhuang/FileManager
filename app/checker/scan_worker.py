"""背景掃描執行緒。

掃描一輪全量約 25–35 分鐘（加上第二個來源更久），必須在背景執行緒跑，且隨時
可停。所有可能拋出的邊界都在此收斂成訊號，不讓例外冒進 Qt 事件圈把主程式一起
帶走。

從 panel.py 拆出來：那個檔案撞到 600 行上限，而這個類別與面板之間只有四個
訊號一條線，是最好切的地方。它也是唯一需要知道「有幾個來源」的地方。
"""

from contextlib import closing

from PyQt5.QtCore import QThread, pyqtSignal

from . import fetcher, scanner, store, wnacg


class ScanWorker(QThread):
    """在背景執行緒跑一輪掃描。"""

    progress = pyqtSignal(int, int, str)   # 索引、總數、目前實體名稱
    entity_done = pyqtSignal(int, int, object)  # 索引、總數、該實體的結果 dict
    done = pyqtSignal(dict)                # summarize() 的結果
    failed = pyqtSignal(str)

    def __init__(self, entity_type='', keyword='', limit=0, parent=None):
        super().__init__(parent)
        self._entity_type = entity_type
        self._keyword = keyword
        self._limit = limit
        self._fetch = None
        self._wnacg_fetch = None

    def cancel(self):
        # 兩個來源各自一個抓取器，取消要同時對兩個講，否則按了停止之後
        # 還會繼續往第二個站打請求。
        for fetch in (self._fetch, self._wnacg_fetch):
            if fetch is not None:
                fetch.cancelled = True

    def run(self):
        from ..authors import db as authors_db
        from ..search.everything import EverythingSDK

        try:
            # EverythingSDK 在建構時會建立一個訊息視窗，而視窗的訊息佇列屬於
            # 建立它的執行緒。必須在這裡（工作執行緒內）建立，若沿用主執行緒的
            # 實例，query() 會安靜地逾時回傳空清單——比對會把整櫃藏書誤判成沒有。
            everything = EverythingSDK()
            if not everything.is_available():
                self.failed.emit('Everything 沒有在執行，無法取得本機檔案清單。')
                return

            self._fetch = fetcher.Fetcher(fetcher.load_cookie_header())
            # 第二個來源自己一個抓取器：不帶 cookie（那個站不需要登入），
            # 間隔也短一些——它沒有 exhentai 那麼嚴，共用一個節流器會讓
            # 整輪時間平白多一倍。
            self._wnacg_fetch = fetcher.Fetcher('', delay=wnacg.DELAY, jitter=0.5)
            lookup = scanner.everything_lookup(everything)

            with closing(store.connect()) as conn:
                entities = authors_db.list_entities(
                    conn, type_=self._entity_type or None,
                    keyword=self._keyword or None, limit=self._limit or None)
                results = scanner.scan_all(
                    conn, entities, self._fetch, lookup,
                    wnacg_fetch=lambda url: self._wnacg_fetch.fetch_html(
                        url, cookie=False),
                    progress=lambda i, total, e: self.progress.emit(
                        i, total, e.get('name') or ''),
                    on_result=lambda i, total, r: self.entity_done.emit(i, total, r))
                self.done.emit(scanner.summarize(results))
        except fetcher.CookieExpired as exc:
            self.failed.emit(str(exc))
        except fetcher.CheckerError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:            # 背景執行緒的例外沒人接就會靜默終止
            self.failed.emit(f'掃描發生未預期的錯誤：{exc}')
