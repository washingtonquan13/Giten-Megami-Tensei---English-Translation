"""String discovery, slot measurement, reference scanning and record-stride
detection.

Everything here is a pure function of the two reference images, so ``extract``
is fully reproducible: delete ``strings.tsv``, re-run, get the same file back
(minus any hand-written ``en``/``note`` values, which ``extract`` preserves by
merging -- see ``extract.py``).
"""
from __future__ import annotations

import struct

from . import config

# ---------------------------------------------------------------------------
# What counts as text
# ---------------------------------------------------------------------------

def _is_text_char(ch: str) -> bool:
    o = ord(ch)
    if ch in "\t\n\r":
        return True
    if 0x20 <= o <= 0x7E:
        return True
    if 0x00A0 <= o <= 0x00FF:          # latin-1 supplement (rare, via cp932)
        return True
    if 0x2010 <= o <= 0x266F:          # CJK punctuation/symbols block range
        return True
    if 0x3000 <= o <= 0x30FF:          # CJK punctuation, hiragana, katakana
        return True
    if 0x3200 <= o <= 0x33FF:          # enclosed CJK / CJK compat
        return True
    if 0x4E00 <= o <= 0x9FFF:          # unified ideographs
        return True
    if 0xF900 <= o <= 0xFAFF:          # compat ideographs
        return True
    if 0xFF01 <= o <= 0xFF9F:          # fullwidth forms + halfwidth katakana
        return True
    return False


def decode_string(raw: bytes):
    """Decode one candidate string.

    Returns ``(text, ok)``.  A single leading control byte (0x01-0x1F) is
    permitted and kept in the text -- the status-effect table stores each record
    as ``[id byte][name]`` and the id byte reads as a control character, which
    the 1999 translator preserved verbatim when they replaced the names.
    """
    if not raw:
        return "", False
    body = raw
    lead = ""
    if raw[0] < 0x20 and raw[0] not in (0x09, 0x0A, 0x0D):
        lead = chr(raw[0])
        body = raw[1:]
        if not body:
            return "", False
    try:
        text = body.decode("cp932")
    except UnicodeDecodeError:
        return "", False
    if not text:
        return "", False
    if not all(_is_text_char(c) for c in text):
        return "", False
    has_jp = any(ord(c) > 0x7F for c in text)
    if not has_jp and len(text) < 2:
        return "", False
    return lead + text, True


def is_japanese(text: str) -> bool:
    return any(ord(c) > 0x7F for c in text)


_JP_SCRIPT_RANGES = (
    (0x3005, 0x3007),    # 々 〆 〇
    (0x3041, 0x309F),    # hiragana
    (0x30A0, 0x30FF),    # katakana
    (0x3400, 0x4DBF),    # CJK ext A
    (0x4E00, 0x9FFF),    # CJK unified ideographs
    (0xF900, 0xFAFF),    # CJK compatibility ideographs
    (0xFF10, 0xFF19),    # fullwidth digits
    (0xFF21, 0xFF3A),    # fullwidth uppercase
    (0xFF41, 0xFF5A),    # fullwidth lowercase
    (0xFF61, 0xFF9F),    # halfwidth katakana
)


def needs_translation(text: str) -> bool:
    """True when the text still reads as Japanese to a player.

    Deliberately narrower than :func:`is_japanese`: fullwidth *punctuation*
    (／, 「, ）, the ideographic space) is not Japanese language, and the v0.05
    patch kept it on purpose -- ``Demon%5d／%2d`` and the kinsoku line-breaking
    tables at 0x68214 are finished work, not leftovers.  Fullwidth Latin and
    digits do count, because ＤＡＳ and １０ are the Japanese typographic form
    of text an English build should render half-width.
    """
    for c in text:
        o = ord(c)
        for lo, hi in _JP_SCRIPT_RANGES:
            if lo <= o <= hi:
                return True
    return False


def _body(text: str) -> str:
    """Text without a leading status-table record-id control byte."""
    if text and ord(text[0]) < 0x20 and text[0] not in "\t\n\r":
        return text[1:]
    return text


def _halfwidth_kana(ch: str) -> bool:
    return 0xFF61 <= ord(ch) <= 0xFF9F


def looks_like_data(pe, off: int, raw: bytes, text: str) -> bool:
    """True when a decodable candidate is really binary, not a string.

    ``.rdata``/``.data`` are full of pointer tables and float constants whose
    bytes happen to decode as CP932.  Three signatures catch essentially all of
    them without discarding real strings:

    * a 4-aligned run of at most 3 bytes whose dword (terminator included)
      resolves to a real section -- that is a pointer, and the exe is packed
      with tables of them;
    * half-width katakana mixed with ASCII, or one or two of them alone -- real
      text either avoids the FF61..FF9F block entirely or is written wholly in
      it (the status name ｽﾗｲﾑ);
    * a one- or two-character string that mixes ASCII with a double-byte
      character -- the tail of a pointer next to the previous entry's high byte.
    """
    if off % 4 == 0 and len(raw) <= 3:
        dword = int.from_bytes(pe.data[off:off + 4], "little")
        if pe.sec_for_rva(dword - pe.imagebase) is not None:
            return True

    body = _body(text)
    kana = [c for c in body if _halfwidth_kana(c)]
    if kana:
        if len(kana) != len(body) or len(body) < 3:
            return True

    if len(body) <= 2 and any(ord(c) < 0x80 for c in body) and any(ord(c) > 0x7F for c in body):
        return True
    return False


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

class Found:
    __slots__ = ("off", "va", "section", "raw", "text", "slot")

    def __init__(self, off, va, section, raw, text, slot):
        self.off = off
        self.va = va
        self.section = section
        self.raw = raw
        self.text = text
        self.slot = slot

    def __repr__(self):  # pragma: no cover - debugging aid
        return "<Found %08x %s %r slot=%d>" % (self.off, self.section, self.text, self.slot)


def find_strings(pe, sections=config.STRING_SECTIONS):
    """Enumerate NUL-terminated text strings in the named sections.

    ``slot`` is the writable extent: the string's own bytes plus the run of NUL
    bytes that follows it, i.e. the distance to the next live byte.  A
    replacement of ``slot`` bytes including its own terminator always fits.
    """
    d = pe.data
    out = []
    for name in sections:
        sec = pe.section(name)
        if sec is None:
            continue
        lo = sec["rawptr"]
        hi = sec["rawptr"] + sec["rawsize"]
        o = lo
        while o < hi:
            if d[o] == 0:
                o += 1
                continue
            end = d.find(b"\0", o, hi)
            if end < 0:
                break
            raw = d[o:end]
            nul = end
            while nul < hi and d[nul] == 0:
                nul += 1
            text, ok = decode_string(raw)
            if ok and not looks_like_data(pe, o, raw, text):
                out.append(Found(o, pe.off2va(o), name, raw, text, nul - o))
            o = nul
    out.sort(key=lambda f: f.off)
    return out


def build_ref_index(pe, sections=config.REF_SECTIONS):
    """Map every 4-byte little-endian value that looks like a section VA to the
    file offsets where it occurs.

    One pass over the scanned sections instead of one ``bytes.find`` sweep per
    string -- with ~2000 strings the naive version is minutes, this is under a
    second.
    """
    d = pe.data
    lo_va = pe.imagebase
    hi_va = pe.imagebase + pe.sizeimage
    index = {}
    for name in sections:
        sec = pe.section(name)
        if sec is None:
            continue
        start = sec["rawptr"]
        stop = sec["rawptr"] + sec["rawsize"] - 3
        for o in range(start, stop):
            v = d[o] | (d[o + 1] << 8) | (d[o + 2] << 16) | (d[o + 3] << 24)
            if lo_va <= v < hi_va:
                index.setdefault(v, []).append(o)
    return index


def detect_record_widths(founds, ref_index, min_run=4, max_stride=64):
    """Return ``{offset: stride}`` for strings that live inside a fixed-stride
    record table rather than being pointed at.

    A run qualifies when at least ``min_run`` consecutive strings share one
    start-to-start stride *and* almost none of them are referenced by an imm32 --
    an unreferenced regular grid is an array the code indexes by record number,
    which is exactly the case where a replacement must stay inside its record.
    Pointer-addressed pools (the character-name table, for instance) also look
    regular but are freely relocatable, so the reference test keeps them out.
    """
    widths = {}
    n = len(founds)
    i = 0
    while i < n - 1:
        stride = founds[i + 1].off - founds[i].off
        if stride <= 0 or stride > max_stride:
            i += 1
            continue
        j = i + 1
        while j < n - 1 and founds[j + 1].off - founds[j].off == stride:
            j += 1
        run = founds[i:j + 1]
        if len(run) >= min_run:
            referenced = sum(1 for f in run if ref_index.get(f.va))
            if referenced * 4 < len(run):          # fewer than 25% referenced
                for f in run:
                    if len(f.raw) < stride:        # string + terminator must fit
                        widths[f.off] = stride
            i = j
        else:
            i += 1
    return widths


# ---------------------------------------------------------------------------
# Width budget
# ---------------------------------------------------------------------------

def pixel_width(text: str) -> int:
    """Rendered width in pixels: 8 px per half-width cell, 16 per double-byte.

    Control bytes (status-table record ids) and format specifiers are not
    rendered literally, so ``%s``/``%d``/newlines are excluded from the budget
    by :func:`display_width`.
    """
    w = 0
    for c in text:
        o = ord(c)
        if o < 0x20:
            continue
        w += config.WIDE_CELL_PX if o > 0x7F else config.ASCII_CELL_PX
    return w


def display_width(text: str) -> int:
    """Pixel width with printf specifiers and newlines stripped.

    A ``%10ld`` occupies ten cells at run time, not five, but the point of the
    budget is comparing jp against en, and both sides carry the same
    specifiers -- so dropping them from both is the honest comparison.
    """
    stripped = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "%":
            j = i + 1
            while j < len(text) and text[j] in "-+ #0123456789.":
                j += 1
            while j < len(text) and text[j] in "hlL":
                j += 1
            if j < len(text):
                j += 1
            i = j
            continue
        if c in "\r\n":
            i += 1
            continue
        stripped.append(c)
        i += 1
    return pixel_width("".join(stripped))


def encode(text: str) -> bytes:
    return text.encode("cp932")
