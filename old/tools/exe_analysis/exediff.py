import os, sys, io, hashlib
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
OUT=os.path.dirname(os.path.abspath(__file__))
rep=io.StringIO()
def P(*a): print(*a,file=rep)

def rd(n):
    with open(os.path.join(ROOT,n),'rb') as f: return f.read()
org=rd('dds_org.exe'); jp=rd('dds.exe'); en=rd('dds_en.exe')
for n,d in [('dds_org.exe',org),('dds.exe',jp),('dds_en.exe',en)]:
    P(f"{n}: {len(d)} bytes  md5={hashlib.md5(d).hexdigest()}")

def diffranges(a,b,name):
    assert len(a)==len(b)
    runs=[]; i=0; n=len(a)
    while i<n:
        if a[i]!=b[i]:
            s=i
            gap=0
            while i<n and (a[i]!=b[i] or gap<16):
                if a[i]==b[i]: gap+=1
                else: gap=0
                i+=1
            runs.append((s,i-gap))
        else: i+=1
    tot=sum(e-s for s,e in runs)
    P(f"\n=== {name}: {len(runs)} differing regions, {tot} differing bytes")
    return runs

r1=diffranges(org,jp,'dds_org.exe vs dds.exe (1999 orig -> 2021)')
for s,e in r1[:40]:
    P(f"  0x{s:X}-0x{e:X} ({e-s}b)")
    P(f"     ORG: {org[s:e][:90]!r}")
    P(f"     JP : {jp[s:e][:90]!r}")

r2=diffranges(jp,en,'dds.exe vs dds_en.exe (2021 -> 2022 English)')
P(f"  showing first 60 of {len(r2)}")
for s,e in r2[:60]:
    a=org[max(0,s-30):e+30]
    P(f"  0x{s:X}-0x{e:X} ({e-s}b)")
    try: P(f"     JP : {jp[s:e].decode('cp932',errors='replace')!r}")
    except: P(f"     JP : {jp[s:e]!r}")
    try: P(f"     EN : {en[s:e].decode('cp932',errors='replace')!r}")
    except: P(f"     EN : {en[s:e]!r}")

open(os.path.join(OUT,'exediff_out.txt'),'w',encoding='utf-8').write(rep.getvalue())
print(rep.getvalue()[:40000])
