"""產生程式的預設圖示：資料夾上面有一個搜尋放大鏡。

以 4 倍超取樣（supersampling）繪製後縮小，邊緣平滑；輸出多解析度 .ico 與預覽 .png。

用法：
    python scripts/generate_icon.py
會在專案根目錄產生 icon.ico 與 icon.png。
"""
import os
from PIL import Image, ImageDraw

S = 4                      # 超取樣倍率
BASE = 256                 # 邏輯座標系（256×256）
W = BASE * S               # 實際繪製尺寸

# 調色盤
FOLDER_FILL = (250, 190, 62, 255)      # 溫暖琥珀色資料夾
FOLDER_FILL_BACK = (236, 168, 40, 255)  # 後片較深，增添層次
FOLDER_EDGE = (176, 98, 20, 255)        # 資料夾深色描邊
GLASS_RING = (38, 50, 71, 255)          # 放大鏡金屬圈／握把（深藍灰）
GLASS_FILL = (219, 234, 254, 235)       # 鏡片淡藍玻璃（半透明，透出資料夾）
GLASS_HILIGHT = (255, 255, 255, 230)    # 鏡片高光


def s(*vals):
    """把邏輯座標放大到繪製座標。"""
    return tuple(int(round(v * S)) for v in vals)


def rounded(draw, box, radius, **kw):
    draw.rounded_rectangle(s(*box), radius=radius * S, **kw)


def draw_folder(draw):
    edge_w = 5 * S
    # 後片（露出上緣一點點，做出雙層資料夾的立體感）
    rounded(draw, (30, 96, 226, 210), 16, fill=FOLDER_FILL_BACK,
            outline=FOLDER_EDGE, width=edge_w)
    # 標籤（左上凸出的資料夾頁籤，梯形）
    draw.polygon([s(34, 96), s(56, 66), s(116, 66), s(140, 96)],
                 fill=FOLDER_FILL_BACK, outline=FOLDER_EDGE, width=edge_w)
    # 前片（資料夾主體）
    rounded(draw, (30, 104, 226, 214), 18, fill=FOLDER_FILL,
            outline=FOLDER_EDGE, width=edge_w)


def draw_magnifier(base_img):
    """放大鏡畫在獨立圖層再合成，方便處理半透明鏡片與描邊。"""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    cx, cy, r = 150, 116, 52          # 鏡片圓心與半徑
    ring_w = 13 * S

    # 握把：從鏡片右下沿 45° 伸出的膠囊
    hx0, hy0 = 150 + 37, 116 + 37     # 靠近鏡片端
    hx1, hy1 = 214, 190               # 末端
    handle_w = 22 * S
    d.line([s(hx0, hy0), s(hx1, hy1)], fill=GLASS_RING, width=handle_w)
    # 握把兩端圓帽
    for (hx, hy) in ((hx0, hy0), (hx1, hy1)):
        rr = handle_w // 2
        d.ellipse([s(hx)[0] - rr, s(hy)[0] - rr, s(hx)[0] + rr, s(hy)[0] + rr],
                  fill=GLASS_RING)

    # 鏡片玻璃（半透明，透出下方資料夾）
    d.ellipse(s(cx - r, cy - r, cx + r, cy + r), fill=GLASS_FILL)
    # 金屬外圈
    d.ellipse(s(cx - r, cy - r, cx + r, cy + r), outline=GLASS_RING, width=ring_w)
    # 鏡片高光（左上一道弧）
    hl = 26
    d.arc(s(cx - hl, cy - hl, cx + hl, cy + hl), start=150, end=250,
          fill=GLASS_HILIGHT, width=6 * S)

    base_img.alpha_composite(layer)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw_folder(draw)
    draw_magnifier(img)

    # 縮小到 256 作為預覽 PNG，同時作為 .ico 的來源影像
    png = img.resize((BASE, BASE), Image.LANCZOS)
    png.save(os.path.join(root, "icon.png"))

    # 多解析度 .ico：由 256 來源影像產生各尺寸（Pillow 會自動降取樣）
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    png.save(os.path.join(root, "icon.ico"), format="ICO", sizes=sizes)

    print("已產生 icon.png 與 icon.ico")


if __name__ == "__main__":
    main()
