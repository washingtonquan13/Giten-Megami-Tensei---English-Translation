"""opdesc.py -- ordered operand descriptor for every implemented script opcode.

Emits, per opcode index, the ordered list of what the handler pulls from the script
stream:  'u8' | 'u16' | 'u32' | 'expr' (a 0x436B00 expression tree) |
'rel16' (a PC-relative branch target read by 0x433EC0) | 'list_ff' (bytes up to and
including a 0xFF terminator).

Writes opdesc.json.
"""
import os, sys, re, struct, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from da import disasm, _p, _buf
from evaltab import ins, TEXT_LO, TEXT_HI

TABLE_VA, TABLE_N, DEFAULT = 0x4318B0, 0x2FE, 0x4318AA

FETCH = {0x438FA0: 'u8', 0x438FC0: 'u16', 0x438FE0: 'u32',
         0x438E50: 'u8', 0x438E80: 'u16', 0x438EC0: 'u32'}
EVAL  = {0x436B00: 'expr', 0x437490: 'expr', 0x4374A0: 'expr2', 0x437700: 'expr'}
REL   = {0x433EC0: 'rel16', 0x434680: 'rel16'}
# handlers whose operand is a 0xFF-terminated byte list (verified at 0x435CF0)
LISTFF = {0x435CF0: 'list_ff'}
STOP  = {0x433EE0: ['rel16'], 0x433F10: ['rel16']}

def trace(va, depth, seen):
    if depth < 0 or va in seen or not (TEXT_LO <= va < TEXT_HI): return []
    seen = seen | {va}
    acts = []
    for a, mn, op in ins(va):
        if mn in ('call', 'jmp') and op.startswith('0x'):
            t = int(op, 16)
            if   t in FETCH:  acts.append(FETCH[t])
            elif t in EVAL:   acts.append(EVAL[t])
            elif t in REL:    acts.append(REL[t])
            elif t in LISTFF: acts.append(LISTFF[t])
            elif t in STOP:   acts += STOP[t]
            elif mn == 'jmp': acts += trace(t, depth - 1, seen); break
            else:             acts += trace(t, depth - 1, seen)
        if mn in ('ret', 'leave'): break
        if mn == 'jmp': break
    return acts

def label(i):
    return ("%02X" % i if i < 0x100 else "1F %02X" % (i-0x100)
            if i < 0x200 else "1E %02X" % (i-0x200) if i < 0x300 else "1D %02X" % (i-0x300))

def build(depth=4):
    o = _p.va2off(TABLE_VA)
    T = [struct.unpack_from('<I', _buf, o + 4*k)[0] for k in range(TABLE_N)]
    out = {}
    for i, h in enumerate(T):
        if h == DEFAULT:
            out[i] = dict(label=label(i), handler=None, impl=False, ops=[])
        else:
            out[i] = dict(label=label(i), handler=h, impl=True,
                          ops=trace(h, depth, frozenset()))
    return out

if __name__ == '__main__':
    tab = build()
    json.dump({str(k): v for k, v in tab.items()},
              open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'opdesc.json'), 'w'), indent=0)
    import collections
    c = collections.Counter(tuple(v['ops']) for v in tab.values() if v['impl'])
    print("implemented %d" % sum(1 for v in tab.values() if v['impl']))
    for k, n in c.most_common(30): print("  %-40s %d" % (str(k), n))
