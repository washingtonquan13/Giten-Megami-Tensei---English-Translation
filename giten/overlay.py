"""Runtime text overlay: the translation lives beside the game, not in it.

The script files stay **byte-identical to the original**.  The patched exe
hooks the interpreter's one byte-fetch routine (``0x438E50``); when the
program counter reaches the first byte of a translated span it serves the
English bytes instead and then rejoins the Japanese stream at the span's end.
No script byte is ever rewritten, so no branch, switch table, flag or record
length can change: the logic of an English run is the logic of the Japanese
run by construction, and ``trace diff`` can demand opcode-for-opcode equality.

Content addressing (v6, 2026-09-10)
-----------------------------------
Every earlier version answered the question *which file is this buffer?* -- from
the engine's current-file global, from a fingerprint of the buffer's record
index, from a cached ``(handle, fid)`` binding.  All of them go stale, because
the engine reuses one handle and one pseudo file id (``0x7F``, "this map's
script slot n") for every shop, terminal, bar and clinic on a map, and rebuilds
the demon merge under ``0xE0`` for every demon.  The hook then served the
previous script's English at the new script's record addresses: the weapon
shop's *"Hurry up and choose."* came out of a terminal, and a later script
entered a span mid-sentence.

**v6 never identifies a file.**  An English byte is served only if the Japanese
*record* it translates is in the buffer, byte for byte, right now.  The key of
every translated span is the content of its record::

    (record id, record length, FNV-1a of the record's bytes)

Nothing is remembered between fetches except a memo, and the memo is
re-validated against the live index on every fetch.  There is no file id, no
index fingerprint, no per-file directory, no membership rule, no merge window,
no bitmap.  Stale bindings, pseudo ids and rebuilt merges stop being cases.

The one residual: two files holding a byte-identical record share a key, so
they must share English.  :func:`plan` reports every disagreement as an
``overlay-conflict`` finding and :func:`build` refuses the table while any
remain; ``tools/unify_duplicates.py`` is what resolves them in the tables.

How the diversion stays stateless
---------------------------------
The PC is a ``u16`` into the buffer's runtime image (``docs/format-notes.md``
section 2.6) and the image ends well below 0x10000.  Every span is served **in
place** first: for ``rec_off <= pc - record_off < rec_off + served`` the hook
returns ``en[pc - record_off - rec_off]`` at the real address.  If the English
is longer, the remaining ``tail = len(en) - served`` bytes live in a virtual
range above the image: ``image_end + virt_off``, where ``virt_off`` is the sum
of the tails of the earlier spans **of the same record**.  The last in-place
byte hands the PC to that virtual address, the last tail byte hands it to the
span's real end.  If the English is shorter, the last byte hands the PC to the
span's end directly.  Virtual space is therefore only ever spent on the *excess*
of English over Japanese.

Every write the engine makes to the PC is a plain value store (jump, call frame
push/pop, menu rescanner), so a virtual PC survives all of them.

A virtual PC names no record on its own -- every record's tails start at the
same ``image_end`` -- so it is resolved through the per-handle memo, which is
the record the fetch before it was in.  That is safe exactly because no opcode
the codec may embed in a span (:data:`codec.INLINE_OPS`: the newline, the page
wait and the eight pool calls) transfers control **within the same handle**: a
pool call switches to the pool file's own buffer, which gets its own memo slot,
and returns.  ``tests/test_overlay.py`` pins that precondition.

``cap`` is the other half of the rules, and it is not optional.  A PC the engine
*jumps* to is one the overlay must answer exactly as the original file would,
because the branch was aimed at a byte in the original file -- almost always
the span's own trailing ``1E 10`` page wait.  So no span is served past the
lowest address any branch in its container jumps to; from there on the hook
falls through and the engine reads the file.  Before this rule the hook
answered every address inside a span, and 278 shipped spans handed a jump a
letter of English where an opcode belonged.

``overlay.dat`` layout (little-endian)
--------------------------------------
::

    header   4s magic "GTOV", u32 version (6), u32 nrecs, u32 nspans
    recs     nrecs x { u16 rec_id, u16 jp_len, u32 jp_hash,
                       u32 span_first, u16 nspans, u16 tail_total }
             sorted by (rec_id, jp_len, jp_hash) -- binary-searchable
    spans    nspans x { u16 rec_off, u16 jp_len, u16 served, u16 len,
                        u16 virt_off, u16 pad, u32 data_off }
             grouped by record entry, sorted by rec_off, non-overlapping
    data     the English bytes (codec-encoded: inline opcodes included)

``served`` is how many bytes a span answers starting at its ``rec_off``; the
hook never answers ``rec_off + served`` or beyond.  It is stored rather than
derived because it is not always ``min(len, jp_len)``: a span some branch jumps
into stops at that branch's target, so the jump reads the original file.  When
the same record content appears in several containers with different branch
layouts, the **smallest** ``served`` wins -- serving less is always safe.

The hook (``giten/exe/hook.c``) and :class:`Model` implement the same rules;
``tests/test_overlay.py`` runs both over the same data and demands the same
bytes.
"""
from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field

from . import build_v2, codec, extract_v2, files, records, script, vmops

MAGIC = b"GTOV"
VERSION = 6
PC_LIMIT = 0x10000

#: The highest runtime image end any buffer that can hold one of our records
#: reaches, plus a margin.  Measured over every container of every ``m/`` file
#: (worst: ``m/MS0030`` c0 at 0x8EA2) and every image ``et/ET0007`` merges
#: (worst: row 23 slot 0 at 0x34D3).  ``et/ET0001`` c0 is larger still, 0xE004,
#: but it is a data table: no record of ours can ever be in that buffer, and a
#: record we do not hold is never served.  ``tests/test_overlay.py`` re-measures
#: this and fails if the corpus outgrows it.  Rounded **up**, deliberately: an
#: over-estimate shrinks the tail budget, an under-estimate lets a tail run off
#: the top of the u16 PC.
MAX_IMAGE_END = 0xA000

#: Per *record*, the English excess over the Japanese must fit between the
#: image end and the top of the u16 PC.  This replaces the old per-*file* bound:
#: a record's tails are laid out from its own container's image end, and the
#: record can turn up in any buffer, so the bound has to hold for the worst one.
MAX_TAIL_TOTAL = PC_LIMIT - MAX_IMAGE_END

HDR = struct.Struct("<4sIII")
REC = struct.Struct("<HHIIHH")       # rec_id, jp_len, jp_hash, span_first, nspans, tail_total
SPAN = struct.Struct("<HHHHHHI")     # rec_off, jp_len, served, len, virt_off, pad, data_off


def fnv1a(data: bytes) -> int:
    h = 0x811C9DC5
    for b in data:
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


def engine_index(recs: "list[records.Record]") -> bytes:
    """The 0x400-byte index the loader builds: 256 x { u16 offset, u16 length }.

    Verified against the engine's own entries logged by the tracer (``trace
    bases``): absent ids are one zero byte at their slot.
    """
    base = records.bases(recs)
    first = {}
    for r in recs:
        first.setdefault(r.id, len(r.data))
    out = bytearray()
    for i in range(256):
        out += struct.pack("<HH", base[i], first.get(i, records.ABSENT_LEN))
    return bytes(out)


def image_bytes(recs: "list[records.Record]") -> bytes:
    """The runtime image: index, then record data in id order (absent = 00)."""
    first = {}
    for r in recs:
        first.setdefault(r.id, r.data)
    out = bytearray(engine_index(recs))
    for i in range(256):
        out += first.get(i, b"\0")
    return bytes(out)


def image_end(recs) -> int:
    return len(image_bytes(recs))


def live_index(image: bytes) -> "list[tuple[int, int]]":
    """The 256 ``(offset, length)`` pairs at the front of a running buffer."""
    return [struct.unpack_from("<HH", image, i * 4) for i in range(256)]


def live_end(image: bytes) -> int:
    """Where the running buffer stops, from its own last index entry.

    The same four bytes ``image_end_of`` reads in ``hook.c``.  Taking it from
    the buffer rather than from any model of a file is what makes a merged image
    -- or any image at all -- need no identity.
    """
    off, ln = struct.unpack_from("<HH", image, 255 * 4)
    return off + ln


_live_end = live_end            # the name the older callers used


@dataclass
class SpanEntry:
    """One translated span, addressed inside its record."""

    rec_off: int                # where the span starts inside the record
    jp_len: int                 # how many Japanese bytes it replaces
    data: bytes                 # the English bytes served
    served: int = 0             # bytes answered in place (min(len, jp_len, cap))
    virt_off: int = 0           # tail's offset above the buffer's image end
    #: ``(rel, ci, rec_id, idx)`` for every table row that produced this span --
    #: several, once two byte-identical records in different files agree.
    sources: list = field(default_factory=list)
    #: set when two rows with this key and offset disagree about the English
    conflict: "str | None" = None

    @property
    def tail(self) -> int:
        return len(self.data) - self.served

    @property
    def where(self) -> str:
        rel, ci, rid, idx = self.sources[0]
        return "%s %d:%02X[%d]" % (rel, ci, rid, idx)


@dataclass
class RecEntry:
    """Every span of one *record content*, whichever file supplies it."""

    rec_id: int
    jp_len: int                 # the record's own length
    jp_hash: int                # FNV-1a over the record's bytes
    spans: "list[SpanEntry]" = field(default_factory=list)

    @property
    def key(self) -> "tuple[int, int, int]":
        return (self.rec_id, self.jp_len, self.jp_hash)

    @property
    def tail_total(self) -> int:
        return sum(s.tail for s in self.spans)


#: "m/MS0017.BIN" -> "0017", "et/ID0099.BIN" -> "0099"
_FID = re.compile(r"^[A-Za-z]*([0-9A-Fa-f]+)$")


#: Unassigned in cp932, so never a text byte.  The menu rescanner at
#: ``0x00435CF0`` scans forward for it through ``0x438FA0`` -> ``0x438E50``,
#: which is one of the five fetch sites this overlay hooks -- so a span whose
#: Japanese contains one cannot be served without breaking that scan.  See
#: ``docs/overlay.md``.
STRUCTURAL_BYTE = 0xFF

#: The tag a span carries when it follows opcode ``11``.  49 of the 50 such spans
#: in the corpus are data the tokenizer walked into; the exception is real text in
#: a container that tiles cleanly, which is why :func:`plan` requires both.
DATA_TAG = "11"


def _fid(rel: str) -> int:
    """The engine's file id for a script file, from its name.

    Nothing in the overlay is keyed on this any more -- v6 identifies no file --
    but ``trace files`` still reports the engine's own file register against the
    names on disk, and that is what this is for.

    Slicing ``rel[4:8]`` happened to be right for ``m/MS####`` and wrong for
    every other family: ``et/ID0099.BIN`` came out ``0xD009``, and so did
    ``ID009B`` and ``ID009C``, so three different files shared an id.
    """
    stem = os.path.splitext(os.path.basename(rel))[0]
    m = _FID.match(stem)
    if not m:
        raise ValueError("no file id in %r" % rel)
    return int(m.group(1), 16)


def _add_span(table, key, span, findings):
    """Merge one planned span into the record entry its content names.

    Two files holding a byte-identical record share a key, so they share the
    record's English.  Three ways they can meet:

    * the same offset and the same encoded English -- one span, both sources;
    * the same offset and *different* English -- an ``overlay-conflict``: the
      first text is kept so the rest of the build is still inspectable, but
      :func:`build` refuses the table until the tables agree;
    * a different offset -- an ordinary second span of the same record.

    ``served`` is taken as the **minimum** over the containers that contributed,
    because a branch target inside the span exists in the buffer whichever file
    supplied the record and serving fewer bytes is always safe.
    """
    ent = table.get(key)
    if ent is None:
        ent = table[key] = RecEntry(key[0], key[1], key[2])
    for s in ent.spans:
        if s.rec_off != span.rec_off:
            continue
        if s.data != span.data:
            msg = _conflict_message(ent, s, span)
            if s.conflict is None:
                s.conflict = msg
            findings.append((span.where, msg))
            return
        s.served = min(s.served, span.served)
        s.sources.extend(span.sources)
        return
    ent.spans.append(span)


def _conflict_message(ent: "RecEntry", a: SpanEntry, b: SpanEntry) -> str:
    """Why two rows cannot both be right about one record's bytes."""
    return ("overlay-conflict: record %02X (%d bytes) is byte-identical in "
            "%s and %s, so one key serves both, but they give different "
            "English at offset 0x%04X: %s has %r and %s has %r.  Unify them "
            "(tools/unify_duplicates.py)"
            % (ent.rec_id, ent.jp_len, a.sources[0][0], b.sources[0][0],
               a.rec_off,
               a.where, a.data.decode("cp932", "replace"),
               b.where, b.data.decode("cp932", "replace")))


def plan(rows, root=None):
    """Turn edited table rows into the content-addressed overlay table.

    Returns ``(entries, findings)``.  ``entries`` is a list of :class:`RecEntry`
    sorted by ``(rec_id, jp_len, jp_hash)``; a finding is ``(where, message)``
    for a row that cannot be overlaid (stale, untiled, unencodable, a span that
    does not start where a token starts, an ``overlay-conflict``, or a record
    whose virtual space is exhausted).  Only ``m/`` files are overlaid: ``p/``
    name fields are fixed-width and stay a direct edit.
    """
    by_file = {}
    for r in rows:
        if r.edited and r.file.startswith("m/"):
            by_file.setdefault(r.file, []).append(r)
    table, findings = {}, []
    for rel in sorted(by_file):
        sc = script.parse(rel, files.read_source(rel, root))
        if not sc.ok:
            continue
        keyed = {}
        for r in by_file[rel]:
            if r.tag == extract_v2.UNTILED_TAG or r.rec == extract_v2.PNAME_REC:
                findings.append(("%s %s[%d]" % (rel, r.rec, r.idx), "record is not editable"))
                continue
            ci, _, rid = r.rec.partition(":")
            keyed[(int(ci), int(rid, 16), r.idx)] = r
        for key, why in build_v2.stale_rows(sc, keyed):
            findings.append(("%s %d:%02X[%d]" % (rel, key[0], key[1], key[2]), why))
            keyed.pop(key)
        for ci, cont in enumerate(sc.containers):
            recs = [records.Record(r.id, r.data) for r in cont]
            base = records.bases(recs)
            # Every address some rel16 in this container jumps to, including the
            # switch-table entries -- vmops types those as rel16 too, so one
            # call covers both.  A span may not be served past the lowest of
            # these that falls inside it.  Held record-relative, because the
            # record can turn up in a buffer this container never built.
            targets = sorted(script._branch_targets(cont, base))
            # a container with a record we cannot tile is one where the walk is
            # known to go out of step; spans after a branch in it are suspect
            untiled_here = any(r.tokens is None for r in cont)
            seen = set()
            for rec in cont:
                # ``span_tokens``, not ``tokens``: a straddling record is untiled
                # for the byte builder but its spans are complete, and the overlay
                # rebuilds nothing, so it can serve them.
                if rec.id in seen or rec.span_tokens is None:
                    continue
                seen.add(rec.id)
                rkey = (rec.id, len(rec.data), fnv1a(rec.data))
                for sp in rec.spans:
                    row = keyed.get((ci, rec.id, sp.idx))
                    if row is None:
                        continue
                    try:
                        data = codec.encode(row.en, allow=codec.INLINE_OPS)
                    except codec.CodecError as exc:
                        findings.append(("%s %s[%d]" % (rel, row.rec, row.idx), str(exc)))
                        continue
                    if not data:
                        findings.append(("%s %s[%d]" % (rel, row.rec, row.idx),
                                         "English encodes to nothing; a span cannot vanish"))
                        continue
                    # The span list and the record's own tiling must agree that
                    # a token starts here.  If they ever disagreed, English
                    # would land at an address the engine only reaches *inside*
                    # another token, overwriting that token's operands.
                    #
                    # **This currently never fires**, and the measurement that
                    # said it would was wrong: it attributed spans to records by
                    # walking every record's address range, which double-counts
                    # the containers that carry duplicate record ids, and named
                    # three innocent spans in `m/MS6012` and `m/MS610B`.  The
                    # guard is kept anyway, because it is one `any()` and the
                    # whole overlay rests on it being true.  A straddling record
                    # has no `tokens` and is judged by `span_tokens`, which is
                    # what its spans were derived from.
                    toks = rec.tokens if rec.tokens is not None else rec.span_tokens
                    if not any(t.off == sp.off for t in toks):
                        findings.append(("%s %s[%d]" % (rel, row.rec, row.idx),
                                         "no token starts here: the span list and "
                                         "the record's tiling disagree about where "
                                         "the text begins, so English would land on "
                                         "another token's operands"))
                        continue
                    # English may not end on a dangling escape prefix.  The
                    # engine reads 1D/1E/1F and then takes the NEXT byte as the
                    # opcode's second half -- and the next byte comes from the
                    # original stream at `end`, so our text and the game's
                    # bytes combine into an opcode neither side has.  Shipped
                    # once: m/MS6000 span 0x2204 ended `... 01 00 1e`, the byte
                    # at 0x2210 is `1F`, and together they made `1E1F` -- which
                    # also swallowed the `1F` that was itself a prefix, putting
                    # every token after it one byte out.
                    if data[-1] in vmops.ESCAPE:
                        findings.append(("%s %s[%d]" % (rel, row.rec, row.idx),
                                         "the English ends on a bare 0x%02X, an escape "
                                         "prefix; the engine would pair it with the "
                                         "original byte at the span's end and dispatch "
                                         "an opcode that is in neither stream"
                                         % data[-1]))
                        continue
                    jp = rec.data[sp.off:sp.end]
                    # A span that follows opcode 11, **in a container we could
                    # not fully tile**, is not text.  Both halves are needed.
                    #
                    # 49 of the 50 such spans corpus-wide contain no kana at all
                    # and decode to the clothing-radical block that binary lands
                    # on when read as Shift-JIS; they sit only in m/MS610D,
                    # m/MS6200 and m/MS6500, whose records the tokenizer also
                    # cannot tile -- the tell that it is out of step there.  A
                    # `02 00` inside one reads as a pool call, so promotion put
                    # "Devil Buster" in the middle of a data table.
                    #
                    # The fiftieth is m/MS6000 12:CE[1], `失敗！` -> `Failure!`,
                    # which is real.  It has kanji and no kana, so "no kana" was
                    # not the rule; and the clothing-radical block was not either
                    # -- it contains 裂 and 裏, and 580 real lines use them.  The
                    # container's own tiling is what separates them, which is the
                    # same correlation that explains every off-boundary branch
                    # target: all 119 sit in a container with an untiled record,
                    # none in a clean one.
                    if row.tag == DATA_TAG and untiled_here:
                        findings.append(("%s %s[%d]" % (rel, row.rec, row.idx),
                                         "the span follows opcode %s in a container "
                                         "holding a record we cannot tile, so the walk is "
                                         "out of step here and this is data, not text"
                                         % DATA_TAG))
                        continue
                    # 0xFF has to be *counted*, not merely present.  A span whose
                    # Japanese holds two and whose English holds one passed this
                    # when it compared presence, and one did: m/MS610D 0:FE[4].
                    if jp.count(STRUCTURAL_BYTE) != data.count(STRUCTURAL_BYTE):
                        findings.append(("%s %s[%d]" % (rel, row.rec, row.idx),
                                         "the Japanese here contains 0x%02X, which is "
                                         "unassigned in cp932 and so is never text; the "
                                         "menu rescanner (0x00435CF0) scans for it through "
                                         "the fetch we hook, and the English carries %d of "
                                         "them against the Japanese's %d"
                                         % (STRUCTURAL_BYTE, data.count(STRUCTURAL_BYTE),
                                            jp.count(STRUCTURAL_BYTE))))
                        continue
                    lo = base[rec.id] + sp.off
                    hi = base[rec.id] + sp.end
                    cap = next((t for t in targets if lo < t < hi), None)
                    jp_len = sp.end - sp.off
                    served = min(len(data), jp_len)
                    if cap is not None:
                        served = min(served, cap - lo)
                    _add_span(table, rkey,
                              SpanEntry(sp.off, jp_len, data, served,
                                        sources=[(rel, ci, rec.id, sp.idx)]),
                              findings)
    entries = []
    for key in sorted(table):
        ent = table[key]
        ent.spans.sort(key=lambda s: s.rec_off)
        cursor, kept = 0, []
        for s in ent.spans:
            # Every span carries the cursor, even one whose English fits in
            # place, so `virt_off` is non-decreasing across the record's spans
            # and the hook can binary-search the virtual side too.  A span with
            # no tail is then an empty range the search steps over; a zero there
            # would break the ordering instead.
            if not s.tail:
                s.virt_off = cursor
                kept.append(s)                  # fits in place, no virtual space
                continue
            if cursor + s.tail > MAX_TAIL_TOTAL:
                findings.append((s.where,
                                 "overlay-space: record %02X has already spent %d of "
                                 "the %d bytes of virtual PC space a record may use "
                                 "(0x%04X is the highest image end any buffer that can "
                                 "hold it reaches); shorten the English in this record"
                                 % (ent.rec_id, cursor, MAX_TAIL_TOTAL, MAX_IMAGE_END)))
                continue
            s.virt_off = cursor
            cursor += s.tail
            kept.append(s)
        ent.spans = kept
        if kept:
            entries.append(ent)
    return entries, findings


def conflicts(entries) -> "list[str]":
    """Every ``overlay-conflict`` still standing in a planned table."""
    return [s.conflict for e in entries for s in e.spans if s.conflict]


def build(entries: "list[RecEntry]") -> bytes:
    """Serialise a planned table.

    Refuses while any ``overlay-conflict`` remains: two files whose records are
    byte-identical share one key, so shipping a table that disagrees about the
    English would silently give one of the two files the other's line.
    """
    bad = conflicts(entries)
    if bad:
        raise ValueError(
            "%d record(s) carry two different English translations of the same "
            "Japanese bytes, and v6 keys on the bytes, so one of the two would "
            "be served for both.  Run tools/unify_duplicates.py.  First: %s"
            % (len(bad), bad[0]))
    entries = sorted(entries, key=lambda e: e.key)
    nspans = sum(len(e.spans) for e in entries)
    recs_off = HDR.size
    spans_off = recs_off + REC.size * len(entries)
    data_off = spans_off + SPAN.size * nspans
    recs, spans, data = bytearray(), bytearray(), bytearray()
    first = 0
    for e in entries:
        recs += REC.pack(e.rec_id, e.jp_len, e.jp_hash, first, len(e.spans),
                         e.tail_total)
        first += len(e.spans)
        for s in e.spans:
            spans += SPAN.pack(s.rec_off, s.jp_len, s.served, len(s.data),
                               s.virt_off, 0, data_off + len(data))
            data += s.data
    return (HDR.pack(MAGIC, VERSION, len(entries), nspans)
            + bytes(recs) + bytes(spans) + bytes(data))


def parse(blob: bytes) -> "list[RecEntry]":
    """Read v6, and only v6.

    A trace is only meaningful against the overlay that produced it, and the v4
    and v5 readers existed to keep recorded fixtures alive.  Those fixtures are
    gone (``tests/test_v2.py`` generates its traces from :class:`Model` now), so
    reading a format the hook cannot read would only invite a silent mismatch.
    """
    magic, version, nrecs, nspans = HDR.unpack_from(blob, 0)
    if magic != MAGIC or version != VERSION:
        raise ValueError("not a v%d overlay.dat" % VERSION)
    recs_off = HDR.size
    spans_off = recs_off + REC.size * nrecs
    out = []
    for i in range(nrecs):
        rec_id, jp_len, jp_hash, first, n, tail_total = REC.unpack_from(
            blob, recs_off + i * REC.size)
        e = RecEntry(rec_id, jp_len, jp_hash)
        for k in range(first, first + n):
            rec_off, sp_len, served, ln, virt_off, _pad, doff = SPAN.unpack_from(
                blob, spans_off + k * SPAN.size)
            e.spans.append(SpanEntry(rec_off, sp_len, blob[doff:doff + ln],
                                     served, virt_off))
        assert e.tail_total == tail_total, "tail_total disagrees with the spans"
        out.append(e)
    return out


def find_entry(entries, rec_id: int, jp_len: int, jp_hash: int):
    """The record entry for one *content*, by binary search -- the hook's lookup.

    ``entries`` must be sorted by ``(rec_id, jp_len, jp_hash)``, which is how
    :func:`build` writes them and :func:`parse` reads them back.
    """
    lo, hi = 0, len(entries) - 1
    want = (rec_id, jp_len, jp_hash)
    while lo <= hi:
        mid = (lo + hi) // 2
        got = entries[mid].key
        if want < got:
            hi = mid - 1
        elif want > got:
            lo = mid + 1
        else:
            return entries[mid]
    return None


class Model:
    """Reference semantics of the exe hook, one fetch at a time.

    One :class:`Model` is one buffer behind one handle.  ``hook.c`` keeps four
    memo slots because several buffers are resident at once; each of them
    behaves exactly like one of these.
    """

    def __init__(self, entries, image: bytes):
        self.entries = sorted(entries or [], key=lambda e: e.key)
        self.image = image
        #: the memo of section 2 step 2: ``(rec, off, len, entry)``, where
        #: ``entry`` may be None ("this record is not translated", memoised too)
        self.memo = None

    # -- the pieces the hook has, in the same order ------------------------
    def image_end(self) -> int:
        return live_end(self.image)

    def _index(self, rec: int) -> "tuple[int, int]":
        return struct.unpack_from("<HH", self.image, rec * 4)

    def find_record(self, pc: int) -> "int | None":
        """The record whose ``[off, off+len)`` holds ``pc``, by binary search.

        Offsets are non-decreasing in id (absent ids occupy one byte each), so
        the last entry at or below ``pc`` is the only candidate.
        """
        lo, hi, best = 0, 255, -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._index(mid)[0] <= pc:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if best < 0:
            return None
        off, ln = self._index(best)
        return best if pc < off + ln else None

    def _memo_valid(self) -> bool:
        if self.memo is None:
            return False
        rec, off, ln, _entry = self.memo
        return self._index(rec) == (off, ln)

    def _entry_for(self, rec: int):
        """The record entry for ``rec``, memoised and re-validated every fetch."""
        off, ln = self._index(rec)
        if self._memo_valid() and self.memo[0] == rec:
            return self.memo[3]
        entry = find_entry(self.entries, rec, ln,
                           fnv1a(self.image[off:off + ln]))
        self.memo = (rec, off, ln, entry)
        return entry

    @staticmethod
    def _span_at(entry, k: int):
        for s in entry.spans:
            if s.rec_off <= k < s.rec_off + s.served:
                return s
        return None

    @staticmethod
    def _tail_at(entry, k: int):
        for s in entry.spans:
            if s.tail and s.virt_off <= k < s.virt_off + s.tail:
                return s
        return None

    def fetch(self, pc: int) -> "tuple[int, int]":
        """``(byte, next pc)`` exactly as the hooked engine would see them."""
        end = self.image_end()
        if pc < end:
            rec = self.find_record(pc)
            if rec is None:
                return self.image[pc], (pc + 1) & 0xFFFF
            entry = self._entry_for(rec)
            if entry is None:
                return self.image[pc], (pc + 1) & 0xFFFF
            off = self._index(rec)[0]
            s = self._span_at(entry, pc - off)
            if s is None:
                return self.image[pc], (pc + 1) & 0xFFFF
            k = pc - off - s.rec_off
            if k + 1 == len(s.data):
                nxt = off + s.rec_off + s.jp_len
            elif k + 1 == s.served:
                nxt = end + s.virt_off
            else:
                nxt = pc + 1
            return s.data[k], nxt & 0xFFFF
        # a virtual PC exists only because the fetch before it created one, so
        # the memo names the record it belongs to
        if not self._memo_valid() or self.memo[3] is None:
            return STRUCTURAL_BYTE, (pc + 1) & 0xFFFF
        rec, off, _ln, entry = self.memo
        s = self._tail_at(entry, pc - end)
        if s is None:
            return STRUCTURAL_BYTE, (pc + 1) & 0xFFFF
        k = s.served + (pc - end - s.virt_off)
        nxt = (off + s.rec_off + s.jp_len) if k + 1 == len(s.data) else pc + 1
        return s.data[k], nxt & 0xFFFF

    def walk(self, pc: int, stop: int, limit: int = 1 << 20) -> bytes:
        """The byte stream a straight-line walk from ``pc`` to the real ``stop`` sees."""
        out = bytearray()
        while pc != stop and len(out) < limit:
            b, pc = self.fetch(pc)
            out.append(b)
        return bytes(out)
