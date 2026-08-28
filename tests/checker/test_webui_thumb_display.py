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


def test_card_order_is_title_then_buttons_then_image():
    """卡片順序：書名 → 按鈕 → 縮圖。見 docs/spec/checker.md「縮圖 → 卡片順序」。"""
    page = _page()
    card = page[page.index('<article class="card"'):page.index('</article>')]
    assert (card.index('class="title"') < card.index('class="acts"')
            < card.index('<img loading="lazy"')), '縮圖要排在書名與按鈕的下方'


def test_cards_share_row_heights():
    """同一橫排的按鈕與縮圖切齊。見 docs/spec/checker.md「縮圖 → 卡片順序」。"""
    card = _rule('.card')
    assert 'grid-template-rows:subgrid' in card, '卡片要向父格線借列高才會整排切齊'
    assert 'grid-row:span 3' in card, '三格：書名／按鈕／圖'
    assert 'margin-bottom' in card, '排距走 margin，row-gap 會被 subgrid 借成卡片內部空隙'
    assert 'row-gap:0' in _rule('main'), '父層列距要歸零，否則會漏進卡片裡'
