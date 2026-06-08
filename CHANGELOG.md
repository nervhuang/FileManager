# Changelog

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
