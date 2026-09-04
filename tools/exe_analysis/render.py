import os, sys, struct, zlib, io
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
OUT=os.path.dirname(os.path.abspath(__file__))

def write_png(path,w,h,rgb):  # rgb: bytes len w*h*3
    raw=b''.join(b'\x00'+rgb[y*w*3:(y+1)*w*3] for y in range(h))
    def chunk(t,d):
        c=t+d; return struct.pack('>I',len(d))+c+struct.pack('>I',zlib.crc32(c)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw,6))+chunk(b'IEND',b'')
    open(path,'wb').write(png)

def bmp8_to_png(src,dst,maxw=None):
    d=open(src,'rb').read()
    doff=struct.unpack_from('<I',d,10)[0]
    hs,w,h,pl,bpp,comp=struct.unpack_from('<IiiHHI',d,14)
    assert bpp==8 and comp==0, (bpp,comp)
    pal=d[14+hs:doff]
    stride=((w*8+31)//32)*4
    rows=[]
    for y in range(abs(h)):
        srow=d[doff+y*stride:doff+y*stride+w]
        out=bytearray()
        for px in srow:
            b,g,r=pal[px*4],pal[px*4+1],pal[px*4+2]
            out+=bytes((r,g,b))
        rows.append(bytes(out))
    if h>0: rows=rows[::-1]
    write_png(dst,w,abs(h),b''.join(rows))
    return w,abs(h)

for fn in ['fc50f1.bin','fc50f2.bin','fc50f6.bin','fc20020.bin']:
    try:
        print(fn, bmp8_to_png(os.path.join(ROOT,'fc',fn), os.path.join(OUT,fn+'.png')))
    except Exception as e: print(fn,'ERR',e)

# render 1bpp font sheets from et/A0000.BIN (8x8?) and A0001.BIN
for fn,cw,ch in [('A0000.BIN',8,8),('A0001.BIN',8,16)]:
    d=open(os.path.join(ROOT,'et',fn),'rb').read()
    bpc=ch  # bytes per char for 8px wide
    n=len(d)//bpc
    cols=16; rows=(n+cols-1)//cols
    W,H=cols*cw,rows*ch
    img=bytearray(b'\x20'*(W*H*3))
    for i in range(n):
        cx=(i%cols)*cw; cy=(i//cols)*ch
        for y in range(ch):
            byte=d[i*bpc+y]
            for x in range(8):
                if byte&(0x80>>x):
                    o=((cy+y)*W+(cx+x))*3
                    img[o]=img[o+1]=img[o+2]=255
    write_png(os.path.join(OUT,fn+'.png'),W,H,bytes(img))
    print(fn,'font sheet',W,H,n,'glyphs')

# render exe font region 0x69E42..0x6AA27 as 8x16 from dds.exe
for exe in ['dds_org.exe','dds.exe']:
    d=open(os.path.join(ROOT,exe),'rb').read()[0x69E00:0x6AA40]
    ch=16; n=len(d)//ch; cols=16; rows=(n+cols-1)//cols
    W,H=cols*8,rows*ch
    img=bytearray(b'\x20'*(W*H*3))
    for i in range(n):
        cx=(i%cols)*8; cy=(i//cols)*ch
        for y in range(ch):
            byte=d[i*ch+y]
            for x in range(8):
                if byte&(0x80>>x):
                    o=((cy+y)*W+(cx+x))*3
                    img[o]=img[o+1]=img[o+2]=255
    write_png(os.path.join(OUT,exe+'_font.png'),W,H,bytes(img))
    print(exe,'font region',W,H)
