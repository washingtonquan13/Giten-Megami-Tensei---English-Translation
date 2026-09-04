import os, sys, re, io, time, collections, random
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
FOLDERS = ["et","fc","m","p","s","w"]
OUT = os.path.dirname(os.path.abspath(__file__))

def is_lead(b): return 0x81<=b<=0x9F or 0xE0<=b<=0xFC
def is_trail(b): return 0x40<=b<=0x7E or 0x80<=b<=0xFC

def sjis_runs(data, minchars=2):
    """yield (offset, text) for runs of >=minchars consecutive valid SJIS double-byte chars
    that decode to kana/CJK/fullwidth."""
    res=[]
    i=0
    n=len(data)
    while i < n-1:
        if is_lead(data[i]) and is_trail(data[i+1]):
            start=i
            j=i
            while j < n-1 and is_lead(data[j]) and is_trail(data[j+1]):
                j+=2
            chunk=data[start:j]
            try:
                t=chunk.decode('cp932')
            except Exception:
                i=start+2; continue
            # validate: mostly CJK/kana/fullwidth
            good=sum(1 for c in t if '\u3000'<=c<='\u30ff' or '\u4e00'<=c<='\u9fff' or '\uff00'<=c<='\uffef')
            if len(t)>=minchars and good>=len(t)*0.8:
                res.append((start,t))
            i=j
        else:
            i+=1
    return res

ASCII_RE = re.compile(rb'[A-Za-z][A-Za-z \'\.,!\?\-]{5,}')
def eng_runs(data):
    res=[]
    for m in ASCII_RE.finditer(data):
        s=m.group().decode('ascii')
        if sum(c.isalpha() for c in s)>=5 and ' ' in s or len(s)>=7:
            res.append((m.start(), s))
    return res

def load(p):
    with open(p,'rb') as f: return f.read()

report = io.StringIO()
def P(*a): print(*a, file=report)

random.seed(42)
summary={}
for fld in FOLDERS:
    d=os.path.join(ROOT,fld)
    files=[f for f in sorted(os.listdir(d)) if os.path.isfile(os.path.join(d,f))]
    # sample: for fc (huge) sample 120 files; else all
    if fld=='fc':
        sample = files[:40] + random.sample(files, 120)
        sample = sorted(set(sample))
    else:
        sample = files
    withjp=0; witheng=0; examples=[]; engex=[]
    sizes={}
    for fn in sample:
        p=os.path.join(d,fn)
        sz=os.path.getsize(p)
        if sz>4_000_000:  # skip enormous
            data=load(p)[:2_000_000]
        else:
            data=load(p)
        runs=sjis_runs(data,2)
        long_runs=[r for r in runs if len(r[1])>=3]
        if len(long_runs)>=3:
            withjp+=1
            if len(examples)<400:
                for off,t in long_runs[:6]:
                    examples.append((fn,off,t))
        er=eng_runs(data)
        if er:
            witheng+=1
            for off,s in er[:5]:
                engex.append((fn,off,s))
    summary[fld]=(len(files),len(sample),withjp,witheng)
    P(f"===== {fld}: sampled {len(sample)}/{len(files)} | files w/ JP text: {withjp} | files w/ English-ish ASCII: {witheng}")
    seen=set(); shown=0
    for fn,off,t in examples:
        if t in seen: continue
        seen.add(t)
        if len(t)<4: continue
        P(f"   {fn} @0x{off:X}: {t}")
        shown+=1
        if shown>=25: break
    P("  --- ASCII/English examples ---")
    seen=set(); shown=0
    for fn,off,s in engex:
        if s in seen: continue
        seen.add(s)
        P(f"   {fn} @0x{off:X}: {s!r}")
        shown+=1
        if shown>=25: break
    P("")

open(os.path.join(OUT,'sniff_out.txt'),'w',encoding='utf-8').write(report.getvalue())
print(report.getvalue())
