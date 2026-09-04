import os, sys, io, struct, collections
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
OUT=os.path.dirname(os.path.abspath(__file__))
rep=io.StringIO()
def P(*a): print(*a,file=rep)

# ---- test "u16[0] == filesize-2" across et/
d=os.path.join(ROOT,'et')
groups=collections.defaultdict(lambda:[0,0])
for fn in sorted(os.listdir(d)):
    p=os.path.join(d,fn); sz=os.path.getsize(p)
    with open(p,'rb') as f: h=f.read(2)
    v=struct.unpack('<H',h)[0]
    pre = ''.join(ch for ch in fn if ch.isalpha() and ch.isupper())[:2]
    pre = fn[:2] if fn[:2] in ('CA','ET','ID') else fn[:1]
    groups[pre][1]+=1
    if v==sz-2: groups[pre][0]+=1
P("et/ prefix : (files where u16[0]==size-2) / total")
for k,(a,b) in sorted(groups.items()): P(f"   {k}: {a}/{b}")

# same for m/ and p/
for fld in ['m','p']:
    d=os.path.join(ROOT,fld)
    g=collections.defaultdict(lambda:[0,0])
    for fn in sorted(os.listdir(d)):
        p=os.path.join(d,fn); sz=os.path.getsize(p)
        with open(p,'rb') as f: h=f.read(2)
        v=struct.unpack('<H',h)[0]
        pre=fn[:2] if fn[:2] in ('MS','M0','P2') else fn[:1]
        pre = 'MS' if fn.startswith('MS') else fn[:1]
        g[pre][1]+=1
        if v==sz-2: g[pre][0]+=1
    P(f"{fld}/ : " + str({k:f"{a}/{b}" for k,(a,b) in sorted(g.items())}))

# ---- CA2000 annotated
P("\n=== CA2000.BIN annotated ===")
with open(os.path.join(ROOT,'et','CA2000.BIN'),'rb') as f: d=f.read()
P(f" size={len(d)}")
P(f" 0x00 u16 = 0x{struct.unpack_from('<H',d,0)[0]:04X} = {struct.unpack_from('<H',d,0)[0]}  (== filesize-2)")
cnt=struct.unpack_from('<H',d,2)[0]
P(f" 0x02 u16 = {cnt}  (record count)")
ptrs=[struct.unpack_from('<H',d,4+2*i)[0] for i in range(cnt)]
P(f" 0x04.. ptr table = {[hex(x) for x in ptrs]}  (table ends at 0x{4+2*cnt:X} == first ptr 0x{ptrs[0]:X})")
for i,pt in enumerate(ptrs):
    end = ptrs[i+1] if i+1<len(ptrs) else len(d)
    P(f"   rec{i} @0x{pt:X}..0x{end:X}: {d[pt:end].hex(' ')}")

P("\n=== CA2001.BIN annotated ===")
with open(os.path.join(ROOT,'et','CA2001.BIN'),'rb') as f: d=f.read()
P(f" size={len(d)} hex={d.hex(' ')}")
cnt=struct.unpack_from('<H',d,2)[0]
ptrs=[struct.unpack_from('<H',d,4+2*i)[0] for i in range(cnt)]
P(f" len={struct.unpack_from('<H',d,0)[0]} cnt={cnt} ptrs={[hex(x) for x in ptrs]}")

# largest CA file
d=os.path.join(ROOT,'et')
cas=[(os.path.getsize(os.path.join(d,f)),f) for f in os.listdir(d) if f.startswith('CA')]
cas.sort(reverse=True)
P("\n largest CA files:", cas[:8])
for sz,fn in cas[:1]+[c for c in cas if c[1].startswith('CA3')][:2]:
    with open(os.path.join(d,fn),'rb') as f: dd=f.read()
    P(f"\n--- {fn} size={sz} first64={dd[:64].hex(' ')}")
    v=struct.unpack_from('<H',dd,0)[0]; c=struct.unpack_from('<H',dd,2)[0]
    P(f"   u16[0]={v} (size-2={sz-2}) cnt={c}")
    if 0<c<200 and 4+2*c<sz:
        pts=[struct.unpack_from('<H',dd,4+2*i)[0] for i in range(c)]
        P(f"   ptrs[0..9]={[hex(x) for x in pts[:10]]} monotonic={all(pts[i]<=pts[i+1] for i in range(len(pts)-1))} first==tableend({4+2*c}) -> {pts[0]==4+2*c}")

# ---- byte-value entropy / control-code check on m and et
P("\n=== control-byte (<0x20) fraction, sample files ===")
for fld,fn in [("et","ET0000.BIN"),("et","CA2000.BIN"),("et","ID0099.BIN"),("m","M0000.BIN"),("p","P2000.BIN")]:
    with open(os.path.join(ROOT,fld,fn),'rb') as f: dd=f.read()
    lo=sum(1 for b in dd if b<0x20); hi=sum(1 for b in dd if b>=0x80)
    P(f"   {fld}/{fn}: <0x20 = {lo}/{len(dd)} ({lo*100//max(1,len(dd))}%), >=0x80 = {hi*100//max(1,len(dd))}%, distinct={len(set(dd))}")

# ---- dump the 2023-dated fc BMPs to PNG
try:
    from PIL import Image
    for fn in ['fc50f1.bin','fc50f2.bin','fc50f6.bin']:
        p=os.path.join(ROOT,'fc',fn)
        im=Image.open(p)
        im.convert('RGB').save(os.path.join(OUT, fn+'.png'))
        P(f"  wrote {fn}.png {im.size} {im.mode}")
except Exception as e:
    P("PIL failed: "+repr(e))

open(os.path.join(OUT,'fmt_out.txt'),'w',encoding='utf-8').write(rep.getvalue())
print(rep.getvalue())
