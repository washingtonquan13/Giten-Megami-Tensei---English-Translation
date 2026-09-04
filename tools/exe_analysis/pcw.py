import os,sys,struct,re
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from da import _p,_buf,disasm
s=[x for x in _p.sections if x['name']=='.text'][0]
base=s['vaddr']+_p.imagebase; off=_p.va2off(base); n=s['rawsize']
seg=_buf[off:off+n]
# 66 89 /r with disp8 = 0x0e  -> modrm 0x40|reg<<3|rm, then 0x0e
hits=[]
for i in range(n-4):
    if seg[i]==0x66 and seg[i+1]==0x89:
        m=seg[i+2]
        if (m>>6)==1 and seg[i+3]==0x0e:
            hits.append(base+i)
print("stores of a word to [reg+0x0e]:",len(hits))
for h in hits: print("---- %08x"%h); print(disasm(h-0x20,0x40))
