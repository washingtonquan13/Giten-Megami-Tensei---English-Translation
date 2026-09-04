import os,sys,struct
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from pe import PE
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
for fn in ('dds_org.exe','dds_en.exe'):
    p=PE(os.path.join(D,fn)); d=p.data
    print("\n############ %s ############"%fn)
    ird,irs=p.dirs[1]
    o=p.rva2off(ird)
    IAT={}
    n=0
    while True:
        oft,tds,fc,namerva,ft=struct.unpack_from('<IIIII',d,o+n*20)
        if namerva==0: break
        no=p.rva2off(namerva)
        dll=d[no:d.index(b'\0',no)].decode()
        print("\n== %s (IAT rva %08x, VA %08x)"%(dll,ft,0x400000+ft))
        t=p.rva2off(oft or ft); iat=ft
        i=0
        while True:
            v=struct.unpack_from('<I',d,t+i*4)[0]
            if v==0: break
            slotva=0x400000+iat+i*4
            if v&0x80000000:
                nm="Ordinal#%d"%(v&0xffff)
            else:
                so=p.rva2off(v)
                nm=d[so+2:d.index(b'\0',so+2)].decode()
            IAT[slotva]=(dll,nm)
            print("   [%08x] %s"%(slotva,nm))
            i+=1
        n+=1
    import json
    json.dump({('%08x'%k):v for k,v in IAT.items()},open('iat_%s.json'%fn,'w'))
