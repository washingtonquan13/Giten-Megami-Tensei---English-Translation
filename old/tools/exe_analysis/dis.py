import os,sys,subprocess,struct
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from pe import PE
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
files={'org':open(os.path.join(D,'dds_org.exe'),'rb').read(),
       'd21':open(os.path.join(D,'dds.exe'),'rb').read(),
       'd22':open(os.path.join(D,'dds_en.exe'),'rb').read()}
p=PE(os.path.join(D,'dds_org.exe'))
def disasm(buf,off,n,va):
    open('_s.bin','wb').write(buf[off:off+n])
    r=subprocess.run(['objdump','-D','-b','binary','-mi386','-Mintel',
                      '--adjust-vma=0x%x'%va,'_s.bin'],capture_output=True,text=True)
    return '\n'.join(l for l in r.stdout.splitlines() if ':\t' in l)
# regions of interest in .text
regions=[(0x1ff00,0x40),(0x54b70,0x40),(0x3be50,0x150),(0x4f3a0,0x40),(0x4f400,0x40),
         (0x4f590,0x40),(0x50340,0x40),(0x50980,0x60)]
for off,n in regions:
    va=p.off2va(off)
    print("\n=========== file %08x  VA %08x ==========="%(off,va))
    for tag in ('org','d22'):
        print("--- %s"%tag)
        print(disasm(files[tag],off,n,va))
