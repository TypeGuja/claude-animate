// Draw a filled curved shape on a new layer inside a symbol (on a COPY of the file).
var doc = openCopy("C:/path/to/file.fla", "C:/Temp/animate_render/draw_copy.fla");
editAt(doc, "MySymbol", "claude", 0);      // new layer "claude", frame 0
clearLayer(doc);
style(doc, "#2E8A8A", 1.5, "#A8E8E8");     // stroke, width, fill
drawPath(doc, [["M", 0, 0], ["C", 30, -20, 60, 10, 80, 50], ["Q", 50, 30, 20, 40], ["Q", 15, 15, 0, 0], ["Z"]]);
exitEdit(doc);
renderSymbol(doc, "MySymbol", 1, 1, "C:/Temp/animate_render/draw");
fl.saveDocument(doc);
log("ok");
// then: python look.py grid C:/Temp/animate_render/draw/MySymbol0001.png
