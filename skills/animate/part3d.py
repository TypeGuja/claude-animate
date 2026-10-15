"""Поворот части рисунка «как кружку» (в глубину) по 3D-модели: поле сдвигов для xfl.py warp.

Модель — облако точек по частям (дамп из Blender: luna3d.py dump → model_<пони>.json:
{"ctr": [x,y,z], "parts": {"head": [[x,y,z],...], ...}}). Камера орто, вокруг вертикали,
угол DHX a → рыскание камеры yaw0 + a (как в turn3d).

python part3d.py field --model M.json --part head[,horn] --from A --to B --box l,t,r,b
                       [--inst a,b,c,d,tx,ty] [--grid 14] [--reg 0] [--damp 1] -o pts.json
    box — рамка рисунка части в координатах родителя (как left/top/width/height в JSFL: l,t,r,b);
    inst — матрица экземпляра, внутри которого гнём (точки переводятся в его локальные координаты);
    shape ellipsoid — гладкий поворот эллипсоида по рамке (для мультяшных голов: черты не рвутся), depth — глубина/ширина;
    damp — доля 3D-сдвига (1 = как у модели); общий сдвиг части вычитается (--keep-shift — оставить).
python part3d.py fit --pts pts.json --elements els.json -o out.json   — аффинное на каждую деталь (для команды Animate)
python part3d.py apply <file.fla> <symbol> --frame N --pts pts.json [--deep 2] [--bend] [--layer L ...] [-o out.fla]
    распаковать → xfl warp (--deep: вложенные символы гнутся внутри) → упаковать (по умолчанию поверх).
"""
import argparse
import json
import math
import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def project(P, ctr, yaw):
    """Мировые точки → камера (x вправо, y вверх, z к камере), метры."""
    y = math.radians(yaw)
    Q = P - ctr
    x = Q[:, 0] * -math.sin(y) + Q[:, 1] * math.cos(y)
    z = Q[:, 0] * math.cos(y) + Q[:, 1] * math.sin(y)
    return np.c_[x, Q[:, 2], z]


def visible(C, grid):
    """Индексы точек, видимых спереди: в каждой клетке сетки — ближайшая к камере."""
    x0, x1, y0, y1 = C[:, 0].min(), C[:, 0].max(), C[:, 1].min(), C[:, 1].max()
    gx = np.clip(((C[:, 0] - x0) / max(x1 - x0, 1e-9) * grid).astype(int), 0, grid - 1)
    gy = np.clip(((C[:, 1] - y0) / max(y1 - y0, 1e-9) * grid).astype(int), 0, grid - 1)
    best = {}
    for i, (a, b, z) in enumerate(zip(gx, gy, C[:, 2])):
        k = (a, b)
        if k not in best or z > C[best[k], 2]:
            best[k] = i
    return np.array(sorted(best.values()))


def field(a):
    if not a.model:  # без модели — только эллипсоид с заданной глубиной
        a.shape = "ellipsoid"; a.depth = a.depth or 0.9
        M = {"ctr": [0, 0, 0], "parts": {"box": [[-1, 0, -1], [1, 0, 1], [0, 1, 0], [0, -1, 0]]}}; a.part = "box"
    else:
        M = json.load(open(a.model, encoding="utf-8"))
    ctr = np.array(M["ctr"]); yaw0 = M.get("yaw0", 270)
    P = np.concatenate([np.array(M["parts"][p]) for p in a.part.split(",")])
    CA, CB = project(P, ctr, yaw0 + a.src_angle), project(P, ctr, yaw0 + a.dst_angle)
    idx = visible(CA, a.grid)
    l, t, r, b = map(float, a.box.split(","))
    x0, x1, y0, y1 = CA[:, 0].min(), CA[:, 0].max(), CA[:, 1].min(), CA[:, 1].max()
    s = (b - t) / (y1 - y0)
    cx3, cy3, cxb, cyb = (x0 + x1) / 2, (y0 + y1) / 2, (l + r) / 2, (t + b) / 2
    to_px = lambda C: np.c_[cxb + (C[:, 0] - cx3) * s, cyb - (C[:, 1] - cy3) * s]
    src = to_px(CA[idx]); dst = src + a.damp * (to_px(CB[idx]) - src)
    if a.shape == "ellipsoid":
        # Гладкий поворот: рисунок на эллипсоиде по рамке (глубина — пропорция 3D-части), вращение вокруг вертикали.
        # Без шума сетки модели (глаза/веки 3D не совпадают с мультяшными) — черты едут по поверхности, дальний край сжимается.
        k = a.depth or (CA[:, 2].max() - CA[:, 2].min()) / (x1 - x0)
        rx, ry = (r - l) / 2, (b - t) / 2
        u, v = np.meshgrid(np.linspace(-1, 1, a.grid), np.linspace(-1, 1, a.grid))
        u, v = u.ravel(), v.ravel(); inside = u * u + v * v <= 1.0
        u, v = u[inside], v[inside]
        # Без складок: в каждой строке точка на «долготе» th (u = sin th); поворот th' = th + k*dl*cos th —
        # монотонно (k*dl < 1), край силуэта (th = ±90°) неподвижен, ближняя сторона растягивается, дальняя сжимается.
        # Честный поворот эллипсоида заводит точки за силуэт → рисунок складывается, Animate выкидывает фигуру.
        rr = rx * np.sqrt(np.clip(1 - v * v, 0, 1))
        th = np.arcsin(np.clip(u / np.maximum(np.sqrt(np.clip(1 - v * v, 1e-9, 1)), 1e-9), -1, 1))
        dl = math.radians(a.dst_angle - a.src_angle)
        x, y = u * rx, v * ry
        x2 = rr * np.sin(th + min(0.9, k * abs(dl)) * math.copysign(1, dl) * np.cos(th))
        src = np.c_[cxb + x, cyb + y]; dst = np.c_[cxb + x + a.damp * (x2 - x), cyb + y]
        idx = np.arange(len(src))
    elif not a.keep_shift:  # общий сдвиг части (центр облака) делает сборка поворота — тут только деформация
        dst -= a.damp * (to_px(CB.mean(0, keepdims=True)) - to_px(CA.mean(0, keepdims=True)))
    if a.inst:  # в локальные координаты экземпляра
        m = list(map(float, a.inst.split(",")))
        A = np.array([[m[0], m[2]], [m[1], m[3]]]); Ai = np.linalg.inv(A); tt = np.array([m[4], m[5]])
        src, dst = (src - tt) @ Ai.T, (dst - tt) @ Ai.T
    d = np.linalg.norm(dst - src, axis=1)
    json.dump({"src": src.round(3).tolist(), "dst": dst.round(3).tolist(), "reg": a.reg}, open(a.out, "w"))
    print(f"{a.out}: точек {len(idx)} из {len(P)}, сдвиг ср {d.mean():.1f} макс {d.max():.1f} px, масштаб {s:.1f} px/м")


def apply(a):
    import xfl
    out = a.out or a.fla
    tmp = tempfile.mkdtemp(prefix="part3d_")
    try:
        d = os.path.join(tmp, "x")
        xfl.unpack(argparse.Namespace(fla=a.fla, dir=d))
        xfl.warp(argparse.Namespace(dir=d, symbol=a.symbol, frame=a.frame, pts=a.pts, layer=a.layer, no_instances=False, deep=a.deep, bend=a.bend))
        xfl.pack(argparse.Namespace(dir=d, fla=out))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def fit(a):
    """Для команды Animate: по полю (pts.json, в координатах символа) — аффинное преобразование каждой детали.
    elements.json: [{"id": ..., "box": [l, t, r, b]}] → out.json: {"id": [a, b, c, d, tx, ty]} (p' = L p + t)."""
    import xfl
    pts = json.load(open(a.pts, encoding="utf-8"))
    f = xfl.tps_fit(pts["src"], pts["dst"], pts.get("reg", 0.0))
    els = json.load(open(a.elements, encoding="utf-8-sig"))
    out = {}
    for e in els:
        l, t, r, b = e["box"]
        u, v = np.meshgrid(np.linspace(l, r, 5), np.linspace(t, b, 5))
        P = np.c_[u.ravel(), v.ravel()]
        edges = [{"path": [["M", *P[0]]] + [["L", *q] for q in P[1:]]}]
        _, A = xfl.warp_shape(edges, f)  # то же регуляризованное аффинное приближение, что и в warp
        if A is None:
            continue
        out[str(e["id"])] = [float(A[0, 0]), float(A[1, 0]), float(A[0, 1]), float(A[1, 1]), float(A[2, 0]), float(A[2, 1])]  # строки L: x' = a0 x + a1 y + a4
    json.dump(out, open(a.out, "w"))
    print(f"{a.out}: деталей {len(out)}")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("field")
    s.add_argument("--model"); s.add_argument("--part", default="head")
    s.add_argument("--from", dest="src_angle", type=float, required=True); s.add_argument("--to", dest="dst_angle", type=float, required=True)
    s.add_argument("--box", required=True); s.add_argument("--inst"); s.add_argument("--grid", type=int, default=14)
    s.add_argument("--reg", type=float, default=0.0); s.add_argument("--damp", type=float, default=1.0)
    s.add_argument("--keep-shift", action="store_true", help="оставить общий сдвиг части (по умолчанию вычитается)")
    s.add_argument("--shape", choices=["mesh", "ellipsoid"], default="mesh", help="mesh — точки модели; ellipsoid — гладкий эллипсоид по рамке")
    s.add_argument("--depth", type=float, default=0.0, help="ellipsoid: глубина/ширина (0 — из модели)")
    s.add_argument("-o", dest="out", required=True); s.set_defaults(fn=field)
    s = sp.add_parser("fit")
    s.add_argument("--pts", required=True); s.add_argument("--elements", required=True); s.add_argument("-o", dest="out", required=True)
    s.set_defaults(fn=fit)
    s = sp.add_parser("apply")
    s.add_argument("fla"); s.add_argument("symbol"); s.add_argument("--frame", type=int, required=True)
    s.add_argument("--pts", required=True); s.add_argument("--deep", type=int, default=2)
    s.add_argument("--layer", action="append"); s.add_argument("-o", dest="out"); s.add_argument("--bend", action="store_true")
    s.set_defaults(fn=apply)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
