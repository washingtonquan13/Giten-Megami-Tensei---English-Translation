"""The English menu strings: that every Japanese string we replace is reachable
from exactly one slot, that the width-locked printf templates keep their column
alignment, and that the built release exe actually serves the English.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten.exe import menus, patch  # noqa: E402
from giten.exe.pe import PE  # noqa: E402


def _release():
    return patch.apply(open(patch.ORG, "rb").read(), "release")


def test_every_menu_string_has_exactly_one_slot():
    img = _release()
    for va in menus.STRINGS:
        off = menus.slot_of(img, va)            # raises unless there is exactly one
        assert struct.unpack_from("<I", img, off)[0] == va


def test_width_locked_templates_keep_their_alignment():
    img = _release()
    pe = PE(img, "menus")
    menus.check_widths(img)                     # raises on a width change
    for va in menus.WIDTH_LOCKED:
        jp = menus.cstring_at(img, pe, va)
        en = menus.STRINGS[va]
        assert jp.count("%") == en.count("%"), (jp, en)
        assert menus.width(jp) == menus.width(en)

    # a template that would shift the columns is refused
    saved = menus.STRINGS[menus.WIDTH_LOCKED[0]]
    menus.STRINGS[menus.WIDTH_LOCKED[0]] = saved + " "
    try:
        menus.check_widths(img)
    except RuntimeError as exc:
        assert "alignment would shift" in str(exc), exc
    else:
        raise AssertionError("a wider template was accepted")
    finally:
        menus.STRINGS[menus.WIDTH_LOCKED[0]] = saved


def test_applying_men_repoints_every_slot_at_the_english():
    img = _release()
    slots = {va: menus.slot_of(img, va) for va in menus.STRINGS}
    out = menus.apply(img)
    assert len(out) > len(img)
    pe = PE(out, "men")
    for va, off in slots.items():
        new = struct.unpack_from("<I", out, off)[0]
        assert new != va, "0x%08X was not re-pointed" % va
        assert menus.cstring_at(out, pe, new) == menus.STRINGS[va]
    # the Japanese is still in .rdata; only the pointers moved
    assert menus.cstring_at(out, pe, 0x0046834C) == "オートマッピング"


# --------------------------------------------------------------------------
# The piecewise sites.  Reading the pointer is not enough here: the bug that
# shipped "Macc" + a stale "カ" passes a pointer test, because the dword *was*
# re-pointed.  What has to be checked is the buffer the engine assembles, so
# these tests emulate the actual loads and stores.

#: (site VA, string VA) -- the five places a string is copied piece by piece.
PIECEWISE_SITES = [
    (0x00436D1A, 0x00469808),
    (0x00436D55, 0x00469810),
    (0x00438CCA, 0x00469818),
    (0x00438D1A, 0x00469820),
    (0x00441B12, 0x0046A400),
]

_REGS = 8                                       # eax ecx edx ebx esp ebp esi edi


def _emulate_copy(img, site):
    """Run the ``mov`` chain at ``site`` and return ``{va: (byte, tainted)}``.

    A deliberately tiny subset of x86: the absolute-address forms ``A0..A3``
    and the ``mod=00 rm=101`` (disp32) encodings of ``88/89/8A/8B``, with the
    ``66`` operand-size prefix.  Anything else stops the walk, which is what
    ends it at the ``ret``/``jmp`` after the last store.  Each register byte
    carries a *taint* flag saying whether it came out of memory this run, so
    the caller can tell our string's bytes from whatever was already in a
    register when the site was entered.
    """
    pe = PE(img, "emul")
    regs = [[(0, False)] * 4 for _ in range(_REGS)]
    mem = {}

    def load(va, n):
        off = pe.va2off(va)
        if off is None:                         # .bss / runtime work buffers
            return [(0, False)] * n
        return [(b, True) for b in img[off:off + n]]

    pc = site
    for _ in range(64):
        off = pe.va2off(pc)
        op = img[off]
        size = 4
        if op == 0x66:
            size, off, pc, op = 2, off + 1, pc + 1, img[off + 1]
        if op in (0xA0, 0xA1, 0xA2, 0xA3):
            n = 1 if op in (0xA0, 0xA2) else size
            va = struct.unpack_from("<I", img, off + 1)[0]
            if op in (0xA0, 0xA1):
                regs[0][:n] = load(va, n)
            else:
                for i in range(n):
                    mem[va + i] = regs[0][i]
            pc += 5
            continue
        if op in (0x88, 0x89, 0x8A, 0x8B) and img[off + 1] & 0xC7 == 0x05:
            reg = (img[off + 1] >> 3) & 7
            n = 1 if op in (0x88, 0x8A) else size
            va = struct.unpack_from("<I", img, off + 2)[0]
            if op in (0x8A, 0x8B):
                regs[reg][:n] = load(va, n)
            else:
                for i in range(n):
                    mem[va + i] = regs[reg][i]
            pc += 6
            continue
        break
    return mem


def _assembled(mem):
    """The contiguous run of bytes the site actually copied."""
    live = sorted(va for va, (_b, t) in mem.items() if t)
    assert live, "the site copied nothing"
    for a, b in zip(live, live[1:]):
        assert b == a + 1, "the copied bytes are not contiguous: %r" % (live,)
    return bytes(mem[va][0] for va in live)


def test_the_piecewise_sites_are_still_the_loads_we_recorded():
    """The piece sizes are read off the instruction stream, so if a site stops
    looking like that chain the table is wrong and everything below is void."""
    img = open(patch.ORG, "rb").read()
    for site, va in PIECEWISE_SITES:
        mem = _emulate_copy(img, site)
        assert len(_assembled(mem)) == sum(menus.PIECEWISE[va]), hex(site)
        # and it assembles the Japanese, terminator and all
        pe = PE(img, "org")
        jp = menus.cstring_at(img, pe, va).encode("cp932")
        assert _assembled(mem).startswith(jp + b"\x00"), hex(site)


def test_every_piece_is_repointed_so_the_engine_assembles_the_english():
    img = _release()
    out = menus.apply(img)
    for site, va in PIECEWISE_SITES:
        want = menus.STRINGS[va].encode("cp932") + b"\x00"
        want = want.ljust(sum(menus.PIECEWISE[va]), b"\x00")
        assert _assembled(_emulate_copy(out, site)) == want, (hex(site), hex(va))


def test_repointing_only_the_first_piece_reassembles_the_japanese_tail():
    """The mutation is the patcher as it shipped: ``targets_of`` returning just
    the base address, so only the dword is re-pointed.  The engine then
    assembles "Macc" out of the new string and a stale カ out of the old one --
    which is exactly what was on screen, and which the pointer test above does
    not notice."""
    img = _release()
    saved = menus.targets_of
    menus.targets_of = lambda va: [va]
    try:
        out = menus.apply(img)
        got = _assembled(_emulate_copy(out, 0x00436D1A))
        want = menus.STRINGS[0x00469808].encode("cp932") + b"\x00"
        assert got != want, "the mutation did not change anything"
        assert got.startswith(want[:4]), got
        assert got[4:].decode("cp932", "replace").startswith("カ"), got
    finally:
        menus.targets_of = saved


def test_a_string_too_long_for_its_pieces_is_refused():
    img = _release()
    saved = menus.STRINGS[0x00469808]
    menus.STRINGS[0x00469808] = " Maccas"[:6]    # 6 + NUL = 7, the buffer is 7
    try:
        menus.check_pieces(img)                  # exactly fits, still fine
        menus.STRINGS[0x00469808] = " Maccas"    # 7 + NUL = 8
        try:
            menus.check_pieces(img)
        except RuntimeError as exc:
            assert "is copied in 7 bytes" in str(exc), exc
        else:
            raise AssertionError("an 8-byte string was accepted into 7 bytes")
    finally:
        menus.STRINGS[0x00469808] = saved


def test_the_mood_values_fit_the_cells_the_label_leaves():
    """`Mood   %s` in a type-16 window: 22 usable cells, a 7-cell label."""
    img = _release()
    menus.check_widths(img)
    assert menus.width(menus.STRINGS[0x00468D1C].split("%")[0]) == 7
    for va, cells in menus.VALUE_BUDGET.items():
        assert cells == 15
        assert menus.width(menus.STRINGS[va]) <= cells, hex(va)

    saved = menus.STRINGS[0x00468C68]
    menus.STRINGS[0x00468C68] = "Extremely Hostile"      # 17 cells
    try:
        menus.check_widths(img)
    except RuntimeError as exc:
        assert "the field holds 15" in str(exc), exc
    else:
        raise AssertionError("a 17-cell mood value was accepted")
    finally:
        menus.STRINGS[0x00468C68] = saved


def test_the_mood_values_are_reached_through_their_pointer_table():
    """One u32 slot each, and the slots are the first five of the table at
    0x00468BF8 -- so re-pointing them is all the Mood line needs."""
    img = _release()
    pe = PE(img, "menus")
    table = pe.va2off(0x00468BF8)
    for i, va in enumerate((0x00468C58, 0x00468C60, 0x00468C68,
                            0x00468C74, 0x00468C7C)):
        assert struct.unpack_from("<I", img, table + i * 4)[0] == va
        assert menus.slot_of(img, va) == table + i * 4
    out = menus.apply(img)
    pe2 = PE(out, "men")
    for i, va in enumerate((0x00468C58, 0x00468C60, 0x00468C68,
                            0x00468C74, 0x00468C7C)):
        new = struct.unpack_from("<I", out, table + i * 4)[0]
        assert menus.cstring_at(out, pe2, new) == menus.STRINGS[va]


def test_equip_labels_stay_within_two_full_width_glyphs():
    """The numeric columns beside them start at a fixed offset."""
    for va in (0x0046A2AC, 0x0046A2B4, 0x0046A2BC, 0x0046A2C4, 0x0046A2CC, 0x0046A2D4):
        assert menus.width(menus.STRINGS[va]) <= 4, (hex(va), menus.STRINGS[va])


def test_the_status_block_still_renders_fourteen_cells():
    """Every line of the block at 0x0046A400 is 14 cells wide and the numbers
    are right-aligned against each other, so a longer label has to be paid for
    out of the field widths."""
    img = _release()
    pe = PE(img, "menus")
    for va in (0x0046A410, 0x0046A41C, 0x0046A42C, 0x0046A43C, 0x0046A454, 0x0046A464):
        assert menus.rendered_width(menus.cstring_at(img, pe, va)) == 14, hex(va)
    assert menus.rendered_width(menus.STRINGS[0x0046A454]) == 14

    # a label that eats into the numbers is refused
    saved = menus.STRINGS[0x0046A454]
    menus.STRINGS[0x0046A454] = "Minions %5d\uff0f%2d"
    try:
        menus.check_widths(img)
    except RuntimeError as exc:
        assert "renders" in str(exc), exc
    else:
        raise AssertionError("a 17-cell status line was accepted")
    finally:
        menus.STRINGS[0x0046A454] = saved


def test_rendered_width_expands_conversions_not_their_source_text():
    assert menus.rendered_width("LEVEL %8d") == 14
    assert menus.rendered_width("HP  %4d\uff0f%4d") == 14
    assert menus.rendered_width("100%% sure") == 9          # %% is one cell
    try:
        menus.rendered_width("%s")                          # unbounded
    except RuntimeError as exc:
        assert "unpadded" in str(exc), exc
    else:
        raise AssertionError("an unpadded conversion was measured")


def test_stat_labels_fit_the_column_the_numbers_leave():
    """Labels start at x=14, numbers are right-aligned ending at x=140."""
    for va in range(0x0046A254, 0x0046A2A4, 8):
        assert menus.width(menus.STRINGS[va]) <= 12, (hex(va), menus.STRINGS[va])


def test_status_conditions_are_rewritten_in_place_within_the_field():
    img = _release()
    menus.check_effects(img)                    # raises if the Japanese moved
    assert len(menus.EFFECTS) == 35
    out = menus.apply(img)
    pe = PE(out, "men")
    for i, (jp, en) in enumerate(menus.EFFECTS):
        off = pe.va2off(menus.EFFECT_TABLE + i * menus.EFFECT_STRIDE)
        # the id byte is what the engine matches on -- it must not move
        assert out[off] == img[off], "condition %d changed id" % i
        field = out[off + 1:off + menus.EFFECT_NAME_BYTES + 1]
        assert field.split(b"\x00")[0].decode("cp932") == en, (i, jp, en)
        assert field[-1] == 0, "condition %d has no terminator" % i
    # in place means in place: the table did not move, and the English is not
    # sitting in the appended section
    assert pe.va2off(menus.EFFECT_TABLE) == PE(img, "orig").va2off(menus.EFFECT_TABLE)
    men = pe.section(".men")
    table = pe.va2off(menus.EFFECT_TABLE)
    assert not (men["rawptr"] <= table < men["rawptr"] + men["rawsize"])
    # and it is still packed at stride 8: entry i+1's id byte follows entry i
    for i in range(len(menus.EFFECTS)):
        off = pe.va2off(menus.EFFECT_TABLE + i * menus.EFFECT_STRIDE)
        assert out[off] == img[off]


def test_a_condition_name_that_overflows_the_inline_field_is_refused():
    img = _release()
    saved = menus.EFFECTS[0]
    menus.EFFECTS[0] = (saved[0], "Ashen!!")               # 7 chars, field holds 6
    try:
        menus.check_effects(img)
    except RuntimeError as exc:
        assert "the field holds" in str(exc), exc
    else:
        raise AssertionError("a 7-character condition was accepted")
    finally:
        menus.EFFECTS[0] = saved


def test_check_effects_refuses_an_image_whose_table_moved():
    img = bytearray(_release())
    pe = PE(bytes(img), "menus")
    img[pe.va2off(menus.EFFECT_TABLE) + 1] ^= 0xFF
    try:
        menus.check_effects(bytes(img))
    except RuntimeError as exc:
        assert "expected" in str(exc), exc
    else:
        raise AssertionError("a moved condition table was accepted")
