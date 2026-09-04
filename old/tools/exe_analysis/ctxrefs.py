"""Find every site that loads ds:0x491160 (script context ptr) and show what it touches."""
import os, sys, struct, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from da import _p, _buf, disasm

PAT = bytes.fromhex('a1 60 11 49 00'.replace(' ',''))
s = [x for x in _p.sections if x['name']=='.text'][0]
base = s['vaddr']+_p.imagebase; off=_p.va2off(base); n=s['rawsize']
seg = _buf[off:off+n]
i=0
while True:
    j = seg.find(PAT, i)
    if j<0: break
    va = base+j
    print("---- %08x" % va)
    print(disasm(va, 0x30))
    i = j+1
