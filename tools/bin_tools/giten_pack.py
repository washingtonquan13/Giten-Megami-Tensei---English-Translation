"""Round-trip pack/unpack for Giten .BIN containers.

  unpack(raw)      -> (hdr:int, body:bytes)
  pack(body, hdr)  -> raw   (hdr defaults to len(body), which is what every
                             m/M*, m/MS0*, p/P*, most et/ET* files use)
Verified byte-exact round trip on all 1103 encoded files.
"""
import os,sys
from giten import ROOT, unxor, enxor

def unpack(raw): return int.from_bytes(raw[:2],'little'), unxor(raw[2:])
def pack(body, hdr=None):
    if hdr is None: hdr=len(body)
    return hdr.to_bytes(2,'little')+enxor(body)

if __name__=='__main__':
    bad=0; n=0
    for d in ['m','p','et']:
        for f in sorted(os.listdir(os.path.join(ROOT,d))):
            if f.startswith('A') or f.startswith('CA'): continue
            raw=open(os.path.join(ROOT,d,f),'rb').read()
            h,b=unpack(raw); n+=1
            if pack(b,h)!=raw: bad+=1; print('ROUNDTRIP FAIL',d,f)
    print(f'round-trip verified on {n} files, {bad} failures')
