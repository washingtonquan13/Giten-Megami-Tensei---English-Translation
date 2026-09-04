"""Reversible text <-> bytes codec for a single translatable span.

A span's bytes are Shift-JIS (cp932) text interleaved with a small number of
control sequences.  :func:`render` turns those bytes into a one-line editable
string; :func:`encode` turns an edited string back into bytes.  ``encode`` is the
exact inverse of ``render`` for everything a translator is allowed to type.

Token language
--------------
======================  =========================================  ===========
bytes                   rendered as                                editable?
======================  =========================================  ===========
``0A``                  ``\\n``                                     yes
``1E 10 01 01``         ``<wait>``                                  yes
``08 nn``               the dictionary entry's text, expanded       n/a (gone)
``08 nn`` (no entry)    ``{DICT:nn}``                               must be fixed
any unclassifiable byte ``{XX}`` (two upper-case hex digits)        keep verbatim
``\\``, ``{``, ``<``      ``\\\\``, ``\\{``, ``\\<``                      yes
======================  =========================================  ===========

``\\t`` and ``\\r`` also exist so a rendered span can never break the TSV, though
neither byte occurs in the shipped data.

Why escape ``{`` and ``<``: without it a literal ``{7B}`` or ``<wait>`` typed by a
translator would be indistinguishable from a control token, and the codec would
stop being reversible.  Escaping is cheap and makes the round trip total.
"""
from __future__ import annotations

import re

# --- byte classes -----------------------------------------------------------
# Shift-JIS lead / trail byte tests.  Getting these right is the single most
# important detail in the whole tokenizer: a trail byte can be anything from
# 0x40..0xFC (0x7F excluded), which overlaps ASCII, so a naive "is this byte a
# control code?" scan mis-reads the second half of a kanji as an opcode.
def is_sjis_lead(b: int) -> bool:
    return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xEF


def is_sjis_trail(b: int) -> bool:
    return 0x40 <= b <= 0xFC and b != 0x7F


def is_halfwidth_kana(b: int) -> bool:
    return 0xA1 <= b <= 0xDF


def is_ascii_text(b: int) -> bool:
    return 0x20 <= b < 0x7F


WAIT_BYTES = b"\x1e\x10\x01\x01"
WAIT_TOKEN = "<wait>"
DICT_ESCAPE = 0x08
NEWLINE = 0x0A

_ESCAPES = {"\\": "\\\\", "{": "\\{", "<": "\\<", "\n": "\\n", "\t": "\\t", "\r": "\\r"}
_UNESCAPES = {"\\": "\\", "{": "{", "<": "<", "n": "\n", "t": "\t", "r": "\r"}

# NB: no ^ anchor -- these are used with .match(text, i), and in Python
# "^" only matches at position 0 regardless of the pos argument.
_CTRL_RE = re.compile(r"\{([0-9A-Fa-f]{2})\}")
_DICT_RE = re.compile(r"\{DICT:([0-9A-Fa-f]{2})\}")


def _escape(s: str) -> str:
    return "".join(_ESCAPES.get(c, c) for c in s)


class SpanDecodeError(ValueError):
    pass


class SpanEncodeError(ValueError):
    pass


# --- bytes -> text ----------------------------------------------------------
def render(data: bytes, dic: "dict[int, bytes] | None" = None, _depth: int = 0) -> str:
    """Render span bytes as an editable string.

    ``dic`` is the ``08 nn`` dictionary (see :mod:`.dictionary`); pass ``None`` to
    leave references as ``{DICT:nn}`` tokens instead of expanding them.
    """
    out = []
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if data[i : i + 4] == WAIT_BYTES:
            out.append(WAIT_TOKEN)
            i += 4
            continue
        if b == DICT_ESCAPE and i + 1 < n:
            idx = data[i + 1]
            if dic is not None and _depth < 6 and idx in dic:
                out.append(render(dic[idx], dic, _depth + 1))
            else:
                out.append("{DICT:%02X}" % idx)
            i += 2
            continue
        if b == NEWLINE:
            out.append("\\n")
            i += 1
            continue
        if is_ascii_text(b):
            out.append(_escape(chr(b)))
            i += 1
            continue
        if is_sjis_lead(b) and i + 1 < n and is_sjis_trail(data[i + 1]):
            try:
                out.append(_escape(data[i : i + 2].decode("cp932")))
                i += 2
                continue
            except UnicodeDecodeError:
                pass
        if is_halfwidth_kana(b):
            out.append(_escape(bytes([b]).decode("cp932")))
            i += 1
            continue
        out.append("{%02X}" % b)
        i += 1
    return "".join(out)


# --- text -> bytes ----------------------------------------------------------
def encode(text: str, allow_dict_refs: bool = False) -> bytes:
    """Encode an edited span string back to bytes.

    Raises :class:`SpanEncodeError` on an unencodable character, a malformed
    escape, or -- unless ``allow_dict_refs`` -- a surviving ``{DICT:nn}`` token.
    """
    out = bytearray()
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            if i + 1 >= n:
                raise SpanEncodeError("trailing backslash")
            e = text[i + 1]
            if e not in _UNESCAPES:
                raise SpanEncodeError("unknown escape \\%s" % e)
            ch = _UNESCAPES[e]
            if ch == "\n":
                out.append(NEWLINE)
            elif ch == "\t":
                out.append(0x09)
            elif ch == "\r":
                out.append(0x0D)
            else:
                out += ch.encode("cp932")
            i += 2
            continue
        if text.startswith(WAIT_TOKEN, i):
            out += WAIT_BYTES
            i += len(WAIT_TOKEN)
            continue
        if c == "{":
            m = _DICT_RE.match(text, i)
            if m:
                if not allow_dict_refs:
                    raise SpanEncodeError(
                        "unexpanded dictionary reference {DICT:%s}" % m.group(1)
                    )
                out += bytes([DICT_ESCAPE, int(m.group(1), 16)])
                i = m.end()
                continue
            m = _CTRL_RE.match(text, i)
            if m:
                out.append(int(m.group(1), 16))
                i = m.end()
                continue
            raise SpanEncodeError("stray '{' at offset %d (write '\\{' for a literal)" % i)
        if c == "<":
            raise SpanEncodeError("stray '<' at offset %d (write '\\<' for a literal)" % i)
        try:
            out += c.encode("cp932")
        except UnicodeEncodeError:
            raise SpanEncodeError("character %r (U+%04X) is not encodable in cp932"
                                  % (c, ord(c)))
        i += 1
    return bytes(out)


# --- helpers used by the validators / stats --------------------------------
_JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff00-\uff9f\u3000-\u303f]")


def has_japanese(text: str) -> bool:
    """True if the rendered text still contains kana/kanji/full-width forms.

    Used to decide whether a span is already translated.  Deliberately counts
    full-width punctuation and half-width katakana (U+FF00..U+FF9F) as Japanese:
    those are exactly the leftovers an unfinished translation shows.
    """
    return bool(_JP_RE.search(strip_tokens(text)))


_TOKEN_RE = re.compile(r"\\.|<wait>|\{DICT:[0-9A-Fa-f]{2}\}|\{[0-9A-Fa-f]{2}\}")


def strip_tokens(text: str) -> str:
    """Rendered text with every control token removed, escapes resolved."""
    def sub(m):
        s = m.group(0)
        if s.startswith("\\"):
            ch = _UNESCAPES.get(s[1], "")
            return "" if ch in ("\n", "\t", "\r") else ch
        return ""
    return _TOKEN_RE.sub(sub, text)


def control_tokens(text: str) -> "list[str]":
    """Every ``{XX}`` / ``{DICT:nn}`` token, in order (validator (b) and (h))."""
    return [m.group(0) for m in _TOKEN_RE.finditer(text)
            if m.group(0).startswith("{")]


def lines_of(text: str) -> "list[str]":
    """Split a rendered span on ``\\n`` and ``<wait>``.

    Both start a new display line as far as the width budget is concerned.  The
    split walks the escape grammar rather than using a regex, so an escaped
    backslash immediately before an ``n`` (``\\\\n``) is not mistaken for a
    newline.
    """
    parts = [[]]
    i = 0
    n = len(text)
    while i < n:
        if text.startswith(WAIT_TOKEN, i):
            parts.append([])
            i += len(WAIT_TOKEN)
            continue
        if text[i] == "\\" and i + 1 < n:
            if text[i + 1] == "n":
                parts.append([])
            else:
                parts[-1].append(text[i : i + 2])
            i += 2
            continue
        parts[-1].append(text[i])
        i += 1
    return ["".join(p) for p in parts]


def display_width(text: str) -> int:
    """Width of one line in half-width units (8 px each).

    Half-width ASCII and half-width katakana are 1, everything else (full-width
    Shift-JIS) is 2, control tokens are 0.  This is the same unit the game's
    8x16 / 16x16 bitmap font measures in.
    """
    w = 0
    for ch in strip_tokens(text):
        if ch in ("\n", "\t", "\r"):
            continue
        o = ord(ch)
        if o < 0x80 or 0xFF61 <= o <= 0xFF9F:
            w += 1
        else:
            w += 2
    return w
