"""Create a flat LaTeX source package and rebuild it from a clean directory.

Usage: python3 make_flat_package.py <manuscript_dir> <out_dir>
All \\input files are copied to the top level with prefixed names, include paths are rewritten,
figures are copied flat, and main.bbl is included so the editorial system need not run BibTeX.
"""
import os
import re
import shutil
import subprocess
import sys

src, out = sys.argv[1], sys.argv[2]
if os.path.exists(out):
    shutil.rmtree(out)
os.makedirs(out)

mapping = {}


def flat_name(rel):
    rel = rel.replace("\\", "/")
    return rel.replace("/", "_")


def process(rel):
    path = os.path.join(src, rel)
    txt = open(path, encoding="utf-8").read()

    def rep_input(m):
        cmd, arg = m.group(1), m.group(2)
        a = arg if arg.endswith(".tex") else arg + ".tex"
        new = flat_name(a)
        if a not in mapping:
            mapping[a] = new
            process(a)
        return f"\\{cmd}{{{new[:-4] if cmd == 'input' else new}}}"

    txt = re.sub(r"\\(input|tabinput)\{([^}]+)\}", rep_input, txt)

    def rep_fig(m):
        opt, arg = m.group(1) or "", m.group(2)
        new = flat_name(arg)
        shutil.copy(os.path.join(src, arg), os.path.join(out, new))
        return f"\\includegraphics{opt}{{{new}}}"

    txt = re.sub(r"\\includegraphics(\[[^\]]*\])?\{([^}]+)\}", rep_fig, txt)
    target = os.path.join(out, mapping.get(rel, rel))
    open(target, "w", encoding="utf-8").write(txt)


mapping["main.tex"] = "main.tex"
process("main.tex")
for f in ("references_verified.bib", "main.bbl"):
    shutil.copy(os.path.join(src, f), os.path.join(out, f))
for d in os.listdir(out):
    assert "/" not in d
r = subprocess.run("pdflatex -interaction=nonstopmode -halt-on-error main.tex && pdflatex -interaction=nonstopmode -halt-on-error main.tex",
                   shell=True, cwd=out, capture_output=True, text=True)
log = open(os.path.join(out, "main.log"), errors="ignore").read()
undefined = len(re.findall(r"undefined", log))
print("exit", r.returncode, "undefined-warnings", undefined, "files", sorted(os.listdir(out)))
for f in os.listdir(out):
    if f.endswith((".aux", ".log", ".out")):
        os.remove(os.path.join(out, f))
