import sys, os, struct
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from pe import PE
sys.stdout.reconfigure(encoding='utf-8')
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
org=open(os.path.join(D,'dds_org.exe'),'rb').read()
d21=open(os.path.join(D,'dds.exe'),'rb').read()
d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
p=PE(os.path.join(D,'dds_org.exe'))

def cluster(idx, gap=16):
    out=[]
    if not idx: return out
    s=e=idx[0]
    for i in idx[1:]:
        if i-e<=gap: e=i
        else: out.append((s,e)); s=e=i
    out.append((s,e)); return out

def hexs(b): return ' '.join('%02x'%x for x in b)
def sjis(b):
    try: return b.decode('cp932','replace')
    except: return repr(b)

def desc_ptr(v):
    if 0x400000 <= v < 0x400000+p.sizeimage:
        s=p.sec_for_rva(v-p.imagebase)
        off=p.va2off(v)
        return "VA %08x -> sec %s off %s" % (v, s['name'] if s else '?', ('%08x'%off) if off is not None else 'NOMAP')
    return None

def report(label,a,b,gap=16):
    idx=[i for i in range(len(a)) if a[i]!=b[i]]
    cl=cluster(idx,gap)
    print("\n########## %s : %d bytes, %d clusters ##########"%(label,len(idx),len(cl)))
    for s,e in cl:
        sec=p.sec_for_off(s); secn=sec['name'] if sec else '?'
        va=p.off2va(s)
        n=e-s+1
        print("\n--- off %08x-%08x (len %d) sec=%s VA=%s"%(s,e,n,secn,'%08x'%va if va else '?'))
        ctx0=max(s-8,0); ctx1=min(e+9,len(a))
        print("  OLD: %s"%hexs(a[ctx0:ctx1]))
        print("  NEW: %s"%hexs(b[ctx0:ctx1]))
        # 4-byte LE pointer interpretation when len<=4 and aligned
        if n<=4:
            base=s & ~3
            ov=struct.unpack_from('<I',a,base)[0]; nv=struct.unpack_from('<I',b,base)[0]
            do=desc_ptr(ov); dn=desc_ptr(nv)
            if do or dn:
                print("  PTR@%08x: %08x -> %08x"%(base,ov,nv))
                if do: print("     old %s"%do)
                if dn: print("     new %s"%dn)
                for tag,v,buf in (("OLDTGT",ov,a),("NEWTGT",nv,b)):
                    o=p.va2off(v)
                    if o is not None:
                        z=buf.index(b'\0',o) if b'\0' in buf[o:o+300] else o+60
                        print("     %s @%08x: %r | sjis=%r"%(tag,o,buf[o:z][:120],sjis(buf[o:z][:120])))
        else:
            print("  OLDstr: %r"%a[s:e+1][:200]); print("   sjis: %r"%sjis(a[s:e+1][:200]))
            print("  NEWstr: %r"%b[s:e+1][:200]); print("   sjis: %r"%sjis(b[s:e+1][:200]))
report("org -> dds_en.exe (2022)",org,d22)
