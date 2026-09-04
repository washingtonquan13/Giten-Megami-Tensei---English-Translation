import sys, os
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from pe import PE

D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
org=open(os.path.join(D,'dds_org.exe'),'rb').read()
d21=open(os.path.join(D,'dds.exe'),'rb').read()
d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
p=PE(os.path.join(D,'dds_org.exe'))

def diffs(a,b):
    return [i for i in range(len(a)) if a[i]!=b[i]]

def cluster(idx, gap=16):
    out=[]
    if not idx: return out
    s=idx[0]; e=idx[0]
    for i in idx[1:]:
        if i-e<=gap: e=i
        else: out.append((s,e)); s=i; e=i
    out.append((s,e))
    return out

for label,a,b in [("org->dds(2021)",org,d21),("org->dds_en(2022)",org,d22),("dds(2021)->dds_en(2022)",d21,d22)]:
    idx=diffs(a,b)
    cl=cluster(idx)
    print("=== %s : %d differing bytes, %d clusters(gap16)" % (label,len(idx),len(cl)))
    # section histogram
    hist={}
    for i in idx:
        s=p.sec_for_off(i)
        n=s['name'] if s else ('HEADER' if i<p.sizeheaders else 'OVERLAY/?')
        hist[n]=hist.get(n,0)+1
    print("   by section:", hist)
    open(os.path.join(os.path.dirname(os.path.abspath(__file__)), label.replace('>','').replace('-','_').replace('(','').replace(')','')+'.clusters.txt'),'w').write(
        "\n".join("%08x-%08x len=%d" % (s,e,e-s+1) for s,e in cl))
    print("   cluster count:", len(cl), " first10:", [("%08x-%08x"%(s,e)) for s,e in cl[:10]])
