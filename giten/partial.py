"""Prefix tiling: recover text from a record the tokenizer cannot walk to the end.

148 of 20,588 ``m/`` records fail to tile, and they are not junk -- they hold shop
clerks, in-script menus and opening-scene dialogue (7,837 full-width characters).
Both the byte builder and the overlay refuse them, so that text is untranslatable
rather than merely untranslated.

For many of them the walk is right for almost the whole record and only fails at
the end.  ``m/MS0080.BIN`` is the worked example: all five records tile for 97% of
their length -- every byte of dialogue -- and fail on a six-byte trailer
``1f 00 10 01 01 00`` that occurs on exactly six records corpus-wide, all of them
untiled.

**Why a partial walk can be safe at all.**  From ``hook.c``: ``in_range`` matches
any ``pc`` in ``[start, start + served)``, and after the last served byte the hook
sets ``*pcp = s->end``.  So the interpreter arrives at ``start``, consumes English,
and resumes at ``end``.  *Nothing else about the record matters.*  The entire
safety condition is:

    ``start`` and ``end`` must both be genuine instruction boundaries.

That is much weaker than "the record is fully understood", and it is checkable.

**Why "before the failure point" is NOT sufficient.**  A prefix walk can contain
errors and resynchronise.  MS0080's own header does exactly that: ``02 1f`` is
read as opcode 0x002 with a ``u8`` operand, eating an escape byte, which produces
two junk spans before the walk realigns.  So a span is accepted only on positive
evidence, never on "the walk had not failed yet":

``anchored``
    ``start`` is immediately preceded by a complete text-introducing opcode token,
    and ``end`` is the offset of a token the walk produced.  The boundary is
    inherited from an opcode we recognise, not from wherever the walk happened to
    be.
``clean``
    ``[start, end)`` decodes as cp932 with no replacement characters, and contains
    no byte below 0x20 that is not a recognised inline code.  A start landing
    mid-character cannot survive this -- that is exactly how the known-bad
    ``j性：`` spans present.
``resumable``
    Re-tokenising the record *from* ``end`` reproduces the same token stream the
    full walk had from ``end`` onward.  If ``end`` were not a real boundary the
    independent walk would diverge or fail.

:func:`verify_span` requires all three.  The fourth and strongest check, when a
trace is available, is the engine's own token program counters -- see
:func:`giten.tile.observe`.
"""
from __future__ import annotations

from . import codec, script, vmops

#: Opcodes that introduce a text run.  A span may only begin right after one of
#: these.  Derived from the tags find_spans already assigns to text spans.
TEXT_INTRO_OPS = frozenset({
    0x1D2,      # 1F D2 -- speaker name
    0x1D3,      # 1F D3 -- dialogue body
    0x1B1,      # 1F B1 -- menu option (choice width)
    0x1B2,      # 1F B2
    0x212,      # 1E 12
})

#: Files where prefix tiling is permitted.  Opt-in per file, so a record is only
#: exposed after its spans have been verified and the file play-tested.
PREFIX_TILE_FILES = frozenset({
    "m/MS0080.BIN",
})


class UnsafeSpan(RuntimeError):
    pass


def tokenize_prefix(data: bytes, tab=None):
    """``(tokens, ok)`` -- tokens tiled from 0, and the offset where tiling stopped.

    ``ok == len(data)`` means the record tiled completely and this is exactly what
    :func:`vmops.tokenize` would have returned.
    """
    tab = tab or vmops.table()
    out, i, n = [], 0, len(data)
    while i < n:
        b = data[i]
        if b >= 0x20:
            size = 2 if (vmops.is_sjis_lead(b) and i + 1 < n) else 1
            out.append(vmops.Token("text", i, size))
            i += size
            continue
        if b in vmops.ESCAPE:
            if i + 1 >= n:
                break
            idx = vmops.ESCAPE[b] + data[i + 1]
            head = 2
        else:
            idx, head = b, 1
        try:
            j, ops = vmops._read_operands(data, i + head, tab.operands(idx), tab)
        except vmops.TileError:
            break
        out.append(vmops.Token("op", i, j - i, idx, tuple(ops)))
        i = j
    return out, i


def _clean_text(data: bytes, lo: int, hi: int) -> bool:
    """Does ``[lo, hi)`` read as text, with no evidence of a bad boundary?"""
    chunk = data[lo:hi]
    if not chunk:
        return False
    try:
        s = chunk.decode("cp932")
    except UnicodeDecodeError:
        return False
    if "�" in s:
        return False
    # a start landing mid-character, or a span swallowing an opcode, shows up as
    # a control byte that is not one of the inline codes the codec knows
    for b in chunk:
        if b < 0x20 and b not in codec.INLINE_OPS:
            return False
    return True


def verify_span(data: bytes, tokens, ok: int, sp) -> None:
    """Raise :class:`UnsafeSpan` unless the span is anchored, clean and resumable."""
    lo, hi = sp.off, sp.end
    if not (0 <= lo < hi <= ok):
        raise UnsafeSpan("span %d..%d is not inside the tiled prefix (0..%d)"
                         % (lo, hi, ok))

    starts = {t.off: t for t in tokens}
    # -- anchored ---------------------------------------------------------
    prev = [t for t in tokens if t.off + t.size == lo]
    if not prev:
        raise UnsafeSpan("span start %d is not immediately after any token" % lo)
    p = prev[0]
    if p.kind != "op" or p.idx not in TEXT_INTRO_OPS:
        raise UnsafeSpan("span start %d follows %s, not a text-introducing opcode"
                         % (lo, "0x%03X" % p.idx if p.kind == "op" else "text"))
    if hi != len(data) and hi not in starts:
        raise UnsafeSpan("span end %d is not a token boundary" % hi)

    # -- clean ------------------------------------------------------------
    if not _clean_text(data, lo, hi):
        raise UnsafeSpan("span %d..%d does not read as clean cp932 text" % (lo, hi))

    # -- resumable --------------------------------------------------------
    if hi < len(data):
        tail, _ok2 = tokenize_prefix(data[hi:])
        want = [(t.off - hi, t.size, t.idx) for t in tokens if t.off >= hi]
        got = [(t.off, t.size, t.idx) for t in tail][:len(want)]
        if got != want:
            raise UnsafeSpan("re-walking from %d diverges: %s vs %s"
                             % (hi, got[:3], want[:3]))


def safe_spans(rel: str, ci: int, rec_id: int, data: bytes, tab=None):
    """``(spans, ok, rejected)`` -- the spans of a record that are safe to overlay."""
    tokens, ok = tokenize_prefix(data, tab)
    spans = script.find_spans(ci, rec_id, data, tokens)
    keep, rejected = [], []
    for sp in spans:
        try:
            verify_span(data, tokens, ok, sp)
        except UnsafeSpan as exc:
            rejected.append((sp, str(exc)))
        else:
            keep.append(sp)
    return keep, ok, rejected


#: **Moved.**  ``observed_boundaries`` used to live here and was wrong twice
#: over: it took ``e.pc``, which is one past the *end* of the token, and it
#: matched on ``e.rel``/``e.rec`` -- the trace's file label and ``ds:RECID``,
#: both written on load and both routinely naming a script that is not running.
#: The real thing is :func:`giten.tile.observe`, which takes ``pc0`` minus the
#: width of the dispatched character and identifies the record by its content.
OBSERVED_BOUNDARIES_MOVED_TO = "giten.tile.observe"


#: How far past its own end a record's final token may reach.  Every one of the
#: 64 records this applies to needs seven bytes or fewer.
STRADDLE_MAX = 8


def tokenize_straddling(data: bytes, following: bytes, tab=None):
    """``(tokens, extra)`` for a record that tiles fully bar a straddling tail.

    The engine's script is one contiguous image -- ``base(id) = 0x400 + sum of the
    record lengths`` -- and the interpreter's byte fetch ``0x00438E50`` is a plain
    ``[base + pc++]`` with no bound.  So a token at the very end of a record
    legally reads on into the next one, and the record layer is an *index* into
    the image, not a limit on the walk.

    That is why 64 of the 78 records that refuse to tile refuse: not because the
    model is wrong about them, but because we tile each record in isolation.  All
    64 finish within **seven** bytes, and the straddling token is nearly always
    control flow emitted at the end of a chunk -- a branch-family opcode (`10`,
    `14`, `16`, `18`) or `1F 0D`/`0E`/`0F`.  ``m/MS0031`` r17 is typical: it ends
    ``1F 00 10 01 01 00`` and `10`'s expression wants one more byte.

    Accepted only when the walk is otherwise complete: every token but the last
    ends at or before the record's end, and the last one starts inside the record
    and finishes outside it.  A record that merely *stops* early is not this and
    is left to :func:`tokenize_prefix`.

    The caller must keep such a record un-rebuildable.  Overlaying is safe --
    the hook only needs ``start`` and ``end`` to be real instruction boundaries,
    and here the whole record is tiled -- but byte-rebuilding would move the
    straddling operand's own PC and change what its rel16 resolves to.
    """
    n = len(data)
    for k in range(1, STRADDLE_MAX + 1):
        if k > len(following):
            break
        try:
            toks = vmops.tokenize(data + following[:k], tab)
        except vmops.TileError:
            continue
        if not toks:
            continue
        last = toks[-1]
        if (last.off < n < last.off + last.size
                and all(t.off + t.size <= n for t in toks[:-1])):
            return toks, k
    return None, 0
