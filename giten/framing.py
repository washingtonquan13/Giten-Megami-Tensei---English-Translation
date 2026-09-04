"""How a decoded body is divided into frames, and which frames own a length field.

A *frame* is a contiguous slice of the body.  Frames tile the body completely and
never overlap, so the builder can walk them in order, splice edited spans into
each one, and copy everything else through untouched.  A frame either carries a
u16 length field that the builder must rewrite when its payload changes size, or
it carries none and is spliced in place.

Two framings are implemented.

``record`` -- ``m/MS6*.BIN`` and ``m/MS7F*.BIN``
    These are pools of records::

        [ id:u8 | len:u16 LE | data:len ]  ...

    ``data`` always ends with ``00``; ``len`` counts that terminator.  The walk is
    *verified* rather than assumed: a candidate record is only accepted when its
    declared length lands on a ``00``.  Most of these files parse cleanly end to
    end, but some (``m/MS6007.BIN``, ``m/MS6F00.BIN``) contain short runs between
    record blocks that are not records -- ``5F 6A 66 00`` sits between the ``A*``
    and ``4*`` id blocks of MS6007, for instance.  Rather than guess at those, the
    parser resynchronises one byte at a time and leaves them as ``gap`` frames,
    which are copied through verbatim.  Because the length field of a real record
    is understood, an edit that changes a record's byte count is safe here.

``flat`` -- everything else
    The ``m/MS0*``..``m/MS1*`` event scripts and ``et/ET*`` / ``et/ID*`` are raw
    opcode streams with the text inlined between ``1F xx`` tags.  A general
    ``[id][len]`` walk does **not** hold for them: only 60 of 303 script files
    parse strictly to the end, and inspecting those shows the matches are
    coincidental (``m/MS0000.BIN`` "parses" as two 13 KB records).  There is
    evidence of a ``0B <u16 len>`` show-message opcode in at least some event
    scripts -- in ``m/MS0003.BIN`` three consecutive message blocks match their
    declared length exactly -- but no framing that reproduces a whole stream has
    been found, and a scan for ``0B``-prefixed blocks covers only 15-80% of the
    text tags depending on the file.  So this module refuses to guess: a flat
    frame has no length field, and ``check`` reports every edit that changes the
    byte length of a span inside one.

Adding a framing later is a two-line change: write a parser that returns
:class:`Frame` objects and register it in :data:`FRAMINGS`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Frame:
    """A contiguous region of the body that spans may live inside.

    ``data_start``/``data_end`` bound the editable payload.  ``len_off`` is the
    offset of the u16 length field that must be rewritten when the payload's size
    changes, or ``None`` when the framing is unknown.  ``len_bias`` is added to
    the payload size to produce the stored value (0 for the record framing, whose
    stored length includes the terminator that is part of the payload).
    """

    index: int                      # ordinal within the file; stable identity
    rec_id: "int | None"            # record id byte, or None
    data_start: int
    data_end: int
    len_off: "int | None" = None
    len_bias: int = 0
    kind: str = "flat"              # "record" | "gap" | "flat"

    @property
    def key(self) -> str:
        """Frame identity used in the TSV ``rec`` column.  Unique within a file."""
        if self.rec_id is None:
            return "F%d" % self.index
        return "R%d:%02X" % (self.index, self.rec_id)


_POOL_RE = re.compile(r"^m/MS(6|7F)", re.I)

#: Sanity bound on a record's declared length.  Real pool records are short
#: (the longest in the corpus is well under 1 KB); a multi-kilobyte "length"
#: is the resync walk landing on binary data, and accepting it would swallow
#: real records whole.
_MAX_RECORD = 0x1000


#: A fresh record chain must be confirmed by this many consecutive parses before
#: the walk believes it.  A single ``[id][len][.. 00]`` match is far too easy to
#: hit by chance in binary data.
_CONFIRM = 3

#: A record's payload must be at least this fraction text to be kept.
_TEXT_FRACTION = 0.6

#: ... and at least this fraction of the walk's records must pass that test
#: before the file is treated as a record pool at all.
_POOL_FRACTION = 0.5
_POOL_MIN_RECORDS = 5


def _record_at(body: bytes, i: int, n: int) -> "int | None":
    if i + 3 > n:
        return None
    ln = int.from_bytes(body[i + 1 : i + 3], "little")
    if 0 < ln <= _MAX_RECORD and i + 3 + ln <= n and body[i + 3 + ln - 1] == 0:
        return ln
    return None


def _confirm(body: bytes, i: int, n: int, k: int) -> "tuple[int, int]":
    """How many records parse consecutively from ``i`` (capped at ``k``)."""
    c = 0
    while c < k:
        ln = _record_at(body, i, n)
        if ln is None:
            break
        i += 3 + ln
        c += 1
    return c, i


def _walk(body: bytes) -> "list[tuple[int, int, int]]":
    """``(header_off, data_start, data_end)`` for every believed record."""
    out = []
    i = 2
    n = len(body)
    while i + 3 <= n:
        ln = _record_at(body, i, n)
        ok = False
        if ln is not None:
            if out and out[-1][2] == i:
                ok = True                     # continuing an established chain
            else:
                c, end = _confirm(body, i, n, _CONFIRM)
                ok = c >= _CONFIRM or (c >= 1 and end == n)
        if ok:
            out.append((i, i + 3, i + 3 + ln))
            i += 3 + ln
        else:
            i += 1                            # resynchronise
    return out


def _payload_is_text(body: bytes, start: int, end: int, text_end) -> bool:
    """Does this record payload consist (mostly) of displayable text?"""
    stop = end - 1                            # drop the trailing 00
    if stop - start < 2:
        return False
    reach = text_end(body, start, stop)
    return (reach - start) >= _TEXT_FRACTION * (stop - start)


def parse_record_pool(body: bytes, text_end=None) -> "list[Frame] | None":
    """``[id][len][data]`` walk, kept only where the payloads are really text.

    ``text_end(body, i, limit)`` reports how far the text grammar reaches from
    ``i``; :mod:`.spans` supplies it (injected rather than imported to keep the
    module dependency one-way).  Records whose payload is not predominantly text
    are dropped and become gaps, so a length field is only ever rewritten for a
    record we can see holds a line of dialogue.  If too few records survive, the
    file is not a pool at all and ``None`` sends it to the flat framing.
    """
    if text_end is None:
        from .spans import _span_end as text_end          # local import: cycle-free
    candidates = _walk(body)
    keep = [c for c in candidates if _payload_is_text(body, c[1], c[2], text_end)]
    if len(keep) < _POOL_MIN_RECORDS or len(keep) < _POOL_FRACTION * len(candidates):
        return None
    return [
        Frame(index=0, rec_id=body[h], data_start=s, data_end=e,
              len_off=h + 1, kind="record")
        for h, s, e in keep
    ]


def _tile(frames: "list[Frame]", n: int) -> "list[Frame]":
    """Fill the holes between frames with ``gap`` frames and renumber in order."""
    out: "list[Frame]" = []
    cursor = 0
    for fr in frames:
        if fr.data_start > cursor:
            out.append(Frame(index=0, rec_id=None, data_start=cursor,
                             data_end=fr.data_start, kind="gap"))
        out.append(fr)
        cursor = fr.data_end
    if cursor < n:
        out.append(Frame(index=0, rec_id=None, data_start=cursor,
                         data_end=n, kind="gap"))
    for k, fr in enumerate(out):
        fr.index = k
    return out


def parse_flat(body: bytes) -> "list[Frame]":
    """One frame covering the whole body, with no length field."""
    return [Frame(index=0, rec_id=None, data_start=0, data_end=len(body),
                  kind="flat")]


#: ``(predicate on the "dir/FILE.BIN" key, parser)``; first match that yields
#: frames wins, otherwise the body is treated as flat.
FRAMINGS = [
    (lambda rel: bool(_POOL_RE.match(rel)), parse_record_pool),
]


def parse(rel: str, body: bytes) -> "list[Frame]":
    """Frames for one decoded body.  Always tiles the body completely."""
    for pred, parser in FRAMINGS:
        if pred(rel):
            frames = parser(body)
            if frames:
                return _tile(frames, len(body))
    return parse_flat(body)
