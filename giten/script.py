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

from . import codec, container, records, vmops

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
#: a record that only tiles up to a point; its verified spans may be overlaid but
#: it must never be byte-rebuilt (see giten/partial.py)
PREFIX_NOTE = "@prefix"


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
    #: for a prefix-tiled record: how many bytes the walk got through
    tiled_bytes: "int | None" = None
    #: how many of its spans the safety kernel refused
    rejected_spans: int = 0

    @property
    def untiled(self) -> bool:
        return self.tokens is None

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


def find_spans(ci: int, rec_id: int, data: bytes, toks) -> "list[Span]":
    """Every translatable span in one tiled record."""
    out: "list[Span]" = []
    n = len(toks)
    i = 0
    menu_width = None
    while i < n:
        t = toks[i]
        if t.kind == "op" and t.idx == MENU_OPEN_OP and t.ops:
            v = literal_expr(data, t.ops[0].off)
            menu_width = v if v and v > 0 else DEFAULT_CHOICE_WIDTH
        if not _inline(t):
            i += 1
            continue
        j = i
        while j < n and _inline(toks[j]):
            j += 1
        if any(_draws(toks[k]) for k in range(i, j)) and _visible(data, toks, i, j):
            prev = toks[i - 1] if i else None
            tag = (vmops.table().encoding(prev.idx)
                   if prev is not None and prev.kind == "op" else DATA_TAG)
            sp = Span(ci, rec_id, len(out), i, j, toks[i].off, toks[j - 1].end, tag)
            if sp.is_choice:
                sp.choice_width = menu_width or DEFAULT_CHOICE_WIDTH
            out.append(sp)
        i = j
    return out


# --- parse ------------------------------------------------------------------
def parse(rel: str, raw: bytes, tab=None) -> Script:
    """Decode, frame and tile one ``.BIN``."""
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
        for r in recs:
            data_off = body_off + r.header_len
            rec = Rec(c.index, r.id, r.order, r.data, data_off,
                      c.off + 2 + data_off, cond=r.cond, param=r.param)
            if r.id in seen:
                dups.append((c.index, r.id))
            seen.add(r.id)
            if r.data:
                try:
                    rec.tokens = vmops.tokenize(r.data, tab)
                except vmops.TileError as exc:
                    rec.tile_error = str(exc)
                    # Opt-in per file: keep the tokens the walk did produce, and
                    # expose only the spans that pass the safety kernel.  The
                    # record stays `blocked` below -- _rebuild_record works from
                    # rec.tokens, so byte-building one of these would drop
                    # everything past the failure point.  The overlay does not
                    # rebuild anything, which is why it can serve them.
                    from . import partial
                    if rel in partial.PREFIX_TILE_FILES:
                        toks, ok = partial.tokenize_prefix(r.data, tab)
                        keep, _ok, rejected = partial.safe_spans(
                            rel, c.index, r.id, r.data, tab)
                        if keep:
                            rec.tokens = toks
                            rec.spans = keep
                            rec.tiled_bytes = ok
                            rec.rejected_spans = len(rejected)
                            rec.blocked = PREFIX_NOTE

                else:
                    rec.unimplemented = vmops.uses_unimplemented(rec.tokens, tab)
                    rec.spans = find_spans(c.index, r.id, r.data, rec.tokens)
            else:
                rec.tokens = []
            rows.append(rec)
            body_off += r.stored_len
        if len(seen) != len(recs):
            # Two records with the same id in one container: the runtime index has
            # one slot per id, so `base(id)` -- and therefore every branch measured
            # against it -- is ambiguous.  9 containers corpus-wide, all in
            # m/MS6000, m/MS6012 and m/MS6800.
            #
            # The ambiguity only *matters* where something is measured against
            # `base(id)`, which means a rel16.  Five of the nine containers hold
            # no branch at all -- they are flat string pools -- so an edit there
            # cannot land wrong, and blocking them would throw away real
            # translations for a hazard that is not present.  The four that do
            # branch (MS6000 containers 0, 1 and 8; MS6800 container 0) are
            # blocked.
            if any(o.kind == "rel16" for rec in rows if rec.tokens
                   for t in rec.tokens for o in t.ops):
                for rec in rows:
                    rec.blocked = DUPID_NOTE
            else:
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
    return Script(rel, raw, True, None, out_conts, cont_offsets, dups, cont_bodies)


def span_text(rec: Rec, sp: Span) -> str:
    return codec.render(rec.data, rec.tokens[sp.tok_lo:sp.tok_hi])


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
    """Every runtime offset some ``rel16`` in this container jumps to."""
    out = set()
    for r in recs:
        if r.untiled or not r.tokens:
            continue
        base = old_base[r.id]
        for tok in r.tokens:
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
        # the first record installed is the one the index describes.
        first = {}
        for pos, r in enumerate(recs):
            first.setdefault(r.id, pos)

        omap = OffsetMap()
        off = records.INDEX_SIZE
        for i in range(256):
            omap.old_base[i] = off
            omap.old_len[i] = (len(recs[first[i]].data) if i in first
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
            omap.new_len[i] = (len(new_data[first[i]]) if i in first
                               else records.ABSENT_LEN)
            omap.runs[i] = (new_runs[first[i]] if i in first
                            else [(0, records.ABSENT_LEN, 0)])
            omap.anchors[i] = new_anchors.get(first.get(i), {})
            off += omap.new_len[i]
        omap.finish()

        _relocate(recs, new_data, omap, report)

        out_recs = [records.Record(r.id, new_data[pos], r.cond, r.param, r.order)
                    for pos, r in enumerate(recs)]
        src = sc.bodies[ci]
        bodies.append(records.serialise_body(
            records.Body(src.count, out_recs, src.tail, src.short_count)))

    return container.join(bodies), report
