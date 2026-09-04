import os,sys,unicodedata
sys.path.insert(0,os.getcwd()); sys.stdout.reconfigure(encoding='utf-8')
from pe import PE
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
org=open(os.path.join(D,'dds_org.exe'),'rb').read()
d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
p=PE(os.path.join(D,'dds_org.exe'))
def jp(ch):
    o=ord(ch)
    return (0x3040<=o<=0x30ff) or (0x4e00<=o<=0x9fff) or (0xff01<=o<=0xff60) or (0xff61<=o<=0xff9f) or (0x3000<=o<=0x303f)
# walk null-terminated strings in .rdata/.data, keep those with >=2 japanese chars
rows=[]
for sec in p.sections:
    if sec['name'] not in ('.rdata','.data'): continue
    lo,hi=sec['rawptr'],sec['rawptr']+sec['rawsize']
    i=lo
    while i<hi:
        if org[i]==0: i+=1; continue
        e=i
        while e<hi and org[e]!=0 and e-i<300: e+=1
        raw=org[i:e]
        try: t=raw.decode('cp932')
        except: t=None
        if t and sum(1 for c in t if jp(c))>=2:
            e2=i
            while e2<len(d22) and d22[e2]!=0 and e2-i<300: e2+=1
            new=d22[i:e2]
            try: nt=new.decode('cp932')
            except: nt=new.decode('cp932','replace')
            rows.append((i,p.off2va(i),sec['name'],t,nt,raw!=new))
        i=e+1
rows.sort()
tr=[r for r in rows if r[5]]
un=[r for r in rows if not r[5]]
print("null-terminated JP strings in .rdata/.data: %d  (translated %d, untouched %d)"%(len(rows),len(tr),len(un)))
out=["# Shift-JIS string inventory of dds_org.exe (.rdata + .data), with dds_en.exe status",
     "",
     "%d Japanese strings total: %d TRANSLATED in dds_en.exe, %d UNTOUCHED"%(len(rows),len(tr),len(un)),
     "","## TRANSLATED (%d)"%len(tr),"",
     "| file off | VA | sec | Japanese | English in dds_en |","|---|---|---|---|---|"]
for i,va,s,t,nt,c in tr:
    out.append("| %08x | %08x | %s | `%s` | `%s` |"%(i,va,s,t.replace('|','\|'),nt.replace('|','\|')))
out+=["","## UNTOUCHED (%d) — still Japanese in dds_en.exe"%len(un),"",
      "| file off | VA | sec | Japanese |","|---|---|---|---|"]
for i,va,s,t,nt,c in un:
    out.append("| %08x | %08x | %s | `%s` |"%(i,va,s,t.replace('|','\|')))
open('sjis_inventory.md','w',encoding='utf-8').write('\n'.join(out))
print("\n--- sample of UNTOUCHED strings ---")
for i,va,s,t,nt,c in un[:80]:
    print("  %08x %s %r"%(i,s,t))
