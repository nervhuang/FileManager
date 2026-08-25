"""更新檢查器面板與背景掃描執行緒。

面板只放摘要：四區塊計數、新書清單與一小塊執行紀錄。要逐本判斷「這本我到底有
沒有」時得看縮圖與並排的本機檔名，那是 Web UI 的工作（雙擊清單項目開啟）。

掃描一輪全量約 25–35 分鐘，必須在背景執行緒跑，且隨時可停。所有可能拋出的
邊界都在此收斂成訊號，不讓例外冒進 Qt 事件圈把主程式一起帶走。

執行紀錄不是裝飾：跑那麼久，狀態列只留得住最後一行，看不出跑到哪、哪幾位失敗、
還要多久。進度條給完成度，紀錄區給逐項結果與失敗原因。
"""

import time
from contextlib import closing

from PyQt5.QtCore import QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolBar, QToolButton,
    QTreeWidget, QTreeWidgetItem, QFrame, QAbstractItemView,
    QProgressBar, QPlainTextEdit, QSplitter, QSizePolicy, QMessageBox,
)

from . import fetcher, matcher, scanner, store, webui
from .icons import (make_checker_icon, make_detail_icon, make_reset_icon,
                    make_stop_icon)

VERDICT_LABEL = {
    matcher.VERDICT_NEW: '🆕 新書',
    matcher.VERDICT_UPGRADE: '⬆️ 版本升級',
    matcher.VERDICT_MAYBE: '❓ 疑似已有',
    matcher.VERDICT_HAVE: '✅ 已有',
}
# 面板只顯示需要動作的兩類；已有與疑似留給 Web UI，否則清單會被淹沒。
PANEL_VERDICTS = (matcher.VERDICT_NEW, matcher.VERDICT_UPGRADE)

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

    def cancel(self):
        if self._fetch is not None:
            self._fetch.cancelled = True

    def run(self):
        from .. import authors_db
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
            lookup = scanner.everything_lookup(everything)

            with closing(store.connect()) as conn:
                entities = authors_db.list_entities(
                    conn, type_=self._entity_type or None,
                    keyword=self._keyword or None, limit=self._limit or None)
                results = scanner.scan_all(
                    conn, entities, self._fetch, lookup,
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


class CheckerPanel(QWidget):
    """更新檢查器的摘要面板。"""

    detail_requested = pyqtSignal(str)     # gid，交給 Web UI 開詳情
    status_message = pyqtSignal(str)       # 主視窗狀態列

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._toolbar_icon_size = QSize(64, 64)
        self._scan_started_at = 0.0
        self._scan_total = 0
        self._scan_finished = 0
        self._scan_new = 0
        self._scan_upgrade = 0
        self._scan_errors = 0
        self._scan_excluded = 0
        # 只在掃描期間跑，用來刷新已耗時與預估剩餘；停掉才不會空轉。
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
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
        layout.addWidget(self.counts_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['作者／標題', '判定', '發布'])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setColumnWidth(0, 380)

        # 清單與紀錄放進 splitter：紀錄區平時只佔一小條，要追細節時可以拉大。
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(self.tree)
        split.addWidget(self._build_log_box())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([460, 150])
        layout.addWidget(split, 1)
        self.splitter = split

        self.apply_font_size(self._base_font_size())
        self.refresh()

    # ── 建構 ────────────────────────────────────────────────────────────

    def _make_hline(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def _build_log_box(self):
        """進度條 ＋ 純文字紀錄。行數設上限，跑幾百位作者也不會吃掉記憶體。"""
        box = QWidget()
        vbox = QVBoxLayout(box)
        vbox.setContentsMargins(8, 4, 8, 6)
        vbox.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.log_title_label = QLabel('執行紀錄')
        self.log_title_label.setStyleSheet('color: #666;')
        self.elapsed_label = QLabel('')
        self.elapsed_label.setStyleSheet('color: #888;')
        self.clear_log_button = QToolButton(self)
        self.clear_log_button.setText('清除')
        self.clear_log_button.setAutoRaise(True)
        self.clear_log_button.setFocusPolicy(Qt.NoFocus)
        self.clear_log_button.setToolTip('清空紀錄')
        self.clear_log_button.clicked.connect(self.clear_log)
        head.addWidget(self.log_title_label)
        head.addStretch(1)
        head.addWidget(self.elapsed_label)
        head.addWidget(self.clear_log_button)
        vbox.addLayout(head)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('待命')
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(18)
        vbox.addWidget(self.progress_bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vbox.addWidget(self.log_view, 1)

        box.setMinimumHeight(110)
        return box

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

        self.scan_button = self._button(
            make_checker_icon(), '檢查更新（背景執行，可隨時停止）', self.start_scan)
        self.stop_button = self._button(
            make_stop_icon(), '停止掃描', self.stop_scan)
        self.stop_button.setEnabled(False)
        self.detail_button = self._button(
            make_detail_icon(), '開啟詳細清單（Web UI）', self._open_detail)
        self.reset_button = self._button(
            make_reset_icon(),
            '重設掃描紀錄（清空比對結果與進度，下次從頭掃描）', self.reset_scan_data)

        bar.addWidget(self.scan_button)
        bar.addWidget(self.stop_button)
        bar.addSeparator()
        bar.addWidget(self.detail_button)
        bar.addWidget(self.reset_button)
        return bar

    def _base_font_size(self):
        size = self.font().pointSize()
        return size if size > 0 else 10

    def apply_font_size(self, size):
        """跟隨主視窗的字型大小（Ctrl+= / Ctrl+-）。

        每個子元件都被明確設過字型（計數列要放大、紀錄區要等寬縮小），設過的
        字型不會再從父層繼承，所以這裡得逐一重設，不能只設面板自己。
        """
        family = self.font().family()
        base = QFont(family, size)
        self.setFont(base)
        self.tree.setFont(base)
        for widget in (self.log_title_label, self.elapsed_label,
                       self.clear_log_button, self.progress_bar):
            widget.setFont(base)

        # 計數列是這個面板的標題，比內文大一級。
        self.counts_label.setFont(QFont(family, size + 1))

        # 紀錄區用等寬字型：逐項紀錄靠欄位對齊才讀得快。比內文小一級但不低於 8pt，
        # 否則主視窗縮到 6pt 時紀錄會小到看不見。
        log_font = QFont('Consolas', max(8, size - 1))
        log_font.setStyleHint(QFont.Monospace)
        self.log_view.setFont(log_font)

        # 明確要求重算列高，不然要等下次重繪才會跟上。
        self.tree.doItemsLayout()

    # ── 版面狀態 ────────────────────────────────────────────────────────

    def layout_state(self):
        """回報面板內部版面，交給主視窗寫進 config.ini。

        面板內部有兩處使用者會動的尺寸：清單／紀錄的分隔位置，以及清單欄寬。
        主視窗只負責存取字串，不必知道這裡有幾個欄位或幾格 splitter。
        """
        return {
            'split': list(self.splitter.sizes()),
            'columns': [self.tree.columnWidth(i)
                        for i in range(self.tree.columnCount())],
        }

    def restore_layout(self, split=None, columns=None):
        """套回 `layout_state()` 存下來的版面。任一項壞掉就跳過該項用預設值。"""
        # 全 0 代表面板從沒顯示過就被存下來（隱藏的 widget 尺寸是 0），
        # 照套會讓清單與紀錄都變成 0 高。
        if split and len(split) == self.splitter.count() and any(x > 0 for x in split):
            self.splitter.setSizes([int(x) for x in split])
        if columns:
            for i, width in enumerate(columns[:self.tree.columnCount()]):
                if int(width) > 0:
                    self.tree.setColumnWidth(i, int(width))

    def set_toolbar_icon_size(self, size):
        self._toolbar_icon_size = size
        self.toolbar.setIconSize(size)
        for btn in (self.scan_button, self.stop_button, self.detail_button,
                    self.reset_button):
            btn.setIconSize(size)

    # ── 掃描 ────────────────────────────────────────────────────────────

    def start_scan(self, *, entity_type='', keyword='', limit=0):
        if self._worker is not None and self._worker.isRunning():
            self.status_message.emit('掃描已在進行中。')
            return
        self._worker = ScanWorker(entity_type, keyword, limit, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.entity_done.connect(self._on_entity_done)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_thread_finished)
        self.scan_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        self._scan_started_at = time.monotonic()
        self._scan_total = 0
        self._scan_finished = 0
        self._scan_new = self._scan_upgrade = self._scan_errors = 0
        self._scan_excluded = 0
        # 總數要等工作執行緒讀完資料庫才知道，先進不確定狀態的忙碌條。
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat('準備中…')
        self.elapsed_label.setText('')
        self._elapsed_timer.start()
        self.log('▶ 開始檢查更新'
                 + (f'（篩選：{keyword}）' if keyword else '')
                 + (f'（上限 {limit} 位）' if limit else ''))
        self.status_message.emit('開始檢查更新…')
        self._worker.start()

    def stop_scan(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.log('■ 收到停止要求，等目前這位掃完就收尾（已掃的都已保留）。')
            self.progress_bar.setFormat('停止中…')
            self.status_message.emit('正在停止…已掃描的部分都會保留。')

    def reset_scan_data(self):
        """清空比對結果與掃描進度，下一輪從頭重建。

        判定規則改動（語系白名單、門檻）之後才需要。舊列的 `markers` 是用舊規則
        判出來的，站上的 tag 早就不在手上，重評救不回來——只能重抓。
        """
        if self._worker is not None and self._worker.isRunning():
            self.status_message.emit('掃描進行中，請先停止再重設。')
            return

        try:
            with closing(store.connect()) as conn:
                findings = conn.execute(
                    'SELECT COUNT(*) FROM checker_findings').fetchone()[0]
        except Exception:
            findings = 0

        answer = QMessageBox.question(
            self, '重設掃描紀錄',
            f'將清空 {findings} 筆比對結果與全部掃描進度，'
            '下次掃描時每位作者都會從頭重建基準（約 25–35 分鐘）。\n\n'
            '你按過的「忽略」與「已下載」不會被清掉。\n\n'
            '確定要重設嗎？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return

        try:
            with closing(store.connect()) as conn:
                removed, states = store.reset_scan_data(conn)
        except Exception as exc:
            self.log(f'✖ 重設失敗：{exc}')
            self.status_message.emit(f'重設失敗：{exc}')
            return

        self.log(f'⟲ 已重設：清掉 {removed} 筆比對結果、{states} 筆掃描紀錄。'
                 '按開始掃描重建基準。')
        self.status_message.emit(f'已重設掃描紀錄（{removed} 筆結果）。')
        self.refresh()

    def shutdown(self):
        """主視窗關閉時呼叫：停掉背景掃描與 Web UI 伺服器並等它們收尾。"""
        self._elapsed_timer.stop()
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
        self._scan_total = total
        if self.progress_bar.maximum() != total:
            self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(index)
        self.progress_bar.setFormat(f'%v/%m（%p%）　{name}')
        self.status_message.emit(f'檢查更新 {index + 1}/{total}：{name}')

    def _on_entity_done(self, index, total, result):
        """一位作者掃完就記一行——這是紀錄區存在的理由：看得到逐項結果。"""
        self._scan_finished = index + 1
        self._scan_total = total
        self.progress_bar.setValue(self._scan_finished)

        name = result.get('name') or '(未知)'
        prefix = f'[{self._scan_finished:>4}/{total}] {name}'
        if result.get('error'):
            self._scan_errors += 1
            self.log(f'{prefix} ⚠ 失敗：{result["error"]}')
        elif result.get('skipped') == 'no_english_name':
            self.log(f'{prefix} ── 略過：沒有填英文名稱')
        elif result.get('skipped'):
            self.log(f'{prefix} ── 略過：{result["skipped"]}')
        else:
            works = result.get('works') or ()
            new_count = sum(1 for w in works if w['verdict'] == matcher.VERDICT_NEW)
            up_count = sum(1 for w in works if w['verdict'] == matcher.VERDICT_UPGRADE)
            excluded = int(result.get('excluded') or 0)
            self._scan_new += new_count
            self._scan_upgrade += up_count
            self._scan_excluded += excluded
            # 排除數要逐位顯示，不能只給總數：語系過濾一旦壞掉（站方改了 tag 格式），
            # 症狀是每位作者都「無更新」，看不出原因。有「排除 25、新書 0」這種行
            # 才分得出是過濾器出事，還是真的沒新書。
            tail = f'（排除 {excluded}）' if excluded else ''
            if new_count or up_count:
                bits = []
                if new_count:
                    bits.append(f'🆕 {new_count}')
                if up_count:
                    bits.append(f'⬆️ {up_count}')
                self.log(f'{prefix} ★ ' + '、'.join(bits) + tail)
            else:
                self.log(f'{prefix} ── 無更新{tail}')
            if result.get('truncated'):
                # 名稱是中日文（等寬字型下佔兩格），對不齊 prefix，改用固定縮排。
                self.log('        ↳ ⚠ 發布量超過取回上限，這位可能有遺漏')
        self._update_elapsed()

    def _on_done(self, summary):
        counts = summary.get('counts') or {}
        new_count = counts.get(matcher.VERDICT_NEW, 0)
        up_count = counts.get(matcher.VERDICT_UPGRADE, 0)
        self.log(f'✔ 檢查完成：掃描 {summary.get("scanned", 0)}/'
                 f'{summary.get("entities", 0)} 位，'
                 f'新書 {new_count}、版本升級 {up_count}'
                 + (f'、排除 {self._scan_excluded}' if self._scan_excluded else '')
                 + f'（耗時 {_format_duration(time.monotonic() - self._scan_started_at)}）')
        if summary.get('skipped'):
            self.log(f'　 略過 {len(summary["skipped"])} 位（沒有英文名稱）')
        if summary.get('errors'):
            self.log(f'　 失敗 {len(summary["errors"])} 位：'
                     + '、'.join(name for name, _ in summary['errors'][:5])
                     + ('…' if len(summary['errors']) > 5 else ''))
        self.status_message.emit(
            f'檢查完成：新書 {new_count}、版本升級 {up_count}')
        if summary.get('truncated'):
            self.log(f'　 ⚠ {len(summary["truncated"])} 位發布量超過取回上限，可能有遺漏：'
                     + '、'.join(summary['truncated'][:5])
                     + ('…' if len(summary['truncated']) > 5 else ''))
            self.status_message.emit(
                f"注意：{len(summary['truncated'])} 位作者發布量超過取回上限，可能有遺漏。")
        self.refresh()

    def _on_failed(self, message):
        self.log(f'✖ 檢查失敗：{message}')
        self.status_message.emit(f'檢查失敗：{message}')

    def _on_thread_finished(self):
        self.scan_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._elapsed_timer.stop()
        # 中途停止時進度條會停在半途，維持原值不歸零：那是真的做到哪。
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
        self.progress_bar.setFormat(
            f'已結束　%v/%m　🆕 {self._scan_new}　⬆️ {self._scan_upgrade}'
            + (f'　🚫 {self._scan_excluded}' if self._scan_excluded else '')
            + (f'　⚠ {self._scan_errors}' if self._scan_errors else ''))
        self._update_elapsed()
        self.refresh()

    # ── 紀錄 ────────────────────────────────────────────────────────────

    def log(self, message):
        """往紀錄區加一行並捲到底。時間戳用本機時鐘，對得上其他工具的 log。"""
        stamp = time.strftime('%H:%M:%S')
        self.log_view.appendPlainText(f'{stamp}  {message}')
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear_log(self):
        self.log_view.clear()

    def _update_elapsed(self):
        """已耗時與預估剩餘。用已完成筆數的平均速度外推，夠用就好。"""
        if not self._scan_started_at:
            return
        elapsed = time.monotonic() - self._scan_started_at
        text = f'已耗時 {_format_duration(elapsed)}'
        if self._scan_finished and self._scan_total > self._scan_finished:
            remain = (elapsed / self._scan_finished) * (
                self._scan_total - self._scan_finished)
            text += f'　剩餘約 {_format_duration(remain)}'
        self.elapsed_label.setText(text)

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


def _format_duration(seconds):
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f'{seconds} 秒'
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f'{minutes} 分 {seconds:02d} 秒'
    hours, minutes = divmod(minutes, 60)
    return f'{hours} 小時 {minutes:02d} 分'


def _format_posted(posted):
    if not posted:
        return ''
    import datetime
    try:
        return datetime.datetime.fromtimestamp(int(posted)).strftime('%Y-%m-%d')
    except (ValueError, OSError):
        return ''
