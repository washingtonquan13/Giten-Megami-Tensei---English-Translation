import os, sys, io
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
OUT = os.path.dirname(os.path.abspath(__file__))

KEYWORDS = ["交渉","話","仲魔","悪魔","はい","いいえ","会話","逃げ","仲間",
            "戦う","逃げる","魔法","道具","アイテム","防御","装備","状態","力","経験",
            "レベル","マッカ","たたかう","にげる","じゅもん","どうぐ"]
KB = {k:k.encode('cp932') for k in KEYWORDS}

def ctx(data, pos, before=40, after=60):
    s=max(0,pos-before); e=min(len(data),pos+after)
    chunk=data[s:e]
    # decode leniently
    txt=chunk.decode('cp932', errors='replace')
    return txt.replace('\x00','·').replace('\n','\\n')

rep=io.StringIO()
def P(*a): print(*a,file=rep)

hits_by_kw = {k:[] for k in KEYWORDS}
targets=[]
for dirpath,dirs,files in os.walk(ROOT):
    for fn in files:
        targets.append(os.path.join(dirpath,fn))

filecount=0
for p in targets:
    try:
        sz=os.path.getsize(p)
        if sz>60_000_000: continue
        with open(p,'rb') as f: data=f.read()
    except Exception: continue
    filecount+=1
    rel=os.path.relpath(p,ROOT)
    for k,b in KB.items():
        if len(b)<2: continue
        start=0
        n=0
        while True:
            i=data.find(b,start)
            if i<0: break
            hits_by_kw[k].append((rel,i,ctx(data,i)))
            start=i+1; n+=1
            if n>=200: break

P(f"scanned {filecount} files")
for k in KEYWORDS:
    h=hits_by_kw[k]
    if len(KB[k])<2:
        P(f"\n##### {k} : single-byte, skipped"); continue
    filesets=sorted(set(x[0] for x in h))
    P(f"\n##### {k!r} ({KB[k].hex()}): {len(h)} hits in {len(filesets)} files")
    P("  files:", ", ".join(filesets[:40]) + (" ..." if len(filesets)>40 else ""))
    for rel,off,c in h[:12]:
        P(f"   {rel} @0x{off:X}: {c}")

open(os.path.join(OUT,'kw_out.txt'),'w',encoding='utf-8').write(rep.getvalue())
print(rep.getvalue()[:60000])
