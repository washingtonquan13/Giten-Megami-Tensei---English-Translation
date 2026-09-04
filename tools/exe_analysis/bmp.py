import os,sys,struct,zlib
sys.path.insert(0,os.getcwd()); sys.stdout.reconfigure(encoding='utf-8')
from pe import PE
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
p=PE(os.path.join(D,'dds_org.exe')); d=p.data
base=p.rva2off(p.dirs[2][0]); entries=[]
def walk(off,path):
    ncn,nin=struct.unpack_from('<HH',d,off+12)
    for k in range(ncn+nin):
        nid,sub=struct.unpack_from('<II',d,off+16+k*8)
        if sub&0x80000000: walk(base+(sub&0x7fffffff),path+[nid])
        else:
            drva,dsize,cp,_=struct.unpack_from('<IIII',d,base+sub); entries.append((path+[nid],p.rva2off(drva),dsize))
walk(base,[])
BM={e[0][1]:e[1] for e in entries if e[0][0]==2}
def decode(o):
    hs,w,h,pl,bpp,comp,szimg,_,_,clr,_=struct.unpack_from('<IiiHHIIiiII',d,o)
    ncol=clr or (1<<bpp); pal=d[o+hs:o+hs+ncol*4]; bits=o+hs+ncol*4
    stride=((w*bpp+31)//32)*4
    return w,h,[[(pal[d[bits+(h-1-y)*stride+x]*4+2],pal[d[bits+(h-1-y)*stride+x]*4+1],pal[d[bits+(h-1-y)*stride+x]*4+0]) for x in range(w)] for y in range(h)]
def png(path,rows):
    H=len(rows);W=len(rows[0])
    raw=b''.join(b'\0'+bytes(v for px in r for v in px) for r in rows)
    ch=lambda t,dat:struct.pack('>I',len(dat))+t+dat+struct.pack('>I',zlib.crc32(t+dat))
    open(path,'wb').write(b'\x89PNG\r\n\x1a\n'+ch(b'IHDR',struct.pack('>IIBBBBB',W,H,8,2,0,0,0))+ch(b'IDAT',zlib.compress(raw,9))+ch(b'IEND',b''))
def sheet(ids,cols,sc,out):
    ts=[decode(BM[i]) for i in ids]
    tw=max(t[0] for t in ts); th=max(t[1] for t in ts)
    rn=(len(ids)+cols-1)//cols
    W=tw*cols*sc;H=th*rn*sc
    cv=[[(255,0,255)]*W for _ in range(H)]
    for k,(w,h,px) in enumerate(ts):
        cx=(k%cols)*tw*sc; cy=(k//cols)*th*sc
        for y in range(h*sc):
            for x in range(w*sc): cv[cy+y][cx+x]=px[y//sc][x//sc]
    png(out,cv); print("wrote",out,ids)
if __name__=='__main__':
    import collections
    g=collections.defaultdict(list)
    for i,o in BM.items():
        hs,w,h=struct.unpack_from('<Iii',d,o); g[(w,h)].append(i)
    for k in sorted(g,key=lambda k:-len(g[k]))[:12]:
        print("%5dx%-5d  n=%3d  ids=%s"%(k[0],k[1],len(g[k]),sorted(g[k])[:24]))
