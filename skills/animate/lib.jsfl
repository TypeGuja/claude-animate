// Helper library for Claude-driven Animate scripts. Inlined by run_jsfl.py before each script.
// (Comments are in Russian; API names are English.)
var __log = [];
var __OUT = null; // раннер задаёт; лог дописывается сразу — при краше Animate видно, где упало

// JSON-сериализатор (в JSFL нет объекта JSON).
function toJSON(o) {
    if (o === null || o === undefined) return "null";
    var t = typeof o;
    if (t == "number") return isFinite(o) ? String(o) : "null";
    if (t == "boolean") return String(o);
    if (t == "string") return '"' + o.split("\\").join("\\\\").split('"').join('\\"').split("\n").join("\\n").split("\r").join("") + '"';
    var r = [];
    if (o instanceof Array) { for (var i = 0; i < o.length; i++) r.push(toJSON(o[i])); return "[" + r.join(",") + "]"; }
    for (var k in o) if (typeof o[k] != "function") r.push(toJSON(String(k)) + ":" + toJSON(o[k]));
    return "{" + r.join(",") + "}";
}

function log(x) {
    var s = typeof x !== "object" ? String(x) : toJSON(x);
    __log.push(s);
    if (__OUT) FLfile.write(__OUT, s + "\n", "append");
}

function uri(path) {
    var p = String(path).replace(/\\/g, "/");
    return "file:///" + p.replace(":", "|");
}

function openDoc(path) {
    var u = uri(path);
    for (var i = 0; i < fl.documents.length; i++)
        if (fl.documents[i].pathURI == u) return fl.documents[i];
    return fl.openDocument(u);
}

function saveAs(doc, path) {
    return fl.saveDocument(doc, uri(path));
}

function findItem(doc, name) {
    var items = doc.library.items;
    for (var i = 0; i < items.length; i++) {
        var n = items[i].name;
        if (n == name || n.split("/").pop() == name) return items[i];
    }
    throw new Error("нет символа: " + name);
}

function listSymbols(doc, filter) {
    var r = [], items = doc.library.items;
    for (var i = 0; i < items.length; i++) {
        var it = items[i];
        if (it.itemType != "graphic" && it.itemType != "movie clip") continue;
        if (filter && it.name.toLowerCase().indexOf(filter.toLowerCase()) < 0) continue;
        r.push(it.name);
    }
    return r;
}

function round(v) { return Math.round(v * 1000) / 1000; }

function describeElement(e) {
    var m = e.matrix, d = {
        type: e.elementType,
        m: [round(m.a), round(m.b), round(m.c), round(m.d), round(m.tx), round(m.ty)]
    };
    if (e.elementType == "instance" && e.libraryItem) {
        d.symbol = e.libraryItem.name;
        if (e.firstFrame !== undefined) d.firstFrame = e.firstFrame;
        var tp = e.getTransformationPoint();
        d.pivot = [round(tp.x), round(tp.y)];
    }
    if (e.name) d.name = e.name;
    return d;
}

// Слои, лейблы и ключевые кадры символа. frames: null — все ключи, или [f0, f1] (0-based).
function describeSymbol(doc, name, frames) {
    var tl = findItem(doc, name).timeline, r = { symbol: name, frameCount: tl.frameCount, layers: [] };
    for (var li = 0; li < tl.layers.length; li++) {
        var L = tl.layers[li], lay = { name: L.name, type: L.layerType, keys: [] };
        for (var f = 0; f < L.frames.length; f++) {
            var fr = L.frames[f];
            if (fr.startFrame != f) continue;
            if (frames && (f < frames[0] || f > frames[1])) continue;
            var k = { f: f, dur: fr.duration, els: [] };
            if (fr.labelType != "none" && fr.name) k.label = fr.name;
            for (var ei = 0; ei < fr.elements.length; ei++) k.els.push(describeElement(fr.elements[ei]));
            lay.keys.push(k);
        }
        r.layers.push(lay);
    }
    return r;
}

// PNG-секвенция кадров символа, f0..f1 1-based.
function renderSymbol(doc, name, f0, f1, outDir) {
    FLfile.createFolder(uri(outDir));
    var it = findItem(doc, name);
    var base = name.split("/").pop().replace(/[^\w\-]/g, "_");
    it.exportToPNGSequence(uri(outDir + "/" + base + ".png"), f0, f1);
    // границы каждого кадра в координатах символа — для сетки/наложений в look.py
    // Animate кладёт все кадры серии на общий холст — объединение границ кадров f0..f1.
    var tl = it.timeline, b = {}, U = null;
    for (var f = f0; f <= f1; f++) {
        var r = frameBounds(tl, f - 1);
        if (!r) continue;
        if (!U) U = { l: r.left, t: r.top, r: r.left + r.width, b: r.top + r.height };
        else { U.l = Math.min(U.l, r.left); U.t = Math.min(U.t, r.top); U.r = Math.max(U.r, r.left + r.width); U.b = Math.max(U.b, r.top + r.height); }
    }
    for (var f = f0; f <= f1 && U; f++) {
        var n = String(f);
        while (n.length < 4) n = "0" + n;
        b[base + n + ".png"] = { left: round(U.l), top: round(U.t), width: round(U.r - U.l), height: round(U.b - U.t) };
    }
    var prev = FLfile.read(uri(outDir + "/bounds.json"));
    if (prev) { try { var o = eval("(" + prev + ")"); for (var k in o) if (!(k in b)) b[k] = o[k]; } catch (e) {} }
    FLfile.write(uri(outDir + "/bounds.json"), toJSON(b));
    return outDir;
}

// Объединённые границы видимых не-гайд слоёв кадра f (0-based) в координатах символа.
function frameBounds(tl, f) {
    var L = 1e9, T = 1e9, R = -1e9, B = -1e9;
    for (var i = 0; i < tl.layers.length; i++) {
        var ly = tl.layers[i];
        if (ly.layerType == "guide" || ly.layerType == "folder" || !ly.visible) continue;
        var fr = ly.frames[f];
        if (!fr) continue;
        for (var k = 0; k < fr.elements.length; k++) {
            var e = fr.elements[k];
            L = Math.min(L, e.left); T = Math.min(T, e.top);
            R = Math.max(R, e.left + e.width); B = Math.max(B, e.top + e.height);
        }
    }
    return R < L ? null : { left: round(L), top: round(T), width: round(R - L), height: round(B - T) };
}

function elementAt(doc, sym, layer, frame, idx) {
    var tl = findItem(doc, sym).timeline, L = null;
    for (var i = 0; i < tl.layers.length; i++) if (tl.layers[i].name == layer) L = tl.layers[i];
    if (!L) throw new Error("нет слоя: " + layer);
    var fr = L.frames[frame];
    if (!fr || !fr.elements[idx]) throw new Error("нет элемента " + idx + " в кадре " + frame);
    return fr.elements[idx];
}

function setTransform(doc, sym, layer, frame, idx, m) {
    var e = elementAt(doc, sym, layer, frame, idx);
    var mm = e.matrix;
    for (var k in m) mm[k] = m[k];
    e.matrix = mm;
}

function setPivot(doc, sym, layer, frame, idx, x, y) {
    elementAt(doc, sym, layer, frame, idx).setTransformationPoint({ x: x, y: y });
}

// ---------- Рисование ----------

// Копия файла и открытие копии (оригинал не трогаем).
function openCopy(src, dst) {
    if (FLfile.exists(uri(dst))) FLfile.remove(uri(dst));
    if (!FLfile.copy(uri(src), uri(dst))) throw new Error("не скопировать " + src);
    return fl.openDocument(uri(dst));
}

// Войти в символ на слой/кадр (0-based). layer: имя или индекс; нет слоя — создаётся сверху.
function editAt(doc, sym, layer, frame) {
    doc.library.editItem(findItem(doc, sym).name);
    var tl = doc.getTimeline(), li = -1;
    if (typeof layer == "number") li = layer;
    else for (var i = 0; i < tl.layers.length; i++) if (tl.layers[i].name == layer) li = i;
    if (li < 0) { tl.currentLayer = 0; li = tl.addNewLayer(layer, "normal", true); }
    tl.setSelectedLayers(li);
    tl.currentLayer = li;
    var L = tl.layers[li];
    if (L.locked) L.locked = false;
    if (!L.visible) L.visible = true;
    if (frame >= L.frames.length) tl.insertFrames(frame - L.frames.length + 1, false, L.frames.length);
    tl.currentFrame = frame;
    if (L.frames[frame].startFrame != frame) tl.convertToBlankKeyframes(frame);
    return tl;
}

function exitEdit(doc) { doc.exitEditMode(); }

// Выделить элементы ТОЛЬКО текущего слоя/кадра (doc.selectAll берёт все слои). → их число.
function selectLayer(doc) {
    var tl = doc.getTimeline(), els = tl.layers[tl.currentLayer].frames[tl.currentFrame].elements;
    doc.selectNone();
    if (els.length) doc.selection = els;
    return els.length;
}

// Очистить текущий слой/кадр.
function clearLayer(doc) {
    if (selectLayer(doc)) doc.deleteSelection();
    doc.selectNone();
}

// Стиль: stroke "#rrggbb" или null, width px, fill "#rrggbb" или null.
function style(doc, stroke, width, fill) {
    var s = doc.getCustomStroke("toolbar");
    if (stroke) { s.style = "solid"; s.color = stroke; s.thickness = width || 1; }
    else s.style = "noStroke";
    doc.setCustomStroke(s);
    var f = doc.getCustomFill("toolbar");
    if (fill) { f.style = "solid"; f.color = fill; } else f.style = "noFill";
    doc.setCustomFill(f);
}

// Контур в духе SVG: [["M",x,y],["L",x,y],["Q",cx,cy,x,y],["C",c1x,c1y,c2x,c2y,x,y],["Z"]].
// Рисует в текущий слой/кадр (editAt), стиль — style(). Кривые раскладываются на отрезки
// (addCurve в Animate 2024 теряет контрольные точки), потом сглаживаются optimizeCurves.
// smooth: 0..100, по умолчанию 40; 0 — без сглаживания.
function drawPath(doc, segs, smooth) {
    var p = fl.drawingLayer.newPath(), cx = 0, cy = 0, sx = 0, sy = 0, N = 16;
    for (var i = 0; i < segs.length; i++) {
        var s = segs[i], t = s[0];
        if (t == "M") { cx = sx = s[1]; cy = sy = s[2]; p.addPoint(cx, cy); continue; }
        if (t == "Z") s = ["L", sx, sy], t = "L";
        if (t == "L") p.addPoint(s[1], s[2]);
        else for (var k = 1; k <= N; k++) {
            var u = k / N, v = 1 - u, x, y;
            if (t == "Q") { x = v*v*cx + 2*u*v*s[1] + u*u*s[3]; y = v*v*cy + 2*u*v*s[2] + u*u*s[4]; }
            else { x = v*v*v*cx + 3*u*v*v*s[1] + 3*u*u*v*s[3] + u*u*u*s[5]; y = v*v*v*cy + 3*u*v*v*s[2] + 3*u*u*v*s[4] + u*u*u*s[6]; }
            p.addPoint(x, y);
        }
        cx = s[s.length - 2]; cy = s[s.length - 1];
    }
    p.makeShape(false, false);
    if (smooth !== 0) {
        if (selectLayer(doc)) doc.optimizeCurves(smooth || 40, true);
        doc.selectNone();
    }
}

function shapesAt(doc, sym, layer, frame) {
    var tl = editAt(doc, sym, layer, frame), els = tl.layers[tl.currentLayer].frames[frame].elements, r = [];
    for (var i = 0; i < els.length; i++) if (els[i].elementType == "shape") r.push(els[i]);
    return r;
}

// Контуры фигур кадра: [{fill, edges:[[x0,y0,cx,cy,x1,y1],...]}] — квадратичные Безье.
function readShapes(doc, sym, layer, frame) {
    var out = [], sh = shapesAt(doc, sym, layer, frame);
    for (var i = 0; i < sh.length; i++) {
        var es = sh[i].edges, e2 = [];
        for (var k = 0; k < es.length; k++) {
            var a = es[k].getControl(0), c = es[k].getControl(1), b = es[k].getControl(2);
            e2.push([round(a.x), round(a.y), round(c.x), round(c.y), round(b.x), round(b.y)]);
        }
        out.push({ edges: e2 });
    }
    return out;
}

// PNG каждого слоя кадра frame (0-based) по отдельности: <outDir>/<NN>_<слой>.png + bounds.json.
// Остальные слои временно становятся guide (маска своей части остаётся), потом всё восстанавливается.
// layers: null — все видимые не-guide слои, или массив имён.
function renderLayers(doc, sym, frame, outDir, layers) {
    FLfile.createFolder(uri(outDir));
    var it = findItem(doc, sym), tl = it.timeline, keep = [], out = [];
    for (var i = 0; i < tl.layers.length; i++) keep.push({ t: tl.layers[i].layerType, p: tl.layers[i].parentLayer, v: tl.layers[i].visible });
    var want = function (L) { return L.layerType != "guide" && L.layerType != "folder" && L.layerType != "mask" && (!layers || layers.indexOf(L.name) >= 0); };
    var targets = [];
    for (var i = 0; i < tl.layers.length; i++) { var fr = tl.layers[i].frames[frame]; if (want(tl.layers[i]) && fr && fr.elements.length) targets.push(i); }
    var b = {};
    try {
        for (var q = 0; q < targets.length; q++) {
            var ti = targets[q], T = tl.layers[ti], mask = T.parentLayer && T.parentLayer.layerType == "mask" ? T.parentLayer : null;
            for (var i = 0; i < tl.layers.length; i++) {
                var L = tl.layers[i];
                if (i == ti || L == mask || L.layerType == "folder") continue;
                if (mask && L.parentLayer == mask) { L.visible = false; continue; }
                if (L.layerType != "guide") L.layerType = "guide";
            }
            var nm = (q < 10 ? "0" : "") + q + "_" + T.name.replace(/[^\w\-]/g, "_");
            var r = frameBounds(tl, frame);
            it.exportToPNGSequence(uri(outDir + "/" + nm + ".png"), frame + 1, frame + 1);
            // Animate дописывает номер кадра к имени — переименуем в nm.png
            var n = String(frame + 1); while (n.length < 4) n = "0" + n;
            var got = outDir + "/" + nm + n + ".png";
            if (FLfile.exists(uri(got))) { FLfile.remove(uri(outDir + "/" + nm + ".png")); FLfile.copy(uri(got), uri(outDir + "/" + nm + ".png")); FLfile.remove(uri(got)); }
            // Animate 2024: exportToPNGSequence(f, f) пишет ДВА кадра (f и f+1) — лишний удаляем
            var n2 = String(frame + 2); while (n2.length < 4) n2 = "0" + n2;
            if (FLfile.exists(uri(outDir + "/" + nm + n2 + ".png"))) FLfile.remove(uri(outDir + "/" + nm + n2 + ".png"));
            if (r) b[nm + ".png"] = r;
            out.push(nm);
            for (var i = 0; i < tl.layers.length; i++) { tl.layers[i].layerType = keep[i].t; if (keep[i].p) tl.layers[i].parentLayer = keep[i].p; tl.layers[i].visible = keep[i].v; }
        }
    } finally {
        for (var i = 0; i < tl.layers.length; i++) { tl.layers[i].layerType = keep[i].t; if (keep[i].p) tl.layers[i].parentLayer = keep[i].p; tl.layers[i].visible = keep[i].v; }
    }
    FLfile.write(uri(outDir + "/bounds.json"), toJSON(b));
    return out;
}

// Новый ракурс: копия ключа base в кадр N (все слои), позиции на t к ключу other (тот же слой и символ),
// firstFrame по ff {символ: кадр} (массив — по порядку встреч).
function makeView(doc, sym, base, other, N, t, ff) {
    doc.library.editItem(findItem(doc, sym).name);
    var tl = doc.getTimeline();
    if (tl.frameCount < N + 2) tl.insertFrames(N + 2 - tl.frameCount, true, tl.frameCount - 1);
    for (var i = 0; i < tl.layers.length; i++) {
        var L = tl.layers[i]; if (L.layerType == "folder") continue;
        var lk = L.locked; L.locked = false;
        tl.setSelectedLayers(i); tl.currentLayer = i;
        if (!L.frames[N]) { L.locked = lk; continue; }
        if (L.frames[N].startFrame != N) tl.convertToBlankKeyframes(N);
        if (L.frames[N + 1] && L.frames[N + 1].startFrame != N + 1) tl.convertToBlankKeyframes(N + 1);
        tl.copyFrames(base, base + 1); tl.pasteFrames(N, N + 1);
        L.locked = lk;
    }
    var moved = 0, notes = [], seen = {};
    for (var i = 0; i < tl.layers.length; i++) {
        var L = tl.layers[i]; if (L.layerType == "folder") continue;
        var fN = L.frames[N], fO = L.frames[other]; if (!fN) continue;
        for (var k = 0; k < fN.elements.length; k++) {
            var e = fN.elements[k]; if (e.elementType != "instance") continue;
            var nm = e.libraryItem.name.split("/").pop();
            if (fO && L.layerType != "guide") for (var q = 0; q < fO.elements.length; q++) {
                var o = fO.elements[q];
                if (o.elementType == "instance" && o.libraryItem == e.libraryItem) {
                    var m = e.matrix; m.tx += (o.matrix.tx - m.tx) * t; m.ty += (o.matrix.ty - m.ty) * t; e.matrix = m; moved++; break;
                }
            }
            if (ff[nm] !== undefined) {
                var v = ff[nm]; if (v instanceof Array) { seen[nm] = (seen[nm] || 0); v = v[Math.min(seen[nm]++, v.length - 1)]; }
                e.firstFrame = v; notes.push(L.name + ":" + nm + "=" + v);
            }
        }
    }
    doc.exitEditMode();
    return "сдвинуто " + moved + "; " + notes.join(", ");
}
