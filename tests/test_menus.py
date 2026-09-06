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
