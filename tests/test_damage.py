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


# ---------------------------------------------------------------------------
# 1F 02 in English builds: ASCII digits (patch.ascii_digits, §1)
#
# The patch turns the one `call _mbbtombc` in the image into `mov eax,ecx`.
# What is worth testing: that the call really is the only conversion and has no
# other user, that the patch lands only on the loop it was written for, and --
# by *executing the loop's own bytes* from the image -- that the patched routine
# emits one ASCII byte per character with the NUL right behind it, while the
# original emits the full-width pairs.
# ---------------------------------------------------------------------------

import re  # noqa: E402

MBBTOMBC = 0x0045B750
MBB_TABLE = 0x0046E3D0          # _mbbtombc's word table for 0x20..0x7E
RUN_FROM = 0x0043BA53           # mov al,[esp+0x18] -- first byte of the %ld text
RUN_TO = 0x0043BA97             # just past the loop
#: mov edi,0x491120 / or ecx,-1 / xor eax,eax / mov byte [esi],0
TAIL = bytes.fromhex("bf2011490083c9ff33c0c60600")


def _org():
    return open(patch.ORG, "rb").read()


def _release():
    return patch.apply(_org(), "release")


def _mbbtombc(img, c):
    """The CRT routine under code page 932, reading the exe's own table."""
    if 0x20 <= c <= 0x7E:
        pe = PE(img, "t")
        return struct.unpack_from("<H", img, pe.va2off(MBB_TABLE) + 2 * c)[0]
    raise AssertionError("the %%ld text cannot contain byte 0x%02X" % c)


def _run(img, value):
    """Execute 0x0043BA53..0x0043BA97 for ``sprintf("%ld", value)``.

    A tiny x86 subset, decoded from the image by exact byte pattern: every
    instruction the original or patched loop contains, and nothing else --
    an unknown byte sequence fails the test rather than being guessed at.  The
    one call is allowed only to ``_mbbtombc`` and is modelled from its table.
    Returns the bytes written to the output buffer (up to the NUL the tail
    writes) and ``esi - 0x004815A0``.
    """
    pe = PE(img, "emul")
    text = b"%d" % value
    assert len(text) < 0x20
    B = 0x10000                                   # the stack buffer
    mem = {B + i: b for i, b in enumerate(text + b"\0")}
    r = {"eax": 0xDEADBEEF, "ecx": 0xDEADBEEF, "edx": 0xDEADBEEF,
         "esi": 0, "edi": 0, "esp": B - 0x18}
    zf = cf = False
    stack = []
    pc = RUN_FROM

    def rd(va):
        return mem.get(va, 0xCC)

    def lo8(v):
        return v & 0xFF

    for _ in range(10000):
        if pc == RUN_TO:
            break
        o = pe.va2off(pc)
        b = img[o:o + 8]
        if b[:4] == bytes.fromhex("8a442418"):             # mov al,[esp+0x18]
            r["eax"] = (r["eax"] & ~0xFF) | rd(r["esp"] + 0x18); pc += 4
        elif b[:3] == bytes.fromhex("83c410"):             # add esp,0x10
            r["esp"] += 0x10; pc += 3
        elif b[:3] == bytes.fromhex("83c404"):             # add esp,4
            r["esp"] += 4; stack.pop(); pc += 3
        elif b[:2] == bytes.fromhex("33ff"):               # xor edi,edi
            r["edi"] = 0; pc += 2
        elif b[:2] == bytes.fromhex("33c9"):               # xor ecx,ecx
            r["ecx"] = 0; pc += 2
        elif b[:2] == bytes.fromhex("33d2"):               # xor edx,edx
            r["edx"] = 0; pc += 2
        elif b[0] == 0xBE:                                 # mov esi,imm32
            r["esi"] = struct.unpack_from("<I", b, 1)[0]; pc += 5
        elif b[:2] == bytes.fromhex("84c0"):               # test al,al
            zf, cf = lo8(r["eax"]) == 0, False; pc += 2
        elif b[:2] == bytes.fromhex("84c9"):               # test cl,cl
            zf, cf = lo8(r["ecx"]) == 0, False; pc += 2
        elif b[0] in (0x74, 0x75, 0x76):                   # je / jne / jbe rel8
            take = {0x74: zf, 0x75: not zf, 0x76: zf or cf}[b[0]]
            pc += 2 + (struct.unpack_from("<b", b, 1)[0] if take else 0)
        elif b[:4] == bytes.fromhex("8d442408"):           # lea eax,[esp+8]
            r["eax"] = r["esp"] + 8; pc += 4
        elif b[:4] == bytes.fromhex("8d440408"):           # lea eax,[esp+eax+8]
            r["eax"] = r["esp"] + r["eax"] + 8; pc += 4
        elif b[:2] == bytes.fromhex("8a08"):               # mov cl,[eax]
            r["ecx"] = (r["ecx"] & ~0xFF) | rd(r["eax"]); pc += 2
        elif b[:4] == bytes.fromhex("8a4c0408"):           # mov cl,[esp+eax+8]
            r["ecx"] = (r["ecx"] & ~0xFF) | rd(r["esp"] + r["eax"] + 8); pc += 4
        elif b[0] == 0x51:                                 # push ecx
            r["esp"] -= 4; stack.append(r["ecx"]); pc += 1
        elif b[0] == 0xE8:                                 # call rel32
            tgt = (pc + 5 + struct.unpack_from("<i", b, 1)[0]) & 0xFFFFFFFF
            assert tgt == MBBTOMBC, hex(tgt)
            r["eax"] = _mbbtombc(img, stack[-1] & 0xFF)
            r["ecx"] = r["edx"] = 0xDEADBEEF               # caller-saved: clobbered
            pc += 5
        elif b[:2] == bytes.fromhex("8bc1"):               # mov eax,ecx
            r["eax"] = r["ecx"]; pc += 2
        elif b[0] == 0x90:                                 # nop
            pc += 1
        elif b[:4] == bytes.fromhex("663dff00"):           # cmp ax,0xff
            ax = r["eax"] & 0xFFFF
            zf, cf = ax == 0xFF, ax < 0xFF; pc += 4
        elif b[0] == 0x46:                                 # inc esi
            r["esi"] += 1; pc += 1
        elif b[0] == 0x47:                                 # inc edi
            r["edi"] += 1; pc += 1
        elif b[:2] == bytes.fromhex("8ad4"):               # mov dl,ah
            r["edx"] = (r["edx"] & ~0xFF) | ((r["eax"] >> 8) & 0xFF); pc += 2
        elif b[:3] == bytes.fromhex("8856ff"):             # mov [esi-1],dl
            mem[r["esi"] - 1] = lo8(r["edx"]); pc += 3
        elif b[:2] == bytes.fromhex("8806"):               # mov [esi],al
            mem[r["esi"]] = lo8(r["eax"]); pc += 2
        elif b[:3] == bytes.fromhex("0fbfc7"):             # movsx eax,di
            di = r["edi"] & 0xFFFF
            r["eax"] = di - 0x10000 if di & 0x8000 else di; pc += 3
        else:
            raise AssertionError("unmodelled bytes at 0x%X: %s" % (pc, b.hex(" ")))
    else:
        raise AssertionError("the loop did not finish")
    assert not stack and r["esp"] == B - 8, "stack unbalanced"

    # the tail is untouched and writes the NUL at esi
    o = pe.va2off(RUN_TO)
    assert img[o:o + len(TAIL)] == TAIL
    n = r["esi"] - patch.DIGITS_OUT_BUF
    out = bytes(mem.get(patch.DIGITS_OUT_BUF + i, 0xCC) for i in range(n))
    assert n + 1 <= patch.DIGITS_OUT_BUF_SIZE
    return out, n


def test_the_conversion_is_mbbtombc_and_it_has_one_caller():
    img = _org()
    pe = PE(img, "t")
    site = pe.va2off(patch.DIGITS_SITE)
    assert img[site:site + 5] == patch.DIGITS_OLD
    assert (patch.DIGITS_SITE + 5 + struct.unpack_from("<i", img, site + 1)[0]) == MBBTOMBC

    text = next(s for s in pe.sections if s["name"] == ".text")
    lo, hi = text["rawptr"], text["rawptr"] + text["rawsize"]
    callers = []
    for m in re.finditer(b"\xe8", img[lo:hi]):
        o = lo + m.start()
        va = text["vaddr"] + pe.imagebase + (o - lo)
        if (va + 5 + struct.unpack_from("<i", img, o + 1)[0]) & 0xFFFFFFFF == MBBTOMBC:
            callers.append(va)
    assert callers == [patch.DIGITS_SITE], [hex(c) for c in callers]
    # ...and no pointer to it anywhere (no indirect call can reach it)
    assert struct.pack("<I", MBBTOMBC) not in img

    # the table maps digits to 82 4F..82 58 and '-' to 81 7C
    assert [_mbbtombc(img, c) for c in b"0123456789"] == list(range(0x824F, 0x8259))
    assert _mbbtombc(img, ord("-")) == 0x817C


def test_the_patch_writes_five_bytes_over_the_expected_ones_only():
    img = _release()
    out = patch.ascii_digits(img)
    pe = PE(img, "t")
    site = pe.va2off(patch.DIGITS_SITE)
    assert len(out) == len(img)
    diff = [i for i in range(len(img)) if img[i] != out[i]]
    assert diff == list(range(site, site + 5)), diff
    assert out[site:site + 5] == patch.DIGITS_NEW


def test_it_refuses_anything_but_the_original_loop():
    img = _release()
    once = patch.ascii_digits(img)
    pe = PE(img, "t")
    doctored = bytearray(img)
    doctored[pe.va2off(patch.DIGITS_LOOP_VA) + len(patch.DIGITS_LOOP_OLD) - 1] ^= 0xFF
    for bad in (once, bytes(doctored)):
        try:
            patch.ascii_digits(bad)
        except RuntimeError as exc:
            assert "is not the original's" in str(exc), exc
        else:
            raise AssertionError("an image without the original loop was accepted")


def test_the_original_loop_prints_full_width():
    """The model is only evidence if it reproduces the bug first."""
    img = _release()
    assert _run(img, 443) == ("４４３".encode("cp932"), 6)
    assert _run(img, -1234) == ("－１２３４".encode("cp932"), 10)
    assert _run(img, -2147483648)[1] == 22


def test_the_patched_loop_prints_ascii_with_the_right_length():
    img = patch.ascii_digits(_release())
    for value in (443, -1234, 0, 7, -2147483648, 2147483647):
        out, n = _run(img, value)
        assert out == b"%d" % value, (value, out)
        assert n == len(b"%d" % value)
        assert all(0x2D == c or 0x30 <= c <= 0x39 for c in out)


def test_english_builds_carry_it_and_the_japanese_dev_build_does_not():
    from giten.exe import tracer

    rel = tracer.build_image(False)
    dev = tracer.build_image(True)
    jp = tracer.build_image(True, english=False)
    for img, want in ((rel, patch.DIGITS_NEW), (dev, patch.DIGITS_NEW), (jp, patch.DIGITS_OLD)):
        pe = PE(img, "t")
        off = pe.va2off(patch.DIGITS_SITE)
        assert img[off:off + 5] == want
    assert _run(rel, 443) == (b"443", 3)
    assert _run(dev, -1234) == (b"-1234", 5)
