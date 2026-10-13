// Inspect a symbol and render a frame range. Edit the paths/names, then:
//   python run_jsfl.py examples/inspect.jsfl
var FILE = "C:/path/to/file.fla";
var SYMBOL = "MyCharacter";
var OUT = "C:/Temp/animate_render/inspect";

var doc = openDoc(FILE);
log(listSymbols(doc, ""));
var d = describeSymbol(doc, SYMBOL, null);
log("frames: " + d.frameCount);
for (var i = 0; i < d.layers.length; i++) {
    var L = d.layers[i], ks = [];
    for (var k = 0; k < L.keys.length; k++) ks.push(L.keys[k].f + (L.keys[k].label ? ":" + L.keys[k].label : "") + "(" + L.keys[k].els.length + ")");
    log(L.name + " [" + L.type + "] " + ks.join(" "));
}
renderSymbol(doc, SYMBOL, 1, Math.min(d.frameCount, 40), OUT);
log("rendered to " + OUT);
