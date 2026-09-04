import os,sys
sys.stdout.reconfigure(encoding='utf-8')
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
org=open(os.path.join(D,'dds_org.exe'),'rb').read()
d21=open(os.path.join(D,'dds.exe'),'rb').read()
d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
BASE=0x69C32
def glyph(buf,c):
    o=BASE+c*16
    return buf[o:o+16]
def render(buf,chars):
    gs=[glyph(buf,c) for c in chars]
    lines=[]
    for r in range(16):
        lines.append(' '.join(''.join('#' if g[r]&(0x80>>b) else '.' for b in range(8)) for g in gs))
    return '\n'.join(lines)
for label,buf in (("ORIGINAL (dds_org.exe)",org),("PATCHED (dds.exe 2021 / dds_en.exe)",d21)):
    print("=== %s ==="%label)
    print("chars: ! \" # A B C a b c")
    print(render(buf,[0x21,0x22,0x23,0x41,0x42,0x43,0x61,0x62,0x63]))
    print()
# extent check
print("font table assumed at %08x .. %08x (256 glyphs x 16 bytes)"%(BASE,BASE+4096))
d=[i for i in range(BASE,BASE+4096) if org[i]!=d21[i]]
print("diffs inside table: %d ; outside-table diffs in .data: %d"%(len(d),
   len([i for i in range(len(org)) if org[i]!=d21[i] and not (BASE<=i<BASE+4096)])))
# which char codes changed
codes=sorted({(i-BASE)//16 for i in d})
print("changed glyph codes (%d): %s"%(len(codes), ' '.join('%02x'%c for c in codes)))
print("as chars:", ''.join(chr(c) if 32<=c<127 else '.' for c in codes))
print("min changed code %02x max %02x"%(min(codes),max(codes)))
# are codes >=0x80 changed?
print("codes >=0x80 changed:", [ '%02x'%c for c in codes if c>=0x80])
# 2022 further changes to font?
d2=[i for i in range(BASE,BASE+4096) if d21[i]!=d22[i]]
print("2021->2022 diffs inside font table:", len(d2))
