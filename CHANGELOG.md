# Changelog

## 2026-08-16
- Add Hermes integration: shared author/circle list and remote file search
  - New `authors.db` (SQLite, WAL) as the single source of truth for authors and circles
    - One entity table with `type` (author/circle), aliases, and many-to-many author⇄circle links
    - Every write is journaled to a `changes` table with before/after snapshots; deletes are soft, so any Hermes mistake can be reverted from the GUI
  - New left-hand authors panel (`app/authors_panel.py`), toggleable via 檢視 → 顯示作者清單面板 (Ctrl+L) to return to the previous two-panel layout
    - Tree of circles with their authors; clicking an entry opens a search tab built from its name plus every alias
    - Add/edit/delete entries, manage aliases and links, and revert Hermes changes from the 最近變更 dialog
    - Panel visibility and width persist in `config.ini` under `[Layout]`
  - New MCP stdio server (`app/hermes_mcp.py`) exposing seven tools to Hermes
    - `fm_search`, `fm_match_author`, `fm_authors_stats` for file search; `fm_authors_list` / `_upsert` / `_delete` for the list; `fm_open_search_tab` to drive the GUI
    - Runs as its own process, so list access and search work whether or not the GUI is open; it applies the same `[Exclude]` settings the GUI uses
    - `fm_open_search_tab` returns `gui_not_running` when the GUI is closed, and only launches it when `launch_if_needed` is set
  - New local pipe between GUI and MCP server (`app/gui_bridge.py`, `QLocalServer`)
    - Hermes writes to the list are pushed to the GUI, which refreshes the panel immediately
    - The GUI answers the pipe before running a search, so slow queries no longer look like timeouts to the caller
  - Extract search-keyword parsing into `app/search_query.py` so the GUI and the MCP server produce identical results (verified against the previous implementation over every keyword in `config.ini`)
  - Extract runtime path resolution into `app/paths.py` (no Qt dependency)
- Add an icon toolbar above the authors panel's filter box
  - Add author / add circle / edit / delete / refresh / recent changes, grouped by separators, replacing the text buttons at the bottom
  - Icons are the same 64px size as the file panel's toolbar and carry text labels, but the bar stays separate because the panel can be closed on its own
  - Icons are drawn in the same filled-and-outlined style as the file panel's folder icons rather than bare strokes; delete and refresh reuse the exact system icons the file panel uses
  - Built on `QToolBar` so a narrowed panel folds the buttons into an overflow menu instead of forcing a wide minimum width (panel minimum stays 151px)
  - Edit and delete are disabled until something is selected
  - Default panel width is now 660px, the width at which all six buttons fit
- Draw the refresh icon instead of using `QStyle`'s
  - `SP_BrowserReload` only ships 24×24 and 32×32, and Qt does not upscale it, so in the 64px toolbars it rendered at half the size of every neighbouring icon — in both toolbars
  - New `widgets.make_refresh_icon()` draws it at the requested size; all 18 toolbar icons now report 64×64
  - Drawn in the folder icon's green, as a single closed path covering both the ring and the arrowhead — drawing them as separate shapes left a visible seam at the join no matter how they were aligned — with the tip landing on the ring's centre line so the arrowhead stays inside the circle
  - Other system icons in use (trash, folder, arrows) ship 128×128 and were never affected
- Rebuild the file panel toolbar on `QToolBar` and enlarge it to match the authors panel toolbar
  - Its fixed `QHBoxLayout` had a 1506px minimum width, which propagated to the middle panel and made the authors panel's splitter handle undraggable below a 1657px window — both sides sat at their minimum. The minimum is now 94px and the handle moves freely
  - Buttons switched to text-under-icon so both toolbars are the same shape, and both are pinned to the same height so they cannot drift apart
  - `_sync_right_header_spacing` now measures the toolbar's fixed height rather than its `sizeHint`, which is 4px smaller and would misalign the search panel's tab bar
- Move the authors panel toggle off `Ctrl+L`, which the breadcrumb bar already uses to focus its path editor — two actions on one sequence made it an ambiguous shortcut. It is now `Ctrl+Shift+A`
- Make it harder to end up with an author and its circle as two unrelated entries
  - New `fm_authors_link` tool links (or unlinks) an author and a circle on its own, creating either side if missing — `fm_authors_upsert` previously required resending the whole record just to add a relation
  - `fm_authors_upsert` now states explicitly that a known author/circle pair must be sent with `linked_names`
  - The edit dialog dropped whatever was typed into the alias/link boxes when OK was pressed without Enter; pending text is now committed first
- List every author under the 作者 group, not only those with no circle, so the group's count matches what it shows
- Make the authors panel follow the application font size
  - `_apply_font_size` never touched the panel, so its tree, filter box and buttons stayed at the default size and ignored Ctrl+= / Ctrl+- (and the size restored from `config.ini` at startup)
  - Its dialogs did not inherit either: Qt stops font propagation at top-level window boundaries, so they always opened at the application default regardless of the panel's size
- Stop bundling `config.ini` into the packaged build
  - It landed in `_internal/`, but the app reads `config.ini` next to the executable, so the bundled copy was never loaded — it only shipped the build machine's search history and private paths
  - First launch with no `config.ini` was already supported: the app runs on built-in defaults and writes the file on exit

## 2026-06-17
- Fix file-operation stalls and full-width-bracket search handling
  - Eliminate the 2–3s UI freeze after create/delete/rename/move
    - Disable the search proxy's dynamic sorting during result-model rebuild (per-`appendRow` re-sort was O(n²) for up to 2000 rows)
    - Only re-run the full Everything query for operations that can add matches (paste/move/drop); delete/rename/external changes now do a lightweight row-existence reconcile instead
    - Deduplicate redundant synchronous search refreshes triggered on drag-and-drop
    - Stop the destructive `setRootPath("")` reload of the file panel; rely on `QFileSystemModel`'s built-in watcher to update the displayed directory incrementally
  - Fix search-panel rename falsely reporting "name already exists" on case-only renames (Windows `os.path.exists` is case-insensitive; the file being renamed is no longer treated as a conflict)
  - Recognize text inside full-width/CJK brackets and hyphen-separated terms when interpreting search keywords
    - Query builder now also searches the de-bracketed inner text (single token directly; multiple tokens via Everything's native space-AND, plus a regex fallback)
    - Match filter switched to token-subset so bracket-induced spacing no longer rejects valid matches
    - `extract_keywords` (click a filename to auto-search) now recognizes full-width `（）［］｛｝` and CJK `【】〔〕「」『』〈〉《》` brackets, not just ASCII `([{`

## 2026-06-14
- Fix multi-selection in the file and search panels
  - File panel: enable `ExtendedSelection` so multiple files can be selected (previously single-only)
  - Search panel: dragging one of several selected items now drags the whole selection instead of collapsing to the clicked item
    - Pressing an already-selected item kept the view in `NoState`, so the first mouse move was treated as rubber-band selection and overwrote the multi-selection
    - Now the selection is preserved on press and the drag is started manually; a click without dragging still collapses to the single clicked item

## 2026-06-08
- Rewrite tab drag-and-drop with fully custom implementation
  - Disable Qt native movable drag (whose ghost widget cannot be repositioned mid-scroll)
  - Draw dragged tab as a floating copy that follows the cursor at all times
  - In-bounds drag reorders tabs immediately as the floating copy center crosses a neighbor
  - Out-of-bounds drag leapfrogs hidden tabs one at a time via timer (80 ms/step)
  - Hide close button on the dragged tab during drag to avoid layout artifacts
  - Add `scroll_index_into_view` using `arrowType()` to reliably find Left/Right scroll buttons

## 2026-06-01
- Improve file browsing interactions and release hygiene
  - Add right-panel horizontal/vertical layout switching and persist splitter orientation per layout
  - Add auto-search from the right search box and improve plain-keyword matching
  - Add copy, cut, paste, Backspace-up navigation, and focus rename after creating a folder
  - Improve search result drag-and-drop refresh behavior and auto-scroll during dragging
  - Reset tracked config.ini to sanitized defaults for repository and release builds

## 2026-02-01
- Add toolbar with font controls, icons and UI fixes
  - Toolbar placed across top with four buttons (font increase/decrease, delete, properties)
  - Added dynamic A/a icons and SVG fallbacks
  - Implemented font increase/decrease actions and status bar display
  - Enabled/disabled delete/props based on selection
  - Various bug fixes and debugging cleanup
