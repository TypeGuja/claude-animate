# claude-animate

A Claude Code plugin that lets Claude **work inside Adobe Animate**. Through JSFL scripts, Claude can:

- open `.fla` files and read symbols, layers, keyframes, labels, matrices and pivots;
- move, rotate and scale puppet parts, and change pivots and keyframes;
- **build in-between views and poses** by tweening part transforms between existing keyframes (for example, a new 34° view between a 7/8 view and a 3/4 view of a character turnaround);
- **draw** new vector shapes with fills and strokes;
- **see what it did**: it renders symbols to PNG with a coordinate grid, an onion-skin overlay, contact sheets and zoomed crops, and it can screenshot the Animate window (useful for dialogs and errors).

Claude never clicks in the UI. It writes a script, runs it in Animate, renders the result, looks at it, and iterates.

## Install

In Claude Code:

```
/plugin marketplace add Type_Guja/claude-animate
/plugin install animate@claude-animate
```

Or copy `skills/animate` into `~/.claude/skills/`.

Requirements:
- Adobe Animate (tested with Animate 2024 on Windows 10);
- Python 3 for the runner;
- [Pillow](https://pypi.org/project/pillow/) for `look.py` (`pip install pillow`).

If Animate is not in the default location, set `ANIMATE_EXE` to the path of `Animate.exe`.

## How it works

| file | what |
|---|---|
| `run_jsfl.py` | Inlines `lib.jsfl` and your script into one file, starts Animate with it, waits, and prints the log. The log is written line by line, so a crash still shows how far the script got. |
| `lib.jsfl` | Helpers for inspecting, transforming, drawing and rendering. |
| `look.py` | Claude's eyes: `screen`, `grid`, `onion`, `sheet`, `zoom`. |
| `examples/` | `inspect.jsfl`, `draw.jsfl`, `inbetween.jsfl`. |

On first run Animate asks *"Run as command or open for editing?"*. Click **Run** (and tick "don't ask again" if offered).

## Known Animate quirks (handled or documented)

- Editing shape vertices through `shape.beginEdit()` crashes Animate 2024. Claude redraws shapes instead.
- `path.addCurve` ignores its control points, so curves are sampled and then smoothed with `optimizeCurves`.
- `doc.selectAll()` grabs every layer. The library selects the current layer only.
- JSFL has no `JSON`; the library ships its own `toJSON`.

## Safety

The skill tells Claude to work on copies (`openCopy`) and never overwrite your source files.

## License

MIT
