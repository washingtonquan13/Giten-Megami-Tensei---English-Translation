"""Giten text extraction with dictionary expansion.

  0x08 <nn>  -> substitute entry <nn> of the word dictionary in m/MS7F07.BIN
                (verified: MS6007 rec AF = 御主に仕 {28} くらい {7D}
                 -> 御主に仕/える/くらい/なら).
Other dictionaries live in MS7F00..MS7F02 (names/nouns) and MS7F06 (a pool of
whole battle-talk sentences).  MS7F03/04 are scripts, MS7F05 is a label.
"""
import os,sys,re
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from giten import ROOT, unxor
DEC=os.path.join(os.path.dirname(os.path.abspath(__file__)),'decoded')

def records(b, start=2):
    """[id:u8][len:u16 LE][data:len]  -- MS6xxx / MS7Fxx / message-pool framing."""
    i=start; out=[]
    while i+3<=len(b):
        rid=b[i]; ln=int.from_bytes(b[i+1:i+3],'little')
        if ln>0 and i+3+ln<=len(b) and b[i+3+ln-1]==0:
            out.append((i,rid,b[i+3:i+3+ln-1])); i+=3+ln
        else: i+=1
    return out

_DICT=None
def dictionary():
    global _DICT
    if _DICT is None:
        _DICT={}
        # Decode the dictionary straight from the game folder (no dependency on a pre-decoded dump).
        from giten_pack import unpack
        p=os.path.join(ROOT,'m','MS7F07.BIN')
        if os.path.exists(p):
            _hdr,body=unpack(open(p,'rb').read())
            for _,rid,d in records(body): _DICT.setdefault(rid,d)
        else:
            raise SystemExit('dictionary m/MS7F07.BIN not found under '+ROOT)
    return _DICT

def render(d, expand=True, depth=0, show_ctrl=True):
    D=dictionary(); out=[]; i=0; n=len(d)
    while i<n:
        b=d[i]
        if b==0x08 and i+1<n:
            op=d[i+1]
            if expand and depth<6 and op in D:
                out.append(render(D[op],expand,depth+1,show_ctrl))
            else: out.append('{%02X}'%op)
            i+=2; continue
        if b==0x1f and i+1<n:
            if show_ctrl: out.append('<1F%02X>'%d[i+1])
            i+=2; continue
        if b==0x0a: out.append('\n'); i+=1; continue
        if b<0x20:
            if show_ctrl: out.append('<%02X>'%b)
            i+=1; continue
        if (0x81<=b<=0x9f or 0xe0<=b<=0xef) and i+1<n and 0x40<=d[i+1]<=0xfc and d[i+1]!=0x7f:
            try: out.append(d[i:i+2].decode('cp932')); i+=2; continue
            except Exception: pass
        if 0x20<=b<0x7f: out.append(chr(b)); i+=1; continue
        if 0xa1<=b<=0xdf: out.append(bytes([b]).decode('cp932')); i+=1; continue
        if show_ctrl: out.append('<%02X>'%b)
        i+=1
    return ''.join(out)

if __name__=='__main__':
    rel=sys.argv[1]
    p=rel if os.path.exists(rel) else os.path.join(DEC,rel)
    b=open(p,'rb').read()
    lim=int(sys.argv[2]) if len(sys.argv)>2 else 10**9
    for k,(off,rid,d) in enumerate(records(b)):
        if k>=lim: break
        t=render(d, show_ctrl=('--ctrl' in sys.argv)).replace('\n','\n')
        if t.strip(): print(f'{off:06x} #{rid:02X}  {t}')
