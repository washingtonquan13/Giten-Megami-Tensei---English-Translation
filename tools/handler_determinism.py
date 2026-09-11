"""Is an opcode's length a function of its bytes, or of the game's state?

`docs/opcodes.json` marks 272 opcodes variable-length.  Every one of them is a
promise: that a tokenizer reading the script cold can say where the next token
starts.  If any of them consumed a different number of bytes depending on a
variable, a save slot or the party's composition, the whole static model would be
unsound -- and not visibly so, because extraction and the byte build share the
tokenizer and would agree with each other while both were wrong.

This settles it per opcode, from the handler.  Three ways a handler can be
length-stable, and one way it cannot:

``byte-determined``
    The walk over the handler's control flow yields exactly **one** read
    sequence.  Nothing branches; the length is the sum of the reads, and each
    read's own length comes from the operand bytes (an ``expr``'s from the
    expression grammar, which is 94/94 against the engine's own two tables).

``caller-constant``
    The handler branches, and the arms read different amounts, but the value it
    branches on is a literal the *dispatch entry* pushed -- not stream data and
    not game state.  So the length still depends only on which opcode it is.
    Two families, both already modelled: ``0x004335C0`` (the ``0x004335E0``
    worker reads an expression only when its argument is 0; every entry reaching
    it is ``push <mode>; call <thunk>`` with the mode a literal) and
    ``0x00434740`` (the ``1F8x`` family gates on ``[esp+0x10]``, also pushed).
    This is exactly the shape the 2026-09-07 sweep flagged and then cleared by
    hand; it is recorded here rather than re-derived every time.

``stream-branch``
    The handler branches on a byte it just read out of the script.  The length is
    still a function of the operand bytes -- that is what a variable-length
    encoding *is*.  The switch table (``0x004327C0``, ``4N+1`` bytes, ``N`` from
    the table's own ``0xFF`` terminator), ``1EBE``'s mode byte
    (``0x004324B0``), ``1F01``'s selector (``0x00436920``), ``1E1E``'s
    ``list_ff`` (``0x00435CF0``) and ``1F03``/``1F04``'s ``pairs_ff``.

``runtime``
    The length depends on something the bytes do not contain.  **Exactly two
    opcodes**, and they are the same site: ``1FA7``/``1FA8``, whose worker
    ``0x00435620`` reads expressions until one **evaluates** to ``0xFFFF``.  A
    static walk cannot know that in general.  ``vmops._read_expr_list`` models it
    as "stop after a two-byte leaf whose payload is ``0xFF``", which holds at all
    five sites in the corpus and raises rather than guessing anywhere else.

Run it fresh, one subprocess per opcode
---------------------------------------
``tools/opcode_operands.py``'s caches change ``_at()``'s decoding base, so a long
in-process run gives answers that depend on what was walked first (its own
docstring records selector 0x59 reading as a leaf in a full run and as
``u8 + expr`` when walked first).  ``--walk`` therefore spawns one subprocess per
opcode.  It takes about half an hour.

    python tools/handler_determinism.py --walk      # refresh the json
    python tools/handler_determinism.py             # json -> the markdown table
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

OPCODES = os.path.join(R, "docs", "opcodes.json")
WALK_JSON = os.path.join(R, "docs", "handler-determinism.json")
DOC = os.path.join(R, "docs", "handler-determinism.md")

BYTE, CALLER, STREAM, RUNTIME, UNRESOLVED = (
    "byte-determined", "caller-constant", "stream-branch", "runtime",
    "unresolved")

#: A walk that stops on "this callee is context-dependent" is not a failure --
#: it names the callee, and there are only eight of them, every one read by
#: hand.  A callee that is not in here is a finding, not a table entry --
#: `tests/test_handler_determinism.py` asserts the set never grows silently.  Address -> (verdict, the rule, where it was
#: established).
AMBIGUOUS_CALLEES = {
    0x004335C0: (CALLER,
                 "the 0x004335E0 worker: u8 u8, then an expression ONLY when "
                 "its argument is 0, then always one more.  Every entry "
                 "reaching it is `push <mode>; call <thunk>` with the mode a "
                 "literal, so mode 0 is `u8 u8 expr expr` and mode 1 is "
                 "`u8 u8 expr`",
                 "limits.md, the 0x004335E0 family (22 entries, 11 per mode)"),
    0x00434740: (CALLER,
                 "the 1F8x family: the gate is [esp+0x10], a caller-pushed "
                 "constant, and the six entries that push 1 are exactly the six "
                 "typed `rel16, expr, expr`",
                 "limits.md, the 2026-09-07 sweep (`0x434759` is a false "
                 "positive)"),
    0x004327C0: (STREAM,
                 "the switch table: `4N+1` bytes, N counted off the table's own "
                 "0xFF terminator.  The match mode is a literal push at all "
                 "nine trampolines and does not affect length",
                 "limits.md, switch tables are fully statically determinable"),
    0x004324B0: (STREAM,
                 "1EBE: a u8 mode read from the stream; non-zero takes two more "
                 "u8, zero takes six expressions",
                 "limits.md, 1EBE reads six expressions when its mode byte is 0"),
    0x00436920: (STREAM,
                 "1F01: a u8 selector read from the stream decides whether a "
                 "second u8 precedes the expression",
                 "format-notes 2.11 / vmops._read_rtstr"),
    0x00435CF0: (STREAM,
                 "1E1E: the menu rescanner's `list_ff` -- single bytes until 0xFF",
                 "limits.md, the 2026-09-07 sweep"),
    0x0043C0C0: (STREAM,
                 "1E10, the page wait: `call READ_U8` twice, the second into "
                 "si, then `sub eax,0 / je`, `dec eax / je`, `dec eax / je` -- "
                 "a third READ_U8 at 0x0043C0ED only when the second byte is 0 "
                 "or 2.  Exactly `vmops._wait_1e10`, decided by a byte that is "
                 "itself an operand",
                 "read 2026-09-11 at 0x0043C0C0-0x0043C0F7; the walker had "
                 "never reached it because `_jump_table` died on a None offset "
                 "first"),
    0x00435620: (RUNTIME,
                 "1FA7/1FA8: rel16 then expressions until one EVALUATES to "
                 "-1.  The terminator is a runtime value; vmops models it as "
                 "'a two-byte leaf whose payload is 0xFF', true at all five "
                 "corpus sites, and raises anywhere else",
                 "limits.md, 1FA7 reads expressions until one is minus one"),
}

SPEC_RULES = {
    "switch": (STREAM, "4N+1, N from the table's own 0xFF terminator"),
    "pairs_ff": (STREAM, "2-byte terms until a first byte of exactly 0xFF, "
                         "the terminator itself costing two"),
    "list_ff": (STREAM, "single bytes until 0xFF"),
    "rtstr": (STREAM, "a u8 selector decides whether a second u8 precedes the "
                      "expression"),
    "mode_1ebe": (STREAM, "a u8 mode: non-zero two more u8, zero six expressions"),
    "expr_list": (RUNTIME, "expressions until one evaluates to -1"),
    "rule:wait_1E10": (STREAM, "u8 u8, and a third u8 when the second is 0 or 2"),
}


def load_opcodes():
    with io.open(OPCODES, encoding="utf-8") as fh:
        return json.load(fh)["opcodes"]


def variable_opcodes(ops=None):
    ops = ops or load_opcodes()
    return sorted((k for k, v in ops.items() if v.get("variable")),
                  key=lambda k: int(k, 16))


# --- the walk ---------------------------------------------------------------
WALKER = r"""
import json, os, sys
R = %r
sys.path.insert(0, R); sys.path.insert(0, os.path.join(R, "tools")); os.chdir(R)
import opcode_operands as oo
idx = int(sys.argv[1], 16)
out = {"idx": "0x%%03X" %% idx}
try:
    h = oo.handler(idx)
    out["handler"] = "0x%%08X" %% h
    try:
        out["shapes"] = sorted(list(x) for x in oo.reads(h))
    except oo.Ambiguous as exc:
        out["ambiguous"] = str(exc)
except Exception as exc:
    out["error"] = "%%s: %%s" %% (type(exc).__name__, exc)
print(json.dumps(out))
""" % R


def walk(keys, workers=6, timeout=1800):
    """``{opcode: result}`` -- one fresh subprocess per opcode, always."""
    import concurrent.futures as cf
    import tempfile

    tmp = tempfile.mkdtemp(prefix="giten-det-")
    one = os.path.join(tmp, "one.py")
    with io.open(one, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(WALKER)

    def run(k):
        try:
            p = subprocess.run([sys.executable, one, k], capture_output=True,
                               text=True, timeout=timeout)
            if p.returncode != 0:
                return k, {"idx": k, "error": "exit %d: %s"
                                              % (p.returncode, p.stderr.strip()[-400:])}
            return k, json.loads(p.stdout.strip().splitlines()[-1])
        except Exception as exc:
            return k, {"idx": k, "error": "%s: %s" % (type(exc).__name__, exc)}

    out = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for k, res in ex.map(run, keys):
            out[k] = res
            print("  %s  %s" % (k, "error" if "error" in res else
                                ("ambiguous" if "ambiguous" in res else "ok")))
    return out


# --- the verdict ------------------------------------------------------------
def verdict(key, res, spec):
    """``(verdict, rule, evidence)`` for one opcode."""
    kinds = [o["kind"] for o in spec["operands"]]
    hand = next((SPEC_RULES[k] for k in kinds if k in SPEC_RULES), None)
    if "ambiguous" in res:
        addr = res["ambiguous"].split("callee ")[-1].split(" ")[0]
        hit = AMBIGUOUS_CALLEES.get(int(addr, 16))
        if hit:
            return hit[0], hit[1], "walk stops at %s; %s" % (addr, hit[2])
        return UNRESOLVED, "; ".join(kinds), "walk stops at callee %s" % addr
    if "error" in res:
        if hand:
            return hand[0], hand[1], "walk failed (%s); the shape is hand-modelled" \
                % res["error"].split(":")[0]
        return UNRESOLVED, "; ".join(kinds), "walk failed: %s" % res["error"][:80]
    shapes = res.get("shapes") or []
    if len(shapes) == 1:
        if hand:
            return hand[0], hand[1], "one read sequence, %s" % _shape(shapes[0])
        return BYTE, _shape(shapes[0]), "one read sequence over every path"
    if hand:
        return hand[0], hand[1], "%d read sequences; the shape is hand-modelled" % len(shapes)
    return UNRESOLVED, "; ".join(kinds), "%d different read sequences: %s" \
        % (len(shapes), shapes[:4])


def _shape(sh):
    a, b, u, c = sh
    bits = []
    for n, name in ((a, "u8"), (b, "u16"), (u, "u32"), (c, "expr")):
        if n:
            bits.append("%d x %s" % (n, name))
    return ", ".join(bits) or "no reads"


def classify(results=None, ops=None):
    ops = ops or load_opcodes()
    if results is None:
        with io.open(WALK_JSON, encoding="utf-8") as fh:
            results = json.load(fh)
    out = []
    for k in variable_opcodes(ops):
        res = results.get(k, {"error": "not walked"})
        v, rule, ev = verdict(k, res, ops[k])
        out.append({"opcode": k, "encoding": ops[k]["encoding"],
                    "handler": res.get("handler", ops[k]["handler"]),
                    "operands": " ".join(o["kind"] for o in ops[k]["operands"]),
                    "uses": ops[k]["uses"], "verdict": v, "rule": rule,
                    "evidence": ev})
    return out


PROSE = """\
`docs/opcodes.json` marks 272 opcodes variable-length.  Every one of them is a
promise: that a tokenizer reading the script cold can say where the next token
starts.  If any consumed a different number of bytes depending on a variable, a
save slot or the party's composition, the static model would be unsound **and
invisibly so** -- extraction and the byte build share the tokenizer, so a checker
that re-parses both sides would see them agree while both were wrong.  That is
not hypothetical: it is exactly what `1EBE` cost, 442 spans of English written
over bytes that were never text.

This settles it per opcode, from the handler, using
`tools/opcode_operands.py`'s inter-procedural walk -- **one fresh subprocess per
opcode**, because that walker's caches change its decoding base and a long
in-process run gives answers that depend on what was walked first.

Three ways a handler can be length-stable, and one way it cannot.

**`byte-determined`** -- the walk yields exactly *one* read sequence over every
path through the handler.  Nothing branches; the length is the sum of the reads,
and each read's own length comes from the operand bytes (an `expr`'s from the
expression grammar, proven 94/94 against the engine's own selector and kind
tables).

**`caller-constant`** -- the handler branches and the arms read different
amounts, but the value it branches on is a literal the *dispatch entry* pushed:
not stream data, not game state.  The length still depends only on which opcode
it is.  Two families, both already modelled: `0x004335C0` (the `0x004335E0`
worker reads an expression only when its argument is 0, and every entry reaching
it is `push <mode>; call <thunk>` with the mode a literal, so mode 0 is
`u8 u8 expr expr` and mode 1 is `u8 u8 expr`) and `0x00434740` (the `1F8x`
family gates on `[esp+0x10]`, also pushed; the six entries that push 1 are
exactly the six typed `rel16, expr, expr`).  This is the shape the 2026-09-07
sweep flagged and then cleared by hand -- recorded here so it is not re-derived
every time, and so a *new* member of either family is a finding.

**`stream-branch`** -- the handler branches on a byte it just read out of the
script.  The length is still a function of the operand bytes; that is what a
variable-length encoding *is*.  The switch table (`0x004327C0`, `4N+1` bytes,
`N` counted off the table's own `0xFF` terminator, the match mode a literal push
that does not affect length), `1EBE`'s mode byte (`0x004324B0`), `1F01`'s
selector (`0x00436920`), `1E1E`'s `list_ff` (`0x00435CF0`), `1F03`/`1F04`'s
`pairs_ff` and `1E10`'s third-byte rule.

**`runtime`** -- the length depends on something the bytes do not contain.
**Two opcodes, and they are one site**: `1FA7`/`1FA8`, whose worker
`0x00435620` reads expressions until one *evaluates* to `0xFFFF`.  A static walk
cannot know that in general.  `vmops._read_expr_list` models it as "stop after a
two-byte leaf whose payload is `0xFF`", which holds at all five sites in the
corpus, and **raises rather than guessing** anywhere else -- so a sixth site with
a computed terminator would refuse the record loudly instead of mistiling it.

A walk that stops on "this callee is context-dependent" is not a failure: it
*names* the callee, and there are only eight, every one of them read by hand.  A walk that fails to finish is allowed only where the shape is one
`vmops` models by hand (the two `pairs_ff` opcodes loop over their term reader
and the walker enumerates paths); everywhere else it is `unresolved`, and
`tests/test_handler_determinism.py` asserts there are none.

Regenerate with `python tools/handler_determinism.py --walk` (about half an
hour), or `python tools/handler_determinism.py` to rebuild the table from the
stored walk."""


def render(rows) -> str:
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    lines = ["# Handler determinism: is an opcode's length a function of its bytes?",
             "",
             "*Generated by `tools/handler_determinism.py` from "
             "`docs/handler-determinism.json`; pinned by "
             "`tests/test_handler_determinism.py`.  Do not edit the table by hand.*",
             "", PROSE, "", "## Result", "",
             "%d variable-length opcodes." % len(rows), ""]
    for v in (BYTE, CALLER, STREAM, RUNTIME, UNRESOLVED):
        if counts.get(v):
            lines.append("* **%s**: %d" % (v, counts[v]))
    lines += ["",
              "So **%d of %d are a function of the operand bytes alone**, and the "
              "%d that are not are one site: `1FA7`/`1FA8`."
              % (sum(counts.get(v, 0) for v in (BYTE, CALLER, STREAM)), len(rows),
                 counts.get(RUNTIME, 0)),
              "", "## Every variable-length opcode", "",
              "| opcode | bytes | handler | operand model | uses | verdict | "
              "the rule | evidence |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| `%s` | `%s` | `%s` | %s | %d | **%s** | %s | %s |"
                     % (r["opcode"], r["encoding"], r["handler"], r["operands"],
                        r["uses"], r["verdict"], r["rule"].replace("|", "/"),
                        r["evidence"].replace("|", "/")))
    return "\n".join(lines) + "\n"


def main(argv):
    ops = load_opcodes()
    keys = variable_opcodes(ops)
    if "--walk" in argv:
        print("walking %d handlers, one subprocess each" % len(keys))
        res = walk(keys)
        old = {}
        if os.path.exists(WALK_JSON):
            with io.open(WALK_JSON, encoding="utf-8") as fh:
                old = json.load(fh)
        old.update(res)
        with io.open(WALK_JSON, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(old, fh, indent=0, sort_keys=True)
            fh.write("\n")
        print("wrote %s" % WALK_JSON)
    rows = classify(ops=ops)
    with io.open(DOC, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(rows))
    print("wrote %s: %d rows" % (DOC, len(rows)))
    for r in rows:
        if r["verdict"] in (RUNTIME, UNRESOLVED):
            print("  %-7s %-14s %s" % (r["opcode"], r["verdict"], r["evidence"][:90]))


if __name__ == "__main__":
    main(sys.argv[1:])
