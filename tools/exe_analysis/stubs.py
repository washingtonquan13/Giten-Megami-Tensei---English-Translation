"""stubs.py -- every opcode handler is a tiny stub `push imm...; call F; ret`.

Recovering (F, args) per opcode lets us resolve the *parameterised* operand reads:
several shared routines read an extra expression only for particular argument
values (e.g. 0x4335C0 reads an expression iff its arg == 0; 0x434740 reads a third
operand iff its 2nd arg == 1).
"""
import os, sys, re, struct, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from da import _p, _buf
from evaltab import ins

TABLE_VA, TABLE_N, DEFAULT = 0x4318B0, 0x2FE, 0x4318AA

def stub(h):
    """-> (callee, [args]) if the handler is a pure `push imm*, call F` stub."""
    args = []
    for a, mn, op in ins(h, 0x40):
        if mn == 'push' and re.fullmatch(r'0x[0-9a-f]+', op):
            args.append(int(op, 16))
        elif mn in ('call', 'jmp') and op.startswith('0x'):
            return int(op, 16), args
        elif mn in ('ret', 'leave'):
            return None, args
        elif mn in ('pop', 'nop', 'xor', 'mov', 'movzx', 'add', 'sub'):
            continue
        else:
            return None, args
    return None, args

if __name__ == '__main__':
    o = _p.va2off(TABLE_VA)
    T = [struct.unpack_from('<I', _buf, o + 4*k)[0] for k in range(TABLE_N)]
    by = collections.defaultdict(list)
    for i, h in enumerate(T):
        if h == DEFAULT: continue
        f, args = stub(h)
        by[(f, tuple(args))].append(i)
    rows = sorted(by.items(), key=lambda kv: -len(kv[1]))
    for (f, args), idxs in rows:
        print("%-10s args=%-14s n=%-4d e.g. %s" %
              (('%08x' % f) if f else 'inline', str(args), len(idxs),
               ' '.join('%03x' % x for x in idxs[:8])))
