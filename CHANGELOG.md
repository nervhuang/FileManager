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
  - Edit and delete are disabled until something is selected; icons scale with the application font size
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
