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
