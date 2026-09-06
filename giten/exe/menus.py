"""English menu strings for the exe.

The system menu, the equip labels and the status-screen stat labels are not
pushed as immediates the way the character names are (``names.py``); they are
``u32`` slots in ``.rdata`` pointer tables (``docs/format-notes.md`` section
6.4)::

    0x00468310  system menus: u32 count, then 6-byte entries [u16 flag][u32 ptr]
    0x0046A118  status stat labels, then the equip labels, one flat u32 array

The ``printf`` templates are ordinary ``push imm32`` operands.  Either way the
fix is the same: put the English in an appended ``.men`` section and write its
address into the one slot that refers to the Japanese.

Every string in :data:`STRINGS` is referenced from **exactly one** place in the
image, and :func:`slot_of` refuses to run if that stops being true -- a bare
four-byte search would otherwise be free to hit a coincidence (the byte pattern
for ``0x004800E8`` also occurs inside a ``call`` instruction's rel32, which is
how this kind of search goes wrong).

:data:`EFFECTS` is the one thing here that is *not* re-pointed.  The status
conditions are a packed struct array with the name stored inline, so they are
overwritten in place and the budget is a hard six characters.

Widths are in half-width cells: a full-width kana or kanji is 2, ASCII is 1.
Two different width rules apply, because two different things are being kept:

* :data:`WIDTH_LOCKED` -- the three ``合計`` templates, whose *leading spaces*
  do column alignment, so the literal string must keep its width.
* :data:`RENDER_LOCKED` -- the status block at ``0x0046A400``, where every line
  renders exactly 14 cells and the numbers are right-aligned against each
  other.  There the *formatted* width is what has to match, so a longer label
  has to be paid for out of the field widths.
"""
from __future__ import annotations

import re
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
    # --- status-screen stat labels (0x0046A118), same pointer array ----------
    # The labels start at x=14 and the numbers are right-aligned ending at
    # x=140, so about 12 cells are free and the words fit spelled out.  This is
    # the wording other translators settled on, and it matches the
    # abbreviations (IT/WI/MA/IN/BL/ST/VI/AG/DX/CH) used elsewhere.
    0x0046A254: "Intuition",                     # 直  感
    0x0046A25C: "Willpower",                     # 精神力
    0x0046A264: "Magic",                         # 魔  力
    0x0046A26C: "Intelligence",                  # 知  力
    0x0046A274: "Blessing",                      # 加  護
    0x0046A27C: "Strength",                      # 強  さ
    0x0046A284: "Vitality",                      # 体  力
    0x0046A28C: "Agility",                       # 敏捷性
    0x0046A294: "Dexterity",                     # 器用さ
    0x0046A29C: "Charisma",                      # 魅  力
    # Narrowing %5d to %2d is safe: the maximum it prints beside is already
    # %2d, so the running count cannot reach three digits.  RENDER_LOCKED
    # checks that the line still comes out 14 cells wide.
    0x0046A454: "Minions %2d／%2d",              # 仲魔
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

#: templates whose *formatted* width must match (the 14-cell status block)
RENDER_LOCKED = (0x0046A454,)

#: The status conditions: a packed array at ``0x004647E0`` of
#: ``[u8 id][7-byte NUL-terminated cp932 name]``, stride 8, 35 entries.  The
#: name is stored *inline*, so unlike everything else in this module it is
#: rewritten in place and cannot grow: six characters plus the NUL.  The list
#: that prints them uses ``%-6.6s`` (``0x0046A47C``), which fixes the same six
#: independently.
EFFECT_TABLE = 0x004647E0
EFFECT_STRIDE = 8
EFFECT_NAME_BYTES = 7                            # including the NUL

#: (Japanese, English) in table order.  The Japanese is asserted before writing.
EFFECTS = [
    ("灰", "Ash"),
    ("死", "Dead"),
    ("瀕死", "Dying"),
    ("昏倒", "Swoon"),
    ("石化", "Stone"),
    ("麻痺", "Palsy"),
    ("凍結", "Freeze"),
    ("憑依", "Haunt"),
    ("ゾンビ", "Zombie"),
    ("呪い", "Curse"),
    ("気絶", "Faint"),
    ("窒息", "Choke"),
    ("禁縛", "Bind"),
    ("眠り", "Sleep"),
    ("恐慌", "Panic"),
    ("猛毒", "Venom"),                           # 猛毒 is the deadly one, 毒 the plain
    ("毒", "Poison"),
    ("幻覚", "Mirage"),
    ("魅了", "Charm"),                           # the status; the stat 魅力 is Charisma
    ("混乱", "Daze"),
    ("舞踏", "Dance"),
    ("感電", "Shock"),
    ("氷結", "Frozen"),                          # paired with 凍結 Freeze above
    ("炎上", "Burn"),
    ("盲目", "Blind"),
    ("封魔", "Seal"),
    ("居眠り", "Doze"),
    ("狂戦士", "Frenzy"),                        # "Berserk" is 7, one over
    ("ハイ", "High"),
    ("泥酔", "Drunk"),
    ("ほろ酔", "Tipsy"),
    ("幸福", "Happy"),
    ("ｽﾗｲﾑ", "Slime"),
    ("吸血", "Drain"),
    ("外傷", "Wound"),
]

_SPEC = re.compile(r"%[-+ #0]*([0-9]*)(?:\.[0-9]+)?(?:ll|l|h)?([diouxXeEfgGcs%])")


def width(s: str) -> int:
    """Display width in half-width cells."""
    return sum(1 if (ord(c) < 0x80 or 0xFF61 <= ord(c) <= 0xFF9F) else 2 for c in s)


def rendered_width(s: str) -> int:
    """Width once ``printf`` has expanded the conversions to their field widths.

    ``%%`` is one cell; every other conversion contributes its field width (the
    engine always pads these, which is the whole point of the column).  A
    conversion with no field width would be unbounded, so it is refused rather
    than guessed at.
    """
    out, last = 0, 0
    for m in _SPEC.finditer(s):
        out += width(s[last:m.start()])
        last = m.end()
        if m.group(2) == "%":
            out += 1
            continue
        if not m.group(1):
            raise RuntimeError("menus: %r has an unpadded conversion %r" % (s, m.group(0)))
        out += int(m.group(1))
    return out + width(s[last:])


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
    for va in RENDER_LOCKED:
        jp, en = cstring_at(image, pe, va), STRINGS[va]
        if rendered_width(jp) != rendered_width(en):
            raise RuntimeError("menus: 0x%08X renders %d cells, English renders %d"
                               % (va, rendered_width(jp), rendered_width(en)))


def check_effects(image: bytes) -> None:
    """Every English condition name must fit the inline field, and the Japanese
    it replaces must still be where we recorded it."""
    pe = PE(image, "menus")
    for i, (jp, en) in enumerate(EFFECTS):
        off = pe.va2off(EFFECT_TABLE + i * EFFECT_STRIDE) + 1
        got = image[off:off + EFFECT_NAME_BYTES].split(b"\x00")[0].decode("cp932")
        if got != jp:
            raise RuntimeError("menus: condition %d is %r, expected %r" % (i, got, jp))
        if len(en.encode("cp932")) + 1 > EFFECT_NAME_BYTES:
            raise RuntimeError("menus: condition %r is %d bytes, the field holds %d"
                               % (en, len(en.encode("cp932")), EFFECT_NAME_BYTES - 1))


def apply(image: bytes) -> bytes:
    """Append ``.men`` with the English strings, re-point every slot, and
    overwrite the status-condition names in place."""
    check_widths(image)
    check_effects(image)
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

    pe = PE(bytes(out), "menus2")
    for i, (_jp, en) in enumerate(EFFECTS):
        off = pe.va2off(EFFECT_TABLE + i * EFFECT_STRIDE) + 1
        out[off:off + EFFECT_NAME_BYTES] = en.encode("cp932").ljust(EFFECT_NAME_BYTES, b"\x00")
    return bytes(out)
