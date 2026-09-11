"""Every variable-length opcode has a verdict, and the verdict is re-derived.

`docs/opcodes.json` marks 272 opcodes variable-length.  The static model is only
sound if each one's *length* is a function of the operand bytes -- if any of them
consumed a different number of bytes depending on game state, extraction and the
byte build would agree with each other while both were wrong, which is the blind
spot `1EBE` cost 442 spans of English over bytes that were never text.

`docs/handler-determinism.md` is the table, generated from
`docs/handler-determinism.json` (one fresh subprocess per handler; the walker's
caches make a long in-process run order-dependent).  This file asserts three
things: the list of variable opcodes is re-derived here rather than copied, every
one of them has a row, and the doc's verdicts are what re-classifying the raw
walk produces -- so the table cannot be edited into agreement by hand.
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))

import handler_determinism as hd

ROW = re.compile(r"^\| `(0x[0-9A-F]{3})` \| .* \| \*\*([a-z-]+)\*\* \| ")
VERDICTS = {hd.BYTE, hd.CALLER, hd.STREAM, hd.RUNTIME}

#: The only opcodes whose length is NOT a function of their bytes.  Both are the
#: same site: `1FA7`/`1FA8`'s worker `0x00435620` reads expressions until one
#: **evaluates** to -1, which a static walk cannot know in general.
#: `vmops._read_expr_list` models it as "stop after a two-byte leaf whose payload
#: is 0xFF" -- true at all five sites in the corpus -- and raises rather than
#: guessing anywhere else.
RUNTIME_OPCODES = {"0x1A7", "0x1A8"}


def _doc_rows():
    with io.open(hd.DOC, encoding="utf-8") as fh:
        out = {}
        for ln in fh:
            m = ROW.match(ln)
            if m:
                out[m.group(1)] = m.group(2)
    return out


def test_every_variable_length_opcode_has_a_verdict():
    want = hd.variable_opcodes()
    assert len(want) == 272, len(want)
    got = _doc_rows()
    missing = [k for k in want if k not in got]
    extra = [k for k in got if k not in want]
    assert not missing, "no verdict for %s" % missing[:10]
    assert not extra, "verdict for a fixed-length opcode: %s" % extra[:10]
    bad = {k: v for k, v in got.items() if v not in VERDICTS}
    assert not bad, bad


def test_the_only_runtime_dependent_opcodes_are_the_expression_list():
    got = _doc_rows()
    runtime = {k for k, v in got.items() if v == hd.RUNTIME}
    assert runtime == RUNTIME_OPCODES, sorted(runtime)
    # and the model says the same thing about them
    ops = hd.load_opcodes()
    for k in RUNTIME_OPCODES:
        kinds = [o["kind"] for o in ops[k]["operands"]]
        assert "expr_list" in kinds, (k, kinds)


def test_nothing_is_unresolved():
    """A walk that fails is not an answer; it has to be run down.

    15 of the 272 failed on a real bug in `tools/opcode_operands._jump_table`
    (`PE.va2off` *returns* None for an address in no section rather than
    raising, and the `except Exception` around it hid that), two timed out and
    three lost their objdump to resource contention.  All were re-walked.
    """
    got = _doc_rows()
    assert hd.UNRESOLVED not in got.values(), \
        sorted(k for k, v in got.items() if v == hd.UNRESOLVED)


def test_the_table_is_what_re_classifying_the_raw_walk_produces():
    """The doc is generated; a hand edit to it fails here."""
    rows = hd.classify()
    fresh = {r["opcode"]: r["verdict"] for r in rows}
    assert fresh == _doc_rows(), [
        (k, fresh[k], _doc_rows().get(k)) for k in sorted(fresh)
        if fresh[k] != _doc_rows().get(k)][:10]


def test_the_raw_walk_covers_every_variable_opcode_and_names_its_handler():
    """Every opcode was attempted, and the walk agrees about which code to read.

    A walk may legitimately fail to *finish* -- the two `pairs_ff` opcodes loop
    over their term reader and the walker enumerates paths -- and where it does,
    the shape is one `vmops` models by hand and `verdict()` says so.  What may
    never happen is a variable opcode nobody looked at, or a walk that read a
    different handler than `docs/opcodes.json` names.
    """
    import json
    with io.open(hd.WALK_JSON, encoding="utf-8") as fh:
        res = json.load(fh)
    ops = hd.load_opcodes()
    for k in hd.variable_opcodes(ops):
        assert k in res, k
        if "error" in res[k]:
            kinds = [o["kind"] for o in ops[k]["operands"]]
            assert any(x in hd.SPEC_RULES for x in kinds), (
                "%s: walk failed (%s) and its shape is not hand-modelled"
                % (k, res[k]["error"][:120]))
            continue
        assert res[k]["handler"].lower() == ops[k]["handler"].lower(), (
            "%s: the walk read handler %s, opcodes.json says %s"
            % (k, res[k]["handler"], ops[k]["handler"]))


def test_every_ambiguous_callee_is_one_already_read_by_hand():
    """A new context-dependent callee is a finding, not a table entry."""
    import json
    with io.open(hd.WALK_JSON, encoding="utf-8") as fh:
        res = json.load(fh)
    seen = set()
    for k, v in res.items():
        if "ambiguous" not in v:
            continue
        addr = int(v["ambiguous"].split("callee ")[-1].split(" ")[0], 16)
        seen.add(addr)
    assert seen <= set(hd.AMBIGUOUS_CALLEES), [
        hex(a) for a in sorted(seen - set(hd.AMBIGUOUS_CALLEES))]
