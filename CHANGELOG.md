# Changelog

## 2026-08-24
- Draw the update checker's remaining two toolbar icons instead of using `QStyle`'s
  - The toolbar carried two visual languages side by side: two hand-drawn flat icons next to two Windows system icons (a glossy document, a skeuomorphic broom). They pass the size rule — both ship 128×128 — but nothing else about them matched
  - `make_detail_icon()` is a browser window with a 2×2 thumbnail grid. A browser rather than a plain list, because the button opens an external tab rather than expanding something in the panel — the silhouette says so before the tooltip does
  - `make_reset_icon()` is a sheet of records with a red circular-arrow badge. Red rather than green: it clears existing results, which is a different kind of act from the green refresh elsewhere in the app, and the colours should separate before the user clicks
  - The badge is drawn deliberately large. At 26px inside a 64px icon the ring, its gap and the arrowhead blur into a white "C" and stop reading as a circular arrow
  - The ring and its arrowhead are one closed path, as in `widgets.make_refresh_icon()`; drawn as separate shapes they leave a visible seam at the join no matter how they are aligned
- Scale the font across the whole application, not a hand-maintained list of widgets
  - Raising the size to 21pt left the menu bar, the status bar, all three toolbars and the main window itself at 12pt; only the lists, tab bars, breadcrumb and the two panels followed
  - The cause was not a few missed widgets but the shape of the code: `_apply_font_size` implemented a cross-cutting concern by enumeration, so every new panel had to remember to register itself. The authors panel was missed once (it ignored Ctrl+= entirely) and the update checker was the second retrofit
  - New `app/font_scaling.py` walks the whole widget tree and applies a *delta* rather than an absolute size, so deliberate offsets survive — toolbar buttons sit two points above body text for icon/text balance, the checker's count row one above, its log one below in a monospace face
  - Measure everything first, then apply. `setFont` propagates to children that have not set a font of their own, so mutating as you walk means each level reads the already-updated value and the delta compounds — measured on a 12pt tree, the leaves were driven down to the 6pt floor
  - `QApplication.setFont` is deliberately left alone: it is global mutable state that makes the operation order-dependent, and the first version of this change made two tests contaminate each other. Dialogs already apply the font themselves, since Qt stops propagation at top-level window boundaries
  - Three tests: every one of the 176 widgets tracks the change, the previously-missed menu/status/toolbars are named explicitly, and scaling is reversible through +9 / 6pt / 40pt round trips
- Draw the update checker's stop icon instead of using `QStyle`'s
  - `SP_MediaStop` only ships up to 32×32 and Qt does not upscale, so in the 64px toolbar it rendered at half the size of its five neighbours — the same problem `SP_BrowserReload` had, and the fix left behind then (`widgets.make_refresh_icon`) had not been reused
  - New `checker.icons.make_stop_icon()`: a red rounded square 40/64 across, matching the refresh ring's diameter so the two carry equal weight side by side. A square rather than a circle so the silhouette stays distinct from the ring next to it. The highlight covers about 40% of the width — spanning the full width read as a minus sign, closer to "remove" than "stop"
  - A new test walks every toolbar button and fails on any icon whose `actualSize(64,64)` is not 64×64. `availableSizes()` reports the source pixmaps' dimensions, not the rendered size, which is why this went unnoticed
- Fix two test scripts that had been failing unnoticed, and isolate tests from personal settings
  - `test_search_click_realapp.py` had been unrunnable since 2026-06-13: it passed a list of path strings while `update_search_results` had moved to `SearchResult` tuples. It guards against proxy mapping corruption crashing the app on click, so that defence had been absent for two months
  - `test_move_no_sync_refresh.py` passed every assertion but exited 1 — a Traditional Chinese Windows console is cp950 and cannot encode the check mark in its result line
  - Both now point `FILEMANAGER_HOME` at an empty temporary directory. They construct a real `FileManager`, which read the developer's own `config.ini`; on this machine `[Exclude]` covers all of `C:\`, so the test files created under `C:\...\Temp` were correctly filtered out and the tests looked broken
- Restrict the update checker to Chinese and Japanese, suppressing everything else
  - A gallery is notified only when its language set is empty (Japanese original) or falls entirely within {japanese, chinese}; any value outside the whitelist suppresses it (`VERDICT_SUPPRESSED` — stored but not shown)
  - Read the site's `language:` namespace values directly instead of matching a keyword dictionary. `_LANGUAGE_KEYWORDS` listed 14 languages against the site's 30-plus, and `is_wanted_language()` treated "unrecognized" as "Japanese original" — so dutch and ukrainian slipped through and the whitelist was really a blacklist. Reading the namespace makes it a true whitelist: anything unlisted is excluded by default. It also stops `female:` / `other:` tags that happen to contain a language name from causing false matches
  - Judge strictly rather than leniently. The site's language tags often lag: a Japanese tag stays put while the title already says it is an English translation, and a lenient rule lets that through because `japanese` is whitelisted. Measured over 5 artists × 25 newest = 103 galleries, both rules agreed exactly (27 excluded each, 26%); the feared multi-language false kill does not occur on tag pages
  - Suppression no longer depends on whether the book is already in the local collection. The old rule only silenced titles already held locally, on the grounds that an uncollected work should still be surfaced; in practice a book that only exists as a Korean or English translation was never going to be collected. The cost is that those books now never appear at all
  - Language markers carry a `lang:` prefix, separate from quality markers. The prefix is not decoration: the site's language values are outside our control, and `language:ukrainian` must still be recognizable as *a language* despite not being in any dictionary
  - Fix `refresh_verdicts()` losing markers. Re-evaluation re-parsed the title only, discarding the language and decensored information the site's tags had supplied — so a book excluded via `language:korean` reverted to "no language marker = Japanese original" and reappeared, undoing its own exclusion; decensored had the same problem, with version upgrades reverting to already-held
  - `FIRST_RUN_LIMIT` raised from 10 to 25. Tag pages return 25 per request and gdata's `API_BATCH` is 25, so 10 and 25 both cost two requests. The language restriction eats about a quarter of that allowance, and too small a baseline leaves single digits
  - The log pane now shows a per-artist excluded count. Per-artist rather than a total, because a silent filter is dangerous: if the language restriction breaks, the symptom is every artist reporting "no updates" with no visible cause. A line reading "excluded 25, new 0" distinguishes a broken filter from a genuinely quiet artist
  - New 重設掃描紀錄 toolbar button clears findings and state while keeping user-marked ignore/downloaded flags — after a rule change the old rows cannot be recovered, only re-fetched
  - `scripts/test_checker_language.py` is a pure-function test: no network, no credentials, no Qt. The site's flat tag-string format was verified against the public gdata API

## 2026-08-23
- Add the update checker: compare new releases on exhentai against the local collection
  - Query exhentai with `artist:` / `group:` tags built from `english_name` in `authors.db`, then match the returned metadata against local filenames, sorted into four groups: new, version upgrade, probably held, held
  - Matching uses the E-Hentai API's `title_jpn`. Local filenames are Japanese while the site's English titles are romanized, so matching against those misses everything
  - The verdict has three levels, not two. Local filenames often contain typos, so the same book may differ by a single kana — and another book by the same artist can differ by a single kana too, scoring identically. No single threshold separates them, so the middle band is left for a human to judge
  - Language uses a whitelist (Chinese translations and Japanese originals) rather than a blacklist: one round over three artists surfaced English, Korean, Spanish and Portuguese — a blacklist cannot be completed. Multi-language editions and duplicate uploads of one book are aggregated into a single row by core title, otherwise the same book is reported three times
  - New icon on the middle toolbar; the right panel shows the four group counts and the new-releases list. Double-clicking opens a local Web UI (bound to 127.0.0.1 only, random port, per-request token) showing a thumbnail wall
  - Thumbnails are cached locally and served from there rather than hot-linked from `s.exhentai.org`
  - Login credentials live in `runtime_root()/exhentai.txt`, which is gitignored and never written to logs, exception messages or web pages. A missing file is a hard error, never a silent fall back to anonymous requests
  - `app/checker/` is a self-contained subpackage; `authors_db.py` is untouched (its schema additions are applied by `store.py`)
- Add a log pane to the update checker, and make its font and layout follow the main window
  - The pane shows a progress bar (`%v/%m %p%` plus the current artist), elapsed and estimated remaining time, and one line per artist. A full round takes 25–35 minutes and the status bar holds only the last line, so there was no way to see progress, failures, or time remaining
  - `scanner.scan_all()` gained an `on_result(index, total, result)` callback; the existing `progress` fires before an entity starts, so it knows who is running but not what came out
  - `QPlainTextEdit` is capped at `maximumBlockCount(2000)` so hundreds of artists do not accumulate memory
  - New `CheckerPanel.apply_font_size()`, called from `FileManager._apply_font_size()` on the same path as `AuthorsPanel`. Child widgets must each be reset — the count row is one size larger than the body and the log is monospace one size smaller, and a widget with an explicitly set font no longer inherits from its parent. That is exactly why Ctrl+= / Ctrl+- had no effect on this panel. The log's floor is 8pt so it stays visible when the main window is at 6pt
  - Four new `[Layout]` keys: panel visibility, panel width, the list/log split, and list column widths. The main window owns the first two; the last two are encapsulated in `CheckerPanel.layout_state()` / `restore_layout()` so the main window need not know how many splitters the panel contains
  - All-zero values are skipped on restore: if the panel was never shown before the config was written, the hidden widgets' sizes are 0, and applying them would collapse both list and log to zero height

## 2026-08-22
- Add `english_name` to authors and circles, for looking entities up from site queries
  - New `english_name` column on `entities` (a single string, one-to-one, not a list), applied to existing databases via `ALTER TABLE`. Pure metadata: it is not folded into `search_terms_for` and does not affect local file search results
  - `fm_authors_list` / `authors-list` cover `english_name` in both the keyword filter and the returned entity
  - `fm_authors_upsert` / `authors-upsert` can write it
  - `fm_match_author` and `fm_authors_link` accept it as a name argument (via `_resolve_entity`), so an English name resolves back to the Japanese or Chinese entity
  - The GUI add/edit dialog gained an 英文名稱 field, and the list tooltip shows it
  - The CLI needed no change: it forwards `hermes_mcp`'s tool functions directly, so new fields flow through automatically
- Add a CLI so programs other than Hermes can call the same functionality
  - `app/cli.py` calls `hermes_mcp.py`'s tool functions directly (the `@server.tool()` decorator returns the function unchanged), duplicating no logic, so behaviour and the authorization gate are identical to the MCP side
  - Nine commands mirror the nine MCP tools; output is one line of JSON on stdout, and `ok=false` exits 1
  - stdout/stderr are pinned to UTF-8. The Windows console defaults to the system codepage (often cp950 in a Traditional Chinese environment), which raises `UnicodeEncodeError` on Japanese artist names — precisely this CLI's core data
- Split multiple authors inside the brackets of a pasted circle name (、 or , separated)
  - `サイクロン (和泉、冷泉)` previously became one author named `和泉、冷泉`. The bracket contents are now split on the ideographic comma and both half- and full-width commas, each becoming a linked author. Any number is supported

## 2026-08-21
- Split a pasted `團體 (作者)` name into a circle plus its authors, and link them
  - The doujin listing convention (`zero戦 (xxzero)`, or bracketed as `[zero戦 (xxzero)]`) pasted into the name field is split into circle plus author and written through the existing `linked_names` path, creating the link in both directions
  - Only intercepted in *add* mode. Editing an existing entry is left alone, because its name may legitimately contain brackets
  - Takes the last bracket group at the end of the string; half-width, full-width, and an outer square bracket are all accepted
- Merge `linked_names` instead of replacing the whole set
  - Hermes usually handles one author at a time, calling upsert separately for the same circle. `_set_links` deleted all of the entity's existing links before inserting, so each later author wiped out the links recorded by the earlier ones. `_add_links` now only adds what is missing; existing links not listed this time are left alone. Removing a link is done with `fm_authors_link(unlink=true)`
- Give `EverythingSDK` a per-thread instance to avoid window class name collisions
  - The MCP framework runs tool calls through `anyio.to_thread.run_sync`, so consecutive calls to one tool can land on different worker threads. A cross-thread singleton meant other threads never received Everything's reply — the query timed out silently and returned an empty list. The instance is now cached per thread, and the reply window's class name includes `id(self)` so a second instance in the same process does not swallow the first one's class registration

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
- Require the FileManager app to be running before any MCP tool responds
  - Opening the app is how the user grants access; with it closed every tool returns `gui_not_running` and nothing on disk or in the list can be read
  - The gate covers all nine tools, not just the ones that touch the disk — gating a subset only invites the model to reach for another tool
  - `fm_open_search_tab` lost its `launch_if_needed` option: a tool that can start the app could grant itself the access the gate exists to withhold
- Add `fm_search_all`, a paginated bulk form of `fm_search`
  - Same fields as `fm_search`, plus `total`, `offset` and `has_more`; page through with `offset` until `has_more` is false. Page size defaults to 200, capped at 2000 (~560KB)
  - `fm_search` could not see past the per-query ceiling Everything is asked for, so a keyword matching 6989 files reported 2000. The bulk tool raises that ceiling for its own calls only, leaving the app's search untouched
  - New `capped` field reports that Everything's own ceiling was reached, meaning `total` itself may be an undercount — distinct from `has_more`, which only says this page was partial
- Report search truncation honestly
  - `truncated` only reflected the caller's `limit`, so a search cut short by the internal per-query ceiling claimed it was complete
- Let `FILEMANAGER_HOME` override the runtime directory
  - The MCP server runs from the project venv (not frozen) and resolved its data directory to the project folder, while the packaged exe resolves to its own folder — so the two processes each read and wrote a separate `authors.db` and `config.ini`, and anything Hermes stored was invisible in the app
  - Point the variable at the installed exe's folder in Hermes's `mcp_servers` entry and both sides use the same files
  - The MCP server's instructions now state the resolved data directory, so a mismatch is visible rather than silent
- Add an "all tabs" list to both panels' tab bars
  - Opened by right-clicking the ＋ button, right-clicking blank space on the tab bar, or clicking the new ˅ button next to ＋; right-clicking a tab itself does nothing
  - Each row shows the tab's full path or search keyword rather than the 10-character label the tab itself can fit, elided in the middle so the drive and the last folder both stay visible, with the full text in a tooltip
  - The current tab is check-marked and bold; clicking a row switches to that tab and scrolls it into view
  - Tabs with no data fall back to their label (本機 / 新頁籤)
- Scale the tab close button with the application font size
  - Tabs already grew with the font, but the close button's size comes from the style's `PM_TabCloseIndicator*` metric, so the ✕ shrank in relative terms as the font grew. The button is now sized from the tab bar's font metrics and resized again whenever a tab is added or the font changes
  - Resizing the button alone was not enough: the native style paints a fixed-size ✕ centred in whatever rect it is given. A proxy style now paints the ✕ scaled to the button, along with its own hover and pressed feedback
  - The proxy style is attached to the buttons rather than the tab bar because `QWidget::setStyle` does not reach children — the close buttons were using the application style, not the tab bar's
- Make the breadcrumb address bar follow the application font size
  - Setting the font on `BreadcrumbBar` was not enough: the bar, its crumb buttons and its edit box each carry a stylesheet, and Qt treats a styled widget's font as explicitly set, so the parent's font stopped propagating. Every child is now assigned the font directly, and crumbs rebuilt on navigation inherit it too
  - The bar's height now grows with the font instead of staying at its 30px minimum
  - `_sync_right_header_spacing` is recomputed after the bar resizes; it previously ran before the new font was applied, leaving the search panel's tab bar 2px out of line at larger sizes
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
