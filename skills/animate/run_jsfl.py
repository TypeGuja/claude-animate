"""Запуск JSFL-скрипта в Adobe Animate с выводом в stdout.

python run_jsfl.py script.jsfl [--timeout 300]
"""
import argparse
import glob
import os
import subprocess
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))


def uri(path):
    p = os.path.abspath(path).replace("\\", "/")
    return "file:///" + p.replace(":", "|", 1)


def find_animate():
    exe = os.environ.get("ANIMATE_EXE")
    if exe and os.path.isfile(exe):
        return exe
    hits = sorted(glob.glob("C:/Program Files/Adobe/Adobe Animate*/Animate.exe")
                  + glob.glob("/Applications/Adobe Animate*/Adobe Animate*.app/Contents/MacOS/Adobe Animate*"))
    if not hits:
        sys.exit("Animate.exe не найден (поставь Animate или задай ANIMATE_EXE)")
    return hits[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--timeout", type=float, default=300)
    a = ap.parse_args()

    work = os.path.join(tempfile.gettempdir(), "claude_jsfl")
    os.makedirs(work, exist_ok=True)
    tag = uuid.uuid4().hex[:8]
    out = os.path.join(work, f"out_{tag}.txt")
    done = os.path.join(work, f"done_{tag}.txt")

    wrapped = os.path.join(work, f"run_{tag}.jsfl")
    # lib и скрипт встраиваются текстом: fl.runScript не делится глобалами.
    with open(os.path.join(HERE, "lib.jsfl"), encoding="utf-8") as f:
        lib = f.read()
    with open(a.script, encoding="utf-8") as f:
        body = f.read()
    with open(wrapped, "w", encoding="utf-8-sig") as f:
        f.write(lib + "\n")
        f.write(f'__OUT = "{uri(out)}";\nFLfile.write(__OUT, "");\n')
        f.write("try {\n" + body + "\n")
        f.write('} catch (e) { log("ОШИБКА: " + e + (e.lineNumber ? " (стр. " + e.lineNumber + ")" : "")); }\n')
        f.write("finally {\n")
        f.write(f'  FLfile.write("{uri(done)}", "ok");\n')
        f.write("}\n")

    exe = find_animate()
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-a", exe.split(".app/")[0] + ".app", wrapped])
    else:
        subprocess.Popen([exe, wrapped])
    t0 = time.time()
    while not os.path.exists(done):
        if time.time() - t0 > a.timeout:
            if os.path.exists(out):
                print(open(out, encoding="utf-8", errors="replace").read())
            sys.exit(f"таймаут {a.timeout}s (Animate упал или ждёт диалог; лог выше — до места остановки)")
        time.sleep(0.5)
    with open(out, encoding="utf-8", errors="replace") as f:
        print(f.read())
    for p in (out, done, wrapped):
        try:
            os.remove(p)
        except OSError:
            pass


if __name__ == "__main__":
    main()
