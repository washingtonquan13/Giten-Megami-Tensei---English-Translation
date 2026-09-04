"""xref.py -- find call/jmp/immediate references to a VA in dds_en.exe."""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from da import _p, _buf

def text_range():
    s = [x for x in _p.sections if x['name'] == '.text'][0]
    base = s['vaddr'] + _p.imagebase
    return base, s['rawsize']

def xrefs(target):
    base, n = text_range()
    off = _p.va2off(base)
    out = []
    for i in range(n - 5):
        b = _buf[off+i]
        if b in (0xE8, 0xE9):
            rel = struct.unpack_from('<i', _buf, off+i+1)[0]
            if base + i + 5 + rel == target:
                out.append((base+i, 'call' if b == 0xE8 else 'jmp'))
    # absolute immediates anywhere in the image
    t = struct.pack('<I', target)
    st = 0
    while True:
        j = _buf.find(t, st)
        if j < 0: break
        va = _p.off2va(j)
        if va: out.append((va, 'imm32'))
        st = j + 1
    return out

if __name__ == '__main__':
    for va, k in xrefs(int(sys.argv[1], 16)):
        print("%08x  %s" % (va, k))
