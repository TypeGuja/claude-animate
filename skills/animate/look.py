"""Глаза: картинки для просмотра через Read.

python look.py screen [out.png] [--full]          — окно Animate (или весь экран)
python look.py grid <png> [out.png] [--step 20]   — сетка в координатах символа (нужен <png>.json от renderSymbol)
python look.py onion <a.png> <b.png> [c.png ...] [-o out.png] — наложение: первый красным, последний синим, середина как есть
python look.py sheet <png...> [-o out.png] [--cols 6] [--size 200]
python look.py zoom <png> x0 y0 x1 y1 [out.png] [--k 4]   — кусок (в координатах символа, если есть .json)
python look.py diff <a.png> <ref.png> [-o out.png] [--thr 32] — силуэт a против эталона: IoU, лишнее (красное), недостающее (синее)
Нужен Pillow (pip install pillow). screen — только Windows.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import tempfile

from PIL import Image, ImageDraw, ImageGrab, ImageFont

OUT_DIR = os.path.join(tempfile.gettempdir(), "claude_animate_look")


def out_path(p, name):
    if p:
        return p
    os.makedirs(OUT_DIR, exist_ok=True)
    return os.path.join(OUT_DIR, name)


def font(sz=12):
    try:
        return ImageFont.truetype("arial.ttf", sz)
    except OSError:
        return ImageFont.load_default()


def meta(png):
    """Границы символа для png: {"left","top","width","height"} в пикселях символа."""
    for j in (os.path.splitext(png)[0] + ".json", os.path.join(os.path.dirname(png), "bounds.json")):
        if os.path.exists(j):
            m = json.load(open(j, encoding="utf-8"))
            return m.get(os.path.basename(png), m)
    return None


def animate_rect():
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _):
        if not user32.IsWindowVisible(h):
            return True
        n = user32.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(h, buf, n + 1)
        t = buf.value
        if "Animate" in t or ".fla" in t.lower():
            r = wt.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            if r.right - r.left > 200:
                found.append((t, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumWindows(cb, 0)
    return found


def screen(a):
    ctypes.windll.user32.SetProcessDPIAware()
    wins = [] if a.full else animate_rect()
    img = ImageGrab.grab(all_screens=True)
    if wins:
        print("окна:", [w[0] for w in wins])
        # all_screens: координаты относительно левого верхнего угла виртуального экрана
        vx = ctypes.windll.user32.GetSystemMetrics(76)
        vy = ctypes.windll.user32.GetSystemMetrics(77)
        l, t, r, b = wins[0][1]
        img = img.crop((l - vx, t - vy, r - vx, b - vy))
    else:
        print("окно Animate не найдено — весь экран" if not a.full else "весь экран")
    if img.width > 1800:
        img = img.resize((1800, int(img.height * 1800 / img.width)))
    p = out_path(a.out, "screen.png")
    img.convert("RGB").save(p)
    print(p, img.size)


def grid(a):
    im = Image.open(a.png).convert("RGBA")
    m = meta(a.png) or {"left": 0, "top": 0, "width": im.width, "height": im.height}
    sx, sy = im.width / m["width"], im.height / m["height"]
    k = max(1, round(600 / max(im.width, im.height)))
    pad = 30
    W, H = im.width * k + pad * 2, im.height * k + pad * 2
    bg = Image.new("RGBA", (W, H), "white")
    bg.paste(im.resize((im.width * k, im.height * k), Image.NEAREST), (pad, pad), im.resize((im.width * k, im.height * k), Image.NEAREST))
    d = ImageDraw.Draw(bg)
    f = font(10)
    step = a.step
    x0 = int(m["left"] // step * step)
    x = x0
    while x <= m["left"] + m["width"]:
        px = pad + (x - m["left"]) * sx * k
        if px >= pad - 1:
            d.line([(px, pad), (px, H - pad)], fill=(255, 0, 0, 140) if x == 0 else (0, 120, 255, 70))
            d.text((px + 1, 2), str(x), fill="blue", font=f)
        x += step
    y = int(m["top"] // step * step)
    while y <= m["top"] + m["height"]:
        py = pad + (y - m["top"]) * sy * k
        if py >= pad - 1:
            d.line([(pad, py), (W - pad, py)], fill=(255, 0, 0, 140) if y == 0 else (0, 120, 255, 70))
            d.text((1, py + 1), str(y), fill="blue", font=f)
        y += step
    p = out_path(a.out, "grid.png")
    bg.convert("RGB").save(p)
    print(p, bg.size, "символ:", m)


def onion(a):
    ims = [Image.open(p).convert("RGBA") for p in a.pngs]
    ms = [meta(p) for p in a.pngs]
    if all(ms):
        # общая система координат символа
        L = min(m["left"] for m in ms); T = min(m["top"] for m in ms)
        R = max(m["left"] + m["width"] for m in ms); B = max(m["top"] + m["height"] for m in ms)
        s = ims[0].width / ms[0]["width"]
        W, H = int((R - L) * s) + 1, int((B - T) * s) + 1
        offs = [(int((m["left"] - L) * s), int((m["top"] - T) * s)) for m in ms]
    else:
        W = max(i.width for i in ims); H = max(i.height for i in ims)
        offs = [((W - i.width) // 2, H - i.height) for i in ims]
    bg = Image.new("RGBA", (W, H), "white")
    n = len(ims)
    for idx, (im, o) in enumerate(zip(ims, offs)):
        if n > 1 and idx in (0, n - 1):
            tint = (255, 60, 60) if idx == 0 else (60, 90, 255)
            alpha = im.getchannel("A").point(lambda v: v * 0.45)
            layer = Image.new("RGBA", im.size, tint + (0,))
            layer.putalpha(alpha)
            bg.alpha_composite(layer, o)
        else:
            bg.alpha_composite(im, o)
    k = max(1, round(500 / max(W, H)))
    bg = bg.resize((W * k, H * k))
    p = out_path(a.out, "onion.png")
    bg.convert("RGB").save(p)
    print(p, bg.size)


def sheet(a):
    ims = [Image.open(p).convert("RGBA") for p in a.pngs]
    w = max(i.width for i in ims); h = max(i.height for i in ims)
    s = a.size / max(w, h)
    cw, ch = int(w * s), int(h * s) + 14
    cols = min(a.cols, len(ims)); rows = (len(ims) + cols - 1) // cols
    bg = Image.new("RGB", (cols * cw, rows * ch), "white")
    d = ImageDraw.Draw(bg); f = font(11)
    for k, (p, im) in enumerate(zip(a.pngs, ims)):
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))
        x, y = (k % cols) * cw, (k // cols) * ch
        bg.paste(im, (x + (cw - im.width) // 2, y + 14 + (ch - 14 - im.height)), im)
        d.text((x + 2, y), os.path.splitext(os.path.basename(p))[0][-14:], fill="red", font=f)
    p = out_path(a.out, "sheet.png")
    bg.save(p)
    print(p, bg.size)


def zoom(a):
    im = Image.open(a.png).convert("RGBA")
    m = meta(a.png)
    x0, y0, x1, y1 = a.x0, a.y0, a.x1, a.y1
    if m:
        s = im.width / m["width"]
        x0, x1 = (x0 - m["left"]) * s, (x1 - m["left"]) * s
        y0, y1 = (y0 - m["top"]) * s, (y1 - m["top"]) * s
    c = im.crop((int(x0), int(y0), int(x1), int(y1)))
    c = c.resize((c.width * a.k, c.height * a.k), Image.NEAREST)
    bg = Image.new("RGBA", c.size, "white"); bg.alpha_composite(c)
    p = out_path(a.out, "zoom.png")
    bg.convert("RGB").save(p)
    print(p, bg.size)


def place(pngs):
    """Картинки в общей системе координат символа (по bounds.json) → (холст W,H, смещения, масштаб)."""
    ims = [Image.open(p).convert("RGBA") for p in pngs]
    ms = [meta(p) for p in pngs]
    if all(ms):
        s = ims[0].width / ms[0]["width"]
        L = min(m["left"] for m in ms); T = min(m["top"] for m in ms)
        R = max(m["left"] + m["width"] for m in ms); B = max(m["top"] + m["height"] for m in ms)
        W, H = int((R - L) * s) + 2, int((B - T) * s) + 2
        offs = [(int(round((m["left"] - L) * s)), int(round((m["top"] - T) * s))) for m in ms]
        return ims, (W, H), offs, (L, T, s)
    W = max(i.width for i in ims); H = max(i.height for i in ims)
    return ims, (W, H), [((W - i.width) // 2, H - i.height) for i in ims], None


def diff(a):
    import numpy as np
    ims, (W, H), offs, org = place([a.png, a.ref])
    masks = []
    for im, o in zip(ims, offs):
        c = Image.new("L", (W, H), 0)
        c.paste(im.getchannel("A"), o)
        masks.append(np.asarray(c) > a.thr)
    A, R = masks
    inter, uni = (A & R).sum(), (A | R).sum()
    extra, miss = (A & ~R).sum(), (R & ~A).sum()
    iou = inter / uni if uni else 1.0
    img = np.full((H, W, 3), 255, np.uint8)
    img[A & R] = (170, 170, 170); img[A & ~R] = (230, 40, 40); img[R & ~A] = (40, 80, 230)
    out = Image.fromarray(img)
    ys, xs = np.nonzero(A ^ R)
    print(f"IoU {iou:.3f}  лишнее {extra / max(R.sum(), 1):.1%}  не хватает {miss / max(R.sum(), 1):.1%}"
          + ("  (без bounds.json — выравнивание по низу/центру)" if not org else ""))
    if len(xs) and org:
        L, T, s = org
        print(f"расхождения в координатах символа: x {L + xs.min() / s:.0f}..{L + xs.max() / s:.0f}, y {T + ys.min() / s:.0f}..{T + ys.max() / s:.0f}")
    k = max(1, round(500 / max(W, H)))
    out = out.resize((W * k, H * k), Image.NEAREST)
    p = out_path(a.out, "diff.png")
    out.save(p)
    print(p, out.size)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("screen"); s.add_argument("out", nargs="?"); s.add_argument("--full", action="store_true"); s.set_defaults(fn=screen)
    s = sp.add_parser("grid"); s.add_argument("png"); s.add_argument("out", nargs="?"); s.add_argument("--step", type=float, default=20); s.set_defaults(fn=grid)
    s = sp.add_parser("onion"); s.add_argument("pngs", nargs="+"); s.add_argument("-o", dest="out"); s.set_defaults(fn=onion)
    s = sp.add_parser("sheet"); s.add_argument("pngs", nargs="+"); s.add_argument("-o", dest="out"); s.add_argument("--cols", type=int, default=6); s.add_argument("--size", type=int, default=200); s.set_defaults(fn=sheet)
    s = sp.add_parser("zoom"); s.add_argument("png")
    for n in ("x0", "y0", "x1", "y1"):
        s.add_argument(n, type=float)
    s.add_argument("out", nargs="?"); s.add_argument("--k", type=int, default=4); s.set_defaults(fn=zoom)
    s = sp.add_parser("diff"); s.add_argument("png"); s.add_argument("ref"); s.add_argument("-o", dest="out"); s.add_argument("--thr", type=int, default=32); s.set_defaults(fn=diff)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
