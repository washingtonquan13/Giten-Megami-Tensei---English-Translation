"""English character names for the exe.

The default names the game installs into the character records (family name
at record+2, given name at record+0x13, 17 bytes each -- see the installer at
VA 0x43CC00) are C strings in ``.rdata`` (8-byte slots from VA 0x469F50),
pushed as immediates by the installer's caller (VA 0x43CA5D..0x43CC00):

    6A nn            push arg5
    68 <given>       push arg4  (given name)
    68 <family>      push arg3  (family name)
    ...              push arg2, arg1
    E8 <installer>

The 8-byte slots cannot hold "Katsuragi", so the English strings live in a
new ``.nam`` section and the ``push`` immediates are re-pointed at them.  The
record fields are 17 bytes, so any name up to 16 characters is safe.

The engine prints the full name (``1F01`` selector 00) as family+given with
no separator, so the given names carry a leading space: "Katsuragi" + " Ayato".
Given-name-only prints (selector 08) therefore start with a space; the script
text around a name print already supplies its own spaces, so that shows as a
double space at worst.
"""
from __future__ import annotations

import struct

from .pe import PE

TABLE_LO, TABLE_HI = 0x469F50, 0x46A018        # the JP name slots
FUNC_LO, FUNC_HI = 0x43CA5D, 0x43CC00          # the caller that pushes them
NAM_CHARACTERISTICS = 0x40000040                # INITIALIZED_DATA | MEM_READ

#: Japanese default name -> English.  Family and given names both appear here;
#: whether a string is used as family or given is read from the push order.
NAMES = {
    "史人": "Ayato", "葛城": "Katsuragi",
    "由宇香": "Yuuka", "橘": "Tachibana",
    "飛鳥": "Asuka", "泪": "Rui",
    "義雄": "Yoshio", "西野": "Nishino",
    "達也": "Tatsuya", "早坂": "Hayasaka",
    "勇": "Isamu", "山瀬": "Yamase",
    "英美": "Emi", "桐島": "Kirishima",
    "ニュートン": "Newton",
    "カズミ": "Kazumi", "山田": "Yamada",
    "惣厳": "Sougen", "立川": "Tachikawa",
    "哲也": "Tetsuya", "園田": "Sonoda",
    "公輝": "Kouki", "上河": "Kamikawa",
    "三四郎": "Sanshirou", "相馬": "Souma",
}
GIVEN_PREFIX = " "


def sites(image: bytes):
    """``[(operand_offset, va, jp_string, is_given)]`` for every name push."""
    pe = PE(image, "names")
    lo, hi = pe.va2off(FUNC_LO), pe.va2off(FUNC_HI)
    out = []
    i = lo
    prev_imm8 = False                      # previous push was ``6A nn``
    while i < hi:
        b = image[i]
        if b == 0x6A:                      # push imm8
            prev_imm8 = True
            i += 2
            continue
        if b == 0x68:                      # push imm32
            va = struct.unpack_from("<I", image, i + 1)[0]
            if TABLE_LO <= va < TABLE_HI:
                s = pe.cstring_at_va(va)
                jp = s.decode("cp932", "replace") if isinstance(s, (bytes, bytearray)) else str(s)
                out.append((i + 1, va, jp, prev_imm8))
            prev_imm8 = False
            i += 5
            continue
        prev_imm8 = False
        i += 1
    return out


def apply(image: bytes) -> bytes:
    """Append ``.nam`` with the English strings and re-point every push."""
    found = sites(image)
    if not found:
        raise RuntimeError("names: no name pushes found in 0x%X..0x%X" % (FUNC_LO, FUNC_HI))
    blob = bytearray()
    offsets: dict[tuple[str, bool], int] = {}
    for _, _, jp, given in found:
        if jp == "":
            continue                       # an empty given name stays empty
        if jp not in NAMES:
            raise RuntimeError("names: no English for %r" % jp)
        key = (jp, given)
        if key not in offsets:
            offsets[key] = len(blob)
            blob += ((GIVEN_PREFIX if given else "") + NAMES[jp]).encode("ascii") + b"\0"
    pe = PE(image, "names")
    nam_va = pe.imagebase + pe.sizeimage
    out = bytearray(pe.append_section(".nam", bytes(blob), NAM_CHARACTERISTICS))
    for off, _, jp, given in found:
        if jp == "":
            continue
        struct.pack_into("<I", out, off, nam_va + offsets[(jp, given)])
    return bytes(out)
