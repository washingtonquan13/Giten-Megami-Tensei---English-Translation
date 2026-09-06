"""What does an opcode handler actually consume?  Ask the engine.

Operands reach the VM through three readers, all of which bottom out in the
interpreter byte fetch family -- 0x00438E50 is the one the overlay hooks:

    0x00438FA0   read one byte      (fetcher 0x438E50)
    0x00438FC0   read two bytes     (fetcher 0x438E80)
    0x00438FE0   read four bytes    (fetcher 0x438EC0)

so an opcode's operand list is exactly the sequence of reads its handler
performs.  Handlers delegate, sometimes three or four levels deep, so this is
inter-procedural: the reads of a call are the reads of its callee.

Three rules learned the hard way:

* **Follow control flow, never a linear scan.**  Handlers are cases of a jump
  table; they share epilogues and jump into one another, so "stop at the first
  ret" runs one case into the next.
* **Reachability is not consumption.**  *Every* handler can reach the byte fetch,
  because the expression reader does.  What matters is how many reads lie on the
  path, so 0x00436B00 (and its wrapper 0x00437490, ``read_expr(); deref``) are
  treated as a single opaque ``expr`` rather than recursed into.
* **Know every reader, or delegation looks like a leaf.**  A handler that reads
  through an intermediate function reports nothing unless the walk follows the
  call *and* recognises what it reaches.  Missing 0x00438FE0 made expression
  selector 0x02 look like a leaf when it is a ``u32``; a walker that stepped over
  unknown calls entirely made 32 selectors look like leaves when they are
  ``u8 + expr``.  Both produced a confident, wrong table.

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

#: The three stream readers.  All share one shape -- load the interpreter state
#: from 0x491160, push the PC slot, call a fetcher -- and differ only in the
#: fetcher: 0x438E50 (1 byte), 0x438E80 (2), 0x438EC0 (4).  0x438FE0 was missed
#: on the first pass, which is why expression selector 0x02 looked like a leaf
#: when it is a ``u32``.
READ_U8, READ_U16, READ_U32 = 0x00438FA0, 0x00438FC0, 0x00438FE0
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


#: Addresses known to be real instruction boundaries: function entries we were
#: asked to walk, and the targets of calls and jumps taken from them.
_ENTRIES: "set[int]" = set()


def _at(va):
    """The instruction at ``va``, decoded from the nearest known good boundary.

    A linear sweep stays aligned only as long as it decodes real instructions, and
    a 0x200-byte window routinely runs off the end of a small function into
    padding or data and then drifts.  Consulting *any* cache that happens to
    contain ``va`` therefore returns misaligned instructions depending on what
    was walked first -- which made expression selector 0x59 read as a leaf in a
    full run and as ``u8 + expr`` when walked first in a fresh process.

    So decode from the greatest known entry at or below ``va``, and if there is
    none, treat ``va`` itself as the boundary.
    """
    if va in _CACHE and va in _CACHE[va]:
        return _CACHE[va][va]
    bases = [b for b in _ENTRIES if b <= va < b + 0x200]
    if bases:
        best = max(bases)
        ins = _sweep(best).get(va)
        if ins is not None:
            return ins
    return _sweep(va).get(va)


def _jump_table(ops, limit=64):
    """Targets of a `jmp *0xTABLE(,%reg,scale)`, read out of the image.

    The entry count is not in the instruction -- it is in the `cmp $N` that
    guards it -- so read u32s while they look like addresses inside .text and
    stop at the first that does not.  Erring long is the safe direction: a spare
    target can only add a path, and a *disagreement* between paths is what makes
    an opcode context-dependent, so this cannot silently claim a fixed length
    that the engine does not have.
    """
    m = _HEX.search(ops)
    if not m:
        return []
    tab, out = int(m.group(1), 16), []
    for i in range(limit):
        try:
            off = PEO.va2off(tab + i * 4)
        except Exception:
            break
        if off + 4 > len(IMG):
            break
        t = struct.unpack_from("<I", IMG, off)[0]
        if not (TEXT_LO <= t < TEXT_HI):
            break
        out.append(t)
    return out


class Ambiguous(RuntimeError):
    pass


def reads(va, depth=0, seen=None):
    """``{(u8 reads, u16 reads, u32 reads, sub-expressions)}`` over every path."""
    if depth > 8:
        return {(0, 0, 0, 0)}
    seen = set() if seen is None else seen
    if va in seen:                                # recursion: contributes nothing
        return {(0, 0, 0, 0)}
    seen = seen | {va}
    _ENTRIES.add(va)

    results, stack, visited = set(), [(va, 0, 0, 0, 0, 0)], set()
    while stack:
        addr, a, b, u, c, steps = stack.pop()
        if steps > 600 or len(results) > 24:
            continue
        while True:
            ins = _at(addr)
            if ins is None:
                results.add((a, b, u, c))
                break
            mnem, ops, size = ins
            key = (addr, a, b, u, c)
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
                elif t == READ_U32:
                    u += 1
                elif t in (EXPR, EXPR_DEREF):
                    c += 1
                elif TEXT_LO <= t < TEXT_HI:
                    sub = reads(t, depth + 1, seen)
                    if len(sub) != 1:
                        raise Ambiguous("callee 0x%08X of 0x%08X is "
                                        "context-dependent" % (t, va))
                    da, db, du, dc = next(iter(sub))
                    a, b, u, c = a + da, b + db, u + du, c + dc
                addr += size
                continue
            if mnem in STOP:
                results.add((a, b, u, c))
                break
            if mnem in UNCOND:
                if ops.lstrip().startswith("*"):
                    # `jmp *0xTABLE(,%reg,4)` -- a switch.  The hex in the operand
                    # is the *table*, not a target; following it as code decodes
                    # data and invents paths that consume bytes nothing consumes.
                    # That is what made expression selectors 0x4B and 0x4F look
                    # context-dependent when both are plainly one `expr`.
                    tgts = _jump_table(ops)
                    if not tgts:
                        results.add((a, b, u, c))
                        break
                    for t in tgts[1:]:
                        _ENTRIES.add(t)
                        stack.append((t, a, b, u, c, steps + 1))
                    addr = tgts[0]
                    _ENTRIES.add(addr)
                    steps += 1
                    continue
                m = _HEX.search(ops)
                if not m:
                    results.add((a, b, u, c))
                    break
                addr = int(m.group(1), 16)
                _ENTRIES.add(addr)
                steps += 1
                continue
            if mnem in COND:
                m = _HEX.search(ops)
                if m:
                    _ENTRIES.add(int(m.group(1), 16))
                    stack.append((int(m.group(1), 16), a, b, u, c, steps + 1))
                addr += size
                steps += 1
                continue
            addr += size
    return results or {(0, 0, 0, 0)}


def handler(idx):
    return struct.unpack_from("<I", IMG, PEO.va2off(DISPATCH + idx * 4))[0]


def spec(shape):
    a, b, u, c = shape
    return ["u8"] * a + ["u16"] * b + ["u32"] * u + ["expr"] * c


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
