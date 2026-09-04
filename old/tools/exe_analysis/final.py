import os, sys, io, struct, collections
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
OUT=os.path.dirname(os.path.abspath(__file__))
rep=io.StringIO()
def P(*a): print(*a,file=rep)

jp=open(os.path.join(ROOT,'dds.exe'),'rb').read()
en=open(os.path.join(ROOT,'dds_en.exe'),'rb').read()

def dump(d,base,n,label):
    P(f"\n--- {label} @0x{base:X} ---")
    for i in range(0,n,16):
        ch=d[base+i:base+i+16]
        P(f"  {base+i:06X}  {' '.join(f'{b:02X}' for b in ch):<47}  {''.join(chr(b) if 32<=b<127 else '.' for b in ch)}")

dump(jp,0x62FE9-9,96,"dds.exe status-name table (JP)")
dump(en,0x62FE9-9,96,"dds_en.exe status-name table (EN)")
dump(jp,0x66480,96,"dds.exe battle message table (JP)")
dump(en,0x66480,96,"dds_en.exe battle message table (EN)")

# slot-size detection
def slots(d,start,end,size):
    out=[]
    for o in range(start,end,size):
        s=d[o:o+size]
        out.append(s)
    return out
NUL=b'\x00'
P("\n32-byte slot decode of 0x66480..0x66640:")
for o in range(0x66480,0x66640,32):
    a=jp[o:o+32].split(NUL)[0]; b=en[o:o+32].split(NUL)[0]
    P(f"   0x{o:X}: len={len(a)}/{len(b)} JP={a.decode('cp932','replace')!r} | EN={b.decode('cp932','replace')!r}")

P("\n8-byte slot decode of status table 0x62FE0..0x630F8:")
for o in range(0x62FE0,0x630F8,8):
    a=jp[o:o+8]; b=en[o:o+8]
    P(f"   0x{o:X}: JP={a[:7].rstrip(NUL).decode('cp932','replace')!r} id=0x{a[7]:02X} | EN={b[:7].rstrip(NUL).decode('cp932','replace')!r} id=0x{b[7]:02X}")
open(os.path.join(OUT,'final_out.txt'),'w',encoding='utf-8').write(rep.getvalue())
print(rep.getvalue())
