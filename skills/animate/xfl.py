"""Геометрия .fla без Animate: XFL-XML напрямую (точно и без крашей JSFL-API вершин).

python xfl.py unpack <file.fla> <dir>
python xfl.py pack <dir> <file.fla>                       — mimetype первым, без сжатия
python xfl.py symbols <dir> [filter]                      — символы библиотеки → файл XML
python xfl.py layers <dir> <symbol> [--frame N]           — слои, ключи, элементы кадра
python xfl.py compare <dir> <symbol> F1,F2,...         — таблица слой × кадр: символ:firstFrame (что меняется между ракурсами)
python xfl.py export <dir> <symbol> --frame N [--layer L ...] [-o shapes.json]
python xfl.py import <dir> <shapes.json>                  — записать изменённые/новые фигуры обратно
python xfl.py warp <dir> <symbol> --frame N --pts pts.json [--layer L ...] [--no-instances]

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
    os.replace(tmp, a.fla)
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


def warp(a):
    pts = json.load(open(a.pts, encoding="utf-8"))
    f = tps_fit(pts["src"], pts["dst"], pts.get("reg", 0.0))
    p = sym_file(a.dir, a.symbol)
    root = ET.parse(p).getroot()
    sidx, iidx = element_index(root, "DOMShape"), element_index(root, "DOMSymbolInstance")
    sel = pick(root, a.frame, a.layer)
    shapes = {sidx[id(e)]: shape_json(e, sidx[id(e)], ln, fr) for ln, fr, t, e in sel if t == "DOMShape"}
    insts = set() if a.no_instances else {iidx[id(e)] for ln, fr, t, e in sel if t == "DOMSymbolInstance"}
    for sh in shapes.values():
        for e in sh["edges"]:
            e["path"] = warp_path(e["path"], f)
    txt = open(p, encoding="utf-8").read()
    for rx, todo, fn in ((SHAPE_RE, shapes, lambda b, k: replace_shape(b, shapes[k])),
                         (INST_RE, insts, lambda b, k: warp_instance(b, f))):
        out, pos = [], 0
        for k, m in enumerate(rx.finditer(txt)):
            if k in todo:
                out.append(txt[pos:m.start()]); out.append(fn(m.group(0), k)); pos = m.end()
        out.append(txt[pos:])
        txt = "".join(out)
    open(p, "w", encoding="utf-8").write(txt)
    print(p, f"фигур {len(shapes)}, экземпляров {len(insts)}")


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
    s.set_defaults(fn=warp)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
