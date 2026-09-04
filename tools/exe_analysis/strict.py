import os, sys, io, re, collections
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
OUT = os.path.dirname(os.path.abspath(__file__))
rep=io.StringIO()
def P(*a): print(*a,file=rep)

# strict: >=3 consecutive hiragana/katakana chars (SJIS 0x82 9F-F1 hiragana, 0x83 40-96 katakana)
def kana_runs(data, minlen=3):
    res=[]; i=0; n=len(data)
    while i<n-1:
        a,b=data[i],data[i+1]
        ok = (a==0x82 and 0x9F<=b<=0xF1) or (a==0x83 and (0x40<=b<=0x7E or 0x80<=b<=0x96))
        if ok:
            s=i
            while i<n-1:
                a,b=data[i],data[i+1]
                if (a==0x82 and 0x9F<=b<=0xF1) or (a==0x83 and (0x40<=b<=0x7E or 0x80<=b<=0x96)): i+=2
                else: break
            if (i-s)//2>=minlen:
                res.append((s,data[s:i].decode('cp932')))
        else: i+=1
    return res

# strict English: >=2 dictionary-ish words separated by spaces, or a word of >=6 lowercase w/ vowel
ENG=re.compile(rb'[A-Z][a-z]{2,}(?: [A-Za-z][a-z]{1,}){1,}|[a-z]{6,}')
VOW=set('aeiou')
def eng_strict(data):
    out=[]
    for m in ENG.finditer(data):
        s=m.group().decode('ascii')
        letters=[c for c in s.lower() if c.isalpha()]
        v=sum(1 for c in letters if c in VOW)
        if len(letters)>=5 and 0.15 <= v/len(letters) <= 0.65:
            out.append((m.start(),s))
    return out

P("========== PART A: strict kana-run scan of BIN folders ==========")
for fld in ["et","fc","m","p","s","w"]:
    d=os.path.join(ROOT,fld)
    files=[f for f in sorted(os.listdir(d)) if os.path.isfile(os.path.join(d,f))]
    nk=0; ne=0; kex=[]; eex=[]
    for fn in files:
        p=os.path.join(d,fn)
        with open(p,'rb') as f: data=f.read()
        kr=kana_runs(data,3)
        if kr:
            nk+=1
            for off,t in kr[:4]: kex.append((fn,off,t))
        er=eng_strict(data)
        if er:
            ne+=1
            for off,s in er[:4]: eex.append((fn,off,s))
    P(f"\n--- {fld}: {len(files)} files | files with >=1 kana-run(>=3 chars): {nk} | files with strict-English: {ne}")
    for fn,off,t in kex[:25]: P(f"    KANA {fn} @0x{off:X}: {t}")
    for fn,off,s in eex[:25]: P(f"    ENG  {fn} @0x{off:X}: {s!r}")

P("\n\n========== PART B: file signatures / headers ==========")
sigs=collections.defaultdict(list)
for fld in ["et","fc","m","p","s","w"]:
    d=os.path.join(ROOT,fld)
    cnt=collections.Counter()
    for fn in sorted(os.listdir(d)):
        p=os.path.join(d,fn)
        if not os.path.isfile(p): continue
        with open(p,'rb') as f: h=f.read(16)
        cnt[h[:4]]+=1
    P(f"\n--- {fld} first-4-bytes histogram (top 10):")
    for k,v in cnt.most_common(10):
        P(f"    {k.hex()}  {k!r}  x{v}")

open(os.path.join(OUT,'strict_out.txt'),'w',encoding='utf-8').write(rep.getvalue())
print(rep.getvalue())
