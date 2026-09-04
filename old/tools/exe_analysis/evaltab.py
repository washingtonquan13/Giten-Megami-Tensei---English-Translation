"""evaltab.py -- recover the Giten VM's *expression* grammar (0x436B00).

Many script opcodes do not take fixed-width operands: they take expression trees,
read by 0x436B00 (`eval`, returns a pointer to the value; 0x437490 = eval + deref).

    eval():  b = read_u8()
             if b > 0x5D: return
             jmp jumptable[bytemap[b]]          bytemap @0x437380, jumptable @0x437288

Each case consumes a different amount: a literal u8/u16/u32, a variable index, or
one/two nested eval()s. This module walks every case and emits, per expression
opcode, the ordered list of what it consumes.
"""
import os, sys, re, struct, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from da import disasm, _p, _buf

BYTEMAP = 0x437380
JT      = 0x437288
NB      = 0x5E          # opcodes 0x00 .. 0x5D

FETCH = {0x438FA0: 'u8', 0x438FC0: 'u16', 0x438FE0: 'u32',
         0x438E50: 'u8', 0x438E80: 'u16', 0x438EC0: 'u32'}
EVAL  = {0x436B00, 0x437490, 0x437700, 0x4374A0}

LINE = re.compile(r'^\s*([0-9a-f]+):\t[0-9a-f ]+\t(\S+)\s*(.*)$')
_cache = {}

def ins(va, n=0x140):
    if va not in _cache:
        out = []
        for l in disasm(va, n).splitlines():
            m = LINE.match(l)
            if m: out.append((int(m.group(1), 16), m.group(2), m.group(3)))
        _cache[va] = out
    return _cache[va]

TEXT_LO, TEXT_HI = 0x401000, 0x464000

def trace(va, depth, seen):
    """Ordered list of operand-stream actions on the straight-line path from va."""
    if depth < 0 or va in seen or not (TEXT_LO <= va < TEXT_HI): return []
    seen = seen | {va}
    acts = []
    for a, mn, op in ins(va):
        if mn in ('call', 'jmp') and op.startswith('0x'):
            t = int(op, 16)
            if t in FETCH: acts.append(FETCH[t])
            elif t in EVAL: acts.append('expr')
            elif mn == 'jmp' and TEXT_LO <= t < TEXT_HI and t not in seen:
                acts += trace(t, depth - 1, seen); break
            else: acts += trace(t, depth - 1, seen)
        if mn in ('ret', 'leave'): break
        if mn == 'jmp': break
    return acts

def build():
    bo = _p.va2off(BYTEMAP); jo = _p.va2off(JT)
    bmap = [_buf[bo + i] for i in range(NB)]
    ncase = max(bmap) + 1
    jt = [struct.unpack_from('<I', _buf, jo + 4*k)[0] for k in range(ncase)]
    tab = {}
    for b in range(NB):
        h = jt[bmap[b]]
        tab[b] = dict(case=bmap[b], handler=h, acts=trace(h, 3, frozenset()))
    return tab

if __name__ == '__main__':
    tab = build()
    out = {}
    for b, v in sorted(tab.items()):
        out['0x%02x' % b] = v['acts']
        print("expr 0x%02x  case=%-3d h=%08x  %s" % (b, v['case'], v['handler'], v['acts']))
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
              'evaltab.json'), 'w'), indent=0)
