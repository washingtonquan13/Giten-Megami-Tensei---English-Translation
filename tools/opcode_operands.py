"""What does an opcode handler actually consume?  Ask the engine.

Operands reach the VM through two readers, both of which bottom out in the
interpreter byte fetch at 0x00438E50 -- the same function the overlay hooks:

    0x00438FA0   read one byte
    0x00438FC0   read two bytes

so an opcode's operand list is exactly the sequence of reads its handler
performs.  Handlers delegate, sometimes three or four levels deep, so this is
inter-procedural: the reads of a call are the reads of its callee.

Two rules learned the hard way:

* **Follow control flow, never a linear scan.**  Handlers are cases of a jump
  table; they share epilogues and jump into one another, so "stop at the first
  ret" runs one case into the next.
* **Reachability is not consumption.**  *Every* handler can reach the byte fetch,
  because the expression reader does.  What matters is how many reads lie on the
  path, so 0x00436B00 (and its wrapper 0x00437490, ``read_expr(); deref``) are
  treated as a single opaque ``expr`` rather than recursed into.

If different paths through a handler disagree, the opcode is context-dependent
and is reported as such instead of being given a constant operand list.
"""
from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten.exe import patch                      # noqa: E402
from giten.exe.pe import PE                      # noqa: E402

IMG = patch.apply(open(patch.ORG, "rb").read(), "release")
PEO = PE(IMG, "o")

READ_U8, READ_U16 = 0x00438FA0, 0x00438FC0
EXPR, EXPR_DEREF = 0x00436B00, 0x00437490
DISPATCH = 0x004318B0
TEXT_LO, TEXT_HI = 0x00401000, 0x004632C4

_LINE = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(\S+)\s*(.*)$")
_HEX = re.compile(r"0x([0-9a-f]+)")
UNCOND = {"jmp"}
COND = {"je", "jne", "jz", "jnz", "ja", "jae", "jb", "jbe", "jg", "jge", "jl",
        "jle", "js", "jns", "jo", "jno", "jp", "jnp", "jcxz", "loop"}
STOP = {"ret", "retw", "hlt", "iret"}

_TMP = tempfile.mkdtemp(prefix="giten-ops-")
_CACHE: "dict[int, tuple]" = {}


def _sweep(va, n=0x200):
    """Linear disassembly from ``va``; ``va`` must be an instruction boundary."""
    if va in _CACHE:
        return _CACHE[va]
    try:
        off = PEO.va2off(va)
    except Exception:
        _CACHE[va] = {}
        return {}
    p = os.path.join(_TMP, "%08x.bin" % va)
    with open(p, "wb") as fh:
        fh.write(IMG[off:off + n])
    out = subprocess.run(["objdump", "-D", "-b", "binary", "-m", "i386",
                          "--adjust-vma=0x%X" % va, p],
                         capture_output=True, text=True, check=True).stdout
    ins = {}
    for ln in out.splitlines():
        m = _LINE.match(ln)
        if m:
            ins[int(m.group(1), 16)] = (m.group(3), m.group(4),
                                        len(m.group(2).split()))
    _CACHE[va] = ins
    return ins


def _at(va):
    """The instruction at ``va``, re-sweeping from it if the cache desynced."""
    for base in list(_CACHE):
        if base <= va < base + 0x200 and va in _CACHE[base]:
            return _CACHE[base][va]
    return _sweep(va).get(va)


class Ambiguous(RuntimeError):
    pass


def reads(va, depth=0, seen=None):
    """``{(u8 reads, u16 reads, sub-expressions)}`` over every path through ``va``."""
    if depth > 8:
        return {(0, 0, 0)}
    seen = set() if seen is None else seen
    if va in seen:                                # recursion: contributes nothing
        return {(0, 0, 0)}
    seen = seen | {va}

    results, stack, visited = set(), [(va, 0, 0, 0, 0)], set()
    while stack:
        addr, a, b, c, steps = stack.pop()
        if steps > 600 or len(results) > 24:
            continue
        while True:
            ins = _at(addr)
            if ins is None:
                results.add((a, b, c))
                break
            mnem, ops, size = ins
            key = (addr, a, b, c)
            if key in visited:
                break
            visited.add(key)
            if mnem == "call":
                m = _HEX.search(ops)
                t = int(m.group(1), 16) if m else 0
                if t == READ_U8:
                    a += 1
                elif t == READ_U16:
                    b += 1
                elif t in (EXPR, EXPR_DEREF):
                    c += 1
                elif TEXT_LO <= t < TEXT_HI:
                    sub = reads(t, depth + 1, seen)
                    if len(sub) != 1:
                        raise Ambiguous("callee 0x%08X of 0x%08X is "
                                        "context-dependent" % (t, va))
                    da, db, dc = next(iter(sub))
                    a, b, c = a + da, b + db, c + dc
                addr += size
                continue
            if mnem in STOP:
                results.add((a, b, c))
                break
            if mnem in UNCOND:
                m = _HEX.search(ops)
                if not m:
                    results.add((a, b, c))
                    break
                addr = int(m.group(1), 16)
                steps += 1
                continue
            if mnem in COND:
                m = _HEX.search(ops)
                if m:
                    stack.append((int(m.group(1), 16), a, b, c, steps + 1))
                addr += size
                steps += 1
                continue
            addr += size
    return results or {(0, 0, 0)}


def handler(idx):
    return struct.unpack_from("<I", IMG, PEO.va2off(DISPATCH + idx * 4))[0]


def spec(shape):
    a, b, c = shape
    return ["u8"] * a + ["u16"] * b + ["expr"] * c


if __name__ == "__main__":
    import json

    doc = json.load(open("docs/opcodes.json"))
    want = sys.argv[1:] or ["0x17F", "0x180", "0x182", "0x183", "0x184",
                            "0x001", "0x018", "0x10D"]
    print("%-7s %-30s %-30s %s" % ("opcode", "table claims", "engine", "agree"))
    for k in want:
        idx = int(k, 16)
        h = handler(idx)
        claims = [o["kind"] for o in doc["opcodes"][k]["operands"]]
        try:
            r = reads(h)
        except Ambiguous as exc:
            print("%-7s %-30s %s" % (k, str(claims), "AMBIGUOUS: %s" % exc))
            continue
        if len(r) != 1:
            print("%-7s %-30s %-30s %s"
                  % (k, str(claims), "context-dependent: %s" % sorted(r), "?"))
            continue
        got = spec(next(iter(r)))
        # rel16 is a u16 that happens to be a branch; compare by size
        norm = ["u16" if x == "rel16" else x for x in claims]
        print("%-7s %-30s %-30s %s"
              % (k, str(claims), str(got), "yes" if norm == got else "NO"))
