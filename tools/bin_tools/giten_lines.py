"""Pull player-visible text lines out of a decoded Giten script, expanding
the 0x08 dictionary escape.  Tags:
  1FD0 window/narration open   1FBA narration line     1FD2 speaker name
  1FD3 speech line             1FB1 open choice list   1FB2 choice option
  1FB7 close choice list       1FD1 close window
"""
import os,sys,re
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from giten_text import dictionary, render
def lines(buf, expand=True):
    D=dictionary(); out=[]; i=0; n=len(buf)
    while i<n:
        if buf[i]==0x1f and i+1<n:
            tag=buf[i+1]; j=i+2; chunk=bytearray()
            while j<n:
                b=buf[j]
                if b==0x1f or b==0x7f: break
                if b==0x08 and j+1<n: chunk+=buf[j:j+2]; j+=2; continue
                if b<0x20: break
                if (0x81<=b<=0x9f or 0xe0<=b<=0xef) and j+1<n and 0x40<=buf[j+1]<=0xfc and buf[j+1]!=0x7f:
                    chunk+=buf[j:j+2]; j+=2; continue
                if 0x20<=b<0x7f or 0xa1<=b<=0xdf: chunk.append(b); j+=1; continue
                break
            s=render(bytes(chunk), expand=expand, show_ctrl=False)
            if s.strip(): out.append((i,'1F%02X'%tag,s))
            i=max(j,i+2); continue
        i+=1
    return out
JP=re.compile(r'[぀-ゟ゠-ヿ一-鿿]')
if __name__=='__main__':
    # Accept either a raw game file (relative paths resolve against ddswin/) or a pre-decoded body.
    from giten import ROOT
    from giten_pack import unpack
    p=sys.argv[1]
    if os.path.exists(p) and os.sep+'decoded'+os.sep in os.path.abspath(p):
        b=open(p,'rb').read()
    else:
        raw=open(p if os.path.isabs(p) else os.path.join(ROOT,p),'rb').read()
        _hdr,b=unpack(raw)
    for o,t,s in lines(b):
        if '--jp' in sys.argv and not JP.search(s): continue
        print(f'{o:06x} {t}  {s}')
