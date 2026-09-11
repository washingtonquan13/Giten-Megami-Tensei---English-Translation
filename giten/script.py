"""The v2 script model: records -> tokens -> spans, and the edit/relocate builder.

This module is where the three verified layers meet:

* :mod:`.container` gives the ``[u16 hdr][chain-XOR body]`` chain and its seed;
* :mod:`.records` gives ``[u8 id][u16 len][data]`` and the runtime buffer layout
  ``base(id) = 0x400 + sum(len(j) for j < id)``;
* :mod:`.vmops` tiles a record's bytes into typed tokens.

A **span** is a maximal run of *inline* tokens -- text, ``0A``, the eight pool
calls and the ``1E 10`` page wait -- containing at least one thing that draws
(literal text or a pool call).  Every other opcode ends the span and is copied
through byte for byte, so no operand is ever exposed to a translator and no
branch displacement can be typed by hand.

Editing a span changes the record's length, which does three things, all handled
here:

1. the record's ``u16 len`` field is rewritten (:mod:`.records`);
2. the container's ``u16 hdr`` -- and therefore its cipher seed -- is recomputed
   (:mod:`.container`);
3. every ``rel16`` whose displacement now spans a different number of bytes is
   **relocated**.  ``docs/format-notes.md`` §2.3 / §2.6: a branch is measured
   from the byte after its own operand, in runtime-buffer coordinates, and
   records sit contiguously in id order -- so lengthening record ``k`` moves
   every record with a higher id and any branch reaching across the edit must be
   adjusted by the same delta.

Relocation is generic and derived from the token stream, never from a per-opcode
special case: build the old runtime image, note where every token lands, build
the new image, and rewrite each ``rel16`` so it points at *the same instruction*
it used to.  If nothing was edited, every delta is zero, every displacement comes
out unchanged, and the rebuild is byte-identical -- which is the identity test.

Untiled records
---------------
123 of 20 226 records (0.6%) cannot be tiled by the recovered table
(``docs/format-notes.md`` §2.10 -- a handful of shared handlers read an extra
operand only for particular constant arguments, and the static tracer took the
fall-through).  Those are marked ``@untiled``: their text is extracted so it can
be read, but the builder refuses to edit them and copies the record verbatim.
"""
from __future__ import annotations



from dataclasses import dataclass, field

from . import cache, codec, container, observed, records, vmops

#: Tags whose span is a menu option and is measured against the menu's declared
#: per-option width rather than the message-box line budget.
CHOICE_TAGS = frozenset({"1FB1", "1FB2", "1E12"})

#: ``1F B1 <expr>`` declares the per-option width in columns.
MENU_OPEN_OP = 0x1B1

#: Default when the ``1F B1`` operand is not a plain literal (1690 of 1752 menus
#: declare 20; see ``docs/format-notes.md`` §3.4).
DEFAULT_CHOICE_WIDTH = 20

DATA_TAG = "DATA"

#: Prefixed to the note of every row the builder will refuse to edit, whatever
#: the specific reason.  One marker for consumers to test, so a new reason never
#: has to be added to a list in three other modules.
NOEDIT_NOTE = "@noedit"

#: The record could not be tiled by the recovered opcode table, so its spans are
#: best-effort reading only and the builder copies it through verbatim.
UNTILED_NOTE = "@untiled"

#: Two records share an id inside one container, so the runtime index slot -- and
#: every branch measured against it -- is ambiguous.  Same treatment.
DUPID_NOTE = "@dupid"

#: The container's declared record count does not match how many records its body
#: actually holds, or the body has bytes after the last record.  Four shipped
#: files (m/MS600A, m/MS610B, et/ID00A2, et/ID00A3); see :class:`records.Body`.
#: The count word and the trailing bytes are re-emitted verbatim.  The record
#: list itself is complete and self-consistent, so these records stay editable;
#: the marker is advisory, because an engine that trusts the count word reads
#: past the end of such a container and what it finds there is garbage either
#: way.  ``m/MS600A`` and ``m/MS610B`` between them hold 318 finished lines.
PARTIAL_NOTE = "@partial"
#: **Retired 2026-09-11.**  A record that only tiled up to a point, whose
#: verified spans could still be overlaid (``giten/partial.py``).  Its one
#: worked example, ``m/MS0080``, tiles completely since the tokenizer started
#: walking the container image, so nothing sets this any more.  The constant
#: stays so a note written by an older extract is still recognised as generated
#: and dropped rather than carried forward for ever.
PREFIX_NOTE = "@prefix"

#: Opening of every reason a record is kept out of the overlay.  One prefix, so
#: :mod:`.extract_v2` can recognise the note as generated, :func:`.overlay.plan`
#: can report the same sentence as its finding, and ``check``'s ``editable`` rule
#: and the overlay cannot drift apart.
NO_OVERLAY_PREFIX = "not served: "

#: a record that tiles completely except for its final token, which continues
#: into the next record.  Legal for the engine -- records are contiguous at
#: runtime and the byte fetch has no bound -- so every span is fully known and
#: may be overlaid; byte-rebuilding is refused because moving the record would
#: move that operand's PC.  See :func:`vmops.tokenize_record`.
STRADDLE_NOTE = "@straddle"


# --- model ------------------------------------------------------------------
@dataclass
class Span:
    ci: int                 # container index
    rec_id: int
    idx: int                # span index within the record
    tok_lo: int             # token slice, half-open
    tok_hi: int
    off: int                # byte offset within the record data
    end: int
    tag: str
    choice_width: "int | None" = None
    #: ``idx`` of the span this one is a continuation of, when a branch target
    #: inside the record cut one run of inline tokens into several spans.  The
    #: head has ``None``; every piece after it names the head.  The tail inherits
    #: the head's ``tag``: the opcode before it is inline, so the default rule
    #: would call it ``DATA`` and a menu option's second half would stop being a
    #: menu option.
    split_head: "int | None" = None
    #: Was the run of inline tokens this span came from cut at all?  True on
    #: every piece of a cut run, including the head, and including a run whose
    #: other piece drew nothing and produced no span -- which is still a span
    #: that got shorter, and still a table row whose old English was written for
    #: more text than it now holds.
    cut_run: bool = False
    #: A record-relative offset some ``rel16`` in this record jumps to that falls
    #: *inside* this span without being a token boundary.  The span cannot be
    #: split there -- there is no boundary to split on -- so the overlay refuses
    #: it (24 corpus-wide, all in ``m/MS0031``).
    cut_inside: "int | None" = None

    @property
    def rec_key(self) -> str:
        return "%d:%02X" % (self.ci, self.rec_id)

    @property
    def is_choice(self) -> bool:
        return self.tag in CHOICE_TAGS


@dataclass
class Rec:
    ci: int
    id: int
    order: int
    data: bytes
    body_off: int                       # data offset within the container body
    raw_off: int                        # same byte's offset in the whole raw file
    tokens: "list | None" = None
    tile_error: "str | None" = None
    unimplemented: bool = False
    spans: "list[Span]" = field(default_factory=list)
    cond: "int | None" = None
    param: "int | None" = None
    #: ``None``, or the marker explaining why this record may not be edited.
    blocked: "str | None" = None
    #: advisory markers that do *not* stop an edit (currently ``@partial``)
    flags: "list[str]" = field(default_factory=list)
    #: Why the overlay must never serve this record, or ``None``.  Always opens
    #: with :data:`NO_OVERLAY_PREFIX`; see :func:`_mark_overlay_refusals`.
    no_overlay: "str | None" = None
    #: For a record the walk cannot finish but whose *code* is known anyway
    #: (:data:`observed.UNREACHED_RECORDS`): every token the model can prove,
    #: from the walk to the failure point and from every address the container's
    #: own ``rel16`` operands and straddles name.  Not a linear tiling -- these
    #: come from several walks at different phases -- so no span is derived from
    #: them; they exist so the record's branch targets are in the container's
    #: target set and the strict rule needs no exception.
    known_tokens: "list | None" = None
    #: an earlier copy of a record id this container repeats.  The loader
    #: installs each copy in turn, so only the last is in the runtime image;
    #: this one is never executed, never branched to and never served, and its
    #: table rows are keyed apart from the winner's.
    dup_loser: bool = False
    #: how many bytes this record's last token reads past its own end.  Legal
    #: for the engine -- records are contiguous at runtime and the byte fetch
    #: has no bound -- so the record is tiled like any other; the byte builder
    #: is the only consumer that has to refuse it.
    straddle: int = 0

    @property
    def untiled(self) -> bool:
        return self.tokens is None

    @property
    def span_tokens(self):
        """Every token this record is known to hold.

        :attr:`tokens` when the walk finished -- which is every record except
        the eight the census calls ``dead`` and ``unreached`` -- and, for an
        ``unreached`` one, :attr:`known_tokens`: the tokens the model can prove
        without claiming to have tiled the record.  Spans are never derived from
        those (they are not one linear walk), but their ``rel16`` operands are
        real branch targets and the container's target set would be incomplete
        without them.
        """
        return self.tokens if self.tokens is not None else self.known_tokens

    @property
    def key(self) -> str:
        return "%d:%02X" % (self.ci, self.id)


@dataclass
class Script:
    rel: str
    raw: bytes
    ok: bool
    error: "str | None" = None
    containers: "list[list[Rec]]" = field(default_factory=list)
    cont_offsets: "list[int]" = field(default_factory=list)
    duplicate_ids: "list[tuple[int, int]]" = field(default_factory=list)
    #: the parsed container bodies, so the declared count word and any trailing
    #: bytes can be re-emitted verbatim (see :class:`records.Body`)
    bodies: "list" = field(default_factory=list)

    def iter_records(self):
        for recs in self.containers:
            for r in recs:
                yield r

    def iter_spans(self):
        for r in self.iter_records():
            for s in r.spans:
                yield r, s

    @property
    def untiled_records(self):
        return [r for r in self.iter_records() if r.untiled and r.data]


# --- expression literals ----------------------------------------------------
_LITERAL_NODES = {0x00: (1, False), 0x01: (2, False), 0x02: (4, False),
                  0x03: (1, True), 0x04: (1, False), 0x05: (2, False)}


def literal_expr(data: bytes, off: int) -> "int | None":
    """Value of an ``expr`` slot when it is a plain literal node, else ``None``."""
    if off >= len(data):
        return None
    spec = _LITERAL_NODES.get(data[off])
    if spec is None:
        return None
    size, signed = spec
    if off + 1 + size > len(data):
        return None
    return int.from_bytes(data[off + 1:off + 1 + size], "little", signed=signed)


# --- span discovery ---------------------------------------------------------
def _inline(tok) -> bool:
    return tok.kind == "text" or tok.idx in codec.INLINE_OPS


def _draws(tok) -> bool:
    return tok.kind == "text" or tok.idx in codec.POOL_OPS


def _visible(data: bytes, toks, lo: int, hi: int) -> bool:
    """Does this run actually draw something a translator can read?

    A run of "text" bytes is not necessarily *text*: ``1F 03`` is followed by two
    16-bit values whose high bytes look like Shift-JIS lead bytes, and they tile
    as ``88 24 88 25`` -- four bytes that decode to nothing.  Requiring at least
    one character that survives cp932 (or one pool call, which always draws)
    keeps those out of the tables without needing a "suspect" heuristic
    afterwards.  The test lives here, in span discovery, so that ``idx`` numbering
    is identical for the extractor and the builder.
    """
    for k in range(lo, hi):
        t = toks[k]
        if t.kind == "op":
            if t.idx in codec.POOL_OPS:
                return True
            continue
        try:
            s = data[t.off:t.end].decode("cp932")
        except UnicodeDecodeError:
            continue
        if s.strip():
            return True
    return False


def find_spans(ci: int, rec_id: int, data: bytes, toks, cuts=()) -> "list[Span]":
    """Every translatable span in one tiled record.

    A token that runs past the record's own end is never part of a span, even if
    it is an inline opcode: the span's text would be half in this record and half
    in the next, which no table row can hold and no overlay can serve.  In
    practice a straddling token is always control flow, so this costs nothing --
    it is here so that it cannot start costing something silently.

    ``cuts`` is the set of record-relative offsets some ``rel16`` **in this
    record** jumps to.  A run of inline tokens ends before each of them and a new
    span starts there, because that is a byte the engine can arrive at from two
    directions: read straight through, it is part of the line; jumped to, it is
    where the line resumes.  One table row cannot be both, and before this the
    overlay's cap silently truncated the English at that byte -- 145 of the 192
    Japanese draws in the Roppongi session were six such lines.  Splitting makes
    the two halves two rows, which a translator can actually write.

    Only *same-record* targets are cuts.  A branch from another record resolves
    through ``base(id)``, which depends on the whole container's layout, and a
    record can turn up in a buffer built from different files; a cut has to be a
    property of the record's own bytes or it is wrong in the other buffer.  Those
    stay with the cap, which is computed per container at plan time.
    """
    out: "list[Span]" = []
    n = len(toks)
    limit = len(data)
    cuts = set(cuts)
    starts = {t.off for t in toks}

    def inline(t):
        return _inline(t) and t.end <= limit

    def emit(a, b, tag, width, head, cut):
        """One piece of a run, if it draws.  Returns its ``idx`` or None."""
        if not (any(_draws(toks[k]) for k in range(a, b))
                and _visible(data, toks, a, b)):
            return None
        sp = Span(ci, rec_id, len(out), a, b, toks[a].off, toks[b - 1].end, tag,
                  split_head=head, cut_run=cut)
        if sp.is_choice:
            sp.choice_width = width or DEFAULT_CHOICE_WIDTH
        sp.cut_inside = next((c for c in sorted(cuts)
                              if sp.off < c < sp.end and c not in starts), None)
        out.append(sp)
        return sp.idx

    i = 0
    menu_width = None
    while i < n:
        t = toks[i]
        if t.kind == "op" and t.idx == MENU_OPEN_OP and t.ops:
            v = literal_expr(data, t.ops[0].off)
            menu_width = v if v and v > 0 else DEFAULT_CHOICE_WIDTH
        if not inline(t):
            i += 1
            continue
        j = i
        while j < n and inline(toks[j]):
            j += 1
        # the run's tag comes from the opcode that introduced it, and every
        # piece keeps it: the token before a tail is inline, so the default
        # rule would make it DATA
        prev = toks[i - 1] if i else None
        tag = (vmops.table().encoding(prev.idx)
               if prev is not None and prev.kind == "op" else DATA_TAG)
        bounds = [i] + [m for m in range(i + 1, j) if toks[m].off in cuts] + [j]
        head = None
        for a, b in zip(bounds, bounds[1:]):
            idx = emit(a, b, tag, menu_width, head, len(bounds) > 2)
            if idx is not None and head is None:
                head = idx
        i = j
    return out


# --- what the model can prove about a container -----------------------------
def walk_from(image: bytes, start: int, length: int, tab) -> "tuple[list, int | None]":
    """``(tokens, stopped_at)`` -- :func:`vmops.tokenize_record` keeping a partial walk.

    ``stopped_at`` is ``None`` when the walk reached ``length`` and the offset it
    refused at otherwise.  Deliberately *not* a resynchronising walk: it is the
    same walk, reported up to the byte it gave up on, which is the only thing
    that can be compared with a program counter.
    """
    data = image[start:]
    out, i, n = [], 0, len(data)
    while i < length:
        if i >= n:
            return out, i
        b = data[i]
        try:
            if b >= 0x20:
                size = 2 if (vmops.is_sjis_lead(b) and i + 1 < length) else 1
                out.append(vmops.Token("text", i, size))
                i += size
                continue
            if b in vmops.ESCAPE:
                if i + 1 >= n:
                    return out, i
                idx = vmops.ESCAPE[b] + data[i + 1]
                head = 2
            else:
                idx, head = b, 1
            j, ops = vmops._read_operands(data, i + head, tab.operands(idx), tab)
            out.append(vmops.Token("op", i, j - i, idx, tuple(ops)))
            i = j
        except vmops.TileError:
            return out, i
    return out, None


@dataclass
class Walks:
    """Every address of one container the model can reach from the model alone.

    ``own`` is what walking each record from its own first byte produces;
    ``entered`` is what walking from every *other* address the container's own
    decoding names produces -- each ``rel16`` target, and the landing point of a
    token that straddles into the next record.  Both are
    ``{record id: {record-relative offset: Token}}``, with ``*_bounds`` carrying
    the same offsets plus the two things that are boundaries without being
    tokens: the address a walk was entered at, and the offset a walk gave up on.

    Nothing here reads a trace.  Every seed comes out of the model's own
    decoding of the container image, so a mistiled record cannot manufacture an
    entry point to excuse itself with.
    """
    own: dict = field(default_factory=dict)
    entered: dict = field(default_factory=dict)
    own_bounds: dict = field(default_factory=dict)
    entered_bounds: dict = field(default_factory=dict)

    def tokens(self, rec_id: int) -> list:
        """Every token proved for one record, in offset order, de-duplicated.

        Two walks that reach the same address decode the same bytes, so a
        repeated offset is the same token and keeping either is the same thing.
        """
        merged = dict(self.own.get(rec_id, {}))
        merged.update(self.entered.get(rec_id, {}))
        return [merged[k] for k in sorted(merged)]


def image_walks(recs, tab=None) -> Walks:
    """Walk one container's runtime image from every address the model names."""
    tab = tab or vmops.table()
    byid = {}
    for r in recs:
        byid[r.id] = r                      # last wins, as the loader does
    image = records.runtime_image(recs)
    bases = records.bases(recs)
    end = bases[255] + (len(byid[255].data) if byid.get(255) is not None
                        and byid[255].data else records.ABSENT_LEN)

    def owner(addr):
        """``(record id, base)`` of the record holding a runtime address."""
        for i in range(255, -1, -1):
            if bases[i] <= addr:
                r = byid.get(i)
                if r is None or not r.data:
                    return None, None
                if addr < bases[i] + len(r.data):
                    return i, bases[i]
                return None, None
        return None, None

    w = Walks({i: {} for i in byid}, {i: {} for i in byid},
              {i: set() for i in byid}, {i: set() for i in byid})
    seeds = [(bases[i], True) for i in sorted(byid) if byid[i].data]
    done = set()
    while seeds:
        addr, own = seeds.pop()
        if addr in done or not (records.INDEX_SIZE <= addr < end):
            continue
        done.add(addr)
        rid, base = owner(addr)
        if rid is None:
            continue
        length = len(byid[rid].data) - (addr - base)
        toks, stopped = walk_from(image, addr - records.INDEX_SIZE, length, tab)
        bag = w.own[rid] if own else w.entered[rid]
        bounds = w.own_bounds[rid] if own else w.entered_bounds[rid]
        bounds.add(addr - base)
        for t in toks:
            at = addr - base + t.off
            bounds.add(at)
            # the token's own offsets are relative to this walk's origin; hold
            # it in the record's coordinates so several walks can be merged
            bag[at] = vmops.Token(t.kind, at, t.size, t.idx,
                                  tuple(vmops.Operand(o.kind, o.off + addr - base,
                                                      o.size, o.raw)
                                        for o in t.ops))
        if stopped is not None:
            bounds.add(addr - base + stopped)
        else:
            # the walk ran to (or past) the record's end: where it lands is the
            # next address the engine fetches from
            spent = sum(t.size for t in toks)
            if spent > length:
                seeds.append((addr + spent, False))
        for t in toks:
            for op in t.ops:
                if op.kind == "rel16":
                    # token offsets are relative to this walk's origin, so the
                    # displacement is measured from `addr`, not `base`
                    seeds.append((vmops.rel16_target(addr, t, op), False))
    for i in w.own_bounds:
        w.entered_bounds[i] -= w.own_bounds[i]
    return w


def same_record_cuts(data: bytes, toks, base: int) -> "set[int]":
    """Record-relative offsets a ``rel16`` **in this record** jumps to.

    Only this record's own branches, because only they give an answer that is a
    property of the record's bytes.  A branch from another record is measured
    through ``base(id)`` -- the whole container's layout -- and a record can be
    installed in a buffer built from a different set of files, where that
    distance is not the same.  Those targets are still honoured, by the cap in
    :func:`overlay.plan`, which is computed per container at plan time.

    Deliberately *not* filtered by :data:`NOT_A_BRANCH`, for the reason given
    there: refusing to *protect* a byte because the opcode looks odd is the
    unsafe direction, and the cap this splits in front of is unfiltered too.  The
    two have to agree or a span would be split where nothing lands, or worse, not
    split where something does.
    """
    out = set()
    hi = len(data)
    for tok in (toks or []):
        for op in tok.ops:
            if op.kind != "rel16":
                continue
            t = vmops.rel16_target(base, tok, op) - base
            if 0 < t < hi:
                out.add(t)
    return out


# --- parse ------------------------------------------------------------------
def parse(rel: str, raw: bytes, tab=None) -> Script:
    """Decode, frame and tile one ``.BIN``.

    The answer is a pure function of ``rel``, ``raw`` and the code that reads
    them, and the same handful of files get parsed over and over -- ``check``
    alone walks the corpus four times in one process -- so the result is
    memoised in this process and cached on disk under ``build/cache/parse``
    (:mod:`giten.cache`, which also documents the key and the invalidation
    rule).  ``GITEN_NO_CACHE=1`` bypasses both.

    **No caller ever receives an object another caller holds.**  A result that
    came straight from the disk entry or from a real parse is already nobody
    else's, and is returned as it is.  Only a *memoised* result is shared, and
    that one is never handed out: :func:`_skeleton` rebuilds the ``Script``, its
    :class:`Rec` objects and their ``spans``/``tokens``/``flags`` lists first, so
    a caller that assigns ``rec.tokens`` or ``rec.spans`` -- three tests do --
    cannot be seen by the next caller.  Tokens, operands, spans and the record
    bytes are shared, because nothing in the tree mutates one of those in place.

    **Nothing is memoised until it is asked for twice.**  Holding 844 parsed
    scripts alive costs more in garbage collection than it saves when each file
    is only wanted once, which is what ``extract``, ``overlay`` and
    ``tile census`` do: measured, the memo made ``tile census`` 0.4 s *slower*
    that way.  A key is remembered on its first use and the object is only kept
    from the second, so a single pass over the corpus pays nothing and
    ``check`` -- four passes in one process -- still gets every repeat for free.

    An explicit ``tab`` is never cached: the result then depends on a table the
    key does not cover.
    """
    if tab is not None or cache.disabled():
        return _parse(rel, raw, tab)
    k = cache.key("parse", rel.encode("utf-8"), raw)
    sc = _MEMO.get(k)
    if sc is not None:
        return _skeleton(sc)
    sc = cache.load(cache.PARSE_DIR, k)
    if sc is None:
        sc = _parse(rel, raw, None)
        cache.store(cache.PARSE_DIR, k, sc)
    if k in _SEEN:
        _MEMO[k] = sc                       # asked for twice: worth keeping
        return _skeleton(sc)
    _SEEN.add(k)
    return sc


#: parse key -> the template ``Script`` for it.  Bounded by the corpus (844
#: files); nothing else is ever parsed.
_MEMO: "dict[str, Script]" = {}

#: keys this process has answered once.  Just the hex digests, so remembering
#: every file in the corpus costs a few tens of kilobytes and no GC pressure.
_SEEN: "set[str]" = set()


def _skeleton(sc: Script) -> Script:
    """A copy of ``sc`` nobody else holds a reference into.

    New ``Script``, new ``Rec`` objects, new lists.  Deliberately *not* a
    :func:`copy.deepcopy`: tokens, operands, spans, the record bytes and the
    parsed container bodies are immutable in practice -- no module in the tree
    assigns an attribute of one -- so copying them would cost the whole saving
    and buy nothing.  What *is* assigned, by ``giten/warp.py``'s callers and by
    three tests, is a ``Rec`` field (``data``, ``tokens``, ``spans``), and each
    of those is per-copy here.
    """
    return Script(sc.rel, sc.raw, sc.ok, sc.error,
                  [[_skeleton_rec(r) for r in cont] for cont in sc.containers],
                  list(sc.cont_offsets), list(sc.duplicate_ids),
                  list(sc.bodies))


def _skeleton_rec(rec: Rec) -> Rec:
    # Field by field rather than ``copy.copy`` + fix-ups: this runs 20 690 times
    # per corpus pass and ``copy.copy`` on a dataclass costs three times what the
    # constructor does.
    toks, known = rec.tokens, rec.known_tokens
    out = Rec(rec.ci, rec.id, rec.order, rec.data, rec.body_off, rec.raw_off,
              None if toks is None else list(toks),
              rec.tile_error, rec.unimplemented, list(rec.spans),
              rec.cond, rec.param, rec.blocked, list(rec.flags),
              rec.no_overlay, None if known is None else list(known),
              rec.dup_loser, rec.straddle)
    return out


def _parse(rel: str, raw: bytes, tab=None) -> Script:
    """:func:`parse` with no cache in front of it."""
    tab = tab or vmops.table()
    if rel.startswith("p/"):
        # p/P*.BIN is a fixed struct, not a script; one of the 432 (P2194)
        # happens to satisfy the record-layer test by coincidence, so exclude the
        # family by name rather than let a coincidence pick the wrong pipeline.
        return Script(rel, raw, False, "p/ is a fixed record struct, not a script")
    conts, end = container.split(raw)
    if not conts or end != len(raw) or any(c.short for c in conts):
        return Script(rel, raw, False, "not a clean container chain")

    cont_bodies = [records.parse_body(c.body) for c in conts]
    bad = next((b for b in cont_bodies if b.error), None)
    if bad is not None:
        return Script(rel, raw, False, bad.error)
    if not records.is_record_layer(cont_bodies):
        return Script(rel, raw, False, "no record layer in this file")

    out_conts = []
    cont_offsets = []
    dups = []
    for c, b in zip(conts, cont_bodies):
        recs = b.records
        seen = set()
        body_off = 2
        rows = []
        # The engine lays the records out contiguously (base(id) = 0x400 + sum of
        # lengths, an absent record being one 0x00) and its byte fetch is
        # unbounded, so a token at a record's end reads on into the next one.
        # Tile against that image, not against the record in isolation: it is
        # the coordinate space the engine actually runs in.
        image = records.runtime_image(recs)
        image_base = records.bases(recs)
        # Which copy of a repeated id the loader ends up with: the last one it
        # installs (``records.bases``, measured on m/MS6800 c0).  Every earlier
        # copy is a *loser* -- never in the image, never branched to, never
        # served -- and has to be told apart from the winner, or two rows in one
        # table are keyed alike.
        last_pos = {}
        for pos, r in enumerate(recs):
            last_pos[r.id] = pos
        for pos, r in enumerate(recs):
            data_off = body_off + r.header_len
            rec = Rec(c.index, r.id, r.order, r.data, data_off,
                      c.off + 2 + data_off, cond=r.cond, param=r.param)
            if r.id in seen:
                dups.append((c.index, r.id))
            seen.add(r.id)
            rec.dup_loser = last_pos[r.id] != pos
            if r.data:
                # Where this record sits in the runtime image -- unless it is
                # the losing copy of a duplicate id, which the loader overwrites
                # and which therefore has nothing after it at all.  Checked by
                # comparing the bytes rather than by counting duplicates: the
                # walk has to agree with `records.bases` or it reads a
                # neighbour's operands.
                start = image_base[r.id] - records.INDEX_SIZE
                if image[start:start + len(r.data)] != r.data:
                    image_for, start = r.data, 0
                else:
                    image_for = image
                try:
                    toks, extra = vmops.tokenize_record(
                        image_for, start, len(r.data), tab)
                except vmops.TileError as exc:
                    # The record is not tiled, and nothing here pretends
                    # otherwise: no span is derived from a partial walk, and the
                    # record is refused by the byte builder and by the overlay
                    # alike.  What the walk *did* reach is recovered below, per
                    # container, and only for the records the engine has already
                    # answered for (`observed.UNREACHED_RECORDS`) -- as
                    # `known_tokens`, which carries branch targets and nothing
                    # else.
                    rec.tile_error = str(exc)
                else:
                    rec.tokens = toks
                    rec.straddle = extra
                    if extra:
                        # An ordinary record whose last token reads `extra` bytes
                        # out of the next one.  Tiled, spanned and overlaid like
                        # any other; only the byte builder refuses it, because
                        # rebuilding would move operand bytes this record does
                        # not own.  `_relocate` skips it for the same reason --
                        # letting it through moved m/MS0031 r0D's branch target
                        # and `audit` caught it.
                        rec.blocked = STRADDLE_NOTE
                    rec.unimplemented = vmops.uses_unimplemented(rec.tokens, tab)
                    # A span ends where a branch in this record lands.  Only this
                    # record's own branches: see `same_record_cuts`.  They need
                    # nothing but the record's own tokens and its base, both of
                    # which are in hand here, so this is not a second pass.
                    rec.spans = find_spans(
                        c.index, r.id, r.data, rec.tokens,
                        same_record_cuts(r.data, rec.tokens, image_base[r.id]))
            else:
                rec.tokens = []
            rows.append(rec)
            body_off += r.stored_len
        # A record the walk cannot finish still has known code when the engine
        # has said so: `unreached` means every program counter observed inside it
        # is reproduced by the model and the failure offset is not one of them
        # (`giten/observed.py`, re-checked by tests/test_tile.py).  Recover those
        # tokens so the container's branch targets are complete.  Computed only
        # when there is such a record -- five containers corpus-wide -- because
        # the closure re-walks the image from every address it names.
        if any((rel, c.index, rec.id) in observed.UNREACHED_RECORDS
               for rec in rows if rec.tokens is None and rec.data):
            walks = image_walks(recs, tab)
            for rec in rows:
                if (rec.tokens is None and rec.data
                        and (rel, c.index, rec.id) in observed.UNREACHED_RECORDS):
                    rec.known_tokens = walks.tokens(rec.id)
        if len(seen) != len(recs):
            # Two records with the same id in one container: the runtime index
            # has one slot per id, so one of them is what the loader keeps and
            # the other is never in the image.  10 containers corpus-wide, in
            # m/MS6000, m/MS6012, m/MS610B and m/MS6800.
            #
            # **Advisory only since 2026-09-11.**  This blocked the container
            # while "which copy wins" was a guess.  It is not a guess any more --
            # the engine's own index entries say the last copy wins
            # (``records.bases``) -- so the layout is as determined here as
            # anywhere else, and the marker is left as a note.  What the answer
            # does change is *identity*: the losing copy is a record nothing ever
            # executes, so its rows are keyed apart and marked `@noedit`
            # (``extract_v2.script_rows``).
            for rec in rows:
                rec.flags.append(DUPID_NOTE)
        if b.short_count or b.tail:
            for rec in rows:
                rec.flags.append(PARTIAL_NOTE)
        out_conts.append(rows)
        cont_offsets.append(c.off)
    for rows in out_conts:
        for rec in rows:
            if rec.untiled and rec.data and rec.blocked is None:
                rec.blocked = UNTILED_NOTE
    sc = Script(rel, raw, True, None, out_conts, cont_offsets, dups, cont_bodies)
    _mark_overlay_refusals(rel, sc)
    return sc


def _mark_overlay_refusals(rel: str, sc: Script) -> None:
    """Fill :attr:`Rec.no_overlay` -- the strict rule, in one place.

    The overlay serves a span only when the whole container it lives in can be
    proved safe, because what makes a served byte wrong is not the span, it is a
    branch elsewhere in the container landing inside it.  Four refusals:

    * **a file the script loader never opens** (``giten.loaders.DATA_FILES``).
      Its records are not code; nothing in them is ever fetched.
    * **a file nothing enters** (``observed.UNUSED_FILES``).  Reachable by the
      loader, entered by nothing -- ``m/MS0080``'s five shop records, each warped
      to and each terminating after two tokens without drawing.
    * **the losing copy of a repeated record id.**  Overwritten on load, so it is
      never in a buffer and no address in it can be reached.
    * **a record the model cannot walk**, and, with it, **every record of its
      container**: if one record's tokens are unknown then so are its branches,
      and a jump out of it could land inside English somewhere else in the same
      image.  ``dead`` records are the one exception and it is not a loophole --
      a warp put the interpreter on the record's first byte and the process died
      there, so those bytes hold no branch that ever runs.  An ``unreached``
      record is not in this class at all: it carries :attr:`Rec.known_tokens`,
      so its targets *are* known and only the record itself is refused.
    """
    from . import loaders
    if rel in loaders.DATA_FILES:
        why = (NO_OVERLAY_PREFIX + "no code path in the game opens %s, so its "
               "records are never handed to the interpreter (giten/loaders.py)"
               % rel)
        for rec in sc.iter_records():
            rec.no_overlay = why
        return
    unused = observed.UNUSED_FILES.get(rel)
    if unused:
        why = NO_OVERLAY_PREFIX + unused
        for rec in sc.iter_records():
            rec.no_overlay = why
        return
    for ci, cont in enumerate(sc.containers):
        unknown = next((r for r in cont
                        if r.data and r.span_tokens is None
                        and (rel, ci, r.id) not in observed.DEAD_RECORDS), None)
        why_container = None
        if unknown is not None:
            why_container = (
                NO_OVERLAY_PREFIX + "this container holds record %02X, which the "
                "model cannot walk (%s), so not every branch target in it is "
                "known and a jump could land inside a served span"
                % (unknown.id, (unknown.tile_error or "no tokens").replace("; ", ", ")))
        for rec in cont:
            if rec.dup_loser:
                rec.no_overlay = (
                    NO_OVERLAY_PREFIX + "this container installs record %02X "
                    "twice and the loader keeps the last copy, so these bytes "
                    "are never in any buffer" % rec.id)
            elif rec.data and rec.tokens is None:
                rec.no_overlay = (
                    NO_OVERLAY_PREFIX + "the record does not tile (%s)"
                    % (rec.tile_error or "no tokens").replace("; ", ", "))
            elif why_container is not None:
                rec.no_overlay = why_container


def span_text(rec: Rec, sp: Span) -> str:
    return codec.render(rec.data, rec.span_tokens[sp.tok_lo:sp.tok_hi])


def untiled_text(rec: Rec) -> str:
    """Best-effort text of a record the table cannot tile, for reading only."""
    out = []
    data = rec.data
    i = 0
    n = len(data)
    run = []
    while i < n:
        b = data[i]
        if b >= 0x20:
            size = 2 if (vmops.is_sjis_lead(b) and i + 1 < n) else 1
            run.append(data[i:i + size])
            i += size
            continue
        if run:
            out.append(b"".join(run))
            run = []
        i += 1
    if run:
        out.append(b"".join(run))
    parts = []
    for chunk in out:
        try:
            parts.append(chunk.decode("cp932"))
        except UnicodeDecodeError:
            continue
    return " / ".join(p for p in parts if p.strip())


# --- the offset map ---------------------------------------------------------
class OffsetMap:
    """Old runtime offset -> new runtime offset, for one container.

    Built from the per-record list of *unchanged runs*.  A byte inside an edited
    span has no image in the new layout (its text was replaced wholesale), so
    :meth:`get` returns ``None`` for it and the caller reports an unrelocatable
    branch instead of guessing.  The two edges of an edited span do map: its
    first byte to the first byte of the replacement, and the byte after it to the
    byte after the replacement.
    """

    def __init__(self):
        self.old_base = {}
        self.new_base = {}
        self.runs = {}           # rec id -> [(old_lo, old_hi, delta)]
        self.anchors = {}        # rec id -> {old offset: new offset}
        self.old_len = {}
        self.new_len = {}
        self._by_old = []        # sorted [(old_base, old_end, rec id)]

    def finish(self):
        self._by_old = sorted((self.old_base[i], self.old_base[i] + self.old_len[i], i)
                              for i in self.old_base)

    def _record_of(self, old_abs: int) -> "int | None":
        lo, hi = 0, len(self._by_old)
        while lo < hi:
            mid = (lo + hi) // 2
            s, e, rid = self._by_old[mid]
            if old_abs < s:
                hi = mid
            elif old_abs > e:          # inclusive: one-past-end belongs here too
                lo = mid + 1
            else:
                return rid
        return None

    def in_image(self, old_abs: int) -> bool:
        """Is this offset inside some record of the container's runtime image?"""
        return self._record_of(old_abs) is not None

    def get(self, old_abs: int) -> "int | None":
        rid = self._record_of(old_abs)
        if rid is None:
            return None
        rel = old_abs - self.old_base[rid]
        anchor = self.anchors.get(rid, ())
        if rel in anchor:
            return self.new_base[rid] + anchor[rel]
        if rel == self.old_len[rid]:
            return self.new_base[rid] + self.new_len[rid]
        for lo, hi, delta in self.runs.get(rid, ()):
            if lo <= rel < hi:
                return self.new_base[rid] + rel + delta
        return None


# --- build ------------------------------------------------------------------
@dataclass
class BuildReport:
    rel: str
    changed_spans: int = 0
    changed_records: int = 0
    relocated: int = 0
    unmapped: int = 0
    #: of those, the ones whose target was inside a replaced span -- the only
    #: subset that represents an actual risk (see :func:`_relocate`)
    unmapped_in_edit: int = 0
    #: edits skipped because a branch lands inside the span (see
    #: :func:`_drop_branched_into`)
    branched_into: int = 0
    #: edits skipped because the span holds the operand bytes of the *previous*
    #: record's straddling last token (see :func:`_drop_straddled_into`)
    straddled_into: int = 0
    #: ``rel16`` slots left alone because the operand does not behave like a
    #: branch at all (see :func:`_is_branch`)
    not_a_branch: int = 0
    #: spans a branch jumps into that were edited anyway, because the target sits
    #: on a trailing escape the translation preserves byte-for-byte
    #: (see :func:`_drop_branched_into`)
    tail_anchored: int = 0
    size_delta: int = 0
    errors: "list[str]" = field(default_factory=list)
    warnings: "list[str]" = field(default_factory=list)


def _rebuild_record(rec: Rec, edits: "dict[int, str]", report: BuildReport,
                    interior=()):
    """New bytes for one record plus its unchanged-run map ``[(lo, hi, delta)]``.

    ``interior`` is the record-relative offsets of branch targets that land
    inside a span, as passed through by :func:`_drop_branched_into`; a target
    whose trailing bytes survive the edit gets an anchor at the same distance
    from the end of the new text.
    """
    if not edits:
        return rec.data, [(0, len(rec.data), 0)], {}, False
    out = bytearray()
    runs = []
    anchors = {}
    cursor = 0
    changed = False
    for sp in rec.spans:
        new_text = edits.get(sp.idx)
        if new_text is None:
            continue
        try:
            new = codec.encode(new_text)
        except codec.CodecError as exc:
            report.errors.append("%s %s[%d]: %s" % (report.rel, sp.rec_key, sp.idx, exc))
            continue
        old = rec.data[sp.off:sp.end]
        if new == old:
            continue
        runs.append((cursor, sp.off, len(out) - cursor))
        out += rec.data[cursor:sp.off]
        # The replacement's own bytes have no old counterparts, but its two edges
        # do: a branch that pointed at the span's first byte must point at the
        # first byte of the new text, and one that pointed just past it must
        # point just past the new text.  Without these anchors a jump onto the
        # start of an edited line would look unrelocatable.
        anchors[sp.off] = len(out)
        out += new
        anchors[sp.end] = len(out)
        # A branch onto the span's trailing page wait / newline: the byte still
        # exists, the same distance from the end.  _drop_branched_into only let
        # this edit through because that tail is byte-identical.
        for t in interior:
            k = sp.end - t
            if sp.off < t < sp.end and preserved_tail(old, new, k):
                anchors[t] = len(out) - k
        cursor = sp.end
        changed = True
        report.changed_spans += 1
        report.size_delta += len(new) - len(old)
    runs.append((cursor, len(rec.data), len(out) - cursor))
    out += rec.data[cursor:]
    return bytes(out), [r for r in runs if r[0] < r[1]], anchors, changed


#: Dispatch indices whose ``rel16`` slot, measured over the whole corpus, does
#: **not** hold a branch displacement.
#:
#: ``docs/opcodes.json`` is a *recovered* table -- it was produced by tracing the
#: interpreter statically -- and a few slots it types ``rel16`` are really a pair
#: of small integers.  The measurement that separates them needs no new
#: disassembly: a real displacement points at an instruction boundary, and ~50%
#: of byte offsets are an instruction boundary by chance, so a genuine branch
#: opcode scores near 100% and a mistyped one scores at or below chance.
#: Measured on the 20 195 ``rel16`` slots in ``m/MS*`` and ``et/ID*``::
#:
#:     op 018  n=7634  98.5%   op 011  n= 85  15.3%   <- not a branch
#:     op 009  n=2004  95.8%   op 010  n= 99  22.2%   <- not a branch
#:     op 014  n= 945  97.8%   op 182  n=203  40.4%   <- not a branch
#:     op 103  n= 777  99.4%
#:
#: ``tests/test_v2.py`` re-derives this from the game files, so an opcode that
#: changes side is a test failure rather than a silent behaviour change.
#:
#: Opcodes between the two extremes (``012``, ``013``, ``016``, ``017``, ``180``,
#: ``183``) are left classified as branches: they are most likely real branches
#: that happen to sit in the records the tokenizer tiles a byte out of step, and
#: relocating a real branch matters more than skipping a rare phantom.
#:
#: 2026-09-06: that prediction came true for ``182``.  It scored 40.4% and sat
#: here as "not a branch"; once ``0x17F``-``0x184`` stopped reading a second
#: expression they never read (their handlers pass A=0 to ``0x00434740``, which
#: reads the second one only when A==1), the walk stopped being a byte out of
#: step and the corpus re-derivation moved it to the branch side on its own.
#: That is the strongest evidence for the operand fix: an independent measure,
#: not aimed at it, agreeing.
NOT_A_BRANCH = frozenset({0x010, 0x011})


def _is_branch(tok) -> bool:
    """Does this opcode's ``rel16`` slot really hold a branch displacement?

    Deliberately a property of the *opcode*, not of the individual value.  A
    per-value test ("does this displacement point at an instruction?") looks
    more precise and is wrong in the case that matters most: a real branch
    inside one of the 123 records the tokenizer tiles a byte out of step has a
    target that cannot be *placed*, yet it is still a branch, and
    :class:`OffsetMap` maps any offset through the unchanged runs -- boundary or
    not -- so it relocates correctly.  Skipping those leaves live jumps pointing
    at the wrong byte once the record moves.

    Measured both ways over the corpus, counting only slots whose opcode is a
    real branch: this rule leaves 3 branch targets moved (all three already
    pointed outside their container image in the source, i.e. dead), against 39
    for the per-value test.
    """
    return tok.idx not in NOT_A_BRANCH


def _branch_targets(recs, old_base) -> "set[int]":
    """Every runtime offset some ``rel16`` in this container jumps to.

    ``span_tokens``, not ``tokens``: a straddling record's tokens are ordinary
    tokens and its branches are ordinary branches, and an ``unreached`` record
    contributes the tokens the model can prove for it (:attr:`Rec.known_tokens`).
    Both matter to the two callers for the same reason -- the byte builder must
    not move a byte a branch lands on, and the overlay must not answer one.
    """
    out = set()
    for r in recs:
        toks = r.span_tokens
        if not toks:
            continue
        base = old_base[r.id]
        for tok in toks:
            for op in tok.ops:
                if op.kind == "rel16":
                    out.add(vmops.rel16_target(base, tok, op))
    return out


def preserved_tail(old: bytes, new: bytes, k: int) -> bool:
    """Do ``old`` and ``new`` end in the same ``k`` bytes?

    If they do, a branch that pointed ``k`` bytes back from the end of the old
    span has an honest destination in the new one: the same byte, the same
    distance from the end.  See :func:`_drop_branched_into`.
    """
    return 0 < k <= min(len(old), len(new)) and old[-k:] == new[-k:]


def _straddled_bytes(recs, old_base) -> "set[int]":
    """Runtime offsets that belong to a *previous* record's last token.

    A straddling record's final token reads its operands out of the record with
    the next id.  Those bytes are an instruction's operands and somebody else's
    text at the same time, and editing them changes an instruction in a record
    the edit never named.  Measured on the shipped data: nine such overlaps, of
    which `m/MS0031` c0 r0B's 406-byte `pairs_ff` covers **all fourteen** spans
    of r0C.  `giten audit` reports it as a structural-opcode difference -- which
    is how it was found, and which it could not do before straddling records
    carried tokens.
    """
    out = set()
    for r in recs:
        if not r.straddle:
            continue
        start = old_base[r.id] + len(r.data)
        out.update(range(start, start + r.straddle))
    return out


def _drop_straddled_into(rel, rec, per, base, owned, report: BuildReport):
    """Refuse an edit to a span holding a previous record's operand bytes."""
    if not per or not owned:
        return per
    keep = {}
    for idx, text in per.items():
        sp = next((s for s in rec.spans if s.idx == idx), None)
        if sp is None:
            continue
        hit = [t for t in owned if base + sp.off <= t < base + sp.end]
        if hit:
            report.straddled_into += 1
            if len(report.warnings) < 40:
                report.warnings.append(
                    "%s %s[%d]: 0x%04X..0x%04X holds the operand bytes of the "
                    "previous record's straddling last token; edit refused"
                    % (rel, rec.key, idx, base + sp.off, base + sp.end))
            continue
        keep[idx] = text
    return keep


def _drop_branched_into(rel, rec, per, base, landed, report: BuildReport):
    """Refuse an edit to a span that some branch jumps *into the middle of*.

    A target on the span's first byte is fine -- it moves with the span.  A target
    strictly inside it usually names a byte the replacement text does not have,
    so there is no honest answer, and quietly leaving the old displacement would
    point a jump into the middle of a new English sentence.

    **Except when the tail is preserved.**  Nearly half of these targets are a
    branch onto the span's own trailing ``1E 10`` page wait or ``0A`` newline --
    "skip the words, go straight to the page break" -- and a translation keeps
    those trailing escapes verbatim, because they are what ends the line.  When
    the last *k* bytes survive the edit unchanged, the target still exists at the
    same distance from the end, and :func:`_rebuild_record` anchors it there.
    Refusing those cost 314 finished lines that never reached the screen.

    Anything else is still refused: a target in the middle of prose names a byte
    the English genuinely does not have.
    """
    if not per:
        return per
    keep = {}
    for idx, text in per.items():
        sp = next((s for s in rec.spans if s.idx == idx), None)
        if sp is None:
            report.errors.append("%s %s: no span %d" % (rel, rec.key, idx))
            continue
        hit = [t for t in landed if base + sp.off < t < base + sp.end]
        if hit:
            old = rec.data[sp.off:sp.end]
            try:
                new = codec.encode(text)
            except codec.CodecError:
                new = None                      # _rebuild_record reports the error
            if new is not None and all(
                    preserved_tail(old, new, base + sp.end - t) for t in hit):
                report.tail_anchored += 1
                keep[idx] = text
                continue
            report.branched_into += 1
            report.errors.append(
                "%s %s[%d]: a branch jumps into the middle of this span "
                "(runtime 0x%04X); edit skipped, source text kept"
                % (rel, rec.key, idx, hit[0]))
            continue
        keep[idx] = text
    return keep


def _relocate(recs, new_data, omap: OffsetMap, report: BuildReport):
    """Rewrite every ``rel16`` so it still points at the same instruction.

    ``new_data`` is keyed by the record's position in the container, so a
    container holding two records with the same id is still addressed correctly
    (such containers are blocked from editing anyway; see :func:`parse`).
    """
    for pos, rec in enumerate(recs):
        if rec.untiled or not rec.tokens:
            continue
        if rec.blocked == STRADDLE_NOTE:
            # A straddling record's final token reads operand bytes out of the
            # *next* record, so its rel16 is not a displacement this function can
            # reason about -- relocating it moved `m/MS0031` r0D's target and
            # `audit` caught it.  These records exist to be overlaid, never
            # byte-rebuilt, so leave their bytes exactly as the untiled state
            # left them: verbatim.
            continue
        base_old = omap.old_base[rec.id]
        base_new = omap.new_base[rec.id]
        buf = None
        for tok in rec.tokens:
            if tok.kind != "op":
                continue
            for op in tok.ops:
                if op.kind != "rel16":
                    continue
                if not _is_branch(tok):
                    # Not a displacement at all -- see :data:`NOT_A_BRANCH`.
                    report.not_a_branch += 1
                    continue
                old_target = vmops.rel16_target(base_old, tok, op)
                new_target = omap.get(old_target)
                new_op_abs = omap.get(base_old + op.off)
                if new_target is None or new_op_abs is None:
                    # Two very different causes, and only one of them is a
                    # hazard: a target that was already outside this container's
                    # runtime image (1.5% of branches in the shipped data --
                    # dead code, or a mis-tiled opcode reading text as a
                    # displacement) versus a target that landed *inside* a span
                    # this build replaced, whose bytes no longer exist.
                    inside = omap.in_image(old_target)
                    report.unmapped += 1
                    if inside:
                        report.unmapped_in_edit += 1
                    if len(report.warnings) < 40:
                        report.warnings.append(
                            "%s %s: branch at 0x%X targets 0x%04X, %s; "
                            "displacement left unchanged"
                            % (report.rel, rec.key, tok.off, old_target,
                               "which is inside a span this build replaced"
                               if inside else
                               "which was already outside the container image"))
                    continue
                new_imm = vmops.rel16_imm(base_new, new_op_abs - base_new,
                                          op.size, new_target)
                if new_imm == op.value:
                    continue
                if buf is None:
                    buf = bytearray(new_data[pos])
                at = new_op_abs - base_new
                buf[at:at + 2] = new_imm.to_bytes(2, "little")
                report.relocated += 1
        if buf is not None:
            new_data[pos] = bytes(buf)


def build(sc: Script, edits: "dict[tuple[int, int, int], str]") -> "tuple[bytes, BuildReport]":
    """Apply ``{(container, record id, span index): english}`` and re-emit the file.

    With ``edits`` empty the output is byte-identical to ``sc.raw``: every delta
    is zero, so every ``rel16`` recomputes to the value it already had, every
    record length is unchanged, and each container is re-encrypted with the seed
    its own (unchanged) header implies.
    """
    report = BuildReport(sc.rel)
    if not sc.ok:
        report.errors.append("%s: %s" % (sc.rel, sc.error))
        return sc.raw, report

    bodies = []
    for ci, recs in enumerate(sc.containers):
        # The runtime index has one slot per id; when a container repeats an id
        # the loader installs each copy in turn, so the **last** one is what the
        # index ends up describing (measured: `records.bases`).
        keep = {}
        for pos, r in enumerate(recs):
            keep[r.id] = pos

        omap = OffsetMap()
        off = records.INDEX_SIZE
        for i in range(256):
            omap.old_base[i] = off
            omap.old_len[i] = (len(recs[keep[i]].data) if i in keep
                               else records.ABSENT_LEN)
            off += omap.old_len[i]

        # Deliberately NOT filtered to plausible targets: refusing to *rewrite* a slot
        # that does not look like a branch is always safe, but refusing to
        # *protect* a span because the slot looks odd is not -- a displacement
        # our table mis-typed may still be a live jump, and letting an edit move
        # the byte it lands on is exactly the corruption this guard exists to
        # prevent.  Blocking on every rel16 target costs a few skipped lines;
        # trusting the table here would cost correctness.
        landed = _branch_targets(recs, omap.old_base)
        owned = _straddled_bytes(recs, omap.old_base)

        new_data = {}
        new_runs = {}
        new_anchors = {}
        for pos, r in enumerate(recs):
            per = {k[2]: v for k, v in edits.items() if k[0] == ci and k[1] == r.id}
            if per and r.blocked:
                report.errors.append(
                    "%s %s: record is %s (%s); edits ignored, record copied "
                    "verbatim" % (sc.rel, r.key, r.blocked,
                                  r.tile_error or "ambiguous record id"))
                per = {}
            rbase = omap.old_base.get(r.id, 0)
            per = _drop_branched_into(sc.rel, r, per, rbase, landed, report)
            per = _drop_straddled_into(sc.rel, r, per, rbase, owned, report)
            inner = [t - rbase for t in landed
                     if rbase <= t < rbase + len(r.data)]
            data, runs, anchors, changed = _rebuild_record(r, per, report, inner)
            if changed:
                report.changed_records += 1
            new_data[pos] = data
            new_runs[pos] = runs
            new_anchors[pos] = anchors

        off = records.INDEX_SIZE
        for i in range(256):
            omap.new_base[i] = off
            omap.new_len[i] = (len(new_data[keep[i]]) if i in keep
                               else records.ABSENT_LEN)
            omap.runs[i] = (new_runs[keep[i]] if i in keep
                            else [(0, records.ABSENT_LEN, 0)])
            omap.anchors[i] = new_anchors.get(keep.get(i), {})
            off += omap.new_len[i]
        omap.finish()

        _relocate(recs, new_data, omap, report)

        out_recs = [records.Record(r.id, new_data[pos], r.cond, r.param, r.order)
                    for pos, r in enumerate(recs)]
        src = sc.bodies[ci]
        bodies.append(records.serialise_body(
            records.Body(src.count, out_recs, src.tail, src.short_count)))

    return container.join(bodies), report
