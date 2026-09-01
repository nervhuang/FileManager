"""Web UI 卡片的版面規則。見 docs/spec/checker.md「縮圖」。

只驗規則，不驗長相：`object-fit:cover` 曾把 250×350 的直式封面上下裁掉一半以上，
而封面正是判斷「這本我有沒有」的依據。實際觀感標 [手動]，得開瀏覽器看。

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


def test_card_image_is_not_cropped():
    rule = _rule('.card img')
    assert 'object-fit:cover' not in rule, '縮圖不得裁切'
    assert 'object-fit:contain' in rule, '整張都要看得到'
    assert 'aspect-ratio:250/350' in rule, '固定框讓每張圖一樣高，缺圖時也不會被撐成大洞'


def test_card_width_is_selectable_and_remembered():
    page = _page()
    assert 'minmax(var(--cw)' in page, '卡片寬度要由 --cw 控制'
    for width in ('260', '340', '420', '560'):
        assert f'value="{width}"' in page, f'缺少 {width}px 這個尺寸選項'
    assert '--cw:420px' in page, '預設大圖'
    assert 'localStorage.setItem("checker_cw"' in page, '尺寸選擇要記在瀏覽器'


def test_thumb_opens_full_screen_view():
    page = _page()
    assert 'id="lb"' in page, '要有滿版檢視的容器'
    assert 'max-height:96vh' in page, '滿版檢視要撐滿視窗'
    assert 'Escape' in page, 'Esc 要能關掉滿版檢視'


def test_card_order_is_title_then_image_then_buttons():
    """卡片順序：書名 → 縮圖 → 按鈕。見 docs/spec/checker.md「縮圖 → 卡片順序」。

    按鈕貼著縮圖下緣：判斷「已下載／忽略」看的就是封面，決定與依據要在同一個
    視線落點上。
    """
    page = _page()
    card = page[page.index('<article class="card"'):page.index('</article>')]
    assert (card.index('class="title"') < card.index('<img alt="" data-src=')
            < card.index('class="acts"')), '按鈕要排在縮圖下方'


def test_all_three_buttons_sit_below_the_image():
    """三顆都要在圖下面——只搬走其中一兩顆比原樣更糟。"""
    page = _page()
    card = page[page.index('<article class="card"'):page.index('</article>')]
    image_at = card.index('<img alt="" data-src=')
    for label in ('已下載', '忽略', '開啟'):
        assert card.index(label) > image_at, f'「{label}」還在圖上面'


def test_cards_share_row_heights():
    """同一橫排的縮圖與按鈕切齊。見 docs/spec/checker.md「縮圖 → 卡片順序」。"""
    card = _rule('.card')
    assert 'grid-template-rows:subgrid' in card, '卡片要向父格線借列高才會整排切齊'
    assert 'grid-row:span 3' in card, '三格：書名／按鈕／圖'
    assert 'margin-bottom' in card, '排距走 margin，row-gap 會被 subgrid 借成卡片內部空隙'
    assert 'row-gap:0' in _rule('main'), '父層列距要歸零，否則會漏進卡片裡'


def test_card_frame_uses_a_contrasting_colour():
    """外框要看得出來是外框。見 docs/spec/checker.md「縮圖 → 卡片外框」。

    一整片同色卡片鋪滿畫面時，低對比的邊界會讓相鄰兩張看起來像同一張。
    實際觀感標 [手動]，這裡只擋住「又被改回 --line」。
    """
    rule = _rule('.card')
    assert 'border:2px solid var(--frame)' in rule, '外框要用對比色且要夠粗'
    assert 'solid var(--line)' not in rule, '外框不得退回低對比的分隔線色'


def test_card_frame_colour_is_defined_for_both_schemes():
    """深色模式沒定義的話會沿用淺色那組，深底配深藍框等於沒有框。"""
    page = _page()
    light, dark = page.split('@media(prefers-color-scheme:dark)', 1)
    assert '--frame:' in light, '淺色沒定義 --frame'
    assert '--frame:' in dark, '深色沒定義 --frame'


def test_inside_the_card_stays_low_contrast():
    """內部分隔線維持 --line：內外都用對比色的話，外框就不再是外框。"""
    for selector in ('.card img', '.acts'):
        assert 'var(--line)' in _rule(selector), f'{selector} 的分隔線不該搶戲'
