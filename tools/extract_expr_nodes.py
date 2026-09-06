"""Extract the script VM's expression model from the engine itself.

0x00436B00 is the expression reader::

    call 0x00438FA0            read the selector byte
    cmp  esi, 0x5D / ja        selectors are 0x00..0x5D
    mov  cl, [0x00437380+esi]  selector -> kind
    jmp  *0x00437288(,ecx,4)   kind -> handler

so a selector's payload is a property of its *kind's* handler, and both tables
are in the image.

**This file used to carry its own walker, and the walker was wrong.**  On a
``call`` it compared the target against the readers it knew and otherwise
stepped straight over it, so any handler that reads through an intermediate
function reported "consumes nothing".  It is not a rare shape -- kind 0x0D
(selectors 0x19..0x23) is::

    0x00436C49  add  $-0x19, %eax        ; index within the family
                call 0x00438C40          ; <- stepped over
    0x00438C40  call 0x00438FA0          ; READ_U8
                call 0x00437490          ; READ_EXPR_DEREF

i.e. ``u8 + expr``.  The old output claimed 32 selectors were leaves and
disagreed with ``docs/opcodes.json`` for 67 of 94; almost all of that was this
bug plus not knowing the u32 reader at 0x00438FE0.  Following delegation, the
engine and ``docs/opcodes.json`` agree for **92 of 94**, and the last two are
context-dependent in the engine.

So the walk now comes from :mod:`opcode_operands`, which already did this
correctly -- one walker, not two that can drift apart.
"""
from __future__ import annotations

import collections
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import opcode_operands as oo                       # noqa: E402

#: selector -> kind (u8), and kind -> handler (u32)
KIND_TAB, JMP_TAB = 0x00437380, 0x00437288
#: ``cmp esi,0x5D / ja <error>`` -- the engine refuses anything above this.
MAXSEL = 0x5D

OUT = "docs/expr-nodes.json"


def kind_of(sel: int) -> int:
    return oo.IMG[oo.PEO.va2off(KIND_TAB + sel)]


def handler_of(kind: int) -> int:
    return struct.unpack_from("<I", oo.IMG, oo.PEO.va2off(JMP_TAB + kind * 4))[0]


def payloads() -> "tuple[dict, dict]":
    """``({selector: [kind, ...] | None}, {kind: reason})`` -- None = undecidable."""
    kinds = {s: kind_of(s) for s in range(MAXSEL + 1)}
    shape, why = {}, {}
    for k in sorted(set(kinds.values())):
        h = handler_of(k)
        try:
            r = oo.reads(h)
        except oo.Ambiguous as exc:
            shape[k], why[k] = None, str(exc)
            continue
        if len(r) != 1:
            shape[k], why[k] = None, "paths disagree: %s" % sorted(r)
        else:
            shape[k] = oo.spec(next(iter(r)))
    return {s: shape[kinds[s]] for s in kinds}, why


def main() -> int:
    out, why = payloads()
    kinds = {s: kind_of(s) for s in range(MAXSEL + 1)}
    cur = json.load(open("docs/opcodes.json", encoding="utf-8"))["expressions"]["nodes"]
    bykey = {int(k, 16): k for k in cur}

    agree, differ, undecidable = [], [], []
    for s in range(MAXSEL + 1):
        ours = cur.get(bykey.get(s, ""))
        got = out[s]
        if got is None:
            undecidable.append(s)
        elif ours == got:
            agree.append(s)
        else:
            differ.append((s, ours, got))

    print("selectors 0x00..0x%02X, %d distinct kinds"
          % (MAXSEL, len(set(kinds.values()))))
    print("agree with docs/opcodes.json: %d   differ: %d   undecidable: %d"
          % (len(agree), len(differ), len(undecidable)))
    for s, ours, got in differ:
        print("   0x%02X  docs=%-16s engine=%s" % (s, ours, got))
    for s in undecidable:
        print("   0x%02X  kind 0x%02X: %s" % (s, kinds[s], why[kinds[s]][:80]))

    doc = {
        "_about": (
            "Expression-node model recovered from the engine.  0x00436B00 reads a "
            "selector byte, maps it through the u8 table at 0x00437380 "
            "(selector -> kind), and dispatches through the u32 table at "
            "0x00437288 (kind -> handler).  Each handler is walked as a "
            "control-flow graph, following calls into their callees, counting "
            "0x00438FA0 (u8) / 0x00438FC0 (u16) / 0x00438FE0 (u32) and treating "
            "0x00436B00 / 0x00437490 as one opaque sub-expression."),
        "_status": (
            "Agrees with docs/opcodes.json for %d of %d selectors.  %d are "
            "context-dependent in the engine and cannot be modelled as a constant "
            "payload; docs/opcodes.json keeps its own value for those."
            % (len(agree), MAXSEL + 1, len(undecidable))),
        "selectors": {
            "0x%02X" % s: {
                "kind": "0x%02X" % kinds[s],
                "handler": "0x%08X" % handler_of(kinds[s]),
                "engine": out[s],
                "current": cur.get(bykey.get(s, "")),
                "note": why.get(kinds[s], ""),
            } for s in range(MAXSEL + 1)},
    }
    groups = collections.defaultdict(list)
    for s in range(MAXSEL + 1):
        groups["null" if out[s] is None else "+".join(out[s]) or "[]"].append("0x%02X" % s)
    doc["shapes"] = dict(groups)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print("\nwritten to %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
