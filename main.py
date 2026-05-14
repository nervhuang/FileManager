import sys
import subprocess
import os
import ctypes
import ctypes.wintypes as wt
import struct
import time
import configparser
import json
import traceback
from PyQt5.QtWidgets import QApplication, QMainWindow, QTreeView, QFileSystemModel, QListView, QWidget, QHBoxLayout, QVBoxLayout, QToolBar, QAction, QMessageBox, QStyle, QToolButton, QSplitter, QLineEdit, QSizePolicy, QFileIconProvider, QTabBar, QAbstractItemView, QMenu, QStylePainter, QStyleOptionTab, QComboBox
from PyQt5.QtCore import QDir, Qt, QSize, QSortFilterProxyModel, QFileInfo, pyqtSignal, QEvent, QTimer, QItemSelection, QItemSelectionModel, QMimeData, QUrl, QModelIndex
from PyQt5.QtGui import QKeySequence, QIcon, QFont, QPixmap, QPainter, QColor, QPalette, QStandardItemModel, QStandardItem, QDrag
from datetime import datetime
# Optional SVG renderer (may not be present in minimal PyQt installs)
try:
    from PyQt5.QtSvg import QSvgRenderer
    HAVE_SVG_RENDERER = True
except Exception:
    QSvgRenderer = None
    HAVE_SVG_RENDERER = False

ref_s = 0
ref_e = 1
global_keywords = []


class EverythingSDK:
    """Everything IPC client supporting both 1.5a (pure IPC2) and 1.4 (DLL)."""

    WM_COPYDATA = 0x004A
    EVERYTHING_IPC_COPYDATA_QUERY2W = 18
    EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME = 0x00000004

    # Window class names for different Everything versions
    _IPC_WNDCLASS_15A = "EVERYTHING_TASKBAR_NOTIFICATION_(1.5a)"
    _IPC_WNDCLASS_14 = "EVERYTHING_TASKBAR_NOTIFICATION"

    def __init__(self):
        self._setup_winapi()
        self._ipc_results = []
        self._ipc_got_reply = False
        self._wndproc_ref = self._WNDPROCTYPE(self._wnd_proc)

    def _setup_winapi(self):
        """Configure ctypes signatures for Windows API calls."""
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32

        self._kernel32.GetModuleHandleW.restype = wt.HMODULE
        self._kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        self._user32.FindWindowW.restype = wt.HWND
        self._user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
        self._user32.DefWindowProcW.restype = ctypes.c_longlong
        self._user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong]
        self._user32.SendMessageW.restype = ctypes.c_longlong
        self._user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong]
        self._user32.PeekMessageW.restype = wt.BOOL
        self._user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
        self._user32.CreateWindowExW.argtypes = [
            wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p
        ]
        self._user32.CreateWindowExW.restype = wt.HWND
        self._user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]

    class _COPYDATASTRUCT(ctypes.Structure):
        _fields_ = [
            ("dwData", ctypes.c_ulonglong),
            ("cbData", wt.DWORD),
            ("lpData", ctypes.c_void_p),
        ]

    _WNDPROCTYPE = ctypes.CFUNCTYPE(ctypes.c_longlong, wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong)

    class _WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wt.UINT), ("style", wt.UINT),
            ("lpfnWndProc", ctypes.CFUNCTYPE(ctypes.c_longlong, wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong)),
            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
            ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
            ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
            ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON),
        ]

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """Window procedure to receive IPC2 reply from Everything."""
        if msg == self.WM_COPYDATA:
            pCds = ctypes.cast(lparam, ctypes.POINTER(self._COPYDATASTRUCT))
            cds = pCds.contents
            if cds.cbData > 0 and cds.lpData:
                raw = (ctypes.c_ubyte * cds.cbData).from_address(cds.lpData)
                data = bytes(raw)
                self._parse_ipc2_response(data)
            self._ipc_got_reply = True
            return 1
        return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _parse_ipc2_response(self, data):
        """Parse EVERYTHING_IPC_LIST2 response data."""
        if len(data) < 20:
            return
        totitems, numitems, offset, req_flags, sort_type = struct.unpack_from('<IIIII', data, 0)
        items_start = 20
        for i in range(numitems):
            item_off = items_start + i * 8
            if item_off + 8 > len(data):
                break
            flags, data_offset = struct.unpack_from('<II', data, item_off)
            if data_offset + 4 > len(data):
                continue
            str_len_chars = struct.unpack_from('<I', data, data_offset)[0]
            str_start = data_offset + 4
            str_bytes = str_len_chars * 2
            if str_start + str_bytes <= len(data):
                full_path = data[str_start:str_start + str_bytes].decode('utf-16-le', errors='replace')
                self._ipc_results.append(full_path)

    def _find_everything_hwnd(self):
        """Find Everything IPC window (1.5a or 1.4)."""
        hwnd = self._user32.FindWindowW(self._IPC_WNDCLASS_15A, None)
        if hwnd:
            return hwnd
        hwnd = self._user32.FindWindowW(self._IPC_WNDCLASS_14, None)
        return hwnd

    def is_available(self):
        return bool(self._find_everything_hwnd())

    def query(self, search_text, max_results=200):
        """Query Everything via IPC2 (WM_COPYDATA)."""
        self._ipc_results = []
        self._ipc_got_reply = False

        everything_hwnd = self._find_everything_hwnd()
        if not everything_hwnd:
            return []

        hInst = self._kernel32.GetModuleHandleW(None)
        cls_name = f"EvIPC{time.time_ns()}"

        wc = self._WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(self._WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hInst
        wc.lpszClassName = cls_name
        self._user32.RegisterClassExW(ctypes.byref(wc))

        reply_hwnd = self._user32.CreateWindowExW(
            0, cls_name, "R", 0, 0, 0, 0, 0, None, None, hInst, None
        )
        if not reply_hwnd:
            try:
                self._user32.UnregisterClassW(cls_name, hInst)
            except Exception:
                pass
            return []

        # Build EVERYTHING_IPC_QUERY2: reply_hwnd, reply_msg, search_flags, offset, max, req_flags, sort
        search_bytes = search_text.encode('utf-16-le') + b'\x00\x00'
        reply_hwnd_32 = reply_hwnd & 0xFFFFFFFF
        header = struct.pack('<IIIIIII', reply_hwnd_32, 0, 0, 0, max_results,
                             self.EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME, 1)
        query_data = header + search_bytes
        data_buf = ctypes.create_string_buffer(query_data)

        cds = self._COPYDATASTRUCT()
        cds.dwData = self.EVERYTHING_IPC_COPYDATA_QUERY2W
        cds.cbData = len(query_data)
        cds.lpData = ctypes.cast(data_buf, ctypes.c_void_p)

        result = self._user32.SendMessageW(
            everything_hwnd, self.WM_COPYDATA, reply_hwnd, ctypes.addressof(cds)
        )

        if result:
            msg = wt.MSG()
            end_time = time.time() + 5
            while time.time() < end_time and not self._ipc_got_reply:
                ret = self._user32.PeekMessageW(ctypes.byref(msg), reply_hwnd, 0, 0, 1)
                if ret:
                    self._user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.01)

        self._user32.DestroyWindow(reply_hwnd)
        try:
            self._user32.UnregisterClassW(cls_name, hInst)
        except Exception:
            pass

        return list(self._ipc_results)


class CustomTreeView(QTreeView):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.expanded_indexes = set()
        self.expanding_in_progress = False

    def mouseDoubleClickEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid() and index not in self.expanded_indexes:
            self.setExpanded(index, not self.isExpanded(index))
            self.expanded_indexes.add(index)

    def setExpanded(self, index, expanded):
        if not self.expanding_in_progress:
            self.expanding_in_progress = True
            super().setExpanded(index, expanded)
            self.expanding_in_progress = False


class SearchSortProxyModel(QSortFilterProxyModel):
    """Proxy model for proper numeric sorting on date and size columns."""
    def lessThan(self, left, right):
        col = left.column()
        if col in (2, 3):  # Date or Size columns
            left_val = left.data(Qt.UserRole)
            right_val = right.data(Qt.UserRole)
            if left_val is not None and right_val is not None:
                return left_val < right_val
        return super().lessThan(left, right)

    def mimeTypes(self):
        source = self.sourceModel()
        if source is not None and hasattr(source, "mimeTypes"):
            return source.mimeTypes()
        return super().mimeTypes()

    def mimeData(self, indexes):
        source = self.sourceModel()
        if source is None:
            return super().mimeData(indexes)

        source_indexes = []
        seen = set()
        for proxy_idx in indexes:
            if not proxy_idx.isValid():
                continue
            src_idx = self.mapToSource(proxy_idx)
            key = (src_idx.row(), src_idx.column(), src_idx.parent().internalId())
            if key in seen:
                continue
            seen.add(key)
            source_indexes.append(src_idx)
        return source.mimeData(source_indexes)

    def supportedDragActions(self):
        source = self.sourceModel()
        if source is not None and hasattr(source, "supportedDragActions"):
            return source.supportedDragActions()
        return super().supportedDragActions()


class SearchResultsModel(QStandardItemModel):
    """Search results model that supports dragging files to external apps."""

    FILEPATH_ROLE = Qt.UserRole + 1

    def flags(self, index):
        base = super().flags(index)
        if index.isValid():
            return base | Qt.ItemIsDragEnabled
        return base

    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, indexes):
        mime = QMimeData()
        if not indexes:
            return mime

        urls = []
        seen = set()
        for index in indexes:
            src = index if index.column() == 0 else index.sibling(index.row(), 0)
            filepath = src.data(self.FILEPATH_ROLE)
            if not filepath or filepath in seen:
                continue
            if os.path.exists(filepath):
                urls.append(QUrl.fromLocalFile(filepath))
                seen.add(filepath)

        if urls:
            mime.setUrls(urls)
        return mime

    def supportedDragActions(self):
        return Qt.CopyAction | Qt.MoveAction | Qt.LinkAction


class SearchListView(QTreeView):
    """QTreeView 子類別，支援鍵盤創點定錨點的 Shift 區間選取和 Ctrl 切換選取。
    Shift+點擊從第一次按下的項目開始延伸，不會因後續 Shift+點擊而變更錨點。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anchor = None  # 錨點 index（第一次普通點擊時設定）
        self._press_pos = None
        self._press_button = Qt.NoButton
        self._suppress_next_context_menu = False
        self._last_drag_button = Qt.NoButton

    def mousePressEvent(self, event):
        self._press_pos = event.pos()
        self._press_button = event.button()

        if event.button() == Qt.RightButton:
            index = self.indexAt(event.pos())
            if index.isValid():
                sel = self.selectionModel()
                if sel and sel.isSelected(index):
                    # 右鍵點在已選取的項目上：保留選取，只觸發 context menu
                    return
            # 右鍵點在未選取項目上：先讓 Qt 選取它，再觸發 context menu
            super().mousePressEvent(event)
            return

        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        index = self.indexAt(event.pos())
        modifiers = event.modifiers()
        sel = self.selectionModel()

        if not index.isValid() or sel is None:
            self._anchor = None
            super().mousePressEvent(event)
            return

        if modifiers & Qt.ShiftModifier:
            # Shift+點擊：從錨點延伸至目前項目，不改變錨點
            anchor = self._anchor if (self._anchor is not None and self._anchor.isValid()) else index
            a_row = anchor.row()
            c_row = index.row()
            model = self.model()
            top = min(a_row, c_row)
            bottom = max(a_row, c_row)
            cols = model.columnCount() if model else 1
            parent_idx = anchor.parent()
            selection = QItemSelection()
            selection.select(
                model.index(top, 0, parent_idx),
                model.index(bottom, cols - 1, parent_idx)
            )
            sel.select(selection, QItemSelectionModel.ClearAndSelect)
            sel.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        elif modifiers & Qt.ControlModifier:
            # Ctrl+點擊：切換目前項目，錨點更新至目前項目
            self._anchor = index
            sel.select(
                QItemSelection(index.sibling(index.row(), 0),
                               index.sibling(index.row(), (self.model().columnCount() - 1) if self.model() else 0)),
                QItemSelectionModel.Toggle
            )
            sel.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        else:
            # 普通點擊：改變錨點並只選該項目
            self._anchor = index
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 右鍵拖曳：Qt 不自動處理，需手動偵測並啟動
        if (self._press_pos is not None
                and self._press_button == Qt.RightButton
                and (event.pos() - self._press_pos).manhattanLength() >= QApplication.startDragDistance()):
            mime = self._build_drag_mime_data()
            if mime is not None and mime.hasUrls():
                drag = QDrag(self)
                drag.setMimeData(mime)
                preview = self._build_drag_preview_pixmap()
                if preview is not None:
                    drag.setPixmap(preview)
                    drag.setHotSpot(preview.rect().center())
                self._last_drag_button = Qt.RightButton
                wnd = self.window()
                if wnd is not None and hasattr(wnd, "_search_drag_button"):
                    wnd._search_drag_button = Qt.RightButton
                result_action = drag.exec_(Qt.CopyAction | Qt.MoveAction | Qt.LinkAction, Qt.IgnoreAction)
                if wnd is not None and hasattr(wnd, "_search_drag_button"):
                    wnd._search_drag_button = Qt.NoButton
                self._suppress_next_context_menu = True
                if result_action != Qt.IgnoreAction:
                    self._notify_search_refresh_delayed()
                self._press_pos = None
                self._press_button = Qt.NoButton
                return
        # 左鍵拖曳：由 Qt 內部偵測閾值後呼叫 startDrag()
        super().mouseMoveEvent(event)

    def startDrag(self, supportedActions):
        """覆寫 Qt 的左鍵拖曳進入點，提供自訂預覽圖與 MIME 資料。"""
        mime = self._build_drag_mime_data()
        if mime is None or not mime.hasUrls():
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        preview = self._build_drag_preview_pixmap()
        if preview is not None:
            drag.setPixmap(preview)
            drag.setHotSpot(preview.rect().center())
        self._last_drag_button = self._press_button
        wnd = self.window()
        if wnd is not None and hasattr(wnd, "_search_drag_button"):
            wnd._search_drag_button = self._press_button
        result_action = drag.exec_(supportedActions, Qt.IgnoreAction)
        if wnd is not None and hasattr(wnd, "_search_drag_button"):
            wnd._search_drag_button = Qt.NoButton
        if result_action != Qt.IgnoreAction:
            self._notify_search_refresh_delayed()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self._resolve_drop_target_dir(event.pos()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() and self._resolve_drop_target_dir(event.pos()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._last_drag_button = Qt.NoButton
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        try:
            target_dir = self._resolve_drop_target_dir(event.pos())
            if not target_dir:
                event.ignore()
                return

            src_paths = self._extract_source_paths_from_mime(event.mimeData())
            if not src_paths:
                event.ignore()
                return

            op = self._decide_drop_operation(src_paths, target_dir, event)
            if op is None:
                event.ignore()
                return

            self._apply_drop_operation(src_paths, target_dir, op)
            event.acceptProposedAction()
            self._notify_search_refresh_delayed()
        except Exception as ex:
            event.ignore()
            QMessageBox.warning(self, "拖曳失敗", f"拖曳處理發生錯誤: {ex}")
        finally:
            self._last_drag_button = Qt.NoButton

    def _build_drag_mime_data(self):
        sel = self.selectionModel()
        model = self.model()
        if sel is None or model is None:
            return None

        indexes = sel.selectedRows(0)
        if not indexes:
            return None

        urls = []
        seen = set()
        for idx in indexes:
            filepath = idx.data(Qt.UserRole + 1)
            if not filepath:
                # Fallback: build path from visible columns (name + directory)
                name = idx.data(Qt.DisplayRole)
                dir_idx = idx.sibling(idx.row(), 1)
                dirname = dir_idx.data(Qt.DisplayRole)
                if name and dirname:
                    filepath = os.path.join(dirname, name)
            if not filepath or filepath in seen:
                continue
            if os.path.exists(filepath):
                urls.append(QUrl.fromLocalFile(filepath))
                seen.add(filepath)

        if not urls:
            return None

        mime = QMimeData()
        mime.setUrls(urls)
        return mime

    def _build_drag_preview_pixmap(self):
        sel = self.selectionModel()
        if sel is None:
            return None

        rows = sel.selectedRows(0)
        if not rows:
            return None

        first = rows[0]
        name = first.data(Qt.DisplayRole) or ""
        icon = first.data(Qt.DecorationRole)
        count = len(rows)

        secondary = f"{count} 個項目" if count > 1 else ""
        w = 260
        h = 52 if secondary else 40
        pix = QPixmap(w, h)
        pix.fill(Qt.transparent)

        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(32, 32, 32, 215))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, w - 1, h - 1, 8, 8)

        x = 10
        if isinstance(icon, QIcon):
            pm = icon.pixmap(20, 20)
            if not pm.isNull():
                p.drawPixmap(x, (h - 20) // 2, pm)
                x += 26

        p.setPen(QColor("white"))
        fm = p.fontMetrics()
        text_w = w - x - 10
        title = fm.elidedText(name, Qt.ElideRight, text_w)
        if secondary:
            p.drawText(x, 20, title)
            p.setPen(QColor(210, 210, 210))
            p.drawText(x, 38, secondary)
        else:
            p.drawText(x, 26, title)
        p.end()
        return pix

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._press_pos = None
        self._press_button = Qt.NoButton

    def contextMenuEvent(self, event):
        if self._suppress_next_context_menu:
            self._suppress_next_context_menu = False
            event.accept()
            return
        super().contextMenuEvent(event)

    def _resolve_drop_target_dir(self, pos):
        idx = self.indexAt(pos)
        if not idx.isValid():
            return ""

        row0 = idx.sibling(idx.row(), 0)
        path = row0.data(Qt.UserRole + 1)
        if not path:
            name = row0.data(Qt.DisplayRole)
            dir_idx = idx.sibling(idx.row(), 1)
            dirname = dir_idx.data(Qt.DisplayRole)
            if name and dirname:
                path = os.path.join(dirname, name)
        if path and os.path.isdir(path):
            return path
        return ""

    def _extract_source_paths_from_mime(self, mime):
        paths = []
        seen = set()
        for url in mime.urls() if mime is not None else []:
            local = url.toLocalFile()
            if not local or local in seen:
                continue
            seen.add(local)
            paths.append(local)
        return paths

    def _decide_drop_operation(self, src_paths, target_dir, event):
        if self._last_drag_button == Qt.RightButton:
            menu = QMenu(self)
            act_copy = menu.addAction("複製到此處")
            act_move = menu.addAction("移動到此處")
            menu.addSeparator()
            act_cancel = menu.addAction("取消")
            global_pos = self.viewport().mapToGlobal(event.pos())
            chosen = menu.exec_(global_pos)
            if chosen == act_copy:
                return "copy"
            if chosen == act_move:
                return "move"
            if chosen == act_cancel or chosen is None:
                return None

        mods = event.keyboardModifiers()
        if mods & Qt.ControlModifier:
            return "copy"
        if mods & Qt.ShiftModifier:
            return "move"

        # 預設行為：同磁碟機移動，不同磁碟機複製
        first = src_paths[0] if src_paths else ""
        src_drive = os.path.splitdrive(os.path.abspath(first))[0].lower() if first else ""
        dst_drive = os.path.splitdrive(os.path.abspath(target_dir))[0].lower() if target_dir else ""
        return "move" if src_drive and src_drive == dst_drive else "copy"

    def _apply_drop_operation(self, src_paths, target_dir, op):
        wnd = self.window()
        if wnd is not None and hasattr(wnd, "perform_shell_file_operation"):
            wnd.perform_shell_file_operation(src_paths, target_dir, op, parent_hwnd=int(self.winId()))
        else:
            QMessageBox.warning(self, "拖曳作業失敗", "找不到檔案作業處理器")

    def _notify_search_refresh_delayed(self):
        wnd = self.window()
        if wnd is not None and hasattr(wnd, "refresh_current_search_results"):
            QTimer.singleShot(600, wnd.refresh_current_search_results)


class CenterFileListView(QTreeView):
    """中央檔案列表：接受從右側搜尋結果拖曳進來的檔案。"""

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event):
        try:
            target_dir = self._resolve_drop_target_dir(event.pos())
            src_paths = self._extract_source_paths_from_mime(event.mimeData())
            if not target_dir or not src_paths:
                event.ignore()
                return

            op = self._decide_drop_operation(src_paths, target_dir, event)
            if op is None:
                event.ignore()
                return

            wnd = self.window()
            if wnd is not None and hasattr(wnd, "perform_shell_file_operation"):
                wnd.perform_shell_file_operation(src_paths, target_dir, op, parent_hwnd=int(self.winId()))
                if hasattr(wnd, "refresh_current_search_results"):
                    QTimer.singleShot(600, wnd.refresh_current_search_results)
            event.acceptProposedAction()
        except Exception as ex:
            event.ignore()
            QMessageBox.warning(self, "拖曳失敗", f"中央列表拖放處理發生錯誤: {ex}")

    def _resolve_drop_target_dir(self, pos):
        model = self.model()
        if model is None:
            return ""

        idx = self.indexAt(pos)
        if idx.isValid():
            raw = model.filePath(idx)
            path = os.path.normpath(raw) if raw else ""
            if path and os.path.isdir(path):
                return path
            if path:
                parent = os.path.dirname(path)
                if os.path.isdir(parent):
                    return parent

        root_idx = self.rootIndex()
        if root_idx.isValid():
            raw = model.filePath(root_idx)
            root_path = os.path.normpath(raw) if raw else ""
            if root_path and os.path.isdir(root_path):
                return root_path
        return ""

    def _extract_source_paths_from_mime(self, mime):
        paths = []
        seen = set()
        for url in mime.urls() if mime is not None else []:
            local = url.toLocalFile()
            if not local or local in seen:
                continue
            seen.add(local)
            paths.append(local)
        return paths

    def _decide_drop_operation(self, src_paths, target_dir, event):
        wnd = self.window()
        drag_btn = Qt.NoButton
        if wnd is not None and hasattr(wnd, "_search_drag_button"):
            drag_btn = wnd._search_drag_button

        if drag_btn == Qt.RightButton:
            menu = QMenu(self)
            act_copy = menu.addAction("複製到此處")
            act_move = menu.addAction("移動到此處")
            menu.addSeparator()
            act_cancel = menu.addAction("取消")
            global_pos = self.viewport().mapToGlobal(event.pos())
            chosen = menu.exec_(global_pos)
            if chosen == act_copy:
                return "copy"
            if chosen == act_move:
                return "move"
            return None

        mods = event.keyboardModifiers()
        if mods & Qt.ControlModifier:
            return "copy"
        if mods & Qt.ShiftModifier:
            return "move"

        first = src_paths[0] if src_paths else ""
        src_drive = os.path.splitdrive(os.path.abspath(first))[0].lower() if first else ""
        dst_drive = os.path.splitdrive(os.path.abspath(target_dir))[0].lower() if target_dir else ""
        return "move" if src_drive and src_drive == dst_drive else "copy"


class FixedWidthTabBar(QTabBar):
    """每個頁籤寬度固定為 10 個字元大小（依字型度量計算），文字靠左對齊。"""
    CHAR_COUNT = 10
    LEFT_PAD = 4  # 文字距左邊距 px

    def tabSizeHint(self, index):
        hint = super().tabSizeHint(index)
        fm = self.fontMetrics()
        char_w = max(fm.averageCharWidth(), fm.height())
        hint.setWidth(char_w * self.CHAR_COUNT)
        return hint

    def minimumTabSizeHint(self, index):
        return self.tabSizeHint(index)

    def paintEvent(self, event):
        # 取得關閉按鈕的像素寬度（含右側 padding），用來保留空間
        close_btn_w = self.style().pixelMetric(QStyle.PM_TabCloseIndicatorWidth, None, self) + 6
        painter = QStylePainter(self)
        for i in range(self.count()):
            opt = QStyleOptionTab()
            self.initStyleOption(opt, i)
            # 移除文字，先畫頁籤底色/邊框
            text = opt.text
            opt.text = ""
            painter.drawControl(QStyle.CE_TabBarTab, opt)
            # 手動繪製靠左文字，右側保留關閉按鈕空間
            tab_rect = self.tabRect(i)
            text_rect = tab_rect.adjusted(self.LEFT_PAD, 0, -close_btn_w, 0)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)


class PathTabBar(QWidget):
    """多頁籤列，追蹤路徑（左/中面板）或搜尋關鍵字（右面板）。
    tab_switched 訊號在使用者切換頁籤時發出，帶出該頁籤儲存的資料。"""
    tab_switched = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tab_bar = FixedWidthTabBar(self)
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.setMovable(True)
        self.tab_bar.setExpanding(False)
        self.tab_bar.tabCloseRequested.connect(self._on_close_tab)
        self.tab_bar.currentChanged.connect(self._on_current_changed)
        self.tab_bar.tabMoved.connect(self._on_tab_moved)

        self._add_btn = QToolButton(self)
        self._add_btn.setText("+")
        self._add_btn.setToolTip("新增頁籤")
        self._add_btn.setFixedSize(22, 22)
        self._add_btn.clicked.connect(lambda: self.add_tab(""))

        layout.addWidget(self.tab_bar, 1)
        layout.addWidget(self._add_btn, 0)
        self.setLayout(layout)

        self._tab_data = []   # 每個頁籤儲存的資料（路徑或關鍵字）
        self._emit_on_change = True

        # 初始頁籤
        self._internal_add("", "新頁籤")

    def _internal_add(self, data, label):
        prev = self._emit_on_change
        self._emit_on_change = False
        idx = self.tab_bar.addTab(label)
        self._tab_data.append(data)
        self._emit_on_change = prev
        return idx

    def add_tab(self, data="", label=""):
        """新增頁籤並切換至該頁籤。label 預設由 data 衍生。"""
        display = label or (data if data else "新頁籤")
        self._internal_add(data, display)
        self._emit_on_change = True
        self.tab_bar.setCurrentIndex(self.tab_bar.count() - 1)
        return self.tab_bar.count() - 1

    def set_current_data(self, data, label=""):
        """更新目前頁籤儲存的資料與標籤文字。"""
        idx = self.tab_bar.currentIndex()
        if 0 <= idx < len(self._tab_data):
            self._tab_data[idx] = data
            display = label or (data if data else "新頁籤")
            self.tab_bar.setTabText(idx, display)

    def current_data(self):
        idx = self.tab_bar.currentIndex()
        if 0 <= idx < len(self._tab_data):
            return self._tab_data[idx]
        return ""

    def _on_close_tab(self, index):
        if self.tab_bar.count() > 1:
            prev = self._emit_on_change
            self._emit_on_change = False
            self.tab_bar.removeTab(index)
            self._tab_data.pop(index)
            self._emit_on_change = prev

    def _on_tab_moved(self, from_index, to_index):
        """頁籤拖動時同步 _tab_data 的順序。"""
        self._tab_data.insert(to_index, self._tab_data.pop(from_index))

    def _on_current_changed(self, index):
        if self._emit_on_change and 0 <= index < len(self._tab_data):
            self.tab_switched.emit(self._tab_data[index])

    def get_all_tabs(self):
        """回傳 [(data, label), ...] 串列及目前頁籤索引。"""
        tabs = []
        for i in range(self.tab_bar.count()):
            data = self._tab_data[i] if i < len(self._tab_data) else ""
            label = self.tab_bar.tabText(i)
            tabs.append((data, label))
        return tabs, self.tab_bar.currentIndex()

    def restore_tabs(self, tabs, current_index):
        """以給定的 [(data, label), ...] 重建整個頁籤列。"""
        prev = self._emit_on_change
        self._emit_on_change = False
        while self.tab_bar.count() > 0:
            self.tab_bar.removeTab(0)
        self._tab_data.clear()
        for data, label in tabs:
            self.tab_bar.addTab(label)
            self._tab_data.append(data)
        if not tabs:
            self.tab_bar.addTab("新頁籤")
            self._tab_data.append("")
        safe_idx = current_index if 0 <= current_index < self.tab_bar.count() else 0
        self.tab_bar.setCurrentIndex(safe_idx)
        self._emit_on_change = prev


class FileManager(QMainWindow):
    def __init__(self):
        super().__init__()

        self.everything = EverythingSDK()
        self.search_model = None
        self.sdk_warned = False
        self._search_drag_button = Qt.NoButton
        self.initUI()

    def initUI(self):
        self.setWindowTitle("文件管理器")
        self.setGeometry(100, 100, 800, 600)

        # 创建左侧的目录树视图
        self.treeView = CustomTreeView(self)
        self.treeView.setHeaderHidden(True)

        # 设置左侧目录树的根目录为计算机的顶级目录
        root_path = ""
        self.model = QFileSystemModel()
        self.model.setRootPath(root_path)

        # 只显示目录和磁盘驱动器，不显示目录属性
        self.model.setFilter(QDir.Dirs | QDir.Drives | QDir.NoDotAndDotDot)

        self.treeView.setModel(self.model)
        root_idx = self.model.index(root_path)
        self.treeView.setRootIndex(root_idx)
        # 尝试展开根节点并确保可以看到内容
        try:
            if root_idx.isValid():
                self.treeView.expand(root_idx)
                self.treeView.scrollTo(root_idx)
        except Exception:
            pass
        self.treeView.hideColumn(1)
        self.treeView.hideColumn(2)
        self.treeView.hideColumn(3)

        # 使用 QToolBar（橫跨左右兩側）並加入快捷鍵與事件
        self.toolbar = QToolBar("Main Toolbar", self)
        self.addToolBar(self.toolbar)
        # 設定圖示大小與 icon-only 顯示
        self.toolbar.setIconSize(QSize(24, 24))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        # 簡單 hover 效果，並讓按鈕與主題顏色相容
        self.toolbar.setStyleSheet('QToolButton { padding: 4px; } QToolButton:hover { background-color: rgba(0,0,0,0.05); }')

        # 前兩個按鈕改為直接調整字型大小（放大 / 縮小）
        action_new = QAction("字型放大", self)
        action_new.setShortcut(QKeySequence("Ctrl+N"))
        action_new.setToolTip("放大字型 (Ctrl+N)")
        action_new.triggered.connect(self.on_font_increase)

        action_open = QAction("字型縮小", self)
        action_open.setShortcut(QKeySequence("Ctrl+O"))
        action_open.setToolTip("縮小字型 (Ctrl+O)")
        action_open.triggered.connect(self.on_font_decrease)

        # 嘗試從 resources/icons 載入自訂圖示；若不存在或無法載入 SVG，會 fallback 或動態繪製一個文字圖示
        icons_dir = os.path.join(os.path.dirname(__file__), "resources", "icons")
        def make_text_icon(ch, font_size=14, color="#222"):
            size = self.toolbar.iconSize()
            pix = QPixmap(size)
            pix.fill(QColor("transparent"))
            p = QPainter(pix)
            p.setPen(QColor(color))
            f = QFont("Arial", font_size)
            f.setBold(True)
            p.setFont(f)
            rect = pix.rect()
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, ch)
            p.end()
            return QIcon(pix)

        def make_bg_text_icon(ch, font_size=14, fg="#222", bg="#fff"):
            size = self.toolbar.iconSize()
            pix = QPixmap(size)
            pix.fill(QColor(bg))
            p = QPainter(pix)
            p.setPen(QColor(fg))
            f = QFont("Arial", font_size)
            f.setBold(True)
            p.setFont(f)
            rect = pix.rect()
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, ch)
            p.end()
            return QIcon(pix)

        def load_icon(name, fallback_sp):
            # For A icons prefer generated icons that match current theme (no SVG dependency)
            palette = QApplication.palette()
            fg_col = palette.color(QPalette.Text).name()
            bg_col = palette.color(QPalette.Window).name()
            if name == 'A_large':
                return make_bg_text_icon('A', font_size=16, fg=fg_col, bg=bg_col)
            if name == 'A_small':
                return make_bg_text_icon('a', font_size=12, fg=fg_col, bg=bg_col)

            path = os.path.join(icons_dir, f"{name}.svg")
            style = QApplication.style()

            # Try loading vendor SVG or fallback to system icon
            try:
                if os.path.exists(path):
                    icon = QIcon(path)
                    if not icon.isNull():
                        pm = icon.pixmap(self.toolbar.iconSize())
                        if pm and not pm.isNull():
                            return icon
                    pix = QPixmap(path)
                    if not pix.isNull():
                        pm = pix.scaled(
                            self.toolbar.iconSize(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        return QIcon(pm)
                    if HAVE_SVG_RENDERER and QSvgRenderer is not None:
                        renderer = QSvgRenderer(path)
                        size = self.toolbar.iconSize()
                        pixmap = QPixmap(size)
                        pixmap.fill(QColor("transparent"))
                        painter = QPainter(pixmap)
                        renderer.render(painter)
                        painter.end()
                        if not pixmap.isNull():
                            return QIcon(pixmap)
            except Exception:
                pass

            if style is not None:
                return style.standardIcon(fallback_sp)
            return QIcon()

        action_new.setIcon(load_icon('A_large', QStyle.StandardPixmap.SP_FileIcon))
        action_open.setIcon(load_icon('A_small', QStyle.StandardPixmap.SP_DialogOpenButton))

        # 使用 QToolButton 並將其明確命名（以便後續啟用/停用）
        self.btn_increase = QToolButton(self)
        self.btn_increase.setDefaultAction(action_new)
        self.btn_increase.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_increase.setIconSize(self.toolbar.iconSize())
        self.btn_increase.setAutoRaise(True)
        self.toolbar.addWidget(self.btn_increase)

        self.btn_decrease = QToolButton(self)
        self.btn_decrease.setDefaultAction(action_open)
        self.btn_decrease.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_decrease.setIconSize(self.toolbar.iconSize())
        self.btn_decrease.setAutoRaise(True)
        self.toolbar.addWidget(self.btn_decrease)

        # 创建右侧的文件列表视图
        self.listView = CenterFileListView(self)
        self.listView.setSortingEnabled(True)
        self.listView2 = SearchListView(self)
        self.listView2.setSortingEnabled(True)
        self.listView2.setContextMenuPolicy(Qt.CustomContextMenu)
        self.listView2.customContextMenuRequested.connect(self._show_search_context_menu)

        # 中間面板：加入多重頁籤列
        self.mid_tab_bar = PathTabBar(self)
        self.mid_info_combo = QComboBox()
        self.mid_info_combo.setEditable(True)
        self.mid_info_combo.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.mid_info_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.mid_container = QWidget()
        mid_vbox = QVBoxLayout()
        mid_vbox.setContentsMargins(0, 0, 0, 0)
        mid_vbox.setSpacing(0)
        mid_vbox.addWidget(self.mid_tab_bar)
        mid_vbox.addWidget(self.mid_info_combo)
        mid_vbox.addWidget(self.listView, 1)
        self.mid_container.setLayout(mid_vbox)

        # 右側面板：加入多重頁籤列並包裝
        self.right_tab_bar = PathTabBar(self)
        self.right_info_combo = QComboBox()
        self.right_info_combo.setEditable(True)
        self.right_info_combo.setInsertPolicy(QComboBox.NoInsert)
        self.right_info_combo.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.right_info_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 儲存使用者輸入的文字，從 textEdited 更新，因此在 returnPressed 時即使 Qt 內部清空 lineEdit 也能取得
        self._combo_typed_text = ""
        self.right_info_combo.lineEdit().textEdited.connect(self._on_combo_text_edited)
        self.right_info_combo.lineEdit().returnPressed.connect(self._on_combo_return_pressed)
        right_frame = QWidget()
        right_frame_vbox = QVBoxLayout()
        right_frame_vbox.setContentsMargins(0, 0, 0, 0)
        right_frame_vbox.setSpacing(0)
        right_frame_vbox.addWidget(self.right_tab_bar)
        right_frame_vbox.addWidget(self.right_info_combo)
        right_frame_vbox.addWidget(self.listView2, 1)
        right_frame.setLayout(right_frame_vbox)

        self.right_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.right_splitter.addWidget(self.mid_container)
        self.right_splitter.addWidget(right_frame)
        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 1)

        right_container = QWidget()
        right_vbox = QVBoxLayout()
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.addWidget(self.right_splitter)
        right_container.setLayout(right_vbox)

        # 左側面板：加入多重頁籤列並包裝
        self.left_tab_bar = PathTabBar(self)
        self.left_info_combo = QComboBox()
        self.left_info_combo.setEditable(True)
        self.left_info_combo.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.left_info_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        left_frame = QWidget()
        left_vbox = QVBoxLayout()
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(0)
        left_vbox.addWidget(self.left_tab_bar)
        left_vbox.addWidget(self.left_info_combo)
        left_vbox.addWidget(self.treeView, 1)
        left_frame.setLayout(left_vbox)

        # 创建一个可调整大小的分割器
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(left_frame)
        self.splitter.addWidget(right_container)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([200, 600])

        self.setCentralWidget(self.splitter)

        # 初始化狀態列並顯示目前字型大小
        status = self.statusBar()
        if status is not None:
            status.showMessage("")

        self.list_input = QLineEdit(self)
        self.list_input.setPlaceholderText("Input text")
        self.list_input.setFixedHeight(self.toolbar.iconSize().height() + 8)
        self.list_input.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.toolbar_spacer = QWidget(self)
        self.toolbar_spacer.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.toolbar.addWidget(self.toolbar_spacer)
        self.toolbar.addWidget(self.list_input)
        self.right_splitter.splitterMoved.connect(self._update_toolbar_input)
        self.splitter.splitterMoved.connect(self._update_toolbar_input)
        self._update_toolbar_input()


        # 设置右侧文件列表的模型
        self.fileListModel = QFileSystemModel()
        self.listView.setModel(self.fileListModel)
        self.search_model = SearchResultsModel(self.listView2)
        self.search_model.setHorizontalHeaderLabels(["檔名", "目錄", "日期", "大小"])
        self.search_proxy = SearchSortProxyModel(self.listView2)
        self.search_proxy.setSourceModel(self.search_model)
        self.listView2.setModel(self.search_proxy)
        self.listView2.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.listView2.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.listView2.setDragEnabled(True)
        self.listView2.setDragDropMode(QAbstractItemView.DragDrop)
        self.listView2.setAcceptDrops(True)
        self.listView2.setDropIndicatorShown(True)
        self.listView2.setDefaultDropAction(Qt.IgnoreAction)

        self.listView.setAcceptDrops(True)
        self.listView.setDragEnabled(False)
        self.listView.setDragDropMode(QAbstractItemView.DropOnly)
        self.listView.setDropIndicatorShown(True)

        header = self.listView.header()
        if header is not None:
            header.moveSection(3, 1)
        self.listView.hideColumn(2)

        header2 = self.listView2.header()
        if header2 is not None:
            header2.setStretchLastSection(True)
        # 顯示初始字型資訊
        self.update_status_bar()
        # 根據選取啟用/停用刪除與屬性按鈕
        try:
            self.listView.doubleClicked.connect(self.on_listView_doubleClicked)
            self.listView.clicked.connect(self.on_listView_clicked)  # 添加單擊事件
            self.listView2.doubleClicked.connect(self.on_listView2_doubleClicked)
        except Exception:
            pass
        # 用 eventFilter 追蹤 listView viewport 上的實際滑鼠按下事件，
        # 只有真正的使用者點擊才觸發 on_listView_clicked 中的搜尋
        self._listview_mouse_pressed = False
        self.listView.viewport().installEventFilter(self)

        # 设置默认排序为日期排序
        self.listView.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self.listView2.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        # 连接目录树的项选择事件到显示文件列表的函数
        tree_selection = self.treeView.selectionModel()
        if tree_selection is not None:
            tree_selection.selectionChanged.connect(self.on_treeView_selectionChanged)
        # 頁籤列切換訊號
        self.left_tab_bar.tab_switched.connect(self._on_left_tab_switched)
        self.mid_tab_bar.tab_switched.connect(self._on_mid_tab_switched)
        self.right_tab_bar.tab_switched.connect(self._on_right_tab_switched)
        # 用 eventFilter 追蹤 listView viewport 上的實際滑鼠按下事件，
        # 只有真正的使用者點擊才觸發 on_listView_clicked 中的搜尋
        self._listview_mouse_pressed = False
        self.listView.viewport().installEventFilter(self)
        # 下拉清單點擊搜尋
        self.right_info_combo.view().pressed.connect(self._on_right_info_combo_list_pressed)
        # 載入 config.ini 並還原上次狀態
        self.load_config()

    def on_treeView_selectionChanged(self, selected, deselected):
        # 左側目錄樹選取變更時，只更新左側狀態列與頁籤，不強制覆蓋中央面板
        if selected.indexes():
            path = self.model.filePath(selected.indexes()[0])
            self.treeView.resizeColumnToContents(0)
            self.left_tab_bar.set_current_data(path, path)
            self.left_info_combo.lineEdit().setText(path)

    def on_listView_clicked(self, index):
        """处理中央视窗文件单击事件"""
        # 只有在 listView viewport 上確實發生過滑鼠按下時才觸發搜尋
        if not self._listview_mouse_pressed:
            return
        self._listview_mouse_pressed = False
        global ref_s, ref_e, global_keywords
        
        if not self.fileListModel.isDir(index):
            file_name = self.fileListModel.fileName(index)
            keywords = self.extract_keywords(file_name)
            global_keywords = keywords
            
            if keywords:
                ref_s = 0
                ref_e = len(keywords)
                search_command = '|'.join(keywords)
                self.execute_search_command(search_command)


    def on_listView_doubleClicked(self, index):
        path = self.fileListModel.filePath(index)
        if self.fileListModel.isDir(index):
            self.fileListModel.setRootPath(path)
            self.fileListModel.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
            self.listView.setRootIndex(self.fileListModel.index(path))
            # 更新中間及左側頁籤列標題
            self.mid_tab_bar.set_current_data(path, path)
            self.mid_info_combo.lineEdit().setText(path)
            self.left_tab_bar.set_current_data(path, path)
            self.left_info_combo.lineEdit().setText(path)
            self._navigate_left_tree(path)
        else:
            try:
                os.startfile(path)
            except Exception as e:
                QMessageBox.warning(self, "錯誤", f"無法開啟檔案: {e}")
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_toolbar_input()

    def _update_toolbar_input(self):
        if self.list_input is None or self.toolbar_spacer is None:
            return
        buttons_width = 0
        for btn in (self.btn_increase, self.btn_decrease):
            if btn is not None:
                buttons_width += btn.sizeHint().width()

        target_left = self.treeView.width()
        spacer_width = max(target_left - buttons_width, 0)
        self.toolbar_spacer.setFixedWidth(spacer_width)

    def keyPressEvent(self, e):
        global ref_s, ref_e, global_keywords

        # Delete 鍵：刪除右側搜尋結果中選取的檔案
        if e.key() == Qt.Key.Key_Delete:
            fw = QApplication.focusWidget()
            if fw is self.listView2 or fw is self.listView2.viewport():
                self._delete_selected_search_files()
                return

        # F3/F4 縮減搜尋關鍵字範圍，其他鍵不觸發檔案式搜尋
        if e.key() == Qt.Key.Key_F3 and ref_e - ref_s > 0:
            ref_s = ref_s + 1
            if ref_e - ref_s > 0:
                self.execute_search_command('|'.join(global_keywords[ref_s:ref_e]))
        elif e.key() == Qt.Key.Key_F4 and ref_e - ref_s > 0:
            ref_e = ref_e - 1
            if ref_e - ref_s > 0:
                self.execute_search_command('|'.join(global_keywords[ref_s:ref_e]))

    def extract_keywords(self, file_name):
        # 自定义解析文件名以提取多个参数，只提取括号内的文字
        keywords = []
        stack = []
        is_inside_brackets = False

        for char in file_name:
            if char in "([{":
                if not is_inside_brackets:
                    is_inside_brackets = True
                elif stack:
                    keywords.append("".join(stack))
                    stack = []
            elif char in ")]}":
                is_inside_brackets = False
                if stack:
                    keywords.append("".join(stack))
                stack = []
            elif is_inside_brackets:
                stack.append(char)

        keywords = [keyword for keyword in keywords if keyword.strip()]
        return keywords

    def _navigate_left_tree(self, path):
        """展開左側目錄樹所有祖先節點並選取指定路徑。"""
        if not path or not os.path.isdir(path):
            return
        idx = self.model.index(os.path.normpath(path))
        if not idx.isValid():
            return
        # 收集所有祖先並依由淺至深展開
        ancestors = []
        parent = idx.parent()
        while parent.isValid():
            ancestors.append(parent)
            parent = parent.parent()
        for anc in reversed(ancestors):
            self.treeView.expand(anc)
        self.treeView.setCurrentIndex(idx)
        self.treeView.scrollTo(idx, QAbstractItemView.PositionAtCenter)

    def _on_left_tab_switched(self, path):
        """切換左側頁籤：導航目錄樹至儲存的路徑。"""
        self.left_info_combo.lineEdit().setText(path)
        if path and os.path.isdir(path):
            self._navigate_left_tree(path)

    def _on_mid_tab_switched(self, path):
        """切換中間頁籤：更新檔案列表至儲存的路徑，左側目錄樹跟著同步。"""
        self.mid_info_combo.lineEdit().setText(path)
        if path and os.path.isdir(path):
            self.fileListModel.setRootPath(path)
            self.fileListModel.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
            self.listView.setRootIndex(self.fileListModel.index(path))
            # 左側目錄樹跟著切換
            self.left_tab_bar.set_current_data(path, path)
            self.left_info_combo.lineEdit().setText(path)
            self._navigate_left_tree(path)
        else:
            # 新頁籤或空路徑：顯示磁碟機清單，左側狀態列清空
            self.fileListModel.setRootPath("")
            self.fileListModel.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
            self.listView.setRootIndex(QModelIndex())
            self.left_info_combo.lineEdit().setText("")

    def _on_combo_text_edited(self, text):
        """user 手動輸入時將文字儲存至 _combo_typed_text，供 returnPressed 時使用。"""
        self._combo_typed_text = text

    def _on_combo_return_pressed(self):
        """lineEdit returnPressed 信號。取得 textEdited 儲存的文字，
        用 singleShot 延遲從而讓 Qt 內部 _q_returnPressed 先執行完畢，
        再套用自定義搜尋。"""
        text = self._combo_typed_text.strip()
        if text:
            QTimer.singleShot(0, lambda t=text: self.execute_search_command(t))

    def eventFilter(self, obj, event):
        """追蹤 listView viewport 滑鼠按下。"""
        # 追蹤 listView viewport 真實的滑鼠按下，讓 on_listView_clicked 能辨別真偽
        if obj is self.listView.viewport() and event.type() == QEvent.MouseButtonPress:
            self._listview_mouse_pressed = True
            return False  # 不消費，讓事件繼續傳遞
        return super().eventFilter(obj, event)

    def _on_right_tab_switched(self, keyword):
        """切換右側頁籤：側边發表 combobox 顯示並復原搜尋結果。
        不更新 tab 資料或 MRU 歷史，只復原查詢。"""
        self.right_info_combo.blockSignals(True)
        self.right_info_combo.lineEdit().setText(keyword)
        self.right_info_combo.blockSignals(False)
        if keyword:
            self._do_search(keyword)
        elif self.search_model:
            self.search_model.removeRows(0, self.search_model.rowCount())

    def _on_right_info_combo_list_pressed(self, model_index):
        """從下拉清單點擊選取項目時執行搜尋。"""
        text = self.right_info_combo.model().data(model_index)
        if text:
            self.execute_search_command(text)

    def execute_search_command(self, search_command):
        """使用者主動搜尋：更新頁籤資料、combobox MRU 歷史，並執行查詢。"""
        # 1. 儲存到目前頁籤
        self.right_tab_bar.set_current_data(search_command, search_command)
        # 2. 更新 combobox MRU 歷史（移除舊同名項目，插入至頂端）
        self.right_info_combo.blockSignals(True)
        for i in range(self.right_info_combo.count() - 1, -1, -1):
            if self.right_info_combo.itemText(i) == search_command:
                self.right_info_combo.removeItem(i)
        self.right_info_combo.insertItem(0, search_command)
        self.right_info_combo.setCurrentIndex(0)
        self.right_info_combo.blockSignals(False)
        self.right_info_combo.lineEdit().setText(search_command)
        # 3. 執行實際查詢
        self._do_search(search_command)

    def _do_search(self, search_command):
        """只執行 Everything 查詢並更新展示，不修改頁籤資料或 combobox 歷史。復原搜尋用。"""
        if self.everything.is_available():
            results = self.everything.query(search_command)
            self.update_search_results(results)
            return

        if not self.sdk_warned:
            self.sdk_warned = True
            status = self.statusBar()
            if status is not None:
                status.showMessage("Everything SDK DLL not found. Place Everything64.dll next to main.py or in a sdk folder.")
            QMessageBox.information(
                self,
                "Everything SDK",
                "Everything SDK DLL not found.\n\nDownload Everything-SDK.zip and place Everything64.dll (or Everything32.dll) next to main.py or in a 'sdk' folder.",
            )
        subprocess.Popen('"Everything.exe" -search "' + search_command + '"', shell=True)

    def update_search_results(self, results):
        if self.search_model is None:
            return
        self.search_model.removeRows(0, self.search_model.rowCount())
        icon_provider = QFileIconProvider()
        for filepath in results:
            name_item = QStandardItem(os.path.basename(filepath))
            name_item.setEditable(False)
            name_item.setData(filepath, Qt.UserRole + 1)
            name_item.setIcon(icon_provider.icon(QFileInfo(filepath)))

            dir_item = QStandardItem(os.path.dirname(filepath))
            dir_item.setEditable(False)

            try:
                mtime = os.path.getmtime(filepath)
                dt_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                mtime = 0
                dt_str = ''

            date_item = QStandardItem(dt_str)
            date_item.setEditable(False)
            date_item.setData(mtime, Qt.UserRole)

            try:
                if os.path.isdir(filepath):
                    size = 0
                    size_str = ''
                else:
                    size = os.path.getsize(filepath)
                    size_str = self._format_size(size)
            except Exception:
                size = 0
                size_str = ''

            size_item = QStandardItem(size_str)
            size_item.setEditable(False)
            size_item.setData(size, Qt.UserRole)

            self.search_model.appendRow([name_item, dir_item, date_item, size_item])

    def _format_size(self, size):
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"

    def on_listView2_doubleClicked(self, index):
        source_index = self.search_proxy.mapToSource(index)
        name_index = self.search_model.index(source_index.row(), 0)
        filepath = name_index.data(Qt.UserRole + 1)
        if filepath and os.path.exists(filepath):
            if os.path.isdir(filepath):
                tree_index = self.model.index(filepath)
                if tree_index.isValid():
                    self.treeView.setCurrentIndex(tree_index)
                    self.treeView.expand(tree_index)
                    self.treeView.scrollTo(tree_index)
            else:
                try:
                    os.startfile(filepath)
                except Exception as e:
                    QMessageBox.warning(self, "錯誤", f"無法開啟檔案: {e}")

    def _get_selected_search_paths(self):
        """回傳 listView2 中所有選取列的完整路徑。"""
        rows_seen = set()
        paths = []
        for proxy_index in self.listView2.selectedIndexes():
            if proxy_index.column() != 0:
                continue
            source_index = self.search_proxy.mapToSource(proxy_index)
            row = source_index.row()
            if row in rows_seen:
                continue
            rows_seen.add(row)
            item = self.search_model.item(row, 0)
            if item is not None:
                filepath = item.data(Qt.UserRole + 1)
                if filepath:
                    paths.append(filepath)
        return paths

    def _show_search_context_menu(self, pos):
        """在 listView2 上顯示 Windows 檔案總管相同的右鍵選單。"""
        paths = self._get_selected_search_paths()
        if not paths:
            return
        global_pos = self.listView2.viewport().mapToGlobal(pos)
        try:
            self._invoke_shell_context_menu(int(self.winId()), paths, global_pos.x(), global_pos.y())
        except Exception:
            import traceback
            traceback.print_exc()
            menu = QMenu(self)
            if len(paths) == 1 and os.path.exists(paths[0]):
                menu.addAction("開啟", lambda p=paths[0]: os.startfile(p))
            menu.addAction("刪除（移至資源回收桶）", self._delete_selected_search_files)
            menu.exec_(global_pos)

    def _invoke_shell_context_menu(self, hwnd, paths, x, y):
        """Show the Windows Shell context menu (identical to Explorer right-click)."""
        from win32com.shell import shell, shellcon
        import win32gui
        import win32con
        import pythoncom

        pythoncom.CoInitialize()
        try:
            # 依第一個路徑的父目錄分組（GetUIObjectOf 要求相同父目錄）
            parent_dir = os.path.normpath(os.path.dirname(os.path.abspath(paths[0])))
            norm_parent = os.path.normcase(parent_dir)
            same_parent = [
                p for p in paths
                if os.path.normcase(
                    os.path.normpath(os.path.dirname(os.path.abspath(p)))
                ) == norm_parent
            ]

            # 取得桌面 IShellFolder
            desktop = shell.SHGetDesktopFolder()

            # SHParseDisplayName 在此 pywin32 版本只接受 2 個參數: (name, sfgaoMask)
            parent_pidl = shell.SHParseDisplayName(parent_dir, 0)[0]

            # BindToObject: pbc 用 None 代表 NULL
            parent_sf = desktop.BindToObject(parent_pidl, None, shell.IID_IShellFolder)

            # 取得每個檔案相對於父目錄的子 PIDL
            # ParseDisplayName 回傳 (eaten, pidl, attrs)，取 index 1 為 PIDL
            child_pidls = []
            for p in same_parent:
                result = parent_sf.ParseDisplayName(hwnd, None, os.path.basename(p))
                child_pidls.append(result[1])

            # GetUIObjectOf 回傳 (reserved, IContextMenu)，取 index 1 為實際介面
            icm = parent_sf.GetUIObjectOf(
                hwnd, child_pidls, shell.IID_IContextMenu, 0
            )[1]

            # 建立彈出選單並填入 Shell 命令
            hmenu = win32gui.CreatePopupMenu()
            icm.QueryContextMenu(
                hmenu, 0, 1, 0x7FFF,
                shellcon.CMF_EXPLORE | shellcon.CMF_CANRENAME
            )

            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass

            cmd = win32gui.TrackPopupMenu(
                hmenu,
                win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON | win32con.TPM_RETURNCMD,
                x, y, 0, hwnd, None
            )
            win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
            win32gui.DestroyMenu(hmenu)

            if cmd > 0:
                # lpVerb 為整數時代表 MAKEINTRESOURCE(cmd - idCmdFirst)
                ci = (0, hwnd, cmd - 1, None, None, win32con.SW_SHOWNORMAL, 0, None)
                icm.InvokeCommand(ci)
                QTimer.singleShot(800, self._refresh_search_results_existence)
        finally:
            pythoncom.CoUninitialize()

    def _refresh_search_results_existence(self):
        """移除搜尋結果中已不存在的檔案列。"""
        rows_to_remove = []
        for row in range(self.search_model.rowCount()):
            item = self.search_model.item(row, 0)
            if item is None:
                continue
            filepath = item.data(Qt.UserRole + 1)
            if filepath and not os.path.exists(filepath):
                rows_to_remove.append(row)
        for row in reversed(rows_to_remove):
            self.search_model.removeRow(row)

    def refresh_current_search_results(self):
        """依目前右側關鍵字重新查詢，確保拖曳後結果更新。"""
        keyword = self.right_tab_bar.current_data().strip() if self.right_tab_bar is not None else ""
        if not keyword and self.right_info_combo is not None:
            keyword = self.right_info_combo.lineEdit().text().strip()
        if keyword:
            self._do_search(keyword)
        else:
            self._refresh_search_results_existence()

    def perform_shell_file_operation(self, src_paths, target_dir, op, parent_hwnd=None):
        """使用 Windows Shell 執行複製/移動，保留檔案總管衝突提示與進度 UI。"""
        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wt.HWND),
                ("wFunc", wt.UINT),
                ("pFrom", ctypes.c_wchar_p),
                ("pTo", ctypes.c_wchar_p),
                ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", wt.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", ctypes.c_wchar_p),
            ]

        FO_MOVE = 0x0001
        FO_COPY = 0x0002
        FOF_SIMPLEPROGRESS = 0x0100

        # Normalize to native Windows backslash separators; SHFileOperationW
        # does not reliably accept forward-slash paths in pFrom/pTo.
        target_dir = os.path.normpath(target_dir)

        valid_sources = []
        for src in src_paths:
            src = os.path.normpath(src)
            if not os.path.exists(src):
                continue
            dest = os.path.join(target_dir, os.path.basename(src))
            if os.path.abspath(src) == os.path.abspath(dest):
                continue
            valid_sources.append(src)

        if not valid_sources:
            return False

        from_buf = ctypes.create_unicode_buffer("\0".join(valid_sources) + "\0\0")
        to_buf = ctypes.create_unicode_buffer(target_dir + "\0")

        op_struct = SHFILEOPSTRUCTW()
        op_struct.hwnd = int(parent_hwnd) if parent_hwnd is not None else int(self.winId())
        op_struct.wFunc = FO_MOVE if op == "move" else FO_COPY
        op_struct.pFrom = ctypes.cast(from_buf, ctypes.c_wchar_p)
        op_struct.pTo = ctypes.cast(to_buf, ctypes.c_wchar_p)
        op_struct.fFlags = FOF_SIMPLEPROGRESS
        op_struct.lpszProgressTitle = "正在處理檔案..."

        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op_struct))
        if result != 0 and not op_struct.fAnyOperationsAborted:
            QMessageBox.warning(self, "拖曳作業失敗", f"Windows 檔案作業失敗，錯誤碼: {result}")
            return False
        return True

    def _delete_selected_search_files(self):
        """將選取的檔案移至資源回收桶（Delete 鍵 / 備援選單）。"""
        paths = self._get_selected_search_paths()
        existing = [p for p in paths if os.path.exists(p)]
        if not existing:
            return

        count = len(existing)
        first_name = os.path.basename(existing[0])
        label = f"「{first_name}」等 {count} 個項目" if count > 1 else f"「{first_name}」"
        reply = QMessageBox.question(
            self, "確認刪除",
            f"確定要將 {label} 移至資源回收桶嗎？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd",                  wt.HWND),
                ("wFunc",                 wt.UINT),
                ("pFrom",                 ctypes.c_wchar_p),
                ("pTo",                   ctypes.c_wchar_p),
                ("fFlags",                ctypes.c_ushort),
                ("fAnyOperationsAborted", wt.BOOL),
                ("hNameMappings",         ctypes.c_void_p),
                ("lpszProgressTitle",     ctypes.c_wchar_p),
            ]

        FO_DELETE = 0x0003
        FOF_ALLOWUNDO = 0x0040

        # 路徑以 \0 分隔，結尾雙 \0
        path_buf = ctypes.create_unicode_buffer('\0'.join(existing) + '\0')
        op = SHFILEOPSTRUCTW()
        op.hwnd = int(self.winId())
        op.wFunc = FO_DELETE
        op.pFrom = ctypes.cast(path_buf, ctypes.c_wchar_p)
        op.pTo = None
        op.fFlags = FOF_ALLOWUNDO

        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if result == 0 and not op.fAnyOperationsAborted:
            self._refresh_search_results_existence()

    def on_new(self):
        # 保留舊功能（建立新檔案），但不再由工具列第一個按鈕觸發
        dir_path = self.fileListModel.rootPath()
        base = "new_file"
        i = 0
        while True:
            name = f"{base}{i}.txt"
            path = os.path.join(dir_path, name)
            if not os.path.exists(path):
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('')
                break
            i += 1
        # 刷新列表
        self.fileListModel.setRootPath(dir_path)
        self.listView.setRootIndex(self.fileListModel.index(dir_path))

    def on_open(self):
        # 保留舊功能（用系統開啟檔案），但不再由工具列第二個按鈕觸發
        indexes = self.listView.selectedIndexes()
        if not indexes:
            return
        path = self.fileListModel.filePath(indexes[0])
        try:
            os.startfile(path)
        except Exception as e:
            QMessageBox.warning(self, "錯誤", f"無法開啟檔案: {e}")

    def _apply_font_size(self, new_size):
        """將字型大小套用至所有 listview 及頁籤列。"""
        for widget in (self.treeView, self.listView, self.listView2):
            current_font = widget.font()
            f = QFont(current_font.family(), new_size)
            widget.setFont(f)
        # 同步頁籤列字型
        for tab_container in (self.left_tab_bar, self.mid_tab_bar, self.right_tab_bar):
            tb = tab_container.tab_bar
            current_font = tb.font()
            f = QFont(current_font.family(), new_size)
            tb.setFont(f)
            tb.update()
        # 同步 info combobox 字型
        for combo in (self.left_info_combo, self.mid_info_combo, self.right_info_combo):
            current_font = combo.font()
            f = QFont(current_font.family(), new_size)
            combo.setFont(f)

    def on_font_increase(self):
        # 放大字型，各增加 1pt（限制最大 72pt）
        current_font = self.treeView.font()
        current_size = current_font.pointSize() if current_font.pointSize() > 0 else 10
        new_size = min(current_size + 1, 72)
        self._apply_font_size(new_size)
        self.update_status_bar()

    def on_font_decrease(self):
        # 縮小字型，各減少 1pt（限制最小 6pt）
        current_font = self.treeView.font()
        current_size = current_font.pointSize() if current_font.pointSize() > 0 else 10
        new_size = max(current_size - 1, 6)
        self._apply_font_size(new_size)
        self.update_status_bar()

    def update_status_bar(self):
        # 更新狀態列以顯示左側視圖的目前字型大小
        left_font = self.treeView.font()
        left_size = left_font.pointSize() if left_font.pointSize() > 0 else 10
        status = self.statusBar()
        if status is not None:
            status.showMessage(f"字型: {left_size}pt")

    def _config_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')

    def load_config(self):
        """從 config.ini 讀取參數並還原狀態。"""
        cfg = configparser.ConfigParser()
        cfg.read(self._config_path(), encoding='utf-8')

        # 還原字型大小
        font_size = cfg.get('General', 'font_size', fallback='')
        if font_size:
            try:
                size = max(6, min(72, int(font_size)))
                self._apply_font_size(size)
                self.update_status_bar()
            except Exception:
                pass

        # 還原左側目錄樹選取的目錄（directoryLoaded 只觸發一次後自動斷開）
        left_dir = cfg.get('General', 'left_dir', fallback='')
        if left_dir and os.path.isdir(left_dir):
            def _on_dir_loaded(path, _target=left_dir):
                idx = self.model.index(_target)
                if idx.isValid():
                    try:
                        self.model.directoryLoaded.disconnect(_on_dir_loaded)
                    except Exception:
                        pass
                    self._navigate_left_tree(_target)
                    self.left_tab_bar.set_current_data(_target, _target)
                    self.left_info_combo.lineEdit().setText(_target)
            self.model.directoryLoaded.connect(_on_dir_loaded)
            self.model.setRootPath(left_dir)

        # 還原分割器大小
        splitter_sizes = cfg.get('Layout', 'splitter_sizes', fallback='')
        if splitter_sizes:
            try:
                self.splitter.setSizes([int(x) for x in splitter_sizes.split(',')])
            except Exception:
                pass
        right_splitter_sizes = cfg.get('Layout', 'right_splitter_sizes', fallback='')
        if right_splitter_sizes:
            try:
                self.right_splitter.setSizes([int(x) for x in right_splitter_sizes.split(',')])
            except Exception:
                pass

        # 還原左側 treeView 欄位寬度
        left_col_widths = cfg.get('Columns', 'left_col_widths', fallback='')
        if left_col_widths:
            try:
                for i, w in enumerate(left_col_widths.split(',')):
                    self.treeView.setColumnWidth(i, int(w))
            except Exception:
                pass

        # 還原中間 listView 欄位寬度與順序
        mid_header = self.listView.header()
        if mid_header is not None:
            mid_col_widths = cfg.get('Columns', 'mid_col_widths', fallback='')
            if mid_col_widths:
                try:
                    for i, w in enumerate(mid_col_widths.split(',')):
                        self.listView.setColumnWidth(i, int(w))
                except Exception:
                    pass
            mid_col_order = cfg.get('Columns', 'mid_col_order', fallback='')
            if mid_col_order:
                try:
                    order = [int(x) for x in mid_col_order.split(',')]
                    for vi, li in enumerate(order):
                        cur = mid_header.visualIndex(li)
                        if cur != vi:
                            mid_header.moveSection(cur, vi)
                except Exception:
                    pass

        # 還原右側 listView2 欄位寬度與順序
        right_header = self.listView2.header()
        if right_header is not None:
            right_col_widths = cfg.get('Columns', 'right_col_widths', fallback='')
            if right_col_widths:
                try:
                    for i, w in enumerate(right_col_widths.split(',')):
                        self.listView2.setColumnWidth(i, int(w))
                except Exception:
                    pass
            right_col_order = cfg.get('Columns', 'right_col_order', fallback='')
            if right_col_order:
                try:
                    order = [int(x) for x in right_col_order.split(',')]
                    for vi, li in enumerate(order):
                        cur = right_header.visualIndex(li)
                        if cur != vi:
                            right_header.moveSection(cur, vi)
                except Exception:
                    pass

        # 還原中間 listView 排序方式
        mid_sort_col = cfg.get('Sort', 'mid_sort_column', fallback='')
        mid_sort_ord = cfg.get('Sort', 'mid_sort_order', fallback='')
        if mid_sort_col and mid_sort_ord:
            try:
                col = int(mid_sort_col)
                order = Qt.SortOrder.AscendingOrder if int(mid_sort_ord) == 0 else Qt.SortOrder.DescendingOrder
                self.listView.sortByColumn(col, order)
            except Exception:
                pass

        # 還原右側 listView2 排序方式
        right_sort_col = cfg.get('Sort', 'right_sort_column', fallback='')
        right_sort_ord = cfg.get('Sort', 'right_sort_order', fallback='')
        if right_sort_col and right_sort_ord:
            try:
                col = int(right_sort_col)
                order = Qt.SortOrder.AscendingOrder if int(right_sort_ord) == 0 else Qt.SortOrder.DescendingOrder
                self.listView2.sortByColumn(col, order)
            except Exception:
                pass

        # 還原三個面板的頁籤資訊
        for key, tab_widget in (('left', self.left_tab_bar), ('mid', self.mid_tab_bar), ('right', self.right_tab_bar)):
            raw = cfg.get('Tabs', f'{key}_tabs', fallback='')
            current = cfg.getint('Tabs', f'{key}_tabs_current', fallback=0)
            if raw:
                try:
                    tabs = [(d, l) for d, l in json.loads(raw)]
                    tab_widget.restore_tabs(tabs, current)
                except Exception:
                    pass

        # 啟動時主動執行右側當前頁籤的搜尋，補上 restore_tabs 不觸發 tab_switched 的缺口
        initial_keyword = self.right_tab_bar.current_data()
        if initial_keyword:
            self.right_info_combo.lineEdit().setText(initial_keyword)
            QTimer.singleShot(0, lambda kw=initial_keyword: self._do_search(kw))

        # 補上 restore_tabs 不觸發 tab_switched 的缺口：初始化中央面板
        initial_mid_path = self.mid_tab_bar.current_data()
        if initial_mid_path and os.path.isdir(initial_mid_path):
            self.fileListModel.setRootPath(initial_mid_path)
            self.fileListModel.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
            self.listView.setRootIndex(self.fileListModel.index(initial_mid_path))
            self.mid_info_combo.lineEdit().setText(initial_mid_path)
        else:
            self.fileListModel.setRootPath("")
            self.fileListModel.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
            self.listView.setRootIndex(QModelIndex())

        # 載入搜尋歷史至右側 combobox
        raw_history = cfg.get('General', 'search_history', fallback='')
        if raw_history:
            try:
                history = json.loads(raw_history)
                self.right_info_combo.blockSignals(True)
                for item in reversed(history):  # reversed 使最新的在頂
                    self.right_info_combo.insertItem(0, item)
                self.right_info_combo.blockSignals(False)
            except Exception:
                pass

    def _try_select_dir(self, dir_path):
        """嘗試在左側樹狀視圖中選取並展開指定目錄（僅更新左側）。"""
        self._navigate_left_tree(dir_path)
        self.left_tab_bar.set_current_data(dir_path, dir_path)
        self.left_info_combo.lineEdit().setText(dir_path)

    def save_config(self):
        """將目前狀態寫入 config.ini。"""
        cfg = configparser.ConfigParser()
        cfg.read(self._config_path(), encoding='utf-8')

        if not cfg.has_section('General'):
            cfg.add_section('General')
        if not cfg.has_section('Layout'):
            cfg.add_section('Layout')
        if not cfg.has_section('Columns'):
            cfg.add_section('Columns')
        if not cfg.has_section('Sort'):
            cfg.add_section('Sort')
        if not cfg.has_section('Tabs'):
            cfg.add_section('Tabs')

        # 儲存右側 combobox 歷史（最多 20 筆）
        history = [self.right_info_combo.itemText(i) for i in range(self.right_info_combo.count())]
        cfg.set('General', 'search_history', json.dumps(history[:20], ensure_ascii=False))

        # 儲存目前字型大小
        current_font = self.treeView.font()
        current_size = current_font.pointSize() if current_font.pointSize() > 0 else 10
        cfg.set('General', 'font_size', str(current_size))

        # 儲存左側目錄樹目前選取的目錄
        indexes = self.treeView.selectedIndexes()
        if indexes:
            left_dir = self.model.filePath(indexes[0])
        else:
            left_dir = ''
        cfg.set('General', 'left_dir', left_dir)

        # 儲存分割器大小
        cfg.set('Layout', 'splitter_sizes', ','.join(str(s) for s in self.splitter.sizes()))
        cfg.set('Layout', 'right_splitter_sizes', ','.join(str(s) for s in self.right_splitter.sizes()))

        # 儲存左側 treeView 欄位寬度
        left_widths = []
        for i in range(self.model.columnCount()):
            left_widths.append(str(self.treeView.columnWidth(i)))
        cfg.set('Columns', 'left_col_widths', ','.join(left_widths))

        # 儲存中間 listView 欄位寬度與順序
        mid_header = self.listView.header()
        if mid_header is not None:
            mid_widths = []
            mid_order = []
            for i in range(mid_header.count()):
                mid_widths.append(str(self.listView.columnWidth(i)))
                mid_order.append(str(mid_header.logicalIndex(i)))
            cfg.set('Columns', 'mid_col_widths', ','.join(mid_widths))
            cfg.set('Columns', 'mid_col_order', ','.join(mid_order))

        # 儲存右側 listView2 欄位寬度與順序
        right_header = self.listView2.header()
        if right_header is not None:
            right_widths = []
            right_order = []
            for i in range(right_header.count()):
                right_widths.append(str(self.listView2.columnWidth(i)))
                right_order.append(str(right_header.logicalIndex(i)))
            cfg.set('Columns', 'right_col_widths', ','.join(right_widths))
            cfg.set('Columns', 'right_col_order', ','.join(right_order))

        # 儲存中間 listView 排序方式
        mid_header = self.listView.header()
        if mid_header is not None:
            cfg.set('Sort', 'mid_sort_column', str(mid_header.sortIndicatorSection()))
            cfg.set('Sort', 'mid_sort_order', str(int(mid_header.sortIndicatorOrder())))

        # 儲存右側 listView2 排序方式
        right_header = self.listView2.header()
        if right_header is not None:
            cfg.set('Sort', 'right_sort_column', str(right_header.sortIndicatorSection()))
            cfg.set('Sort', 'right_sort_order', str(int(right_header.sortIndicatorOrder())))

        # 儲存三個面板的頁籤資訊
        for key, tab_widget in (('left', self.left_tab_bar), ('mid', self.mid_tab_bar), ('right', self.right_tab_bar)):
            tabs, current = tab_widget.get_all_tabs()
            cfg.set('Tabs', f'{key}_tabs', json.dumps(tabs, ensure_ascii=False))
            cfg.set('Tabs', f'{key}_tabs_current', str(current))

        with open(self._config_path(), 'w', encoding='utf-8') as f:
            cfg.write(f)

    def closeEvent(self, event):
        self.save_config()
        super().closeEvent(event)

def main():
    app = QApplication(sys.argv)
    window = FileManager()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
