// Build an in-between view N between turnaround keyframes A and B (0-based) by tweening part transforms.
// Works on a COPY. Parts are matched by symbol name, then by "family" (name without _3-4/_7-8/... suffix).
var SRC = "C:/path/to/puppet.fla";
var DST = "C:/Temp/animate_render/puppet_inbetween.fla";
var CHARACTER = "~XX_Character";   // top-level puppet symbol (layers may reorder between views)
var NESTED = ["~XX_Head"];         // synced nested symbols with stable layers (matched per layer)
var A = 104, B = 106, N = 105, T = 0.5;

var doc = openCopy(SRC, DST);

function fam(n) { return n.replace(/_(7-8|3-4|5-8|front|side|back|3-4rear|3-4far)$/i, "").replace(/\(overlap\)$/, ""); }
function lerpM(a, b, t) { var m = a; m.a += (b.a - a.a) * t; m.b += (b.b - a.b) * t; m.c += (b.c - a.c) * t; m.d += (b.d - a.d) * t; m.tx += (b.tx - a.tx) * t; m.ty += (b.ty - a.ty) * t; return m; }
function center(e) { return { x: e.left + e.width / 2, y: e.top + e.height / 2 }; }
function inst(fr) { var r = []; for (var i = 0; i < fr.elements.length; i++) if (fr.elements[i].elementType == "instance") r.push(fr.elements[i]); return r; }

function build(symName, byLayer) {
    doc.library.editItem(findItem(doc, symName).name);
    var tl = doc.getTimeline(), pool = [], used = [], moved = 0, lost = [];
    if (!byLayer) for (var i = 0; i < tl.layers.length; i++) { var fb = tl.layers[i].frames[B]; if (fb) pool = pool.concat(inst(fb)); }
    for (var i = 0; i < tl.layers.length; i++) {
        var L = tl.layers[i];
        if (L.layerType == "folder" || !L.frames[N]) continue;
        var lk = L.locked; L.locked = false;
        tl.setSelectedLayers(i); tl.currentLayer = i;
        if (L.frames[N].startFrame == N) tl.clearKeyframes(N);          // blink/expression key in the gap
        if (L.frames[N].startFrame != A) { L.locked = lk; continue; }
        tl.convertToKeyframes(N);
        var els = inst(L.frames[N]), cand = byLayer && L.frames[B] ? inst(L.frames[B]) : pool;
        for (var k = 0; k < els.length; k++) {
            var e = els[k], nm = e.libraryItem.name, best = -1;
            for (var j = 0; j < cand.length; j++) if (used.indexOf(cand[j]) < 0 && cand[j].libraryItem.name == nm) { best = j; break; }
            if (best < 0) for (var j = 0; j < cand.length; j++) if (used.indexOf(cand[j]) < 0 && fam(cand[j].libraryItem.name) == fam(nm)) { best = j; break; }
            if (best < 0) { lost.push(nm.split("/").pop()); continue; }
            var o = cand[best]; used.push(o);
            if (o.libraryItem.name == nm) e.matrix = lerpM(e.matrix, o.matrix, T);
            else { var ca = center(e), cb = center(o), m = e.matrix; m.tx += (cb.x - ca.x) * T; m.ty += (cb.y - ca.y) * T; e.matrix = m; }
            moved++;
        }
        L.locked = lk;
    }
    doc.exitEditMode();
    log(symName + ": moved " + moved + (lost.length ? ", unmatched: " + lost.join(", ") : ""));
}

for (var i = 0; i < NESTED.length; i++) build(NESTED[i], true);
build(CHARACTER, false);

// nested synced symbols in frame N must show their own frame N
doc.library.editItem(findItem(doc, CHARACTER).name);
var tl = doc.getTimeline();
for (var i = 0; i < tl.layers.length; i++) {
    var fr = tl.layers[i].frames[N]; if (!fr || fr.startFrame != N) continue;
    for (var k = 0; k < fr.elements.length; k++) {
        var e = fr.elements[k];
        if (e.elementType == "instance" && e.firstFrame == A) e.firstFrame = N;
    }
}
doc.exitEditMode();
fl.saveDocument(doc);
renderSymbol(doc, CHARACTER, A + 1, B + 1, "C:/Temp/animate_render/inbetween");
log("done: " + DST + " frame " + (N + 1));
// then: python look.py sheet C:/Temp/animate_render/inbetween/*.png --cols 3
