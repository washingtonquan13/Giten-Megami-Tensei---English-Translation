import os,sys,struct
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from pe import PE
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
org=open(os.path.join(D,'dds_org.exe'),'rb').read()
d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
p=PE(os.path.join(D,'dds_org.exe'))
def cluster(idx,gap=16):
    out=[];s=e=idx[0]
    for i in idx[1:]:
        if i-e<=gap: e=i
        else: out.append((s,e));s=e=i
    out.append((s,e));return out
idx=[i for i in range(len(org)) if org[i]!=d22[i]]
cl=cluster(idx,gap=24)
def strat(buf,o,limit=200):
    e=o
    while e<len(buf) and buf[e]!=0 and e-o<limit: e+=1
    return buf[o:e]
def dec(b):
    try: return b.decode('cp932')
    except: return b.decode('cp932','replace')
print("# In-place string replacements (data sections), org -> dds_en\n")
tot=0
for s,e in cl:
    sec=p.sec_for_off(s)
    if not sec or sec['name'] not in ('.data','.rdata'): continue
    # walk backwards to string start
    st=s
    while st>0 and org[st-1]!=0: st-=1
    o=st
    print("### cluster off %08x-%08x  sec %s  VA %08x"%(s,e,sec['name'],p.off2va(s)))
    while o<=e+1:
        a=strat(org,o); b=strat(d22,o)
        if a or b:
            L=max(len(a),len(b))
            mark='*' if a!=b else ' '
            print("  %s off=%08x va=%08x len_jp=%-3d len_en=%-3d | %-42r | %r"%(mark,o,p.off2va(o),len(a),len(b),dec(a),dec(b)))
            if a!=b: tot+=1
            o+= max(L,1)
            while o<len(org) and org[o]==0 and d22[o]==0 and o<=e+1: o+=1
        else:
            o+=1
    print()
print("total changed strings:",tot)
