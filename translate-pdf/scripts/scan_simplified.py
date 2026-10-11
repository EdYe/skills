"""Flag simplified-exclusive characters in Traditional Chinese markdown (code blocks skipped).

Usage: python3 scan_simplified.py <file.md>...   (exit 1 if any hit)
Requires: pip install --user opencc-python-reimplemented
"""
import os, sys, opencc
d = os.path.join(os.path.dirname(opencc.__file__), "dictionary")
def load(name):
    m = {}
    for line in open(os.path.join(d, name), encoding="utf-8"):
        k, v = line.rstrip("\n").split("\t")
        m[k] = v.split()
    return m
st = load("STCharacters.txt")                      # simplified -> traditional candidates
tw = {c for v in load("TWVariants.txt").values() for c in v}  # Taiwan-standard forms
# simplified-exclusive: not its own traditional candidate and not a Taiwan-standard variant
bad = {s for s, ts in st.items() if s not in ts and s not in tw}
hits = 0
for path in sys.argv[1:]:
    in_code = False
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        found = sorted({c for c in line if c in bad})
        if found and not in_code:
            hits += 1
            print(f"{path}:{n}: {' '.join(c + '→' + st[c][0] for c in found)}")
sys.exit(1 if hits else 0)
