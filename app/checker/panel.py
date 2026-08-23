"""更新檢查器面板與背景掃描執行緒。

面板只放摘要：四區塊計數與新書清單。要逐本判斷「這本我到底有沒有」時得看縮圖
與並排的本機檔名，那是 Web UI 的工作（雙擊清單項目開啟）。

掃描一輪全量約 25–35 分鐘，必須在背景執行緒跑，且隨時可停。所有可能拋出的
邊界都在此收斂成訊號，不讓例外冒進 Qt 事件圈把主程式一起帶走。
"""

from contextlib import closing

from PyQt5.QtCore import QSize, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QIcon
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolBar, QToolButton,
    QTreeWidget, QTreeWidgetItem, QFrame, QStyle, QAbstractItemView,
)

from . import fetcher, matcher, scanner, store, webui

VERDICT_LABEL = {
    matcher.VERDICT_NEW: '🆕 新書',
    matcher.VERDICT_UPGRADE: '⬆️ 版本升級',
    matcher.VERDICT_MAYBE: '❓ 疑似已有',
    matcher.VERDICT_HAVE: '✅ 已有',
}
# 面板只顯示需要動作的兩類；已有與疑似留給 Web UI，否則清單會被淹沒。
PANEL_VERDICTS = (matcher.VERDICT_NEW, matcher.VERDICT_UPGRADE)

_INK = QColor('#4a4a4a')
_PAPER = QColor('#fdfdfd')
_COVER = QColor('#7aa8dc')
_COVER_EDGE = QColor('#37567a')
_GLASS = QColor('#eaf3ff')
_BADGE = QColor('#e0483c')


def make_checker_icon(size=64):
    """書本加放大鏡：沿用面板工具列的實心填色＋深色描邊風格，不是線稿。"""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 64.0

    # 書本
    p.setPen(QPen(_COVER_EDGE, 2.4 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(_COVER)
    p.drawRoundedRect(int(8 * s), int(10 * s), int(34 * s), int(44 * s), 3 * s, 3 * s)
    p.setBrush(_PAPER)
    p.drawRoundedRect(int(14 * s), int(16 * s), int(24 * s), int(32 * s), 2 * s, 2 * s)
    p.setPen(QPen(_INK, 1.6 * s, Qt.SolidLine, Qt.RoundCap))
    for i in range(3):
        y = int((22 + i * 7) * s)
        p.drawLine(int(18 * s), y, int(34 * s), y)

    # 放大鏡
    p.setPen(QPen(_INK, 3.2 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(_GLASS)
    p.drawEllipse(int(30 * s), int(28 * s), int(24 * s), int(24 * s))
    p.drawLine(int(50 * s), int(48 * s), int(59 * s), int(58 * s))
    p.end()
    return QIcon(pix)


class ScanWorker(QThread):
    """在背景執行緒跑一輪掃描。"""

    progress = pyqtSignal(int, int, str)   # 已完成、總數、目前實體名稱
    done = pyqtSignal(dict)                # summarize() 的結果
    failed = pyqtSignal(str)

    def __init__(self, entity_type='', keyword='', limit=0, parent=None):
        super().__init__(parent)
        self._entity_type = entity_type
        self._keyword = keyword
        self._limit = limit
        self._fetch = None

    def cancel(self):
        if self._fetch is not None:
            self._fetch.cancelled = True

    def run(self):
        from .. import authors_db
        from ..everything_sdk import EverythingSDK

        try:
            # EverythingSDK 在建構時會建立一個訊息視窗，而視窗的訊息佇列屬於
            # 建立它的執行緒。必須在這裡（工作執行緒內）建立，若沿用主執行緒的
            # 實例，query() 會安靜地逾時回傳空清單——比對會把整櫃藏書誤判成沒有。
            everything = EverythingSDK()
            if not everything.is_available():
                self.failed.emit('Everything 沒有在執行，無法取得本機檔案清單。')
                return

            self._fetch = fetcher.Fetcher(fetcher.load_cookie_header())
            lookup = scanner.everything_lookup(everything)

            with closing(store.connect()) as conn:
                entities = authors_db.list_entities(
                    conn, type_=self._entity_type or None,
                    keyword=self._keyword or None, limit=self._limit or None)
                results = scanner.scan_all(
                    conn, entities, self._fetch, lookup,
                    progress=lambda i, total, e: self.progress.emit(
                        i, total, e.get('name') or ''))
                self.done.emit(scanner.summarize(results))
        except fetcher.CookieExpired as exc:
            self.failed.emit(str(exc))
        except fetcher.CheckerError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:            # 背景執行緒的例外沒人接就會靜默終止
            self.failed.emit(f'掃描發生未預期的錯誤：{exc}')


class CheckerPanel(QWidget):
    """更新檢查器的摘要面板。"""

    detail_requested = pyqtSignal(str)     # gid，交給 Web UI 開詳情
    status_message = pyqtSignal(str)       # 主視窗狀態列

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._toolbar_icon_size = QSize(64, 64)
        # Web UI 由面板持有：兩者同生共死，主視窗不必知道伺服器的存在。
        self._webui = webui.WebUI()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toolbar = self._build_toolbar()
        layout.addWidget(self.toolbar)
        layout.addWidget(self._make_hline())

        self.counts_label = QLabel()
        self.counts_label.setContentsMargins(8, 6, 8, 6)
        font = self.counts_label.font()
        font.setPointSizeF(font.pointSizeF() + 1.0)
        self.counts_label.setFont(font)
        layout.addWidget(self.counts_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['作者／標題', '判定', '發布'])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setColumnWidth(0, 380)
        layout.addWidget(self.tree, 1)

        self.refresh()

    # ── 建構 ────────────────────────────────────────────────────────────

    def _make_hline(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def _button(self, icon, tooltip, handler):
        btn = QToolButton(self)
        btn.setIcon(icon)
        btn.setIconSize(self._toolbar_icon_size)
        btn.setToolTip(tooltip)
        btn.setAutoRaise(True)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.clicked.connect(handler)
        return btn

    def _build_toolbar(self):
        bar = QToolBar(self)
        bar.setFloatable(False)
        bar.setMovable(False)
        bar.setFocusPolicy(Qt.NoFocus)
        bar.setIconSize(self._toolbar_icon_size)
        bar.setStyleSheet('QToolBar { spacing: 6px; }')

        style = self.style()
        self.scan_button = self._button(
            make_checker_icon(), '檢查更新（背景執行，可隨時停止）', self.start_scan)
        self.stop_button = self._button(
            style.standardIcon(QStyle.SP_MediaStop), '停止掃描', self.stop_scan)
        self.stop_button.setEnabled(False)
        self.detail_button = self._button(
            style.standardIcon(QStyle.SP_FileDialogDetailedView),
            '開啟詳細清單（Web UI）', self._open_detail)

        bar.addWidget(self.scan_button)
        bar.addWidget(self.stop_button)
        bar.addSeparator()
        bar.addWidget(self.detail_button)
        return bar

    def set_toolbar_icon_size(self, size):
        self._toolbar_icon_size = size
        self.toolbar.setIconSize(size)
        for btn in (self.scan_button, self.stop_button, self.detail_button):
            btn.setIconSize(size)

    # ── 掃描 ────────────────────────────────────────────────────────────

    def start_scan(self, *, entity_type='', keyword='', limit=0):
        if self._worker is not None and self._worker.isRunning():
            self.status_message.emit('掃描已在進行中。')
            return
        self._worker = ScanWorker(entity_type, keyword, limit, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_thread_finished)
        self.scan_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_message.emit('開始檢查更新…')
        self._worker.start()

    def stop_scan(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.status_message.emit('正在停止…已掃描的部分都會保留。')

    def shutdown(self):
        """主視窗關閉時呼叫：停掉背景掃描與 Web UI 伺服器並等它們收尾。"""
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        self._webui.stop()

    def open_detail(self, gid=''):
        """啟動 Web UI（必要時）並以系統預設瀏覽器開啟。

        cookie 只是拿來抓縮圖用的，讀不到就讓縮圖從缺——頁面其他部分照常可用，
        不該因為抓不到圖就整個開不起來。
        """
        import webbrowser

        try:
            if not self._webui.running:
                try:
                    cookie = fetcher.load_cookie_header()
                except fetcher.CheckerError:
                    cookie = None
                    self.status_message.emit('找不到登入憑證，Web UI 的縮圖將無法顯示。')
                self._webui.start(cookie)
            url = self._webui.url(gid)
            webbrowser.open(url)
            self.status_message.emit(f'已開啟詳細清單：{url.split("?")[0]}')
        except Exception as exc:
            self.status_message.emit(f'無法開啟 Web UI：{exc}')

    def _on_progress(self, index, total, name):
        self.status_message.emit(f'檢查更新 {index + 1}/{total}：{name}')

    def _on_done(self, summary):
        counts = summary.get('counts') or {}
        self.status_message.emit(
            f"檢查完成：新書 {counts.get(matcher.VERDICT_NEW, 0)}、"
            f"版本升級 {counts.get(matcher.VERDICT_UPGRADE, 0)}")
        if summary.get('truncated'):
            self.status_message.emit(
                f"注意：{len(summary['truncated'])} 位作者發布量超過取回上限，可能有遺漏。")
        self.refresh()

    def _on_failed(self, message):
        self.status_message.emit(f'檢查失敗：{message}')

    def _on_thread_finished(self):
        self.scan_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.refresh()

    # ── 顯示 ────────────────────────────────────────────────────────────

    def refresh(self):
        """從資料庫重讀計數與清單。掃描中也可安全呼叫。"""
        try:
            with closing(store.connect()) as conn:
                counts = store.counts(conn)
                findings = store.load_findings(conn, verdicts=list(PANEL_VERDICTS))
        except Exception as exc:
            self.counts_label.setText(f'讀取結果失敗：{exc}')
            return

        self.counts_label.setText(
            f"🆕 新書 {counts[matcher.VERDICT_NEW]}　"
            f"⬆️ 版本升級 {counts[matcher.VERDICT_UPGRADE]}　"
            f"❓ 疑似 {counts[matcher.VERDICT_MAYBE]}　"
            f"✅ 已有 {counts[matcher.VERDICT_HAVE]}")

        self.tree.clear()
        by_entity = {}
        for item in findings:
            by_entity.setdefault(item['entity_name'] or '(未知)', []).append(item)

        bold = QFont()
        bold.setBold(True)
        for name in sorted(by_entity, key=lambda n: -len(by_entity[n])):
            items = by_entity[name]
            parent = QTreeWidgetItem([f'{name}（{len(items)}）', '', ''])
            parent.setFont(0, bold)
            for item in items:
                child = QTreeWidgetItem([
                    item['title_jpn'] or item['title'],
                    VERDICT_LABEL.get(item['verdict'], item['verdict']),
                    _format_posted(item['posted']),
                ])
                child.setData(0, Qt.UserRole, item['gid'])
                child.setToolTip(0, item['url'])
                parent.addChild(child)
            self.tree.addTopLevelItem(parent)
            parent.setExpanded(True)

    def _on_double_click(self, item, _column):
        gid = item.data(0, Qt.UserRole)
        if gid:
            self.detail_requested.emit(str(gid))

    def _open_detail(self):
        self.detail_requested.emit('')


def _format_posted(posted):
    if not posted:
        return ''
    import datetime
    try:
        return datetime.datetime.fromtimestamp(int(posted)).strftime('%Y-%m-%d')
    except (ValueError, OSError):
        return ''
