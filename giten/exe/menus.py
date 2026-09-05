"""English menu strings for the exe.

The system menu and the equip-stat labels are not pushed as immediates the way
the character names are (``names.py``); they are ``u32`` slots in ``.rdata``
pointer tables (``docs/format-notes.md`` section 6.4)::

    0x00468310  system menus: u32 count, then 6-byte entries [u16 flag][u32 ptr]
    0x0046A140  equip labels: a flat u32 pointer array

The four ``printf`` templates are ordinary ``push imm32`` operands.  Either way
the fix is the same: put the English in an appended ``.men`` section and write
its address into the one slot that refers to the Japanese.

Every string in :data:`STRINGS` is referenced from **exactly one** place in the
image, and :func:`slot_of` refuses to run if that stops being true -- a bare
four-byte search would otherwise be free to hit a coincidence (the byte pattern
for ``0x004800E8`` also occurs inside a ``call`` instruction's rel32, which is
how this kind of search goes wrong).

Widths are in half-width cells: a full-width kana or kanji is 2, ASCII is 1.
The three ``合計`` templates are padded so the English occupies the same width
as the Japanese, because their leading spaces are doing column alignment.  The
equip labels are held to 4 cells (the width of two full-width glyphs) because
the numeric columns beside them start at a fixed offset; they can be spelled out
if play-testing shows there is room.
"""
from __future__ import annotations

import struct

from .pe import PE

MEN_CHARACTERISTICS = 0x40000040                 # INITIALIZED_DATA | MEM_READ

#: Japanese string VA -> English.  See the module docstring on widths.
STRINGS = {
    # --- system menu (0x00468310) -------------------------------------------
    0x0046834C: "Auto-Mapping",
    0x00468360: "Auto-Navigation",
    0x00468378: "Suspend Game",
    0x00468384: "Suspend",                       # 中断する
    0x00468390: "Cancel",                        # 中断しない
    0x0046839C: "Free",                          # 自由表示  (map view)
    0x004683A8: "Fixed",                         # 固定表示
    # --- equip stat labels (0x0046A140), 4 cells each ------------------------
    0x0046A2A4: "Fate",                          # 命  運
    0x0046A2AC: "Skl",                           # 技能
    0x0046A2B4: "Hit",                           # 命中
    0x0046A2BC: "Atk",                           # 攻撃
    0x0046A2C4: "Evd",                           # 回避
    0x0046A2CC: "Def",                           # 防御
    0x0046A2D4: "Ammo",                          # 弾数
    # --- printf templates ----------------------------------------------------
    0x0046A540: "Items Held %1d/8",              # 所持アイテム %1d/8
    0x00468DAC: "               Total %10ld   ",  # 合計, width-preserving
    0x00468DCC: "               Total ",
    0x00468DE4: "Total %10ld  ",
}

#: templates whose English must occupy exactly the width of the Japanese
WIDTH_LOCKED = (0x00468DAC, 0x00468DCC, 0x00468DE4)


def width(s: str) -> int:
    """Display width in half-width cells."""
    return sum(1 if (ord(c) < 0x80 or 0xFF61 <= ord(c) <= 0xFF9F) else 2 for c in s)


def cstring_at(image: bytes, pe: PE, va: int) -> str:
    off = pe.va2off(va)
    return image[off:image.index(b"\x00", off)].decode("cp932")


def slot_of(image: bytes, va: int) -> int:
    """File offset of the single ``u32`` that holds ``va``."""
    needle = struct.pack("<I", va)
    hits, start = [], 0
    while True:
        i = image.find(needle, start)
        if i < 0:
            break
        start = i + 1
        hits.append(i)
    if len(hits) != 1:
        raise RuntimeError("menus: 0x%08X is referenced %d times, expected 1" % (va, len(hits)))
    return hits[0]


def check_widths(image: bytes) -> None:
    pe = PE(image, "menus")
    for va in WIDTH_LOCKED:
        jp, en = cstring_at(image, pe, va), STRINGS[va]
        if width(jp) != width(en):
            raise RuntimeError("menus: 0x%08X width %d -> %d, alignment would shift"
                               % (va, width(jp), width(en)))


def apply(image: bytes) -> bytes:
    """Append ``.men`` with the English strings and re-point every slot."""
    check_widths(image)
    slots = {va: slot_of(image, va) for va in STRINGS}

    blob = bytearray()
    at: dict[int, int] = {}
    for va, en in STRINGS.items():
        at[va] = len(blob)
        blob += en.encode("cp932") + b"\x00"

    pe = PE(image, "menus")
    men_va = pe.imagebase + pe.sizeimage
    out = bytearray(pe.append_section(".men", bytes(blob), MEN_CHARACTERISTICS))
    for va, off in slots.items():
        struct.pack_into("<I", out, off, men_va + at[va])
    return bytes(out)
