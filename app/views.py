import os
import ctypes
import ctypes.wintypes as wt
import traceback

from PyQt5.QtWidgets import QTreeView, QApplication, QMessageBox, QMenu
from PyQt5.QtCore import Qt, QItemSelection, QItemSelectionModel, QMimeData, QUrl, QTimer
from PyQt5.QtGui import QDrag, QPixmap, QPainter, QColor, QIcon, QFont


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

    def startDrag(self, supportedActions):
        """Qt 在左鍵拖曳達到閾值時呼叫此方法，提供自訂 MIME 資料與預覽圖。"""
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
        result_action = drag.exec_(supportedActions, Qt.CopyAction)
        if wnd is not None and hasattr(wnd, "_search_drag_button"):
            wnd._search_drag_button = Qt.NoButton
        if result_action != Qt.IgnoreAction:
            self._notify_search_refresh_delayed(self._extract_source_paths_from_mime(mime))

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
                result_action = drag.exec_(Qt.CopyAction | Qt.MoveAction | Qt.LinkAction, Qt.CopyAction)
                if wnd is not None and hasattr(wnd, "_search_drag_button"):
                    wnd._search_drag_button = Qt.NoButton
                self._suppress_next_context_menu = True
                if result_action != Qt.IgnoreAction:
                    self._notify_search_refresh_delayed(self._extract_source_paths_from_mime(mime))
            self._press_pos = None
            self._press_button = Qt.NoButton
            return
        # 左鍵拖曳：交由 Qt 內建機制偵測並呼叫 startDrag()
        super().mouseMoveEvent(event)

    def dragEnterEvent(self, event):
        # 只要有 URL 就先接受，讓 drag session 保持活躍；
        # 是否有有效目標由 dragMoveEvent 和 dropEvent 判斷
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            if self._resolve_drop_target_dir(event.pos()):
                event.acceptProposedAction()
            else:
                # 游標不在目錄上：顯示禁止圖示但保持 drag session 活躍
                event.setDropAction(Qt.IgnoreAction)
                event.accept()
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

            if self._last_drag_button == Qt.RightButton:
                # 右鍵拖曳：呼叫 Windows Shell IDropTarget::Drop(MK_RBUTTON)
                # Shell 自動顯示原生選單（移動/複製/建立捷徑/取消）並執行操作
                handled = self._shell_right_drag_drop(src_paths, target_dir, event)
                if handled:
                    event.acceptProposedAction()
                    self._notify_search_refresh_delayed(src_paths, target_dir)
                else:
                    event.ignore()
                return

            op = self._decide_drop_operation(src_paths, target_dir, event)
            if op is None:
                event.ignore()
                return

            self._apply_drop_operation(src_paths, target_dir, op)
            event.acceptProposedAction()
            self._notify_search_refresh_delayed(src_paths, target_dir)
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

    def _shell_right_drag_drop(self, src_paths, target_dir, event):
        """呼叫 Windows Shell IDropTarget::Drop(MK_RBUTTON) 顯示原生右鍵拖曳選單。
        Shell 自動顯示選單、執行操作並回傳結果。
        失敗時 fallback 到符合 Windows 樣式的 Qt 選單。
        回傳 True 表示已完成（含使用者選取後執行），False 表示取消。"""
        try:
            from win32com.shell import shell
            import pythoncom

            pythoncom.CoInitialize()
            try:
                hwnd = int(self.winId())
                desktop = shell.SHGetDesktopFolder()

                # --- 建立來源 IDataObject ---
                src_parent = os.path.normpath(os.path.dirname(os.path.abspath(src_paths[0])))
                src_parent_pidl = shell.SHParseDisplayName(src_parent, 0)[0]
                src_sf = desktop.BindToObject(src_parent_pidl, None, shell.IID_IShellFolder)

                child_pidls = []
                for p in src_paths:
                    r = src_sf.ParseDisplayName(hwnd, None, os.path.basename(p))
                    child_pidls.append(r[1])

                data_obj = src_sf.GetUIObjectOf(
                    hwnd, child_pidls, pythoncom.IID_IDataObject, 0
                )[1]

                # --- 取得目標資料夾的 IDropTarget ---
                tdir = os.path.normpath(target_dir)
                tparent = os.path.dirname(tdir)
                tname = os.path.basename(tdir)
                tparent_pidl = shell.SHParseDisplayName(tparent, 0)[0]
                tparent_sf = desktop.BindToObject(tparent_pidl, None, shell.IID_IShellFolder)
                tdir_pidl = tparent_sf.ParseDisplayName(hwnd, None, tname)[1]

                drop_target = tparent_sf.GetUIObjectOf(
                    hwnd, [tdir_pidl], pythoncom.IID_IDropTarget, 0
                )[1]

                # --- 模擬右鍵拖放（Shell 顯示選單並執行操作）---
                MK_RBUTTON = 2
                DROPEFFECT_NONE = 0
                DROPEFFECT_ALL = 7  # Copy | Move | Link

                gpos = self.viewport().mapToGlobal(event.pos())
                pt = (gpos.x(), gpos.y())

                drop_target.DragEnter(data_obj, MK_RBUTTON, pt, DROPEFFECT_ALL)
                result_effect = drop_target.Drop(data_obj, MK_RBUTTON, pt, DROPEFFECT_ALL)
                return result_effect != DROPEFFECT_NONE
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            traceback.print_exc()
            # COM 路徑失敗：改用符合 Windows 風格的自訂選單
            return self._fallback_right_drag_menu(src_paths, target_dir, event)

    def _fallback_right_drag_menu(self, src_paths, target_dir, event):
        """Shell IDropTarget 不可用時，以符合 Windows 檔案總管風格的 Qt 選單處理右鍵拖曳。"""
        menu = QMenu(self)

        font_bold = QFont(menu.font())
        font_bold.setBold(True)

        act_move = menu.addAction("移動到這裡(&M)")
        act_move.setFont(font_bold)  # 預設動作加粗
        act_copy = menu.addAction("複製到這裡(&C)")
        act_link = menu.addAction("建立捷徑到這裡(&S)")
        menu.addSeparator()
        act_cancel = menu.addAction("取消")

        gpos = self.viewport().mapToGlobal(event.pos())
        chosen = menu.exec_(gpos)

        if chosen == act_move:
            self._apply_drop_operation(src_paths, target_dir, "move")
            return True
        if chosen == act_copy:
            self._apply_drop_operation(src_paths, target_dir, "copy")
            return True
        if chosen == act_link:
            self._create_shortcuts(src_paths, target_dir)
            return True
        return False  # 取消

    def _create_shortcuts(self, src_paths, target_dir):
        """在 target_dir 建立 src_paths 的 Windows 捷徑（.lnk）。"""
        try:
            import pythoncom
            from win32com.shell import shell

            pythoncom.CoInitialize()
            try:
                for src in src_paths:
                    if not os.path.exists(src):
                        continue
                    base = os.path.splitext(os.path.basename(src))[0]
                    lnk_path = os.path.join(target_dir, f"{base} - 捷徑.lnk")
                    link = pythoncom.CoCreateInstance(
                        shell.CLSID_ShellLink, None,
                        pythoncom.CLSCTX_INPROC_SERVER,
                        shell.IID_IShellLink
                    )
                    link.SetPath(src)
                    link.SetWorkingDirectory(os.path.dirname(src))
                    persist = link.QueryInterface(pythoncom.IID_IPersistFile)
                    persist.Save(lnk_path, True)
            finally:
                pythoncom.CoUninitialize()
        except Exception as ex:
            QMessageBox.warning(self, "建立捷徑失敗", f"無法建立捷徑：{ex}")

    def _apply_drop_operation(self, src_paths, target_dir, op):
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

        valid_sources = []
        for src in src_paths:
            if not os.path.exists(src):
                continue
            dest = os.path.join(target_dir, os.path.basename(src))
            if os.path.abspath(src) == os.path.abspath(dest):
                continue
            valid_sources.append(src)

        if not valid_sources:
            return

        from_buf = ctypes.create_unicode_buffer("\0".join(valid_sources) + "\0\0")
        to_buf = ctypes.create_unicode_buffer(target_dir + "\0")

        op_struct = SHFILEOPSTRUCTW()
        op_struct.hwnd = int(self.winId())
        op_struct.wFunc = FO_MOVE if op == "move" else FO_COPY
        op_struct.pFrom = ctypes.cast(from_buf, ctypes.c_wchar_p)
        op_struct.pTo = ctypes.cast(to_buf, ctypes.c_wchar_p)
        op_struct.fFlags = FOF_SIMPLEPROGRESS
        op_struct.lpszProgressTitle = "正在處理檔案..."

        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op_struct))
        if result != 0 and not op_struct.fAnyOperationsAborted:
            QMessageBox.warning(self, "拖曳作業失敗", f"Windows 檔案作業失敗，錯誤碼: {result}")
        self._notify_search_refresh_delayed(valid_sources, target_dir)

    def _notify_search_refresh_delayed(self, src_paths=None, target_dir=""):
        wnd = self.window()
        if wnd is not None:
            if hasattr(wnd, "track_file_operation"):
                wnd.track_file_operation(src_paths or [], target_dir)
            if hasattr(wnd, "refresh_current_search_results"):
                QTimer.singleShot(600, wnd.refresh_current_search_results)
                QTimer.singleShot(1500, wnd.refresh_current_search_results)
            if hasattr(wnd, "refresh_mid_panel"):
                QTimer.singleShot(600, wnd.refresh_mid_panel)
                QTimer.singleShot(1500, wnd.refresh_mid_panel)
