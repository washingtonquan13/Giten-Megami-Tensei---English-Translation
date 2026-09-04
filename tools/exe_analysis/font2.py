import os,sys
sys.stdout.reconfigure(encoding='utf-8')
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
org=open(os.path.join(D,'dds_org.exe'),'rb').read()
d21=open(os.path.join(D,'dds.exe'),'rb').read()
d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
BASE=0x69C32
def glyph(buf,c): return buf[BASE+c*16:BASE+c*16+16]
def render(bufs,c):
    gs=[glyph(b,c) for b in bufs]
    for r in range(16):
        print('  '+' | '.join(''.join('#' if g[r]&(0x80>>b) else '.' for b in range(8)) for g in gs))
d2=sorted({(i-BASE)//16 for i in range(BASE,BASE+4096) if d21[i]!=d22[i]})
print("Glyphs changed by the 2022 English patch (on top of 2021): %s"%[('%02x'%c)+(" '%s'"%chr(c) if 32<=c<127 else '') for c in d2])
for c in d2:
    print("\n-- code %02x %r  [org | 2021 | 2022]"%(c, chr(c) if 32<=c<127 else ''))
    render([org,d21,d22],c)
print("\n=== half-width katakana region sample (org vs 2021), codes b1 b2 b3 (ｱｲｳ) ===")
for c in (0xb1,0xb2,0xb3):
    print("-- %02x  [org | 2021]"%c); render([org,d21],c)
print("\n=== codes 81..85 (org vs 2021) ===")
for c in (0x81,0x82,0x83):
    print("-- %02x  [org | 2021]"%c); render([org,d21],c)
