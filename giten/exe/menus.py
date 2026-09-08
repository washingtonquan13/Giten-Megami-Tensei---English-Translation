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

    # --- level-up box (bug report 3) -----------------------------------------
    0x00468AAC: "Learned %s!",                   # %sを会得した！
    0x00468ABC: "Learned %s!",
    0x00468ACC: "Please distribute your points\n",   # ポイントを振り分けてください
    0x00468AEC: "%.1d points remaining  \n",     # 後 %.1d ポイント
    0x00468B00: "%s leveled up!\n",              # %sはレベルが上がった
    0x0046A400: "Maximum level",                 # 最高レベルです
    # --- battle skill list (bug report 4) ------------------------------------
    # Two cells move from the name field to the wider English "Effect", so the
    # header still renders 26 cells and the columns stay put.  English skill
    # names are short (Agi, Bufu, Zan, Dia); 14 is not a real constraint.
    0x0046A5A4: "Skill Name",                    # 魔法名称
    0x0046A5B0: "%-14.14s  MP  Effect",          # %-16.16s  MP  効果
    # --- analyze block (bug report 6) ----------------------------------------
    # Every label is 7 cells wide in the Japanese and the values are a column;
    # LABEL_LOCKED keeps the English 7 cells too.
    0x00468C8C: "DAS is not installed",          # ＤＡＳがインストゥールされていません
    0x00468CBC: "No analysis data\n",             # アナライズデータがありません
    0x00468CDC: "Align  %c/%c\n",                 # 属性　 %c/%c
    0x00468CEC: "Level  L%2d\n",                  # レベル L%2d
    0x00468CFC: "HP     %d/%d\n",                 # ＨＰ   %d/%d
    0x00468D0C: "MP     %d/%d\n",                 # ＭＰ   %d/%d
    0x00468D1C: "Mood   %s\n",                    # 態度   %s
    0x00468D28: "State  %s\n",                    # 状態   %s
    0x00468D34: "Run a detailed analysis?",      # 詳細アナライズしますか？
    # --- field menu and equipment (bug report 6) -----------------------------
    0x00468B18: "<Items>",                       # <アイテム>
    0x00468F58: "Discard Item",                  # アイテム削除
    0x00469808: "Macca",                         # マッカ, the currency
    0x00469810: "MAG",                           # ＭＡＧ
    0x00469818: "Macca",
    0x00469820: "MAG",
    # The item name is printed immediately before these two, so they have to
    # read as a continuation and not as a sentence of their own.
    0x0046A4D4: " equipped.",                    # をはめ込んだ
    0x0046A4E4: " swapped for %s.",              # と%sを付け替えた
    0x0046A4FC: " equipped.",
    0x0046A50C: " swapped for %s.",
    # --- field and battle messages -------------------------------------------
    0x004684D0: "Out of range!",                 # 攻撃がとどかない！
    0x00468654: "The door is locked.",           # 扉はロックされている
    0x0046866C: "The door is locked.",
    0x0046C0F8: "Quit the game?",                # 終了しますか？
    0x0046C110: "Quit the game?",
    0x0046C1D4: "DirectX initialisation failed.",  # ＤｉｒｅｃｔＸ初期化に失敗しました。
    0x0046C1FC: "Initialisation failed.",        # 初期化に失敗しました。
    # Why the field menu greyed an option out.  The bracketed tag is part of
    # the string, so it moves with it.
    # The battle-command refusals.  Two blocks hold the same seven messages --
    # both are live, each address referenced exactly once -- so the wording has
    # to match across them or the same refusal reads differently depending on
    # which command produced it.
    #
    # The Japanese uses three fixed patterns and the English now follows them
    # one-for-one, which is what the first pass did not do: it mixed full
    # sentences ("That item cannot be used") with bare noun phrases ("Nothing to
    # fight", "No items", "Nobody to talk to") that read as captions rather than
    # messages.
    #
    #   ...が居ません        -> "There is no one to X"   (no *person* to act on)
    #   ...を所持していません -> "You have no X"          (you are not carrying it)
    #   ...できません        -> "That item cannot be used"
    #
    # Length is not a constraint here: every one of these replaces a much longer
    # Japanese string, and the longest English in this module already ships at
    # 31 cells.
    0x00468880: "[ITEM] No one can use that",       # 使用できる人が居ません
    0x004688A0: "[ITEM] You have no items",         # アイテムが有りません
    0x004688BC: "[DDS] You have no DDS",            # DDSを所持していません
    0x004688D8: "[FIGHT] There is no one to fight",  # 戦う相手が居ません
    0x004688F4: "[TALK] There is no one to talk to",  # 会話相手が居ません
    0x00468910: "[TALK] You have no DCS",           # DCSを所持していません
    0x00468930: "[MAPPING] You have no AMS",        # AMSを所持していません
    0x00468950: "[TALK] You have no DCS",           # DCSを所持していません
    0x00468970: "[FIGHT] There is no one to fight",  # 戦う相手が居ません
    0x0046898C: "[GUN] There is no one to fight",   # 戦う相手が居ません
    0x004689A8: "[ITEM] That item cannot be used",  # アイテムを使用できません
    0x004689C8: "[ITEM] You have no items",         # アイテムが有りません
    0x004689E4: "[DEFENCE] There is no one to fight",  # 戦う相手が居ません
    0x00468A04: "[DDS] You have no DDS",            # DDSを所持していません
    0x00468A20: "[MAPPING] You have no AMS",        # AMSを所持していません
    # --- the leftover debug menu ---------------------------------------------
    # Not reachable in the shipping build, but the dev build arms it and the
    # plan uses it to set up trace routes, so it may as well be readable.
    0x00468054: "BGM",                           # ＢＧＭ
    0x0046805C: "SE",                            # ＳＥ
    0x00468064: "Spell Effect",                  # 魔法効果
    0x00468070: "Kill All Demons",               # 悪魔全滅
    0x0046807C: "Get Item",                      # アイテム取得
    0x0046808C: "Change Stats",                  # 能力値変化
    0x00468098: "3D Move",                       # ３Ｄ移動
    0x004680A4: "Change Flags",                  # フラグ変更
    0x004680B0: "Save",                          # セーブ
    0x004680B8: "Load",                          # ロード
    0x004680C0: "Check Data",                    # データ確認
    0x004680CC: "+1",                            # ＋１
    0x004680D4: "-1",
    0x004680DC: "+10",
    0x004680E4: "-10",
    0x004680EC: "+100",
    0x004680F8: "-100",
    0x00468104: "Distance",                      # 距離
    0x0046810C: "Execute",                       # 実行
    0x00468114: "<Debug Menu>",                  # <デバッグメニュー>
    0x00468128: "<Spell Debug>",                 # <魔法デバッグ>
    0x00468468: "Condition Effect Flow",         # コンディション影響フロー
    0x00468618: "Enemy Action Flow",             # 敵行動フロー
}

#: templates whose English must occupy exactly the width of the Japanese
WIDTH_LOCKED = (0x00468DAC, 0x00468DCC, 0x00468DE4)

#: Templates whose *label* -- the text before the first conversion -- has to keep
#: its width.  The analyze box prints one of these per line and the values form
#: a column down the right; a label one cell wider puts that line's value out of
#: line with the rest.  This is weaker than RENDER_LOCKED (which fixes the whole
#: rendered line) because these conversions have no field width to add up.
LABEL_LOCKED = (0x00468CDC, 0x00468CEC, 0x00468CFC, 0x00468D0C,
                0x00468D1C, 0x00468D28)

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

    for va in LABEL_LOCKED:
        jp, en = cstring_at(image, pe, va), STRINGS[va]
        jl, el = jp.split("%")[0], en.split("%")[0]
        if width(jl) != width(el):
            raise RuntimeError("menus: 0x%08X label %r is %d cells, English %r "
                               "is %d; the value column would step"
                               % (va, jl, width(jl), el, width(el)))


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
