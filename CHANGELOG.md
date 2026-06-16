# Changelog

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
