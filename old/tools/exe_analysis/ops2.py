"""ops2.py -- full opcode analysis for the Giten script VM in dds_en.exe.

Beyond opcodes.py's operand-byte count, this walks each handler's local CFG and
records which VM primitives it reaches, so we can classify opcodes as
branch/offset-bearing, script-switching, text-emitting, etc.
"""
import os, sys, re, struct, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from da import disasm, _p, _buf

TABLE_VA, TABLE_N, DEFAULT = 0x4318B0, 0x2FE, 0x4318AA

# operand readers (bytes pulled from the script stream)
FETCH = {0x438FA0: 1, 0x438FC0: 2, 0x438FE0: 4,
         0x438E50: 1, 0x438E80: 2, 0x438EC0: 4}
# VM primitives worth tagging
PRIM = {
    0x433EC0: 'reltarget',      # u16 operand -> pc_after + imm16
    0x433EE0: 'jump',           # reltarget then set_pc
    0x433EF0: 'cond_jump',      # set_pc(target) if cond==0
    0x433F10: 'gosub',          # run at target, then restore pc
    0x433C40: 'set_pc',
    0x433C50: 'set_script',
    0x433C70: 'set_script2',
    0x438F00: 'read_char',
    0x439150: 'submenu',
}
# reltarget itself consumes a u16
PRIM_FETCH = {0x433EC0: 2, 0x433EE0: 2, 0x433F10: 2}

LINE = re.compile(r'^\s*([0-9a-f]+):\t[0-9a-f ]+\t(\S+)\s*(.*)$')
_dis = {}

def ins(va, n=0x200):
    if va not in _dis:
        out = []
        for l in disasm(va, n).splitlines():
            m = LINE.match(l)
            if m: out.append((int(m.group(1), 16), m.group(2), m.group(3)))
        _dis[va] = out
    return _dis[va]

JCC = set(('je jne jz jnz jg jge jl jle ja jae jb jbe js jns jo jno jp jnp '
           'jecxz jcxz').split())

def walk(entry, depth, seen_fn):
    """Explore the handler's CFG. Returns (min_bytes, max_bytes, prims, calls)."""
    if depth < 0 or entry in seen_fn:
        return 0, 0, set(), set()
    seen_fn = seen_fn | {entry}
    prims = set(); calls = set()
    body = ins(entry)
    idx = {a: k for k, (a, m, o) in enumerate(body)}
    results = {}
    def block(start_addr, visited):
        nonlocal prims, calls
        if start_addr in visited: return (0, 0)
        visited = visited | {start_addr}
        k = idx.get(start_addr)
        if k is None: return (0, 0)
        lo = hi = 0
        while k < len(body):
            a, mn, op = body[k]
            if mn in ('call',) and op.startswith('0x'):
                t = int(op, 16)
                if t in FETCH: lo += FETCH[t]; hi += FETCH[t]
                elif t in PRIM:
                    prims.add(PRIM[t])
                    n = PRIM_FETCH.get(t, 0); lo += n; hi += n
                else:
                    calls.add(t)
                    s = walk(t, depth - 1, seen_fn)
                    prims |= s[2]; calls |= s[3]
                    lo += s[0]; hi += s[1]
            elif mn == 'jmp' and op.startswith('0x'):
                t = int(op, 16)
                if t in idx: k = idx[t]; continue
                if t in FETCH: lo += FETCH[t]; hi += FETCH[t]
                elif t in PRIM:
                    prims.add(PRIM[t]); n = PRIM_FETCH.get(t, 0); lo += n; hi += n
                else:
                    calls.add(t)
                    s = walk(t, depth - 1, seen_fn)
                    prims |= s[2]; calls |= s[3]; lo += s[0]; hi += s[1]
                return (lo, hi)
            elif mn in JCC and op.startswith('0x'):
                t = int(op, 16)
                b1 = block(t, visited)                      # taken
                b2 = block(body[k+1][0], visited) if k+1 < len(body) else (0,0)
                return (lo + min(b1[0], b2[0]), hi + max(b1[1], b2[1]))
            elif mn in ('ret', 'leave', 'hlt'):
                return (lo, hi)
            k += 1
        return (lo, hi)
    lo, hi = block(entry, frozenset())
    return lo, hi, prims, calls

def label(i):
    if i < 0x100: return "%02X" % i
    if i < 0x200: return "1F %02X" % (i - 0x100)
    if i < 0x300: return "1E %02X" % (i - 0x200)
    return "1D %02X" % (i - 0x300)

def analyze(depth=4):
    o = _p.va2off(TABLE_VA)
    T = [struct.unpack_from('<I', _buf, o + 4*k)[0] for k in range(TABLE_N)]
    rows = []
    for i, h in enumerate(T):
        if h == DEFAULT:
            rows.append(dict(idx=i, label=label(i), handler=h, impl=False)); continue
        lo, hi, prims, calls = walk(h, depth, frozenset())
        rows.append(dict(idx=i, label=label(i), handler=h, impl=True,
                         lo=lo, hi=hi, prims=sorted(prims)))
    return rows

if __name__ == '__main__':
    rows = analyze(int(sys.argv[1]) if len(sys.argv) > 1 else 4)
    json.dump(rows, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
              'ops2.json'), 'w'), indent=0)
    var = [r for r in rows if r.get('impl') and r['lo'] != r['hi']]
    print("implemented: %d / %d" % (sum(1 for r in rows if r['impl']), len(rows)))
    print("variable operand length (lo!=hi): %d" % len(var))
    for r in var[:60]:
        print("   %-8s idx=0x%03x h=%08x lo=%d hi=%d %s" %
              (r['label'], r['idx'], r['handler'], r['lo'], r['hi'], r['prims']))
    print("\nopcodes touching pc/branch primitives:")
    for r in rows:
        if r.get('prims'):
            print("   %-8s idx=0x%03x h=%08x bytes=%d..%d  %s" %
                  (r['label'], r['idx'], r['handler'], r['lo'], r['hi'], ','.join(r['prims'])))
