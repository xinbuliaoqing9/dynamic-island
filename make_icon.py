# -*- coding: utf-8 -*-
"""
make_icon.py — 生成灵动岛应用图标 icon.ico（v2 设计感版）

设计：iOS 风圆角方形深空底 + 双色氛围光晕，
中央悬浮一个迷你「灵动岛胶囊」——霓虹青紫描边、
内含圆形封面 / 歌词条 / 播放键，即应用本身的缩影。

运行：python make_icon.py   （产出 icon.ico 和 icon_preview.png）
"""
from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 512          # 主画布
R_BG = 118       # 背景圆角（接近 iOS 图标观感）
BORDER = 6       # 胶囊描边宽度


def lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def vgrad(size, top, bottom):
    img = Image.new("RGBA", size)
    px = img.load()
    for y in range(size[1]):
        c = lerp(top, bottom, y / max(size[1] - 1, 1))
        for x in range(size[0]):
            px[x, y] = c
    return img


def diag_grad(size, c1, c2):
    """对角渐变：垂直渐变旋转 45° 近似"""
    big = vgrad((int(size[0] * 1.6), int(size[1] * 1.6)), c1, c2)
    img = big.rotate(45, expand=False)
    w, h = size
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m


def glow_dot(size, color, radius, blur):
    """一个模糊光斑"""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([radius[0], radius[1], radius[2], radius[3]], fill=color)
    return layer.filter(ImageFilter.GaussianBlur(blur))


def build():
    # ---------- 1. 深空对角渐变底 ----------
    bg = diag_grad((S, S),
                   (11, 16, 38, 255),      # 深蓝黑
                   (30, 16, 60, 255))      # 深紫
    mask_bg = rounded_mask((S, S), R_BG)
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(bg, (0, 0), mask_bg)

    # ---------- 2. 氛围光晕（左上青、右下紫） ----------
    glow_c = glow_dot((S, S), (90, 208, 240, 90),
                      (-140, -160, 360, 360), 90)
    glow_p = glow_dot((S, S), (176, 106, 255, 95),
                      (220, 240, 700, 700), 100)
    icon = Image.alpha_composite(icon, glow_c)
    icon = Image.alpha_composite(icon, glow_p)
    icon = Image.composite(icon, Image.new("RGBA", (S, S), (0, 0, 0, 0)),
                           mask_bg)          # 光晕裁回圆角内

    # ---------- 3. 中央迷你胶囊（霓虹描边） ----------
    px0, py0, px1, py1 = 76, 186, 436, 326   # 胶囊外框（含描边）
    pw, ph = px1 - px0, py1 - py0
    r_cap = (py1 - py0) // 2

    # 描边环 = 外胶囊 mask 挖掉内胶囊 mask
    grad_cap = diag_grad((pw, ph), (90, 208, 240, 255), (176, 106, 255, 255))
    ring = rounded_mask((pw, ph), r_cap)
    inset = BORDER
    hole = rounded_mask((pw - 2 * inset, ph - 2 * inset), r_cap - inset)
    ring.paste(hole, (inset, inset))
    icon.paste(grad_cap, (px0, py0), ring)

    # 胶囊内部近黑底
    inner_bg = vgrad((pw - 2 * inset, ph - 2 * inset),
                     (16, 24, 52, 255), (34, 20, 66, 255))
    icon.paste(inner_bg, (px0 + inset, py0 + inset), hole)

    # ---------- 4. 胶囊内元素 ----------
    d = ImageDraw.Draw(icon)
    cy = (py0 + py1) // 2

    # 4.1 圆形「封面」：青→紫渐变圆 + 内圈暗环（黑胶感）
    ccx, cr = px0 + 80, 40
    disc = diag_grad((2 * cr, 2 * cr),
                     (90, 208, 240, 255), (176, 106, 255, 255))
    disc_mask = Image.new("L", (2 * cr, 2 * cr), 0)
    ImageDraw.Draw(disc_mask).ellipse([0, 0, 2 * cr - 1, 2 * cr - 1], fill=255)
    icon.paste(disc, (ccx - cr, cy - cr), disc_mask)
    d.ellipse([ccx - 13, cy - 13, ccx + 13, cy + 13],
              fill=(14, 18, 38, 255))                 # 中孔
    d.ellipse([ccx - 5, cy - 5, ccx + 5, cy + 5],
              fill=(240, 246, 255, 255))              # 中心点亮

    # 4.2 歌词条：两条圆角横线（上亮下暗）
    d.rounded_rectangle([ccx + cr + 26, cy - 26, ccx + cr + 26 + 118, cy - 8],
                        radius=9, fill=(240, 246, 255, 235))
    d.rounded_rectangle([ccx + cr + 26, cy + 8, ccx + cr + 26 + 84, cy + 26],
                        radius=8, fill=(150, 165, 200, 130))

    # 4.3 播放键：右端白色三角
    tx = px1 - 52
    d.polygon([(tx - 14, cy - 17), (tx - 14, cy + 17), (tx + 18, cy)],
              fill=(255, 255, 255, 245))

    # ---------- 5. 导出 ----------
    icon.save("icon.ico", sizes=[(256, 256), (128, 128), (64, 64),
                                 (48, 48), (32, 32), (16, 16)])
    icon.save("icon_preview.png")
    print("icon.ico + icon_preview.png generated (v2)")


if __name__ == "__main__":
    build()
