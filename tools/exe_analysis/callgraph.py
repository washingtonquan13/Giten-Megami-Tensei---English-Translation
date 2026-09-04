"""callgraph.py -- crude but complete call graph of dds_en.exe .text.

Scans every E8/E9 rel32 in .text, attributes it to the nearest preceding
function entry (a function entry = any address that is the target of some E8),
and lets you ask "which opcode handlers can reach primitive X".
"""
import os, sys, struct, bisect, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from da import _p, _buf

s = [x for x in _p.sections if x['name'] == '.text'][0]
BASE = s['vaddr'] + _p.imagebase
OFF = _p.va2off(BASE)
N = s['rawsize']
END = BASE + N

def scan():
    sites = []   # (site_va, target_va, is_jmp)
    for i in range(N - 5):
        b = _buf[OFF+i]
        if b in (0xE8, 0xE9):
            t = BASE + i + 5 + struct.unpack_from('<i', _buf, OFF+i+1)[0]
            if BASE <= t < END:
                sites.append((BASE+i, t, b == 0xE9))
    return sites

SITES = scan()
def jumptable_targets():
    """Opcode handlers are reached through the dispatch table, not by call."""
    out = set()
    o = _p.va2off(0x4318B0)
    for k in range(0x2FE):
        out.add(struct.unpack_from('<I', _buf, o + 4*k)[0])
    return out

ENTRIES = sorted({t for _, t, j in SITES if not j} | jumptable_targets())

def owner(va):
    k = bisect.bisect_right(ENTRIES, va) - 1
    return ENTRIES[k] if k >= 0 else None

GRAPH = collections.defaultdict(set)   # caller_entry -> set(callee)
for site, t, isjmp in SITES:
    o = owner(site)
    if o is not None:
        GRAPH[o].add(t)

def reaches(start, targets, maxdepth=6):
    """BFS from start; return the set of `targets` reachable and the depth."""
    seen = {start}; frontier = [start]; hit = {}
    for d in range(maxdepth):
        nxt = []
        for f in frontier:
            for c in GRAPH.get(f, ()):
                if c in targets and c not in hit: hit[c] = d + 1
                if c not in seen:
                    seen.add(c); nxt.append(c)
        frontier = nxt
        if not frontier: break
    return hit

if __name__ == '__main__':
    print("call sites: %d  distinct entries: %d" % (len(SITES), len(ENTRIES)))
