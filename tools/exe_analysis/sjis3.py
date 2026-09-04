import os,sys
sys.path.insert(0,os.getcwd()); sys.stdout.reconfigure(encoding='utf-8')
from pe import PE
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
org=open(os.path.join(D,'dds_org.exe'),'rb').read()
d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
p=PE(os.path.join(D,'dds_org.exe'))
def lead(b): return 0x81<=b<=0x9f or 0xe0<=b<=0xef   # JIS L1/L2 only
def trail(b): return (0x40<=b<=0x7e) or (0x80<=b<=0xfc)
def cls(ch):
    o=ord(ch)
    if 0x3040<=o<=0x309f: return 'H'   # hiragana
    if 0x30a0<=o<=0x30ff: return 'K'   # katakana
    if 0x4e00<=o<=0x9fff: return 'C'   # kanji
    if 0x3000<=o<=0x303f or 0xff01<=o<=0xff60: return 'P'  # fullwidth punct
    if 0x20<=o<0x7f: return 'A'
    if o in (0x0a,0x0d,0x09): return 'A'
    if 0xff61<=o<=0xff9f: return 'k'   # halfwidth katakana
    return 'X'
def scan(lo,hi):
    rows=[];i=lo
    while i<hi:
        if org[i]==0: i+=1; continue
        if i>lo and org[i-1]!=0: 
            i+=1; continue
        e=i
        while e<hi and org[e]!=0 and e-i<250: e+=1
        raw=org[i:e]
        try: t=raw.decode('cp932')
        except: i=e+1; continue
        c=[cls(x) for x in t]
        if 'X' in c: i=e+1; continue
        nj=sum(1 for x in c if x in 'HKCP')
        if nj>=2 and len(t)<=120:
            rows.append((i,raw,t))
        i=e+1
    return rows
rows=[]
for sec in p.sections:
    if sec['name'] not in ('.rdata','.data'): continue
    for i,raw,t in scan(sec['rawptr'],sec['rawptr']+sec['rawsize']):
        e2=i
        while e2<len(d22) and d22[e2]!=0 and e2-i<250: e2+=1
        new=d22[i:e2]
        try: nt=new.decode('cp932')
        except: nt=new.decode('cp932','replace')
        rows.append((i,p.off2va(i),sec['name'],t,nt,raw!=new))
rows.sort()
tr=[r for r in rows if r[5]]; un=[r for r in rows if not r[5]]
print("clean JP strings: %d  translated %d  untouched %d"%(len(rows),len(tr),len(un)))
from collections import Counter
print("by section:",Counter(r[2] for r in rows))
E=lambda s: s.replace('|','\|').replace('\n','\n').replace('\r','\r')
out=["# Shift-JIS string inventory — dds_org.exe (.rdata + .data)","",
 "Detector: null-delimited strings, decodable as CP932, all characters in {ASCII, hiragana, katakana, kanji, fullwidth/halfwidth punctuation}, >=2 double-byte Japanese characters, <=120 chars.","",
 "**%d Japanese strings found: %d TRANSLATED in dds_en.exe, %d left UNTOUCHED.**"%(len(rows),len(tr),len(un)),"",
 "## TRANSLATED (%d)"%len(tr),"","| file off | VA | sec | Japanese (dds_org) | English (dds_en) |","|---|---|---|---|---|"]
for i,va,s,t,nt,c in tr: out.append("| %08x | %08x | %s | `%s` | `%s` |"%(i,va,s,E(t),E(nt)))
out+=["","## UNTOUCHED (%d) — still Japanese in dds_en.exe"%len(un),"","| file off | VA | sec | Japanese |","|---|---|---|---|"]
for i,va,s,t,nt,c in un: out.append("| %08x | %08x | %s | `%s` |"%(i,va,s,E(t)))
open('sjis_inventory.md','w',encoding='utf-8').write('\n'.join(out))
print("\n=== ALL UNTOUCHED JAPANESE STRINGS ===")
for i,va,s,t,nt,c in un: print("  %08x %-7s %r"%(i,s,t))
