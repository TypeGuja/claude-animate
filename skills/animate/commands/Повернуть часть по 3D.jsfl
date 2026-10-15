// Команды → «Повернуть часть по 3D»: повернуть выделенную часть (символ) в глубину, «как кружку на столе».
// Выдели ОДИН экземпляр символа (голову, глаз, прядь...), введи градусы (+ вправо, − влево; обычно до ±12).
// Часть копируется (Имя__turnN) — остальные кадры не меняются. Каждая деталь внутри копии (глаз, радужка,
// прядь, ухо, рог...) сдвигается и сжимается по повороту 3D-модели пони, если она есть (иначе — эллипсоида):
// G:/mlp_characters/mlp_2d/tools/turn3d/data/model_<пони>.json). Файл не закрывается, Ctrl+Z работает.
var PY = "C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python314\\python.exe";
var TOOL = "C:\\Users\\user\\.claude\\skills\\animate\\part3d.py";
var MODELS = "G:\\mlp_characters\\mlp_2d\\tools\\turn3d\\data\\";

(function () {
    var doc = fl.getDocumentDOM();
    if (!doc) { alert("Нет открытого документа"); return; }
    var sel = doc.selection;
    if (sel.length != 1 || sel[0].elementType != "instance" || sel[0].instanceType != "symbol") { alert("Выдели одну часть — экземпляр символа"); return; }
    var el = sel[0], nm = el.libraryItem.name;
    var auto = fl.configURI + "part3d_auto.txt", deg;  // для автотестов: угол из файла вместо окна
    if (FLfile.exists(auto)) { deg = FLfile.read(auto); FLfile.remove(auto); }
    else deg = prompt("Повернуть на градусов (+ вправо, − влево; обычно до ±12):", "6");
    if (deg === null) return;
    deg = parseFloat(deg);
    if (isNaN(deg) || deg == 0) return;
    var low = nm.toLowerCase(), part = low.indexOf("tail") >= 0 ? "tail" : low.indexOf("mane") >= 0 || low.indexOf("hair") >= 0 ? "mane"
        : low.indexOf("torso") >= 0 ? "torso" : "head";
    var dn = (doc.name + " " + nm).toLowerCase(), pony = dn.indexOf("luna") >= 0 || dn.indexOf("pl_") >= 0 ? "princess_luna"
        : dn.indexOf("celestia") >= 0 || dn.indexOf("pc_") >= 0 ? "princess_celestia" : "";
    var model = pony ? MODELS + "model_" + pony + ".json" : "";
    if (model && !FLfile.exists(FLfile.platformPathToURI(model))) model = "";

    // копия символа — только у этого экземпляра
    var lib = doc.library, k = 1, base = nm.split("/").pop(), copyName;
    do { copyName = base + "__turn" + k; k++; } while (lib.itemExists((nm.indexOf("/") >= 0 ? nm.substring(0, nm.lastIndexOf("/") + 1) : "") + copyName));
    lib.selectItem(nm); lib.duplicateItem(nm); lib.renameItem(copyName);
    var dup = lib.getSelectedItems()[0];
    el.libraryItem = dup;
    var frame = el.symbolType == "graphic" ? el.firstFrame : 0;

    // детали кадра копии (в координатах символа)
    var tl = dup.timeline, items = [], refs = {};
    for (var li = 0; li < tl.layers.length; li++) {
        var L = tl.layers[li]; if (L.layerType == "folder" || L.layerType == "guide" || !L.frames[frame]) continue;
        var els = L.frames[frame].elements;
        for (var e = 0; e < els.length; e++) {
            var x = els[e]; if (x.elementType != "instance") continue;
            var id = li + "_" + e; refs[id] = x;
            items.push('{"id":"' + id + '","box":[' + [x.left, x.top, x.left + x.width, x.top + x.height].join(",") + ']}');
        }
    }
    // рамка эллипсоида — в координатах символа: у головы по основе головы и ушам (без гривы/рога), иначе по всем деталям
    var bb = function (re) { var r = null; for (var id in refs) { var x = refs[id]; if (re && !re.test(x.libraryItem.name)) continue;
        if (!r) r = [x.left, x.top, x.left + x.width, x.top + x.height];
        else r = [Math.min(r[0], x.left), Math.min(r[1], x.top), Math.max(r[2], x.left + x.width), Math.max(r[3], x.top + x.height)]; } return r; };
    var box = (part == "head" && bb(model ? /headbase|head_base|_ear|horn/i : /headbase|head_base|_ear/i)) || bb(null);
    if (!box) { alert("В кадре части нет деталей-символов"); return; }
    box = box.join(",");
    var cfg = FLfile.uriToPlatformPath(fl.configURI), pts = cfg + "part3d_pts.json", ej = cfg + "part3d_els.json",
        oj = cfg + "part3d_out.json", log = cfg + "part3d_log.txt", bat = cfg + "part3d_run.bat";
    FLfile.write(FLfile.platformPathToURI(ej), "[" + items.join(",") + "]");
    if (FLfile.exists(FLfile.platformPathToURI(oj))) FLfile.remove(FLfile.platformPathToURI(oj));
    var q = function (s) { return '"' + s + '"'; };
    var lines = ["@echo off", "set PYTHONIOENCODING=utf-8",
        // есть 3D-модель — поле по её точкам (голова с рогом и короной), иначе гладкий эллипсоид
        q(PY) + " " + q(TOOL) + " field" + (model ? " --model " + q(model) + " --part " + (part == "head" ? "head,horn,crown" : part) + " --damp 0.8 --reg 3000"
            : " --depth 0.9 --shape ellipsoid --part " + part) + " --from 0 --to " + deg + " --box=" + box + " -o " + q(pts) + " > " + q(log) + " 2>&1",
        "if errorlevel 1 exit /b 1",
        q(PY) + " " + q(TOOL) + " fit --pts " + q(pts) + " --elements " + q(ej) + " -o " + q(oj) + " >> " + q(log) + " 2>&1"];
    FLfile.write(FLfile.platformPathToURI(bat), lines.join("\r\n"));
    FLfile.runCommandLine(q(bat));
    var txt = FLfile.read(FLfile.platformPathToURI(oj));
    if (!txt) { alert("Поворот не удался, лог: " + log + "\n" + (FLfile.read(FLfile.platformPathToURI(log)) || "").slice(-400)); return; }
    var A = eval("(" + txt + ")"), n = 0;
    for (var id in A) {
        var x = refs[id]; if (!x) continue;
        var a = A[id], M = x.matrix;  // p' = L p + t,  L = [[a0 a1] [a2 a3]] (строки) — в координатах символа
        var na = a[0] * M.a + a[1] * M.b, nb = a[2] * M.a + a[3] * M.b, nc = a[0] * M.c + a[1] * M.d, nd = a[2] * M.c + a[3] * M.d;
        var ntx = a[0] * M.tx + a[1] * M.ty + a[4], nty = a[2] * M.tx + a[3] * M.ty + a[5];
        M.a = na; M.b = nb; M.c = nc; M.d = nd; M.tx = ntx; M.ty = nty; x.matrix = M; n++;
    }
    fl.trace("Повернуть часть по 3D: " + dup.name + ", " + deg + "°, деталей " + n);
})();
