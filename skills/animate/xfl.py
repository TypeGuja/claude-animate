"""Геометрия .fla без Animate: XFL-XML напрямую (точно и без крашей JSFL-API вершин).

python xfl.py unpack <file.fla> <dir>
python xfl.py pack <dir> <file.fla>                       — mimetype первым, без сжатия
python xfl.py symbols <dir> [filter]                      — символы библиотеки → файл XML
python xfl.py layers <dir> <symbol> [--frame N]           — слои, ключи, элементы кадра
python xfl.py compare <dir> <symbol> F1,F2,...         — таблица слой × кадр: символ:firstFrame (что меняется между ракурсами)
python xfl.py export <dir> <symbol> --frame N [--layer L ...] [-o shapes.json]
python xfl.py import <dir> <shapes.json>                  — записать изменённые/новые фигуры обратно
python xfl.py warp <dir> <symbol> --frame N --pts pts.json [--layer L ...] [--no-instances] [--deep 2] [--bend]

Координаты везде в пикселях символа (XFL хранит twips = px*20).
shapes.json: {"symbol", "shapes": [{"sid", "layer", "frame", "fills": [...], "strokes": [...],
  "edges": [{"fill0", "fill1", "stroke", "path": [["M",x,y],["L",x,y],["Q",cx,cy,x,y], ...]}]}]}
  fills/strokes: {"index", "color", "alpha"} или {"index", "xml"} (сырой стиль, например градиент).
  sid — номер DOMShape в файле символа. Новая фигура: "sid": null + "layer" + "frame" (кадр должен быть ключом).
pts.json: {"src": [[x,y],...], "dst": [[x,y],...]} — опорные точки; между ними тонкая пластина (TPS).
Fla должна быть CC/XFL (zip). Бинарный CS4 сначала пересохранить в Animate.
"""
import argparse
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

NS = "{http://ns.adobe.com/xfl/2008/}"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
SEVENZIP = next((p for p in ("C:/Program Files/7-Zip/7z.exe", "C:/Program Files (x86)/7-Zip/7z.exe") if os.path.isfile(p)), None)


# ---------- zip ----------

def unpack(a):
    if os.path.isdir(a.dir):
        shutil.rmtree(a.dir)
    os.makedirs(a.dir)
    if SEVENZIP:  # zipfile отвергает часть .fla из Animate
        # 7-Zip на части .fla пишет "Headers Error" (код 2), но всё распаковывает — проверяем по результату
        r = subprocess.run([SEVENZIP, "x", "-y", a.fla, "-o" + a.dir], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if not os.path.exists(os.path.join(a.dir, "DOMDocument.xml")):
            sys.exit(f"7z не распаковал {a.fla}: {r.stderr.strip()}")
        if r.returncode:
            print("7z предупреждение:", r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.returncode)
    else:
        zipfile.ZipFile(a.fla).extractall(a.dir)
    print(a.dir)


def pack(a):
    tmp = a.fla + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    with zipfile.ZipFile(tmp, "w") as z:
        mt = os.path.join(a.dir, "mimetype")
        if os.path.exists(mt):
            z.write(mt, "mimetype", zipfile.ZIP_STORED)
        for root, _, files in os.walk(a.dir):
            for f in files:
                p = os.path.join(root, f)
                rel = os.path.relpath(p, a.dir).replace("\\", "/")
                if rel != "mimetype":
                    z.write(p, rel, zipfile.ZIP_DEFLATED)
    import time
    for k in range(60):  # Animate держит только что закрытый .fla ещё несколько секунд
        try:
            os.replace(tmp, a.fla)
            break
        except PermissionError:
            if k == 59:
                raise
            time.sleep(0.5)
    print(a.fla, os.path.getsize(a.fla))


# ---------- библиотека ----------

def library(d):
    """{имя символа: путь к XML}"""
    r = {}
    for p in glob.glob(os.path.join(d, "LIBRARY", "**", "*.xml"), recursive=True):
        with open(p, encoding="utf-8") as f:
            head = f.read(2000)
        m = re.search(r'<DOMSymbolItem\b[^>]*?\bname="([^"]*)"', head)
        if m:
            r[unesc(m.group(1))] = p
    return r


def unesc(s):
    return s.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&apos;", "'").replace("&amp;", "&")


def sym_file(d, name):
    lib = library(d)
    if name in lib:
        return lib[name]
    hits = [k for k in lib if k.split("/")[-1] == name]
    if len(hits) == 1:
        return lib[hits[0]]
    sys.exit(f"нет символа {name!r}" + (f" (несколько: {hits})" if hits else ""))


def symbols(a):
    for k, p in sorted(library(a.dir).items()):
        if not a.filter or a.filter.lower() in k.lower():
            print(k, "→", os.path.relpath(p, a.dir))


# ---------- разбор структуры ----------

def walk_frames(root):
    """(слой, тип слоя, DOMFrame) по всем слоям таймлайна символа."""
    for lay in root.iter(NS + "DOMLayer"):
        fr = lay.find(NS + "frames")
        if fr is None:
            continue
        for f in fr.findall(NS + "DOMFrame"):
            yield lay.get("name"), lay.get("layerType", "normal"), f


def frame_covers(f, n):
    i = int(f.get("index", 0))
    return i <= n < i + int(f.get("duration", 1))


def element_index(root, tag):
    return {id(e): k for k, e in enumerate(root.iter(NS + tag))}


def pick(root, frame, layers):
    """Фигуры и экземпляры символов кадра: [(слой, DOMFrame, тег, элемент)]."""
    out = []
    for ln, lt, f in walk_frames(root):
        if layers and ln not in layers:
            continue
        if not frame_covers(f, frame):
            continue
        for tag in ("DOMShape", "DOMSymbolInstance"):
            for e in f.iter(NS + tag):
                out.append((ln, f, tag, e))
    return out


def layers_cmd(a):
    root = ET.parse(sym_file(a.dir, a.symbol)).getroot()
    for ln, lt, f in walk_frames(root):
        if a.frame is not None and not frame_covers(f, a.frame):
            continue
        sh = len(list(f.iter(NS + "DOMShape")))
        inst = [e.get("libraryItemName") + (":" + e.get("firstFrame") if e.get("firstFrame") else "") for e in f.iter(NS + "DOMSymbolInstance")]
        lab = f.get("name")
        print(f"{ln!r:28} {lt:7} кадр {f.get('index', '0'):>4}+{f.get('duration', '1'):<3}"
              + (f" [{lab}]" if lab else "") + (f" фигур {sh}" if sh else "") + (f" {inst}" if inst else ""))


def compare(a):
    root = ET.parse(sym_file(a.dir, a.symbol)).getroot()
    fs = [int(x) for x in a.frames.split(",")]
    rows = []
    for lay in root.iter(NS + "DOMLayer"):
        if lay.get("layerType") in ("guide", "folder"):
            continue
        cells = [""] * len(fs)
        box = lay.find(NS + "frames")
        for f in (box if box is not None else []):
            for k, n in enumerate(fs):
                if frame_covers(f, n):
                    cell = [e.get("libraryItemName").split("/")[-1] + ":" + e.get("firstFrame", "0") for e in f.iter(NS + "DOMSymbolInstance")]
                    sh = len(list(f.iter(NS + "DOMShape")))
                    cells[k] = " ".join(cell + ([f"фигур {sh}"] if sh else []))
        if any(cells):
            rows.append((lay.get("name") or "?", cells))
    w = max([len(r[0]) for r in rows] + [5])
    cw = max([len(c) for _, cs in rows for c in cs] + [6])
    print(" " * w + " | " + " | ".join(f"{n:>{cw}}" for n in fs))
    for ln, cells in rows:
        print(f"{ln:<{w}} | " + " | ".join(f"{c:>{cw}}" for c in cells))


# ---------- формат рёбер ----------

TOK = re.compile(r"[!|/\[\]]|(?<!S)-?\d+(?:\.\d+)?|#[A-Z0-9]+\.[A-Z0-9]+")


def num(t):
    if t[0] == "#":
        a, b = t[1:].split(".")
        v = int.from_bytes(bytes.fromhex("{:>06}{:<02}".format(a, b)), "big", signed=True)
        return v / 256 / 20
    return float(t) / 20


def parse_edges(s):
    tk = TOK.findall(s)
    i, out = 0, []
    while i < len(tk):
        c = tk[i]
        if c == "!":
            out.append(["M", num(tk[i + 1]), num(tk[i + 2])]); i += 3
        elif c in "|/":
            out.append(["L", num(tk[i + 1]), num(tk[i + 2])]); i += 3
        elif c in "[]":
            out.append(["Q", num(tk[i + 1]), num(tk[i + 2]), num(tk[i + 3]), num(tk[i + 4])]); i += 5
        else:
            i += 1
    return out


def tw(v):
    s = f"{v * 20:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def fmt_edges(path):
    r = []
    for c in path:
        if c[0] == "M":
            r.append(f"!{tw(c[1])} {tw(c[2])}")
        elif c[0] == "L":
            r.append(f"|{tw(c[1])} {tw(c[2])}")
        elif c[0] == "Q":
            r.append(f"[{tw(c[1])} {tw(c[2])} {tw(c[3])} {tw(c[4])}")
    return "".join(r)


# ---------- export / import ----------

def style_list(shape, kind):
    out = []
    box = shape.find(NS + kind)
    if box is None:
        return out
    for st in box:
        d = {"index": int(st.get("index"))}
        inner = list(st)
        sc = st.find(".//" + NS + "SolidColor")
        if kind == "fills" and len(inner) == 1 and inner[0].tag == NS + "SolidColor":
            d["color"] = sc.get("color", "#000000")
            if sc.get("alpha"):
                d["alpha"] = float(sc.get("alpha"))
        else:
            if sc is not None:
                d["color"] = sc.get("color", "#000000")  # подсказка; записывается xml
            sk = st.find(".//" + NS + "SolidStroke")
            if sk is not None and sk.get("weight"):
                d["weight"] = float(sk.get("weight"))
            d["xml"] = re.sub(r'\s+xmlns(:\w+)?="[^"]*"', "", ET.tostring(st, encoding="unicode").replace("ns0:", ""))
        out.append(d)
    return out


def shape_json(e, sid, layer, frame):
    d = {"sid": sid, "layer": layer, "frame": int(frame.get("index", 0)),
         "fills": style_list(e, "fills"), "strokes": style_list(e, "strokes"), "edges": []}
    if e.find(NS + "matrix") is not None:
        d["warning"] = "у фигуры своя матрица: координаты локальные"
    box = e.find(NS + "edges")
    for ed in (box if box is not None else []):
        if not ed.get("edges"):
            continue
        d["edges"].append({"fill0": int(ed.get("fillStyle0")) if ed.get("fillStyle0") else None,
                           "fill1": int(ed.get("fillStyle1")) if ed.get("fillStyle1") else None,
                           "stroke": int(ed.get("strokeStyle")) if ed.get("strokeStyle") else None,
                           "path": [[c[0]] + [round(v, 3) for v in c[1:]] for c in parse_edges(ed.get("edges"))]})
    return d


def export(a):
    p = sym_file(a.dir, a.symbol)
    root = ET.parse(p).getroot()
    idx = element_index(root, "DOMShape")
    shapes = [shape_json(e, idx[id(e)], ln, f) for ln, f, tag, e in pick(root, a.frame, a.layer) if tag == "DOMShape"]
    out = {"symbol": a.symbol, "frame": a.frame, "shapes": shapes}
    s = json.dumps(out, ensure_ascii=False)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(s)
        n = sum(len(x["edges"]) for x in shapes)
        print(a.out, f"фигур {len(shapes)}, рёбер {n}")
    else:
        print(s)


def style_xml(kind, st):
    if "xml" in st:
        return re.sub(r'\bindex="\d+"', f'index="{st["index"]}"', st["xml"], count=1)
    al = f' alpha="{st["alpha"]}"' if st.get("alpha") is not None else ""
    if kind == "fills":
        return f'<FillStyle index="{st["index"]}"><SolidColor color="{st["color"]}"{al}/></FillStyle>'
    return (f'<StrokeStyle index="{st["index"]}"><SolidStroke scaleMode="normal" weight="{st.get("weight", 1)}">'
            f'<fill><SolidColor color="{st["color"]}"{al}/></fill></SolidStroke></StrokeStyle>')


def shape_inner(sh):
    r = []
    if sh.get("fills"):
        r.append("<fills>" + "".join(style_xml("fills", s) for s in sh["fills"]) + "</fills>")
    if sh.get("strokes"):
        r.append("<strokes>" + "".join(style_xml("strokes", s) for s in sh["strokes"]) + "</strokes>")
    eds = []
    for e in sh["edges"]:
        at = "".join(f' {k}="{e[j]}"' for j, k in (("fill0", "fillStyle0"), ("fill1", "fillStyle1"), ("stroke", "strokeStyle")) if e.get(j) is not None)
        eds.append(f'<Edge{at} edges="{fmt_edges(e["path"])}"/>')
    r.append("<edges>" + "".join(eds) + "</edges>")
    return "".join(r)


SHAPE_RE = re.compile(r"<DOMShape\b[^>]*?/>|<DOMShape\b.*?</DOMShape>", re.S)
INST_RE = re.compile(r"<DOMSymbolInstance\b[^>]*?/>|<DOMSymbolInstance\b.*?</DOMSymbolInstance>", re.S)


def replace_shape(block, sh):
    m = re.match(r"<DOMShape\b[^>]*?>", block)
    head = m.group(0)
    if head.endswith("/>"):
        head = head[:-2].rstrip() + ">"
    body = block[len(m.group(0)):]
    keep = re.sub(r"<(fills|strokes|edges)\b.*?</\1>|<(fills|strokes|edges)\b[^>]*/>", "", body, flags=re.S)
    keep = keep.replace("</DOMShape>", "")
    return head + keep.strip() + shape_inner(sh) + "</DOMShape>"


def import_(a):
    js = json.load(open(a.json, encoding="utf-8"))
    p = sym_file(a.dir, js["symbol"])
    txt = open(p, encoding="utf-8").read()
    blocks = [(m.start(), m.end()) for m in SHAPE_RE.finditer(txt)]
    edits, new = {}, []
    for sh in js["shapes"]:
        if sh.get("sid") is None:
            new.append(sh)
        else:
            edits[sh["sid"]] = sh
    out, pos = [], 0
    for k, (s, e) in enumerate(blocks):
        if k in edits:
            out.append(txt[pos:s]); out.append(replace_shape(txt[s:e], edits[k])); pos = e
    out.append(txt[pos:])
    txt = "".join(out)
    for sh in new:
        txt = insert_shape(txt, sh)
    open(p, "w", encoding="utf-8").write(txt)
    print(p, f"заменено {len(edits)}, добавлено {len(new)}")


def insert_shape(txt, sh):
    """Новая фигура в ключевой кадр sh["frame"] слоя sh["layer"]."""
    lm = re.search(r'<DOMLayer\b[^>]*\bname="%s"' % re.escape(sh["layer"]), txt)
    if not lm:
        sys.exit(f"нет слоя {sh['layer']!r}")
    end = txt.find("</DOMLayer>", lm.end())
    fm = None
    for m in re.finditer(r"<DOMFrame\b[^>]*>", txt[lm.end():end]):
        im = re.search(r'\bindex="(\d+)"', m.group(0))
        if int(im.group(1) if im else 0) == sh["frame"]:
            fm = m
            break
    if not fm:
        sys.exit(f"кадр {sh['frame']} слоя {sh['layer']!r} не ключевой")
    s = lm.end() + fm.end()
    shape = "<DOMShape>" + shape_inner(sh) + "</DOMShape>"
    if fm.group(0).endswith("/>"):
        sys.exit("пустой самозакрытый DOMFrame — сначала создай ключ в Animate")
    el = txt.find("<elements", s)
    fe = txt.find("</DOMFrame>", s)
    if el < 0 or el > fe:
        return txt[:s] + "<elements>" + shape + "</elements>" + txt[s:]
    if txt[el:txt.find(">", el) + 1].endswith("/>"):
        tag_end = txt.find(">", el) + 1
        return txt[:el] + "<elements>" + shape + "</elements>" + txt[tag_end:]
    tag_end = txt.find(">", el) + 1
    return txt[:tag_end] + shape + txt[tag_end:]


# ---------- TPS warp ----------

def tps_fit(src, dst, reg=0.0):
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    n = len(src)
    if n < 3:
        off = (dst - src).mean(0)
        return lambda P: np.asarray(P, float) + off

    def U(r2):
        with np.errstate(divide="ignore", invalid="ignore"):
            v = r2 * np.log(r2)
        return np.nan_to_num(v)

    K = U(((src[:, None] - src[None]) ** 2).sum(-1)) + reg * np.eye(n)
    P = np.hstack([np.ones((n, 1)), src])
    A = np.zeros((n + 3, n + 3)); A[:n, :n] = K; A[:n, n:] = P; A[n:, :n] = P.T
    b = np.zeros((n + 3, 2)); b[:n] = dst
    w = np.linalg.lstsq(A, b, rcond=None)[0]

    def f(Q):
        Q = np.atleast_2d(np.asarray(Q, float))
        k = U(((Q[:, None] - src[None]) ** 2).sum(-1))
        return k @ w[:n] + np.hstack([np.ones((len(Q), 1)), Q]) @ w[n:]
    return f


def warp_path(path, f):
    pts = []
    for c in path:
        pts += [c[i:i + 2] for i in range(1, len(c), 2)]
    if not pts:
        return path
    q = f(np.array(pts))
    out, k = [], 0
    for c in path:
        m = (len(c) - 1) // 2
        out.append([c[0]] + [round(float(v), 3) for v in q[k:k + m].ravel()])
        k += m
    return out


def _warp_shape_tps(edges, f):
    """Изогнуть все рёбра фигуры разом. Концы рёбер, совпадающие до 0.1 твипа (DHX пишет одну точку то hex,
    то десятичной — значения расходятся на тысячные), получают ОДНУ координату: иначе после округления
    контур размыкается и Animate не заливает фигуру (при сдвиге/масштабе везёт, при изгибе — нет)."""
    # Кривые бьются на куски (≈4 px), у куска контрольная точка подбирается так, чтобы изогнутая кривая шла
    # через изогнутую середину: иначе тонкие полосы (каёмки, нарисованные заливкой между двумя кривыми)
    # при нелинейном изгибе перехлёстываются, а пересекающиеся рёбра Animate выкидывает вместе с фигурой.
    key = lambda x, y: (round(x * 200), round(y * 200))
    ends, segs = {}, []          # segs: (тип, P0, P1-контроль|None, P2) в исходных координатах
    for e in edges:
        cur, ss = None, []
        for c in e["path"]:
            if c[0] == "M":
                cur = (c[1], c[2]); ends.setdefault(key(*cur), cur); ss.append(("M", None, None, cur))
            elif c[0] == "L":
                p2 = (c[1], c[2]); ends.setdefault(key(*p2), p2); ss.append(("L", cur, None, p2)); cur = p2
            else:
                p1, p2 = (c[1], c[2]), (c[3], c[4]); ends.setdefault(key(*p2), p2)
                n = int(min(16, max(1, math.ceil((math.dist(cur, p1) + math.dist(p1, p2)) / 4.0))))
                for i in range(n):  # де Кастельжо: кусок [t0, t1]
                    t0, t1 = i / n, (i + 1) / n
                    B = lambda t: ((1 - t) ** 2 * cur[0] + 2 * t * (1 - t) * p1[0] + t * t * p2[0], (1 - t) ** 2 * cur[1] + 2 * t * (1 - t) * p1[1] + t * t * p2[1])
                    ss.append(("Q", B(t0) if i else cur, B((t0 + t1) / 2), B(t1) if i < n - 1 else p2))
                cur = p2
        segs.append(ss)
    ek = list(ends)
    mids = [s[2] for ss in segs for s in ss if s[0] == "Q"]
    inner = [s[1] for ss in segs for s in ss if s[0] == "Q"] + [s[3] for ss in segs for s in ss if s[0] == "Q"]
    pts = [ends[k] for k in ek] + mids + inner
    q = f(np.array(pts)) if pts else []
    em = {k: (float(q[i][0]), float(q[i][1])) for i, k in enumerate(ek)}
    nm, nq = len(mids), len(ek)
    qm, qa, qb = q[nq:nq + nm], q[nq + nm:nq + 2 * nm], q[nq + 2 * nm:]
    r3 = lambda p: (round(float(p[0]), 3), round(float(p[1]), 3))
    j = 0
    for e, ss in zip(edges, segs):
        out = []
        for t, p0, pm, p2 in ss:
            if t == "M":
                out.append(["M", *r3(em[key(*p2)])])
            elif t == "L":
                out.append(["L", *r3(em[key(*p2)])])
            else:
                a = em[key(*p0)] if key(*p0) in em else qa[j]
                b = em[key(*p2)] if key(*p2) in em else qb[j]
                c = (2 * qm[j][0] - (a[0] + b[0]) / 2, 2 * qm[j][1] - (a[1] + b[1]) / 2)  # кривая через f(середины)
                out.append(["Q", *r3(c), *r3(b)]); j += 1
        e["path"] = out



def _polyline(path, k=6):
    """Рёбра → отрезки (кривые по k точек): [(x0,y0,x1,y1), ...]."""
    segs, cur = [], None
    for c in path:
        if c[0] == "M":
            cur = (c[1], c[2])
        elif c[0] == "L":
            segs.append((*cur, c[1], c[2])); cur = (c[1], c[2])
        else:
            p1, p2 = (c[1], c[2]), (c[3], c[4]); prev = cur
            for i in range(1, k + 1):
                t = i / k
                q = ((1 - t) ** 2 * cur[0] + 2 * t * (1 - t) * p1[0] + t * t * p2[0], (1 - t) ** 2 * cur[1] + 2 * t * (1 - t) * p1[1] + t * t * p2[1])
                segs.append((*prev, *q)); prev = q
            cur = p2
    return segs


def _crosses(edges):
    """Есть ли собственные пересечения рёбер фигуры (кроме касаний в общих концах)."""
    S = np.array([sg for e in edges for sg in _polyline(e["path"])], float)
    if len(S) < 2:
        return False
    a, b = S[:, None, :2], S[:, None, 2:]
    c, d = S[None, :, :2], S[None, :, 2:]
    cr = lambda u, v, w: (v[..., 0] - u[..., 0]) * (w[..., 1] - u[..., 1]) - (v[..., 1] - u[..., 1]) * (w[..., 0] - u[..., 0])
    d1, d2, d3, d4 = cr(c, d, a), cr(c, d, b), cr(a, b, c), cr(a, b, d)
    hit = (d1 * d2 < -1e-9) & (d3 * d4 < -1e-9)
    np.fill_diagonal(hit, False)
    return bool(hit.any())


BEND = [False]  # True (--bend): гнуть фигуры внутри по полю; иначе — каждая фигура своим аффинным приближением


def warp_shape(edges, f):
    """--bend: изогнуть фигуру по полю; если контур от этого пересекает сам себя (тонкие каёмки, острые кончики) —
    взять лучшее аффинное приближение поля на этой фигуре: оно контур не ломает никогда.
    Без --bend — сразу аффинно (надёжно: Animate выкидывает фигуры с самопересечениями, а тонкие каёмки DHX
    при изгибе внутри иногда отбрасываются даже без найденных пересечений)."""
    import copy
    orig = copy.deepcopy(edges)
    P = np.array([v for e in orig for c in e["path"] for v in zip(c[1::2], c[2::2])], float)
    if not len(P):
        return "empty", None
    Q = f(P)
    # аффинное приближение поля на фигуре: A = I + D, D с регуляризацией к нулю (для почти линейных фигур —
    # ресницы, штрихи — чистый МНК даёт вырожденное/зеркальное сжатие поперёк, и Animate выкидывает фигуру)
    c0 = P.mean(0); Pc = P - c0
    lam = 0.05 * len(P) * max(float((Pc ** 2).sum(1).mean()), 1e-6)
    X = np.c_[Pc, np.ones(len(P))]
    Xa = np.r_[X, np.sqrt(lam) * np.array([[1.0, 0, 0], [0, 1.0, 0]])]
    Ya = np.r_[Q - P, np.zeros((2, 2))]
    D = np.linalg.lstsq(Xa, Ya, rcond=None)[0]
    L = np.eye(2) + D[:2]
    if np.linalg.det(L) < 0.3:  # всё равно вырождается — только сдвиг
        L = np.eye(2)
    t = c0 + D[2] - c0 @ L
    A = np.r_[L, t[None, :]]  # 3x2: [x y 1] @ A — для рёбер и матриц градиентов
    if BEND[0]:
        _warp_shape_tps(edges, f)
        if not _crosses(edges) or _crosses(orig):
            return "tps", A
    for e, o in zip(edges, orig):
        e["path"] = [[c[0]] + [round(float(v), 3) for xy in zip(c[1::2], c[2::2]) for v in (np.array([*xy, 1.0]) @ A)] for c in o["path"]]
    return "affine", A


def warp_styles(styles, A):
    """Матрицы градиентов/растровых заливок (в координатах фигуры) — тем же аффинным преобразованием."""
    if A is None:
        return
    L = np.array([[A[0, 0], A[1, 0]], [A[0, 1], A[1, 1]]]); t = A[2]
    for st in styles:
        if "xml" not in st or "<Matrix" not in st["xml"]:
            continue
        def fix(m):
            a, b, c, d, tx, ty = mat_get(m.group(0))
            N = L @ np.array([[a, c], [b, d]]); tt = L @ np.array([tx, ty]) + t
            return mat_tag([N[0, 0], N[1, 0], N[0, 1], N[1, 1], tt[0], tt[1]])
        st["xml"] = MAT_RE.sub(fix, st["xml"])

MAT_RE = re.compile(r"<Matrix\b[^>]*/>")


def mat_get(tag):
    g = lambda k, d: float(re.search(rf'\b{k}="([-\d.e]+)"', tag).group(1)) if re.search(rf'\b{k}="', tag) else d
    return [g("a", 1), g("b", 0), g("c", 0), g("d", 1), g("tx", 0), g("ty", 0)]


def mat_tag(m):
    return '<Matrix a="%.6f" b="%.6f" c="%.6f" d="%.6f" tx="%.3f" ty="%.3f"/>' % tuple(m)


def warp_instance(block, f):
    mm = MAT_RE.search(block)
    m = mat_get(mm.group(0)) if mm else [1, 0, 0, 1, 0, 0]
    tp = re.search(r'<transformationPoint>\s*<Point\b([^>]*)/>', block)
    px = py = 0.0
    if tp:
        g = lambda k: float(re.search(rf'\b{k}="([-\d.e]+)"', tp.group(1)).group(1)) if re.search(rf'\b{k}="', tp.group(1)) else 0.0
        px, py = g("x"), g("y")
    cx, cy = m[0] * px + m[2] * py + m[4], m[1] * px + m[3] * py + m[5]
    h = 2.0
    c0, cxp, cyp = f([[cx, cy], [cx + h, cy], [cx, cy + h]])
    J = np.array([[(cxp - c0)[0] / h, (cyp - c0)[0] / h], [(cxp - c0)[1] / h, (cyp - c0)[1] / h]])
    L = J @ np.array([[m[0], m[2]], [m[1], m[3]]])
    a, c, b, d = L[0, 0], L[0, 1], L[1, 0], L[1, 1]
    tx, ty = c0[0] - (a * px + c * py), c0[1] - (b * px + d * py)
    new = mat_tag([a, b, c, d, tx, ty])
    if mm:
        return block[:mm.start()] + new + block[mm.end():]
    head = re.match(r"<DOMSymbolInstance\b[^>]*?>", block).group(0)
    if head.endswith("/>"):
        return head[:-2].rstrip() + "><matrix>" + new + "</matrix></DOMSymbolInstance>"
    return head + "<matrix>" + new + "</matrix>" + block[len(head):]



# ---------- глубокий изгиб: вложенные символы гнутся внутри (копия символа на экземпляр) ----------

def _lib_dir(d):
    return os.path.join(d, "LIBRARY")


def dup_symbol(d, name, tag):
    """Копия символа name под именем name__tag (файл рядом, Include в DOMDocument). → (имя, путь)."""
    lib = library(d)
    src = lib.get(name) or sym_file(d, name)
    new = name + "__" + tag
    if new in lib:
        sys.exit(f"копия {new!r} уже есть")
    txt = open(src, encoding="utf-8").read()
    iid = "%08x-%08x" % (int.from_bytes(os.urandom(4), "big"), int.from_bytes(os.urandom(4), "big"))
    head = re.search(r"<DOMSymbolItem\b[^>]*>", txt).group(0)
    nh = re.sub(r'\bname="([^"]*)"', lambda m: 'name="%s__%s"' % (m.group(1), tag), head, count=1)
    nh = re.sub(r'\bitemID="[^"]*"', 'itemID="%s"' % iid, nh, count=1)
    txt = txt.replace(head, nh, 1)
    dst = os.path.join(os.path.dirname(src), os.path.basename(src)[:-4] + "__" + tag + ".xml")
    open(dst, "w", encoding="utf-8").write(txt)
    href = os.path.relpath(dst, _lib_dir(d)).replace("\\", "/")
    shref = os.path.relpath(src, _lib_dir(d)).replace("\\", "/")
    dp = os.path.join(d, "DOMDocument.xml")
    doc = open(dp, encoding="utf-8").read()
    m = re.search(r'<Include href="%s"[^>]*/>' % re.escape(shref.replace("&", "&amp;")), doc) or re.search(r'<Include href="%s"[^>]*/>' % re.escape(shref), doc)
    inc = '<Include href="%s" itemIcon="1" loadImmediate="false" itemID="%s"/>' % (href.replace("&", "&amp;"), iid)
    nl = chr(10)
    doc = doc[:m.end()] + nl + "          " + inc + doc[m.end():] if m else doc.replace("</symbols>", "     " + inc + nl + "     </symbols>", 1)
    open(dp, "w", encoding="utf-8").write(doc)
    return new, dst


def _compose_inner(f, m):
    """Поле в координатах символа: M^-1 ∘ f ∘ M (M — матрица экземпляра: локальные → родитель)."""
    A = np.array([[m[0], m[2]], [m[1], m[3]]]); t = np.array([m[4], m[5]])
    Ai = np.linalg.inv(A)
    def g(Q):
        Q = np.atleast_2d(np.asarray(Q, float))
        return (f(Q @ A.T + t) - t) @ Ai.T
    return g


_DEEP_N = [0]
_DEEP_RUN = "%04x" % int.from_bytes(os.urandom(2), "big")  # свой префикс копий на запуск — имена не пересекаются


def warp_text(d, txt, f, depth, only=None):
    """Изогнуть фигуры и экземпляры в тексте символа. only=(множество sid, множество iid) или None — всё.
    depth>0: экземпляр → копия его символа, изогнутая внутри (рекурсивно); иначе — аффинно по якобиану."""
    root = ET.fromstring(txt)
    shapes = {}
    for k, e in enumerate(root.iter(NS + "DOMShape")):
        if only is None or k in only[0]:
            shapes[k] = shape_json(e, k, None, ET.Element("f"))
            mx = e.find(NS + "matrix/" + NS + "Matrix")  # фигура со своей матрицей — координаты локальные
            fs = _compose_inner(f, [float(mx.get(q, dv)) for q, dv in (("a", 1), ("b", 0), ("c", 0), ("d", 1), ("tx", 0), ("ty", 0))]) if mx is not None else f
            _, A = warp_shape(shapes[k]["edges"], fs)
            warp_styles(shapes[k]["fills"] + shapes[k]["strokes"], A)
    def inst(b, k):
        if depth <= 0:
            return warp_instance(b, f)
        nm = unesc(re.search(r'libraryItemName="([^"]*)"', b).group(1))
        mm = MAT_RE.search(b)
        m = mat_get(mm.group(0)) if mm else [1, 0, 0, 1, 0, 0]
        if abs(m[0] * m[3] - m[1] * m[2]) < 1e-9:
            return b
        _DEEP_N[0] += 1
        new, path = dup_symbol(d, nm, "w%s_%d" % (_DEEP_RUN, _DEEP_N[0]))
        inner = open(path, encoding="utf-8").read()
        open(path, "w", encoding="utf-8").write(warp_text(d, inner, _compose_inner(f, m), depth - 1))
        return re.sub(r'libraryItemName="[^"]*"', 'libraryItemName="%s"' % new.replace("&", "&amp;").replace('"', "&quot;"), b, count=1)
    for rx, todo, fn in ((SHAPE_RE, shapes, lambda b, k: replace_shape(b, shapes[k])),
                         (INST_RE, None, inst)):
        out, pos = [], 0
        for k, m in enumerate(rx.finditer(txt)):
            take = (k in todo) if todo is not None else (only is None or k in only[1])
            if take:
                out.append(txt[pos:m.start()]); out.append(fn(m.group(0), k)); pos = m.end()
        out.append(txt[pos:])
        txt = "".join(out)
    return txt


def warp(a):
    pts = json.load(open(a.pts, encoding="utf-8"))
    f = tps_fit(pts["src"], pts["dst"], pts.get("reg", 0.0))
    p = sym_file(a.dir, a.symbol)
    root = ET.parse(p).getroot()
    sidx, iidx = element_index(root, "DOMShape"), element_index(root, "DOMSymbolInstance")
    sel = pick(root, a.frame, a.layer)
    shapes = {sidx[id(e)]: shape_json(e, sidx[id(e)], ln, fr) for ln, fr, t, e in sel if t == "DOMShape"}
    insts = set() if a.no_instances else {iidx[id(e)] for ln, fr, t, e in sel if t == "DOMSymbolInstance"}
    # --deep N: вложенные символы гнутся внутри (копии); 0 — экземпляры аффинно. Сам символ — только выбранный кадр.
    BEND[0] = bool(getattr(a, "bend", False))
    txt = warp_text(a.dir, open(p, encoding="utf-8").read(), f, a.deep, (set(shapes), insts))
    open(p, "w", encoding="utf-8").write(txt)
    print(p, f"фигур {len(shapes)}, экземпляров {len(insts)}" + (f", копий символов {_DEEP_N[0]}" if a.deep else ""))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("unpack"); s.add_argument("fla"); s.add_argument("dir"); s.set_defaults(fn=unpack)
    s = sp.add_parser("pack"); s.add_argument("dir"); s.add_argument("fla"); s.set_defaults(fn=pack)
    s = sp.add_parser("symbols"); s.add_argument("dir"); s.add_argument("filter", nargs="?"); s.set_defaults(fn=symbols)
    s = sp.add_parser("layers"); s.add_argument("dir"); s.add_argument("symbol"); s.add_argument("--frame", type=int); s.set_defaults(fn=layers_cmd)
    s = sp.add_parser("compare"); s.add_argument("dir"); s.add_argument("symbol"); s.add_argument("frames"); s.set_defaults(fn=compare)
    s = sp.add_parser("export"); s.add_argument("dir"); s.add_argument("symbol"); s.add_argument("--frame", type=int, required=True)
    s.add_argument("--layer", action="append"); s.add_argument("-o", dest="out"); s.set_defaults(fn=export)
    s = sp.add_parser("import"); s.add_argument("dir"); s.add_argument("json"); s.set_defaults(fn=import_)
    s = sp.add_parser("warp"); s.add_argument("dir"); s.add_argument("symbol"); s.add_argument("--frame", type=int, required=True)
    s.add_argument("--pts", required=True); s.add_argument("--layer", action="append"); s.add_argument("--no-instances", action="store_true")
    s.add_argument("--deep", type=int, default=0, help="глубина: вложенные символы гнуть внутри (копии)")
    s.add_argument("--bend", action="store_true", help="гнуть фигуры внутри по полю (по умолчанию — аффинно на фигуру)")
    s.set_defaults(fn=warp)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
