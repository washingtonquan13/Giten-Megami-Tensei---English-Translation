import os,sys,re
sys.path.insert(0,os.getcwd()); sys.stdout.reconfigure(encoding='utf-8')
from pe import PE
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
org=open(os.path.join(D,'dds_org.exe'),'rb').read()
d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
p=PE(os.path.join(D,'dds_org.exe'))
def lead(b): return 0x81<=b<=0x9f or 0xe0<=b<=0xfc
def trail(b): return (0x40<=b<=0x7e) or (0x80<=b<=0xfc)
def find_sjis(buf,lo,hi,minchars=2):
    out=[];i=lo
    while i<hi-1:
        if lead(buf[i]) and trail(buf[i+1]):
            st=i;n=0;s=b''
            while i<hi-1 and ((lead(buf[i]) and trail(buf[i+1])) or (0x20<=buf[i]<0x7f) or (0xa1<=buf[i]<=0xdf)):
                if lead(buf[i]) and trail(buf[i+1]): s+=buf[i:i+2];i+=2;n+=1
                else: s+=buf[i:i+1];i+=1
            if n>=minchars:
                try: t=s.decode('cp932')
                except: t=s.decode('cp932','replace')
                out.append((st,s,t))
        else: i+=1
    return out
res={}
for sec in p.sections:
    if sec['name']=='.rsrc': continue
    lo,hi=sec['rawptr'],sec['rawptr']+sec['rawsize']
    res[sec['name']]=find_sjis(org,lo,hi)
tot=0
lines=[]
for n,v in res.items():
    tot+=len(v)
    lines.append("\n########## %s : %d Shift-JIS strings (>=2 DBCS chars) ##########"%(n,len(v)))
    for st,s,t in v:
        changed = d22[st:st+len(s)]!=s
        # what's there now
        e=st
        while e<len(d22) and d22[e]!=0 and e-st<160: e+=1
        cur=d22[st:e]
        try: curt=cur.decode('cp932')
        except: curt=cur.decode('cp932','replace')
        lines.append("%s off=%08x va=%08x jp=%-46r en=%r"%('TRANSLATED' if changed else 'UNTOUCHED ',st,p.off2va(st),t,curt if changed else ''))
open('sjis_inventory.txt','w',encoding='utf-8').write('\n'.join(lines))
print("total SJIS strings in .text/.rdata/.data:",tot)
for n,v in res.items(): print("  %s: %d"%(n,len(v)))
ch=sum(1 for n,v in res.items() for st,s,t in v if d22[st:st+len(s)]!=s)
print("translated:",ch," untouched:",tot-ch)
