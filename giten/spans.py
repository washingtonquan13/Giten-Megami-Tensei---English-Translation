"""Finding the translatable text spans inside a decoded body.

A *span* is a maximal run of displayable bytes that the game will draw.  Spans
are found, never guessed at: a span may only start at a place we know introduces
text, and it stops at the first byte that is not part of the text grammar.
Everything outside a span -- opcodes, operands, jump targets, tables -- is never
shown to a translator and is re-emitted from the source file verbatim.

Where a span can start
----------------------
* right after one of the :data:`TEXT_TAGS` two-byte ``1F xx`` tags;
* at the first byte of a record's payload, in the ``m/MS6*`` / ``m/MS7F*``
  record pools, whose records hold bare text with no leading tag.

Where a span stops
------------------
At the first byte that is not one of: ASCII ``20..7E``, half-width katakana
``A1..DF``, a valid Shift-JIS pair, ``0A`` (newline), ``08 nn`` (dictionary
macro), the four-byte page-wait ``1E 10 01 01``, or one of the five
:data:`INLINE_CONTROLS`.

The inline-control set is empirical, not assumed.  Counting control bytes that
sit *surrounded on both sides* by at least three text characters across all 412
script files gives a sharp split: ``02`` (592), ``01`` (229), ``03`` (175),
``0C`` (127), ``0B`` (66), then a long tail of ones and tens that are plainly
neighbouring opcodes (``18``: 21, ``1E``: 13, ...).  The first five are variable
inserts -- ``{01}{03}：`` is a speaker line whose name is substituted at runtime.
They are carried through as ``{XX}`` tokens and must be preserved by the
translator; every other control byte ends the span.

Why ``0x1F`` scanning advances one byte at a time
-------------------------------------------------
``08 1F`` (dictionary entry 0x1F) is a legal two-byte sequence, and it occurs
immediately before ``1F D2`` in several files.  A scanner that consumed two bytes
per ``1F`` would swallow the real tag and silently drop the speaker name.
Advancing by one recovers it.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import framing, tokens

#: ``1F xx`` tags after which display text begins.  Derived by counting, for every
#: distinct tag in the corpus, how often it is followed by >= 2 text characters:
#: D2 99%, B2 93%, D3 91%, D0 53%, FA/FB/BA/D1 lower but with unmistakable real
#: lines among them.  Every other tag scores ~0% and is treated as an opcode.
TEXT_TAGS = {
    0xD0: "1FD0",   # narration window open
    0xD1: "1FD1",   # window close -- occasionally carries a prompt line
    0xD2: "1FD2",   # speaker name
    0xD3: "1FD3",   # speech line
    0xB2: "1FB2",   # choice option
    0xBA: "1FBA",   # narration continuation
    0xFA: "1FFA",   # styled-run text (opened by 1F F9)
    0xFB: "1FFB",   # styled-run continuation
}

#: Control bytes that occur *within* running text (runtime variable inserts).
INLINE_CONTROLS = frozenset({0x01, 0x02, 0x03, 0x0B, 0x0C})

STOP_BYTES = frozenset({0x00, 0x1F, 0x7F})

#: Tag used for a record-pool payload that starts with bare text (no ``1F`` tag).
DATA_TAG = "DATA"


@dataclass
class Span:
    """One translatable run of bytes.

    ``rec``/``idx`` together with the file name form the stable row identity used
    by the TSV tables; ``off`` is the byte offset of the span inside its frame and
    is informational only (it moves when an earlier span changes length).
    """

    rec: str          # frame key: "R7:AA" for a record, "F0" otherwise
    idx: int          # index of this span within its frame
    start: int        # absolute offset in the body
    end: int
    tag: str
    frame_index: int
    fixed_len: "int | None" = None   # fixed-width field (p/ names): exact byte size

    @property
    def off(self) -> int:
        return self.start


def _span_end(body: bytes, i: int, limit: int) -> int:
    """Walk forward from ``i`` while the bytes belong to the text grammar."""
    n = limit
    while i < n:
        b = body[i]
        if b in STOP_BYTES:
            break
        if body[i : i + 4] == tokens.WAIT_BYTES:
            i += 4
            continue
        if b == tokens.NEWLINE:
            i += 1
            continue
        if b == tokens.DICT_ESCAPE:
            if i + 1 >= n:
                break           # dangling 08 at the edge -- not text
            i += 2
            continue
        if b in INLINE_CONTROLS:
            i += 1
            continue
        if b < 0x20:
            break               # unknown opcode: stop, do not guess its operands
        if tokens.is_ascii_text(b):
            i += 1
            continue
        if tokens.is_sjis_lead(b) and i + 1 < n and tokens.is_sjis_trail(body[i + 1]):
            i += 2
            continue
        if tokens.is_halfwidth_kana(b):
            i += 1
            continue
        break                   # high byte that is not valid Shift-JIS
    return i


def _accept(text: str) -> bool:
    """Is this rendered span worth showing to a translator?"""
    return bool(tokens.strip_tokens(text).strip())


def scan_frame(body: bytes, frame: framing.Frame, dic) -> "list[Span]":
    """Every span inside one frame, in offset order."""
    out = []
    lo, hi = frame.data_start, frame.data_end
    i = lo

    # Record payloads may open with bare text and no introducing tag.
    if frame.kind == "record" and i < hi and body[i] not in STOP_BYTES:
        end = _span_end(body, i, hi)
        if end > i and _accept(tokens.render(body[i:end], dic)):
            out.append(Span(frame.key, len(out), i, end, DATA_TAG, frame.index))
            i = end

    while i < hi - 1:
        if body[i] == 0x1F and body[i + 1] in TEXT_TAGS:
            tag = TEXT_TAGS[body[i + 1]]
            s = i + 2
            e = _span_end(body, s, hi)
            if e > s and _accept(tokens.render(body[s:e], dic)):
                out.append(Span(frame.key, len(out), s, e, tag, frame.index))
                i = e
                continue
        i += 1
    return out


# --- p/ character records ---------------------------------------------------
#: Byte offset of the display-name field inside a ``p/P%04X.BIN`` body, and its
#: fixed width.  The field is NUL-padded and edited in place: the record is a
#: fixed 122-byte (occasionally 121-byte) struct, so the name may never grow.
PNAME_OFF = 0x36
PNAME_LEN = 16
PNAME_TAG = "NAME"


def scan_pname(body: bytes, frame: framing.Frame) -> "list[Span]":
    if len(body) < PNAME_OFF + PNAME_LEN:
        return []
    return [
        Span(frame.key, 0, PNAME_OFF, PNAME_OFF + PNAME_LEN, PNAME_TAG,
             frame.index, fixed_len=PNAME_LEN)
    ]


def pname_text(body: bytes, dic=None) -> str:
    """The name as stored: everything up to the first NUL."""
    raw = body[PNAME_OFF : PNAME_OFF + PNAME_LEN].split(b"\x00", 1)[0]
    return tokens.render(raw, dic)


def scan(rel: str, body: bytes, dic) -> "tuple[list[framing.Frame], list[Span]]":
    """Frames and spans for one decoded body."""
    frames = framing.parse(rel, body)
    if rel.startswith("p/"):
        return frames, scan_pname(body, frames[0])
    spans = []
    for fr in frames:
        spans.extend(scan_frame(body, fr, dic))
    return frames, spans


def span_text(body: bytes, sp: Span, dic) -> str:
    """Rendered text for one span (handles the NUL padding of fixed fields)."""
    raw = body[sp.start : sp.end]
    if sp.fixed_len is not None:
        raw = raw.split(b"\x00", 1)[0]
    return tokens.render(raw, dic)


def suspect(text: str) -> bool:
    """True if a rendered span looks like misread operand data rather than a line.

    Reported in the ``note`` column and counted separately by ``stats`` so the
    "remaining to translate" figure is not inflated by a few hundred fragments.
    """
    stripped = tokens.strip_tokens(text).strip()
    if not stripped:
        return True
    if not any(c.isalnum() or ord(c) > 0x7F for c in stripped):
        return True
    # A line that is nothing but a variable insert and one stray character.
    return len(stripped) < 2 and text.startswith("{")
