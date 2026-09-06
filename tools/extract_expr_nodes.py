"""Extract the script VM's expression model from the engine itself.

0x00436B00 is the expression reader:

    call 0x00438FA0            read the selector byte
    cmp  esi, 0x5D / ja        selectors are 0x00..0x5D
    mov  cl, [0x00437380+esi]  selector -> kind
    jmp  *0x00437288(,ecx,4)   kind -> handler

Each kind's handler is a *case* of that jump table, not a tidy function: cases
share epilogues and jump into one another.  A linear "stop at the first ret"
scan therefore runs one case into the next -- that is how the earlier attempt
invented a "5 sub-expression" node.  So walk the control-flow graph instead, and
report the payload separately for every path that ends in a `ret`: if the paths
disagree, the node is context-dependent and must not be modelled as a constant.

The region 0x00436B00..0x00437288 is disassembled once, linearly, because it is
dense code; the two tables live above it and are read as data.
"""
import collections
import os
import re
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, "C:/Giten Megami Tensei - English - v0.05/Giten Megami Tensei - English Translation")
os.chdir("C:/Giten Megami Tensei - English - v0.05/Giten Megami Tensei - English Translation")

from giten.exe import patch                      # noqa: E402
from giten.exe.pe import PE                      # noqa: E402

IMG = patch.apply(open(patch.ORG, "rb").read(), "release")
PEO = PE(IMG, "o")

CODE_LO, CODE_HI = 0x00436B00, 0x00437288        # handlers; the tables start here
JMP_TAB = 0x00437288
KIND_TAB = 0x00437380
MAXSEL = 0x5D
READ_U8 = 0x00438FA0
READ_U16 = 0x00438FC0
EXPR = 0x00436B00
EXPR_DEREF = 0x00437490                          # read_expr(); *result

_LINE = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(\S+)\s*(.*)$")
_HEX = re.compile(r"0x([0-9a-f]+)")

tmp = tempfile.mkdtemp(prefix="giten-expr-")
blob = os.path.join(tmp, "code.bin")
with open(blob, "wb") as fh:
    fh.write(IMG[PEO.va2off(CODE_LO):PEO.va2off(CODE_HI)])
out = subprocess.run(["objdump", "-D", "-b", "binary", "-m", "i386",
                      "--adjust-vma=0x%X" % CODE_LO, blob],
                     capture_output=True, text=True, check=True).stdout

INS = {}
order = []
for ln in out.splitlines():
    m = _LINE.match(ln)
    if not m:
        continue
    a = int(m.group(1), 16)
    INS[a] = (m.group(3), m.group(4), len(m.group(2).split()))
    order.append(a)

UNCOND = {"jmp"}
COND = {"je", "jne", "jz", "jnz", "ja", "jae", "jb", "jbe", "jg", "jge",
        "jl", "jle", "js", "jns", "jo", "jno", "jp", "jnp", "jcxz", "loop"}
STOP = {"ret", "retw", "hlt"}


def paths(entry, limit=4000):
    """Every ret-terminated path's (u8 reads, u16 reads, sub-expressions)."""
    results = set()
    seen_states = set()
    stack = [(entry, 0, 0, 0, 0)]
    while stack:
        addr, b1, b2, sub, steps = stack.pop()
        if steps > 400 or len(results) > 32:
            continue
        while True:
            ins = INS.get(addr)
            if ins is None:                       # left the decoded region
                results.add((b1, b2, sub))
                break
            mnem, ops, size = ins
            key = (addr, b1, b2, sub)
            if key in seen_states:
                break
            seen_states.add(key)
            if mnem == "call":
                m = _HEX.search(ops)
                t = int(m.group(1), 16) if m else 0
                if t == READ_U8:
                    b1 += 1
                elif t == READ_U16:
                    b2 += 1
                elif t in (EXPR, EXPR_DEREF):
                    sub += 1
                addr += size
                continue
            if mnem in STOP:
                results.add((b1, b2, sub))
                break
            if mnem in UNCOND:
                m = _HEX.search(ops)
                if not m:
                    results.add((b1, b2, sub))    # indirect jmp: treat as exit
                    break
                addr = int(m.group(1), 16)
                steps += 1
                continue
            if mnem in COND:
                m = _HEX.search(ops)
                if m:
                    stack.append((int(m.group(1), 16), b1, b2, sub, steps + 1))
                addr += size
                steps += 1
                continue
            addr += size
    return results


kinds = {s: IMG[PEO.va2off(KIND_TAB + s)] for s in range(MAXSEL + 1)}
handlers = {k: struct.unpack_from("<I", IMG, PEO.va2off(JMP_TAB + k * 4))[0]
            for k in sorted(set(kinds.values()))}

prof = {}
for k, h in handlers.items():
    prof[k] = paths(h)

print("kinds: %d, handlers: %d" % (len(kinds), len(handlers)))
amb = [k for k, v in prof.items() if len(v) != 1]
print("kinds whose paths disagree (context-dependent): %s"
      % (["0x%02X" % k for k in amb] or "none"))
print()

shape = {}
for s in range(MAXSEL + 1):
    v = prof[kinds[s]]
    shape[s] = sorted(v)[0] if len(v) == 1 else None

groups = collections.defaultdict(list)
for s, sh in shape.items():
    groups[sh].append(s)
print("%-26s %s" % ("(u8, u16, sub-expr)", "selectors"))
for sh, sels in sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0])):
    print("%-26s %s" % (sh, " ".join("%02X" % x for x in sels)))

import json
json.dump({"%02X" % s: shape[s] for s in shape},
          open("build/_expr_shapes.json", "w"), indent=1)
print()
print("written to build/_expr_shapes.json")
