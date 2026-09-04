import os,sys,struct
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from pe import PE
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
org=open(os.path.join(D,'dds_org.exe'),'rb').read()
d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
p=PE(os.path.join(D,'dds_org.exe'))
rs=[s for s in p.sections if s['name']=='.rsrc'][0]
print("file size          : %d (0x%x)"%(len(org),len(org)))
print(".rsrc rawptr %08x rawsize %08x -> raw end %08x"%(rs['rawptr'],rs['rawsize'],rs['rawptr']+rs['rawsize']))
print(".rsrc vaddr  %08x vsize   %08x -> virt end RVA %08x  VA %08x"%(rs['vaddr'],rs['vsize'],rs['vaddr']+rs['vsize'],0x400000+rs['vaddr']+rs['vsize']))
print("file offset of vsize end = %08x"%(rs['rawptr']+rs['vsize']))
print("SizeOfImage %08x -> VA end %08x"%(p.sizeimage,0x400000+p.sizeimage))
S=0xc16600; E=len(org)
print("\n== ORIGINAL tail from %08x =="%S)
for o in range(S,E,16):
    print("%08x  %s  |%s|"%(o,' '.join('%02x'%b for b in org[o:o+16]),
        ''.join(chr(b) if 32<=b<127 else '.' for b in org[o:o+16])))
print("\n== dds_en TAIL from %08x =="%S)
for o in range(S,E,16):
    m='<<' if org[o:o+16]!=d22[o:o+16] else '  '
    print("%08x %s %s  |%s|"%(o,m,' '.join('%02x'%b for b in d22[o:o+16]),
        ''.join(chr(b) if 32<=b<127 else '.' for b in d22[o:o+16])))
