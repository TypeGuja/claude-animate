---
name: animate
description: Drive Adobe Animate from Claude through JSFL scripts. Use it to open .fla files and inspect symbols, layers, frames, matrices and pivots; to move, rotate or scale parts; to build in-between views or poses by tweening part transforms; to draw new vector shapes; and to render symbol frames to PNG and look at them (with grid, onion skin and window screenshots). Use it whenever the user wants something done in Adobe Animate or to a .fla/.xfl puppet.
---

# Adobe Animate via JSFL

Claude never clicks in the Animate UI. Everything is a JSFL script run by `run_jsfl.py`. All files sit next to this SKILL.md.

## Run a script

```
python <skill dir>/run_jsfl.py <script.jsfl> [--timeout 300]
```

- Finds Animate in `C:/Program Files/Adobe/Adobe Animate*/` or `/Applications/Adobe Animate*`. Set env `ANIMATE_EXE` to override.
- Wraps the script. `lib.jsfl` is inlined, because `fl.runScript` does not share globals. Errors are caught, and everything passed to `log()` comes back on stdout.
- The log is appended line by line. If Animate crashes or hangs, the output shows the last line that ran.
- Animate opens a window (there is no headless mode). If it is already running, the script goes to the open instance.
- On first run Animate may ask "Run as command or open for editing?". The user must click **Run**. If the runner times out, take a screenshot (`look.py screen`) to see the dialog.
- Write scripts to a scratch/temp folder, never into the user's asset folders.

## lib.jsfl (available in every script)

Basics:
- `log(x)` prints a value; objects become JSON. `toJSON(o)` is also available, since JSFL has no `JSON`.
- `uri(path)` turns an OS path into `file:///C|/...`.
- `openDoc(path)` opens a file or reuses an open one. `openCopy(src, dst)` copies the file and opens the copy. **Edit copies only**, and use a new `dst` name each time, because an open file cannot be overwritten.
- `listSymbols(doc, filter)`, `findItem(doc, name)`.
- `describeSymbol(doc, name, [f0, f1])` returns layers, labels and keyframes (0-based). For each element it gives its symbol, `firstFrame`, matrix `m=[a,b,c,d,tx,ty]` and pivot.
- `renderSymbol(doc, name, f0, f1, outDir)` writes a PNG sequence (frames 1-based) plus `bounds.json` with symbol-space bounds. Look at the PNGs with the image reader.
- `setTransform(doc, sym, layer, frame, idx, {a,b,c,d,tx,ty})`, `setPivot(...)`.

Drawing:
- `editAt(doc, sym, layer, frame)` enters a symbol at a layer and frame. A layer given by name is created if it is missing.
- `style(doc, strokeHex|null, width, fillHex|null)`.
- `drawPath(doc, [["M",x,y],["L",x,y],["Q",cx,cy,x,y],["C",c1x,c1y,c2x,c2y,x,y],["Z"]], smooth)`. Curves are sampled into segments and then smoothed with `optimizeCurves` (default 40; 0 turns it off).
- `selectLayer(doc)` and `clearLayer(doc)` act on the current layer only.
- `readShapes(doc, sym, layer, frame)` returns contours as quadratic edges. Take palette colours from `shape.contours[i].fill.color`.
- `exitEdit(doc)`.

## Eyes: look.py (needs Pillow)

Each command writes a PNG to `<temp>/claude_animate_look/`, which you then view.
- `look.py screen` captures the Animate window (`--full` for the whole screen; Windows only).
- `look.py grid <png> --step 20` draws a grid in symbol coordinates (the red lines are the 0 axes). Use it to place `drawPath` points.
- `look.py onion a.png b.png [...]` overlays the images: the first in red, the last in blue, middle ones as-is. Use it as tracing paper for in-betweens.
- `look.py sheet <png...>` makes a labelled contact sheet. `look.py zoom <png> x0 y0 x1 y1 --k 4` gives a zoomed crop in symbol coordinates.
- Every frame of a `renderSymbol` sequence shares one canvas. `bounds.json` holds that canvas in symbol space.

## Known Animate 2024 pitfalls

- **Crash:** editing shape vertices (`shape.beginEdit` + `vertex.setLocation` / `edge.setControl`) kills Animate. To deform a shape, read it, recompute the points, `clearLayer`, and redraw.
- `fl.drawingLayer` `path.addCurve` drops its control points; that is why `drawPath` samples curves.
- `document.importFile` with SVG imported nothing during testing.
- `doc.selectAll()` selects across **all** layers. Use `selectLayer`.
- `fl.runScript` runs in its own scope; that is why the runner inlines the library.
- Old binary CS4 .fla files (header `D0 CF`) open fine; save a copy to get CC/XFL.

## Recipe: in-between view from a turnaround

See `examples/inbetween.jsfl`. Character puppets often keep each turnaround view as a keyframe built from the same part symbols.
1. Convert the gap frame to a keyframe; it becomes a copy of view A.
2. Match each part to its counterpart in view B, by symbol name or else by "family" (the name without its `_3-4` / `_7-8` suffix).
3. Lerp the matrix by `t`. For different symbols, move only the bbox centre.
4. Do the same inside nested synced symbols (heads) per layer. Point their `firstFrame` at the new frame. Clear blink or expression keys that sit in the gap.

Render A, the new frame and B, then compare them side by side or as onion skin before reporting.

## Rules

- Never overwrite the user's original files. Work on `openCopy` copies, and tell the user where the result is.
- Look at every render before claiming a result.
- Drawing is blind-coordinate work: draw, render, view with `grid`, fix. For hand-drawn art quality, prefer reusing and transforming existing parts over drawing from scratch.
