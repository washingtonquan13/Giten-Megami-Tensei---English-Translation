import os,sys,re
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); sys.stdout.reconfigure(encoding='utf-8')
from pe import PE
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
org=open(os.path.join(D,'dds_org.exe'),'rb').read(); d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
p=PE(os.path.join(D,'dds_org.exe'))
rows=[]
for sec in p.sections:
    if sec['name'] not in ('.rdata','.data'): continue
    lo,hi=sec['rawptr'],sec['rawptr']+sec['rawsize']
    i=lo
    while i<hi:
        if d22[i]==0: i+=1; continue
        if i>lo and d22[i-1]!=0: i+=1; continue
        e=i
        while e<hi and d22[e]!=0 and e-i<200: e+=1
        s=d22[i:e]
        if len(s)>=3 and all(0x20<=b<0x7f or b in (9,10,13) for b in s) and re.search(r'[A-Za-z]{2}',s.decode()):
            rows.append((i,p.off2va(i),sec['name'],s.decode(),org[i:e]!=s))
        i=e+1
o=0xc166b4
while o<0xc16784:
    if d22[o]==0: o+=1; continue
    e=o
    while d22[e]: e+=1
    rows.append((o,p.off2va(o),'.rsrc-cave',d22[o:e].decode(),True))
    o=e+1
rows.sort()
newly=[r for r in rows if r[4]]
print("ASCII strings in dds_en .rdata/.data/cave: %d total, %d NEW"%(len(rows),len(newly)))
E=lambda s:s.replace('|','\|').replace('\n','\n').replace('\r','\r')
out=["# English / ASCII strings in dds_en.exe (.rdata, .data, .rsrc tail cave)","",
 "%d ASCII strings; **%d are new** (inserted by the translation patch); the rest were already ASCII in the 1999 Japanese original."%(len(rows),len(newly)),"",
 "## NEW — inserted by the English patch","","| file off | VA | section | English |","|---|---|---|---|"]
for i,va,s,t,n in newly: out.append("| %08x | %08x | %s | `%s` |"%(i,va,s,E(t)))
out+=["","## Pre-existing ASCII in dds_org.exe (unchanged)","","| file off | VA | section | text |","|---|---|---|---|"]
for i,va,s,t,n in rows:
    if not n: out.append("| %08x | %08x | %s | `%s` |"%(i,va,s,E(t)))
open('english_inventory.md','w',encoding='utf-8').write('\n'.join(out))
for i,va,s,t,n in newly: print("  %08x %-11s %r"%(i,s,t))
