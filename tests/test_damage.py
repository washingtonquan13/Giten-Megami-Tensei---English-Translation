"""The battle-outcome table and the four result accessors.

Pins the two structural claims of ``docs/combat-damage.md`` -- everything there
that can be checked without running the game.

Why these two and not the arithmetic: the formula in section 4 is a reading of
float code and cannot be asserted from data files, but the *plumbing* around it
is entirely in the shipped scripts and in fixed exe tables, so a future retiling
change or an opcode-table edit that quietly moved a span boundary would show up
here rather than in a play-test.

The graze row is the one that earns its keep. The first draft of the document
said a graze prints no number, because record ``0x0C`` has no number token in
its text; the call that prints one is its last token, past the end of the text.
A live trace caught it. This test would have caught it too.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import files, script  # noqa: E402
from giten.exe import patch  # noqa: E402
from giten.exe.pe import PE  # noqa: E402

#: outcome code -> the record m/MS00DD:05 dispatches it to (combat-damage.md §2)
OUTCOMES = {0: 0x0A, 1: 0x0B, 2: 0x0C, 3: 0x0D, 4: 0x0E, 5: 0x0F,
            6: 0x10, 7: 0x11, 8: 0x12, 9: 0x13, 10: 0x61}

#: the records that call the damage line DD:4C rather than printing on their own
CALLS_THE_DAMAGE_LINE = (0x0C, 0x0D, 0x0E)

DAMAGE_LINE = 0x4C


def _dd():
    return script.parse("m/MS00DD.BIN", files.read_source("m/MS00DD.BIN"))


def _rec(sc, rec_id):
    for r in sc.iter_records():
        if r.id == rec_id:
            return r
    raise AssertionError("m/MS00DD has no record 0x%02X" % rec_id)


def test_the_outcome_switch_dispatches_eleven_codes_to_eleven_records():
    """m/MS00DD:05 is `var[7] = f(0); switch (var[7])` onto the message set."""
    rec = _rec(_dd(), 0x05)
    toks = rec.span_tokens
    assert toks[0].idx == 0x1E8, "record 0x05 must open with an assignment"
    assert rec.data[toks[0].off:toks[0].end] == bytes.fromhex("1fe803074b0000"), (
        "expected `var[7] = battle_result(0)`, got %s"
        % rec.data[toks[0].off:toks[0].end].hex(" "))

    sw = next(t for t in toks if t.idx == 0x11A)
    body = rec.data[sw.off:sw.end]
    assert body[:4] == bytes.fromhex("1f1a0307"), (
        "the switch must key on var[7], got %s" % body[:4].hex(" "))

    # 0xFF-terminated table of [u8 case][u8 kind][u16]; kind 0 == (file, record)
    table, i = {}, 4
    while body[i] != 0xFF:
        case, kind, f, r = body[i], body[i + 1], body[i + 2], body[i + 3]
        assert kind == 0, "case %d is a rel16 branch, not a record reference" % case
        assert f == 0xDD, "case %d leaves MS00DD for file %02X" % (case, f)
        table[case] = r
        i += 4
    assert table == OUTCOMES, "outcome table drifted:\n  %r\nexpected\n  %r" % (
        table, OUTCOMES)


def test_a_graze_prints_its_number_like_any_other_hit():
    """Graze, ordinary hit and critical all *call* DD:4C, the damage line.

    Opcode 0x0D is a call, so the record resumes afterwards -- which is why a
    trace of a real fight shows `05 0D 4C 0D` and not `05 0D 4C`.
    """
    sc = _dd()
    for rec_id in CALLS_THE_DAMAGE_LINE:
        rec = _rec(sc, rec_id)
        calls = [t for t in rec.span_tokens if t.idx == 0x00D
                 and rec.data[t.off + 1] == 0xDD
                 and rec.data[t.off + 2] == DAMAGE_LINE]
        assert calls, ("record 0x%02X no longer calls DD:%02X -- if this is "
                       "deliberate, combat-damage.md §2 is now wrong"
                       % (rec_id, DAMAGE_LINE))

    dmg = _rec(sc, DAMAGE_LINE)
    prints = [t for t in dmg.span_tokens if t.idx == 0x102]
    assert prints, "DD:4C prints no number at all"

    # and the records that must NOT reach it
    for rec_id in (0x0A, 0x0B):
        rec = _rec(sc, rec_id)
        bad = [t for t in rec.span_tokens if t.idx == 0x00D
               and rec.data[t.off + 1] == 0xDD
               and rec.data[t.off + 2] == DAMAGE_LINE]
        assert not bad, "record 0x%02X calls the damage line" % rec_id


def test_the_damage_line_reads_result_slot_one():
    """DD:4C is `var[8] = battle_result(1); print var[8]`."""
    rec = _rec(_dd(), DAMAGE_LINE)
    toks = rec.span_tokens
    assign, printer = toks[0], toks[1]
    assert rec.data[assign.off:assign.end] == bytes.fromhex("1fe803084b0001"), (
        "expected `var[8] = battle_result(1)`, got %s"
        % rec.data[assign.off:assign.end].hex(" "))
    assert rec.data[printer.off:printer.end] == bytes.fromhex("1f020308"), (
        "expected `print var[8]`, got %s"
        % rec.data[printer.off:printer.end].hex(" "))


def test_the_four_result_accessors_are_the_globals_we_named():
    """Expression node 0x4B -> 0x00437440(n), a four-way read of fixed globals.

    Asserted against the exe's own jump table rather than against a
    disassembly, so it stays true for any build we produce.
    """
    img = patch.apply(open(patch.ORG, "rb").read(), "release")
    pe = PE(img, "<release>")

    # 0x00437440: movsx eax,[esp+4]; cmp eax,3; ja ...; jmp [eax*4 + 0x437474]
    head = pe.data[pe.va2off(0x00437440):pe.va2off(0x00437440) + 8]
    assert head == bytes.fromhex("0fbf44240483f803"), (
        "0x00437440 is no longer the four-way result read: %s" % head.hex(" "))

    arms = [struct.unpack_from("<I", pe.data, pe.va2off(0x00437474) + 4 * i)[0]
            for i in range(4)]
    # each arm is `movsx eax, word ptr ds:<global>` + ret, 8 bytes
    globals_ = []
    for a in arms:
        ins = pe.data[pe.va2off(a):pe.va2off(a) + 8]
        assert ins[:3] == bytes.fromhex("0fbf05"), (
            "arm %08X is not a movsx from a fixed global: %s" % (a, ins.hex(" ")))
        globals_.append(struct.unpack_from("<I", ins, 3)[0])
    assert globals_ == [0x00491994, 0x00491998, 0x0049198C, 0x00491986], (
        "the battle-result globals moved: %s"
        % " ".join("%08X" % g for g in globals_))


def test_the_script_register_file_is_twenty_six_dwords():
    """`var[n]` is dword [0x004815E0 + 4n], 0 <= n < 26, via 0x0043BFA0."""
    img = patch.apply(open(patch.ORG, "rb").read(), "release")
    pe = PE(img, "<release>")
    body = pe.data[pe.va2off(0x0043BFA0):pe.va2off(0x0043BFA0) + 0x1B]
    assert bytes.fromhex("663d1a00") in body, "the 26-register bound is gone"
    assert struct.pack("<I", 0x004815E0) in body, "the register file moved"
