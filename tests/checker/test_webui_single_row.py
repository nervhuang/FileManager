"""單排版面與版面切換的規則。見 docs/spec/checker.md「版面模式」。

只驗規則，不驗手感：一次捲一排順不順、封面夠不夠大，只有真的開瀏覽器才知道，
標 [手動]。這裡擋的是「哪天有人把 snap、張數上限或行數限制順手拿掉」——
那正是這個專案原本會默默失效的形態。

頁面是純字串，不需要 Qt，也不需要起伺服器。
"""
import pytest

from app.checker import webui

pytestmark = pytest.mark.logic


def _page():
    return webui._render_page('tok-en')


def _rule(selector):
    """抓出某個 CSS 選擇器的宣告內容。選擇器一律頂格寫，所以認行首就夠。"""
    page = _page()
    head = '\n' + selector + '{'
    start = page.index(head) + len(head)
    return page[start:page.index('}', start)]


def test_single_is_the_default_layout():
    page = _page()
    assert '<select id="layout"' in page, '要有版面切換'
    assert page.index('value="single"') < page.index('value="wall"'), '單排是第一個選項'
    assert 'localStorage.getItem("checker_layout")' in page, '版面選擇要記在瀏覽器'
    assert 'checker_cw' in page, '牆模式的縮圖大小沿用原本的鍵，兩者互不干擾'


def test_one_row_fills_the_scroll_area():
    """卡片高度＝捲動區高度，第 N 排的起點才會剛好是 N×高度。"""
    assert 'height:var(--rowh)' in _rule('body.single .card')
    assert 'setProperty("--rowh", h + "px")' in _page()
    assert 'const h = main.clientHeight;' in _page()


def test_row_height_is_remeasured_on_every_draw():
    """每次重畫都要重量捲動區高度。

    分頁按鈕與分類選單是資料回來才生出來的：只在啟動時量一次的話，量到的表頭
    比最後矮一截，卡片就比捲動區高出那一截，一排於是不再剛好是一排。
    實測（headless Edge ＋ CDP）抓到過：捲動區 837、卡片 871。
    """
    page = _page()
    draw = page[page.index('function draw(){'):page.index('function card(i)')]
    assert 'measureRow()' in draw


def test_resize_cannot_measure_a_transient_scrollbar():
    """改視窗大小時，量到的高度不得帶著上一輪版面的暫時捲軸。

    實測（headless Edge ＋ CDP，1920×1080 → 1600×700）：捲動區 554、卡片 539。
    差的 15px 就是水平捲軸——縮窄的瞬間舊卡片還太寬、捲軸冒出來把 clientHeight
    壓掉一截，量完之後版面才更新、捲軸又消失。一排於是永遠差 15px。
    """
    page = _page()
    assert 'overflow-x:hidden' in _rule('body.single main'), '橫向永遠不該出現捲軸'
    resize = page[page.index('addEventListener("resize"'):]
    assert 'requestAnimationFrame' in resize, '版面更新後要再量一次'


def test_scroll_snaps_to_one_row_at_a_time():
    assert 'scroll-snap-type:y mandatory' in _rule('body.single main')
    card = _rule('body.single .card')
    assert 'scroll-snap-align:start' in card
    assert 'scroll-snap-stop:always' in card
    page = _page()
    # snap 只決定最後停在哪；一次手勢只走一排得自己攔 wheel。
    assert 'main.addEventListener("wheel"' in page
    assert '{passive:false}' in page, '要 preventDefault 就不能是 passive'
    assert 'if(sliding' in page, '平滑捲動期間的事件要丟掉，否則慣性會一路翻下去'


def test_ctrl_wheel_is_left_to_the_browser():
    """Ctrl＋滾輪是瀏覽器的縮放，不是換排。

    單排模式的 wheel 攔截原本無條件 preventDefault，把縮放也一起吃掉了——
    頁面自己沒有縮放功能，吃掉等於整個功能消失。
    """
    page = _page()
    wheel = page[page.index('main.addEventListener("wheel"'):page.index('// 縮圖大小是看的人')]
    assert 'e.ctrlKey' in wheel, 'Ctrl＋滾輪要原封不動交給瀏覽器'
    assert wheel.index('e.ctrlKey') < wheel.index('e.preventDefault()'),         '要在 preventDefault 之前就讓路'


def test_keyboard_walks_by_rows():
    page = _page()
    assert 'const STEP = {ArrowDown:1, PageDown:1, ArrowUp:-1, PageUp:-1};' in page
    assert 'e.key === "Home" ? 0 : main.scrollHeight' in page
    assert 'tag === "input" || tag === "select"' in page, '搜尋框裡的方向鍵是編輯游標'


def test_columns_are_derived_from_height_and_capped():
    page = _page()
    assert 'imgH * 5 / 7' in page, '封面是 5:7，寬度由高度反推'
    assert 'Math.min(6, Math.max(1,' in page, '一排夾在 1–6 張'


def test_text_block_is_fixed_height_and_clamped():
    """文字高度一浮動，同頁縮圖就各自高矮不一，每排放得下幾張也算不出來。"""
    assert '--texth:168px' in _rule('body.single')
    assert 'height:var(--texth)' in _rule('body.single .body')
    assert '-webkit-line-clamp:2' in _rule('body.single .title')
    assert 'text-overflow:ellipsis' in _rule('body.single .meta,body.single .match')


def test_cover_is_still_not_cropped_in_single_mode():
    """單排模式不得把「封面不裁切」這條規則弄丟（見「顯示尺寸」）。"""
    assert 'object-fit:contain' in _rule('.card img')
    assert 'aspect-ratio:auto' in _rule('body.single .card img'), '高度改由剩餘空間決定'
    assert 'flex:1' in _rule('body.single .card img')


def test_next_row_is_preloaded():
    page = _page()
    assert 'rootMargin: "100% 0px"' in page, '往下多留一個視窗高，跳過去時圖已經在載'
    assert 'root: main' in page, '捲動的是 main，不是整頁'
    assert 'data-src' in page, '沒輪到的圖不帶 src，開頁不會一次打幾百個請求'


def test_size_selector_belongs_to_wall_mode_only():
    assert 'display:none' in _rule('body.single #cw')


def test_view_resets_to_the_first_row():
    assert 'main.scrollTop = 0;' in _page(), '換分頁／搜尋／版面後回到第一排'
