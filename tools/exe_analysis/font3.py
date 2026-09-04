import os,sys,subprocess
sys.stdout.reconfigure(encoding='utf-8')
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
org=open(os.path.join(D,'dds_org.exe'),'rb').read()
d21=open(os.path.join(D,'dds.exe'),'rb').read()
d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
# realign disasm of the halfwidth glyph fetch
open('_s.bin','wb').write(org[0x50668:0x506c8])
r=subprocess.run(['objdump','-D','-b','binary','-mi386','-Mintel','--adjust-vma=0x451268','_s.bin'],capture_output=True,text=True)
print("=== half-width glyph fetch routine (dds_org) ===")
print('\n'.join(l for l in r.stdout.splitlines() if ':\t' in l)[:1600])
BASE=0x69E30; FIRST=0x20
def off(c): return BASE+(c-FIRST)*16
def render(bufs,chars):
    print('    '+'    '.join('%02x'%c for c in chars))
    for r in range(16):
        print('  '+' '.join(''.join('#' if bufs[k][off(c)+r]&(0x80>>b) else '.' for b in range(8)) for c in chars for k in range(len(bufs))))
print("\nfont base VA 0x46C230 -> file 0x%X ; index = (code-0x20)*16"%BASE)
print("\n=== ORIGINAL vs 2021-PATCHED, 'A' 'g' '5' (each pair: org | patched) ===")
render([org,d21],[0x41,0x67,0x35])
d=[i for i in range(len(org)) if org[i]!=d21[i] and 0x65c00<=i<0x6ee00]
codes=sorted({(i-BASE)//16+FIRST for i in d})
print("\n2021 changed %d bytes in .data; glyph codes changed: %d, range %02x..%02x"%(len(d),len(codes),min(codes),max(codes)))
print(" ASCII part:", ''.join(chr(c) if 32<=c<127 else '' for c in codes))
print(" >=0x80 part:", ' '.join('%02x'%c for c in codes if c>=0x7f))
print(" unchanged codes in 20..df:", ' '.join('%02x'%c for c in range(0x20,0xe0) if c not in codes))
d2=[i for i in range(len(org)) if d21[i]!=d22[i] and 0x65c00<=i<0x6ee00]
c2=sorted({(i-BASE)//16+FIRST for i in d2 if i>=BASE})
print("\n2022-only .data diffs: %d bytes; inside font table: %s"%(len(d2), [ '%02x %r'%(c,chr(c)) for c in c2]))
print("2022-only .data diffs BELOW font table (offsets):", ['%08x'%i for i in d2 if i<BASE][:40])
print("\n=== glyphs the 2022 patch further edited (org | 2021 | 2022) ===")
if c2: render([org,d21,d22],c2)
# table extent sanity: bytes after 0x6AA30
print("\nbytes at 0x6AA30..0x6AA60 (org):", ' '.join('%02x'%b for b in org[0x6AA30:0x6AA60]))
print("last changed byte 2021:", '%08x'%max(d))
