import os,sys,struct,subprocess
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from pe import PE
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
org=open(os.path.join(D,'dds_org.exe'),'rb').read()
d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
p=PE(os.path.join(D,'dds_org.exe'))
targets={0x464038:'CreateFontA',0x46402c:'GetGlyphOutlineA',0x464050:'TextOutA',
         0x464178:'MessageBoxA',0x464184:'CreateWindowExA',0x464188:'RegisterClassA',
         0x4640dc:'MultiByteToWideChar'}
def disasm(buf,off,n,va):
    open('_s.bin','wb').write(buf[off:off+n])
    r=subprocess.run(['objdump','-D','-b','binary','-mi386','-Mintel','--adjust-vma=0x%x'%va,'_s.bin'],capture_output=True,text=True)
    return '\n'.join(l for l in r.stdout.splitlines() if ':\t' in l)
for va,nm in sorted(targets.items(), key=lambda kv: kv[1]):
    pat=b'\xff\x15'+struct.pack('<I',va)
    i=0; found=[]
    while True:
        j=org.find(pat,i)
        if j<0: break
        found.append(j); i=j+1
    print("\n=== %s (IAT %08x): %d call sites: %s"%(nm,va,len(found),[('%08x'%p.off2va(f)) for f in found]))
    if nm in ('CreateFontA','GetGlyphOutlineA','TextOutA','RegisterClassA'):
        for f in found:
            print("  --- call site file %08x VA %08x  ORIGINAL"%(f,p.off2va(f)))
            st=f-0x50
            print(disasm(org,st,0x5c,p.off2va(st)))
            if org[st:st+0x5c]!=d22[st:st+0x5c]:
                print("  ~~~ PATCHED (dds_en) differs:")
                print(disasm(d22,st,0x5c,p.off2va(st)))
