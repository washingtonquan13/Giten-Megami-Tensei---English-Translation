import os,sys,datetime,collections,re
import os as _os
def _find_root():
    """Locate ddswin/: $GITEN_ROOT, else search upward from this file for a folder containing ddswin/."""
    r = _os.environ.get("GITEN_ROOT")
    if r: return r
    d = _os.path.dirname(_os.path.abspath(__file__))
    for _ in range(6):
        cand = _os.path.join(d, "ddswin")
        if _os.path.isdir(cand): return cand
        for sub in _os.listdir(d):
            cand = _os.path.join(d, sub, "ddswin")
            if _os.path.isdir(cand): return cand
        d = _os.path.dirname(d)
    raise SystemExit("ddswin/ not found: set GITEN_ROOT to the game's ddswin folder")
ROOT = _find_root()
out=[]
for d in ["m","et","p","s","w"]:
    p=os.path.join(ROOT,d)
    files=sorted(os.listdir(p))
    pat=collections.Counter()
    sizes=[]
    modern=[]
    old=0
    for f in files:
        fp=os.path.join(p,f)
        st=os.stat(fp)
        yr=datetime.datetime.fromtimestamp(st.st_mtime)
        base=re.sub(r'[0-9A-Fa-f]+','#',f)
        pat[base]+=1
        sizes.append(st.st_size)
        if yr.year>=2021: modern.append((f,st.st_size,yr.strftime('%Y-%m-%d')))
        else: old+=1
    out.append(f"## {d}/  ({len(files)} files, {sum(sizes)} bytes)")
    out.append(f"name patterns: {dict(pat)}")
    out.append(f"size min={min(sizes)} max={max(sizes)} distinct_sizes={len(set(sizes))}")
    out.append(f"modern(>=2021): {len(modern)}  original: {old}")
    out.append("modern files: "+", ".join(f"{a}" for a,b,c in modern))
    out.append("")
print("\n".join(out))
