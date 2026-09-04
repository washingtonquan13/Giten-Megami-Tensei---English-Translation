import os,sys,struct
sys.path.insert(0,os.getcwd()); sys.stdout.reconfigure(encoding='utf-8')
from pe import PE
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
p=PE(os.path.join(D,'dds_org.exe')); d=p.data
d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
base=p.rva2off(p.dirs[2][0])
TYPES={1:'CURSOR',2:'BITMAP',3:'ICON',4:'MENU',5:'DIALOG',6:'STRING',7:'FONTDIR',8:'FONT',9:'ACCELERATOR',10:'RCDATA',11:'MESSAGETABLE',12:'GROUP_CURSOR',14:'GROUP_ICON',16:'VERSION',24:'MANIFEST'}
entries=[]
def name_at(rva):
    o=base+ (rva & 0x7fffffff)
    n=struct.unpack_from('<H',d,o)[0]
    return d[o+2:o+2+n*2].decode('utf-16-le')
def walk(off,path):
    ncn,nin=struct.unpack_from('<HH',d,off+12)
    for k in range(ncn+nin):
        nid,sub=struct.unpack_from('<II',d,off+16+k*8)
        nm = name_at(nid) if nid&0x80000000 else nid
        if sub&0x80000000:
            walk(base+(sub&0x7fffffff), path+[nm])
        else:
            drva,dsize,cp,_=struct.unpack_from('<IIII',d,base+sub)
            entries.append((path+[nm],p.rva2off(drva),dsize))
walk(base,[])
from collections import Counter,defaultdict
c=Counter(); sz=defaultdict(int)
for path,o,s in entries:
    t=path[0]; tn=TYPES.get(t,str(t)) if isinstance(t,int) else t
    c[tn]+=1; sz[tn]+=s
print("total resource entries:",len(entries))
print("%-14s %6s %14s"%("TYPE","count","total bytes"))
for k in sorted(c,key=lambda k:-sz[k]):
    print("%-14s %6d %14d"%(k,c[k],sz[k]))
# which entries changed in dds_en?
ch=[(path,o,s) for path,o,s in entries if d[o:o+s]!=d22[o:o+s]]
print("\nresource entries whose bytes differ in dds_en.exe:",len(ch))
for path,o,s in ch[:20]: print("   ",path,'%08x'%o,s)
# japanese in RCDATA?
def jphits(buf):
    n=0
    for i in range(len(buf)-1):
        if (0x88<=buf[i]<=0x9f or 0xe0<=buf[i]<=0xea) and (0x40<=buf[i+1]<=0xfc): n+=1
    return n
import random
rc=[e for e in entries if (isinstance(e[0][0],int) and TYPES.get(e[0][0],'')=='RCDATA') or e[0][0]==10]
print("\nRCDATA entries:",len(rc))
for path,o,s in rc[:12]:
    buf=d[o:o+min(s,4096)]
    print("  %s off=%08x size=%d  jp-like pairs in first4k=%d  head=%s"%(path,o,s,jphits(buf),buf[:32].hex(' ')))
