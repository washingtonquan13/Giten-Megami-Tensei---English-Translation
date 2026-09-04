"""Recover the Giten script VM opcode table (operand byte counts) from dds_en.exe.

The VM dispatcher is at VA 0x42FF50:
    exec_op(u16 op):  ds:0x481228 = op
                      if op > 0x2FD -> default (0x4318AA, no-op)
                      jmp DWORD PTR [op*4 + 0x4318B0]
Index space:
    0x000..0x0FF  bare opcode byte
    0x100..0x1FF  `1F xx`   (handler 0x42FF97 fetches xx, adds 0x100)
    0x200..0x2FD  `1E xx`   (handler 0x42FF86 fetches xx, adds 0x200)
    0x300..       `1D xx`   (handler 0x42FF75 adds 0x300 -> always > 0x2FD -> no-op)

Operands are pulled from the script stream by:
    0x438FA0 -> 0x438E50   read u8
    0x438FC0 -> 0x438E80   read u16 LE
    0x438FE0 -> 0x438EC0   read u32 LE
This script walks each handler (and the functions it tails into) counting those
reads on the straight-line path, which yields operand byte counts.
"""
import os, sys, re, struct, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from da import disasm, read, _p, _buf

TABLE_VA = 0x4318B0
TABLE_N = 0x2FE
DEFAULT = 0x4318AA
FETCH = {0x438FA0: 1, 0x438FC0: 2, 0x438FE0: 4,
         0x438E50: 1, 0x438E80: 2, 0x438EC0: 4}

def table():
    o = _p.va2off(TABLE_VA)
    return [struct.unpack_from('<I', _buf, o + 4 * k)[0] for k in range(TABLE_N)]

LINE = re.compile(r'^\s*([0-9a-f]+):\t[0-9a-f ]+\t(\S+)\s*(.*)$')

_blocks = {}
def block(va, limit=0x180):
    """Linear instruction list from va until ret/jmp-out, as (addr, mnem, ops)."""
    if va in _blocks: return _blocks[va]
    out = []
    for l in disasm(va, limit).splitlines():
        m = LINE.match(l)
        if not m: continue
        a = int(m.group(1), 16); mn = m.group(2); op = m.group(3)
        out.append((a, mn, op))
        if mn in ('ret', 'leave', 'hlt'): break
        if mn == 'jmp' and op.startswith('0x'): break
    _blocks[va] = out
    return out

def scan(va, depth, seen):
    """Count operand bytes fetched on the straight-line path from va."""
    if depth < 0 or va in seen: return 0, []
    seen = seen | {va}
    n = 0; calls = []
    for a, mn, op in block(va):
        if mn in ('call', 'jmp') and op.startswith('0x'):
            t = int(op, 16)
            if t in FETCH:
                n += FETCH[t]
            else:
                calls.append(t)
    # follow callees (handlers are thin wrappers around the real routine)
    for t in calls:
        sub, _ = scan(t, depth - 1, seen)
        n += sub
    return n, calls

def label(i):
    if i < 0x100: return "%02X" % i
    if i < 0x200: return "1F %02X" % (i - 0x100)
    return "1E %02X" % (i - 0x200)

if __name__ == '__main__':
    DEPTH = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    T = table()
    rows = []
    for i, h in enumerate(T):
        if h == DEFAULT:
            rows.append((i, h, None)); continue
        n, _ = scan(h, DEPTH, frozenset())
        rows.append((i, h, n))
    for i, h, n in rows:
        if n is None: continue
        print("%-8s idx=0x%03x handler=%08x operand_bytes=%d" % (label(i), i, h, n))
    print("\nunimplemented (dispatch to no-op 0x4318AA): %d of %d"
          % (sum(1 for r in rows if r[2] is None), len(rows)))
