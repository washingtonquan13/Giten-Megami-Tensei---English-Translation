import os, sys, io, struct, collections
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
OUT=os.path.dirname(os.path.abspath(__file__))
rep=io.StringIO()
def P(*a): print(*a,file=rep)

def hexdump(data, base=0, n=256):
    for i in range(0,min(n,len(data)),16):
        ch=data[i:i+16]
        hx=' '.join(f'{b:02X}' for b in ch)
        asc=''.join(chr(b) if 32<=b<127 else '.' for b in ch)
        P(f"  {base+i:08X}  {hx:<47}  {asc}")

# ---------- 1) locate real Japanese narrative in dds.exe ----------
def hira_dense(data, minchars=6):
    """runs of >=minchars SJIS DB chars containing >=40% hiragana"""
    res=[]; i=0; n=len(data)
    def islead(b): return 0x81<=b<=0x9F or 0xE0<=b<=0xFC
    def istrail(b): return 0x40<=b<=0x7E or 0x80<=b<=0xFC
    while i<n-1:
        if islead(data[i]) and istrail(data[i+1]):
            s=i
            while i<n-1 and islead(data[i]) and istrail(data[i+1]): i+=2
            if (i-s)//2>=minchars:
                try: t=data[s:i].decode('cp932')
                except: continue
                h=sum(1 for c in t if '\u3041'<=c<='\u309f')
                if h/len(t)>=0.35:
                    res.append((s,t))
        else: i+=1
    return res

for name in ['dds.exe','dds_en.exe']:
    with open(os.path.join(ROOT,name),'rb') as f: d=f.read()
    r=hira_dense(d,6)
    P(f"\n########## {name}: {len(r)} hiragana-dense SJIS runs (>=6 chars, >=35% hiragana)")
    if r:
        offs=[x[0] for x in r]
        P(f"  offset span 0x{min(offs):X} .. 0x{max(offs):X}")
        buckets=collections.Counter(o>>16 for o in offs)
        P("  by 64KB bucket:", {f"0x{k:X}0000":v for k,v in sorted(buckets.items())})
    for off,t in r[:60]:
        P(f"   @0x{off:X}: {t}")

# ---------- 2) hexdumps of BIN formats ----------
samples=[("et","ET0000.BIN"),("et","CA2000.BIN"),("et","ID0099.BIN"),("et","A0000.BIN"),
         ("m","M0000.BIN"),("m","MS0000.BIN"),("p","P2000.BIN"),("s","SB000.BIN"),
         ("s","SM000.BIN"),("fc","fc50f1.bin"),("fc","fc20020.bin")]
for fld,fn in samples:
    p=os.path.join(ROOT,fld,fn)
    if not os.path.exists(p):
        # find any
        c=[x for x in sorted(os.listdir(os.path.join(ROOT,fld)))]
        P(f"\n### {fld}/{fn} NOT FOUND; dir has e.g. {c[:5]}"); continue
    with open(p,'rb') as f: d=f.read()
    P(f"\n########## {fld}/{fn}  size={len(d)} (0x{len(d):X})")
    hexdump(d,0,256)
    if d[:2]==b'BM':
        sz,_,_,doff = struct.unpack_from('<IHHI',d,2)
        hs,w,h,pl,bpp,comp = struct.unpack_from('<IiiHHI',d,14)
        P(f"   BMP: filesize={sz} dataoffset={doff} hdr={hs} {w}x{h} bpp={bpp} comp={comp}")

# ---------- 3) p/ file structure (all 123/124 bytes) ----------
P("\n########## p/ folder structure analysis")
d=os.path.join(ROOT,'p')
szs=collections.Counter()
for fn in sorted(os.listdir(d)):
    szs[os.path.getsize(os.path.join(d,fn))]+=1
P("  size histogram:", dict(szs))

# ---------- 4) et header interpretation ----------
P("\n########## et/ header field survey (first 8 bytes as 4x uint16)")
d=os.path.join(ROOT,'et')
rows=[]
for fn in sorted(os.listdir(d))[:1000]:
    p=os.path.join(d,fn); sz=os.path.getsize(p)
    with open(p,'rb') as f: h=f.read(8)
    if len(h)<8: continue
    a,b,c,e=struct.unpack('<4H',h)
    rows.append((fn,sz,a,b,c,e))
for r in rows[:25]:
    P(f"   {r[0]:<12} size={r[1]:<7} u16=[{r[2]},{r[3]},{r[4]},{r[5]}]  w*h?={r[2]}x{r[4] if r[4] else '?'}")
# test hypothesis: size == a*c + header?
ok=0
for fn,sz,a,b,c,e in rows:
    for hdr in (4,6,8,16,32):
        if a*c+hdr==sz: ok+=1; break
P(f"   files where u16[0]*u16[2]+hdr == filesize: {ok}/{len(rows)}")
ok2=0
for fn,sz,a,b,c,e in rows:
    if a and (sz-a) >=0: pass
# alt: a = width, b = ?, maybe size-?
P("\n########## m/ header field survey")
d=os.path.join(ROOT,'m')
for fn in sorted(os.listdir(d))[:20]:
    p=os.path.join(d,fn); sz=os.path.getsize(p)
    with open(p,'rb') as f: h=f.read(8)
    a,b,c,e=struct.unpack('<4H',h)
    P(f"   {fn:<12} size={sz:<7} u16=[{a},{b},{c},{e}] bytes={h.hex()}")

open(os.path.join(OUT,'deep_out.txt'),'w',encoding='utf-8').write(rep.getvalue())
print(rep.getvalue()[:60000])
