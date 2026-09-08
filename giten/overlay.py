"""Runtime text overlay: the translation lives beside the game, not in it.

The script files stay **byte-identical to the original**.  The patched exe
hooks the interpreter's one byte-fetch routine (``0x438E50``); when the
program counter reaches the first byte of a translated span it serves the
English bytes instead and then rejoins the Japanese stream at the span's end.
No script byte is ever rewritten, so no branch, switch table, flag or record
length can change: the logic of an English run is the logic of the Japanese
run by construction, and ``trace diff`` can demand opcode-for-opcode equality.

How the diversion stays stateless
---------------------------------
The PC is a ``u16`` into the file's runtime image (``docs/format-notes.md``
section 2.6) and the image ends well below 0x10000.  Every translated span is
given a **virtual PC range** above the image end; serving English is then a
pure function of the PC:

Every span is served **in place** first: for ``start <= PC < start + head``,
where ``head = min(len(en), len(jp), cap - start)``, the hook returns
``en[PC - start]`` at the real address.  If the English is longer, the
remaining ``tail = len(en) - head`` bytes live in a virtual range
``[virt, virt + tail)`` above the image; the last in-place byte hands the PC to
``virt``, the last tail byte hands it to ``span.end``.  If the English is
shorter, the last byte hands the PC to ``span.end`` directly.  Virtual space is
therefore only ever spent on the *excess* of English over Japanese, and serving
is a pure function of the PC:

* start <= PC < start + head     -> en[PC - start]; next: PC+1, or virt (head done, tail exists), or end
* virt <= PC < virt + tail       -> en[head + PC - virt]; next: PC+1, or end

Every write the engine makes to the PC is a plain value store (jump, call
frame push/pop, menu rescanner), so a virtual PC survives all of them.

``cap`` is the other half of that, and it is not optional.  A PC the engine
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

    header   4s magic "GTOV", u32 version (4), u32 nfiles, u32 reserved
    dir      nfiles x { u16 fid, u16 pad, u32 fp, u16 image_end, u16 nspans, u32 spans_off,
                        u16 ntails, u16 pad, u32 tails_off }
    spans    per file, sorted by start:
             { u16 start, u16 end, u16 virt, u16 len, u16 served, u16 pad, u32 data_off }
             (virt == 0 when the English fits in place)
    tails    per file, sorted by virt, one per span with an excess:
             { u16 start = virt, u16 end, u16 virt, u16 len = served = tail bytes,
               u32 data_off (of the tail) }
             -- the same struct, so one range search serves both arrays
    data     the English bytes (codec-encoded: inline opcodes included)

``served`` is how many bytes this entry answers starting at ``start``; the hook
never answers ``start + served`` or beyond.  It is stored rather than derived
because it is not always ``min(len, end - start)``: a span some branch jumps
into stops at that branch's target, so the jump reads the original file.

``fid`` is the engine's current-file id (``0x4911B0``); ``fp`` is FNV-1a over
the engine's own 0x400-byte record index at the start of the buffer, which
tells the containers of a multi-container file apart (the hook only hashes a
buffer whose entry 0 sits at 0x400, i.e. a script buffer).
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
VERSION = 5
FP_BYTES = 0x400                # the whole record index (two MS610B containers agree on 32 entries)
PC_LIMIT = 0x10000

#: The hook keeps one verification bit per span in a fixed array and refuses an
#: entry it cannot cover, so an entry over this would ship with its English
#: silently switched off.  ``m/MS0030`` c0 is already at 1,013, so the headroom
#: is thin -- which is why this is a build error rather than only a test.
#: ``tests/test_merged_overlay.py`` checks that hook.c still says the same.
MAX_SPANS = 1024

HDR = struct.Struct("<4sIII")
DIR = struct.Struct("<HHIHHIHHI")            # the second u16 is the container index
SPAN = struct.Struct("<HHHHHHIHHI")         # start, JP LEN, virt, len, served,
                                            # pad, data_off, rec, rec_off, jp_hash


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


def fingerprint(recs) -> int:
    return fnv1a(engine_index(recs)[:FP_BYTES])


def image_end(recs) -> int:
    return len(image_bytes(recs))


@dataclass
class SpanEntry:
    start: int              # real PC of the first Japanese byte
    end: int                # real PC just past the Japanese span
    virt: int               # first virtual PC of the tail (0 = no tail)
    data: bytes             # the English bytes served
    rec_id: int = -1
    idx: int = -1
    cap: "int | None" = None    # lowest address a branch jumps to inside the span
    rec_off: int = 0            # where the span starts inside its record
    jp_hash: int = 0            # fnv1a of the Japanese this span replaces

    @property
    def head(self) -> int:
        """Bytes served in place.

        As many as the Japanese occupied, at most -- and never past an address
        some branch in the container jumps to.  ``cap`` is that address, and
        stopping there is what keeps the overlay's answer to a jump equal to
        the original file's: everything from ``cap`` on falls through to
        ``ORIG_FETCH``, so the branch reads exactly the bytes it always read.
        The English displaced by the cap is not lost, it moves to the tail.

        Without the cap the hook answered any address inside the span, so a
        branch aiming at the span's own trailing ``1E 10`` page wait got a
        letter instead and the interpreter ran prose as opcodes.  278 of those
        shipped.
        """
        h = min(len(self.data), self.end - self.start)
        if self.cap is not None:
            h = min(h, self.cap - self.start)
        return h

    @property
    def tail(self) -> int:
        return len(self.data) - self.head

    @property
    def vend(self) -> int:
        return self.virt + self.tail


@dataclass
class Entry:
    rel: str
    ci: int
    fid: int
    fp: int
    image_end: int
    spans: "list[SpanEntry]" = field(default_factory=list)      # every span, by start

    @property
    def tails(self) -> "list[SpanEntry]":
        return [s for s in self.spans if s.tail]


#: "m/MS0017.BIN" -> "0017", "et/ID0099.BIN" -> "0099"
_FID = re.compile(r"^[A-Za-z]*([0-9A-Fa-f]+)$")


#: Unassigned in cp932, so never a text byte.  The menu rescanner at
#: ``0x00435CF0`` scans forward for it through ``0x438FA0`` -> ``0x438E50``,
#: which is one of the five fetch sites this overlay hooks -- so a span whose
#: Japanese contains one cannot be served without breaking that scan.  See
#: ``docs/overlay.md``.
STRUCTURAL_BYTE = 0xFF


def _fid(rel: str) -> int:
    """The engine's file id for a script file, from its name.

    Slicing ``rel[4:8]`` happened to be right for ``m/MS####`` and wrong for
    every other family: ``et/ID0099.BIN`` came out ``0xD009``, and so did
    ``ID009B`` and ``ID009C``, so three different files shared an id.  Nothing
    was keyed on it because ``plan`` only ever passed ``m/`` files, but that is
    the sort of latent wrongness that surfaces the moment the filter widens.
    """
    stem = os.path.splitext(os.path.basename(rel))[0]
    m = _FID.match(stem)
    if not m:
        raise ValueError("no file id in %r" % rel)
    return int(m.group(1), 16)


def plan(rows, root=None):
    """Turn edited table rows into overlay entries.

    Returns ``(entries, findings)``; a finding is ``(where, message)`` for a row
    that cannot be overlaid (stale fingerprint, encode error, untiled record,
    or the file's virtual space is exhausted).  Only ``m/`` files are overlaid:
    ``p/`` name fields are fixed-width and stay a direct edit.
    """
    by_file = {}
    for r in rows:
        if r.edited and r.file.startswith("m/"):
            by_file.setdefault(r.file, []).append(r)
    entries, findings = [], []
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
            ent = Entry(rel, ci, _fid(rel), fingerprint(recs), image_end(recs))
            # Every address some rel16 in this container jumps to, including the
            # switch-table entries -- vmops types those as rel16 too, so one
            # call covers both.  A span may not be served past the lowest of
            # these that falls inside it.
            targets = sorted(script._branch_targets(cont, base))
            seen = set()
            for rec in cont:
                # ``span_tokens``, not ``tokens``: a straddling record is untiled
                # for the byte builder but its spans are complete, and the overlay
                # rebuilds nothing, so it can serve them.
                if rec.id in seen or rec.span_tokens is None:
                    continue
                seen.add(rec.id)
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
                    if STRUCTURAL_BYTE in jp and STRUCTURAL_BYTE not in data:
                        findings.append(("%s %s[%d]" % (rel, row.rec, row.idx),
                                         "the Japanese here contains 0x%02X, which is "
                                         "unassigned in cp932 and so is never text; the "
                                         "menu rescanner (0x00435CF0) scans for it through "
                                         "the fetch we hook, and English drops it"
                                         % STRUCTURAL_BYTE))
                        continue
                    lo = base[rec.id] + sp.off
                    hi = base[rec.id] + sp.end
                    cap = next((t for t in targets if lo < t < hi), None)
                    ent.spans.append(SpanEntry(lo, hi, 0, data, rec.id, sp.idx,
                                               cap=cap, rec_off=sp.off,
                                               jp_hash=fnv1a(jp)))
            ent.spans.sort(key=lambda s: s.start)
            cursor = ent.image_end
            kept = []
            for s in ent.spans:
                if not s.tail:
                    kept.append(s)                          # fits in place, no virtual space
                    continue
                if cursor + s.tail > PC_LIMIT:
                    findings.append(("%s %d:%02X[%d]" % (rel, ci, s.rec_id, s.idx),
                                     "overlay-space: the file's virtual PC space is full "
                                     "(image ends at 0x%04X, %d English bytes before this "
                                     "span); shorten the English in this file"
                                     % (ent.image_end, cursor - ent.image_end)))
                    continue
                s.virt = cursor
                cursor += s.tail
                kept.append(s)
            ent.spans = kept
            if kept:
                entries.append(ent)
    return entries, findings


def build(entries: "list[Entry]") -> bytes:
    for e in entries:
        if len(e.spans) > MAX_SPANS or len(e.tails) > MAX_SPANS:
            raise ValueError(
                "%s c%d has %d spans and %d tails; the hook verifies at most %d "
                "of each and refuses an entry over that, so this file would ship "
                "with no English at all.  Raise MAX_SPANS in giten/overlay.py "
                "*and* giten/exe/hook.c together, or shorten the file."
                % (e.rel, e.ci, len(e.spans), len(e.tails), MAX_SPANS))
    dir_off = HDR.size
    spans_off = dir_off + DIR.size * len(entries)
    data_off = spans_off + SPAN.size * sum(len(e.spans) + len(e.tails) for e in entries)
    dirs, spans, data = bytearray(), bytearray(), bytearray()
    for e in entries:
        soff = spans_off + len(spans)
        doffs = {}
        for s in e.spans:
            doffs[id(s)] = data_off + len(data)
            spans += SPAN.pack(s.start, s.end - s.start, s.virt, len(s.data),
                               s.head, 0, doffs[id(s)], s.rec_id & 0xFFFF,
                               s.rec_off, s.jp_hash)
            data += s.data
        toff = spans_off + len(spans)
        tails = e.tails
        for s in tails:
            spans += SPAN.pack(s.virt, s.end - s.start, s.virt, s.tail, s.tail,
                               0, doffs[id(s)] + s.head, s.rec_id & 0xFFFF,
                               s.rec_off, s.jp_hash)
        dirs += DIR.pack(e.fid, e.ci & 0xFFFF, e.fp, e.image_end,
                         len(e.spans), soff, len(tails), 0, toff)
    return HDR.pack(MAGIC, VERSION, len(entries), 0) + bytes(dirs) + bytes(spans) + bytes(data)


#: v4 spans stop at ``data_off``; v5 appends ``rec``, ``rec_off`` and ``jp_hash``.
SPAN_V4 = struct.Struct("<HHHHHHI")


def parse(blob: bytes) -> "list[Entry]":
    """Read v5, and still read v4.

    Recorded traces are only meaningful against the overlay that produced them
    (``tests/data/verify-overlay.gtov`` is one), so dropping v4 here would throw
    away the fixtures rather than upgrade them.  A v4 span resolves to itself:
    with ``rec_off`` 0 and ``jp_hash`` 0 :func:`resolve` cannot verify it, which
    is why :func:`resolve` refuses a v4 entry outright instead of guessing.
    """
    magic, version, nfiles, _ = HDR.unpack_from(blob, 0)
    if magic != MAGIC or version not in (4, VERSION):
        raise ValueError("not an overlay.dat")
    span = SPAN if version == VERSION else SPAN_V4
    out = []
    for i in range(nfiles):
        fid, ci, fp, iend, n, soff, nt, _, toff = DIR.unpack_from(blob, HDR.size + i * DIR.size)
        e = Entry("m/MS%04X.BIN" % fid, ci, fid, fp, iend)
        for k in range(n):
            f = span.unpack_from(blob, soff + k * span.size)
            start, second, virt, ln, served, _, doff = f[:7]
            rec, rec_off, jp_hash = f[7:] if version == VERSION else (-1, 0, 0)
            end = (start + second) if version == VERSION else second
            e.spans.append(SpanEntry(start, end, virt, blob[doff:doff + ln],
                                     rec_id=rec, cap=start + served,
                                     rec_off=rec_off, jp_hash=jp_hash))
        # the tails array is derived from the spans; check it says the same thing
        for k in range(nt):
            vstart, second, virt, tlen, _served, _, doff = span.unpack_from(
                blob, toff + k * span.size)[:7]
            s = next(s for s in e.spans if s.virt == virt and s.tail)
            end = (s.start + second) if version == VERSION else second
            assert (vstart, end, tlen, blob[doff:doff + tlen]) == (s.virt, s.end, s.tail, s.data[s.head:])
        out.append(e)
    return out


def live_index(image: bytes) -> "list[tuple[int, int]]":
    """The 256 ``(offset, length)`` pairs at the front of a running buffer."""
    return [struct.unpack_from("<HH", image, i * 4) for i in range(256)]


def _live_end(image: bytes) -> int:
    """Where the running buffer stops, from its own last index entry.

    The same four bytes ``image_end_of`` reads in ``hook.c``; taking it from the
    buffer rather than from the directory is what makes a merged image safe.
    """
    off, ln = struct.unpack_from("<HH", image, 255 * 4)
    return off + ln


def resolve(entry: "Entry", image: bytes) -> "list[SpanEntry]":
    """The spans of ``entry`` that the buffer ``image`` actually holds.

    A span is placed at ``live_index[rec].offset + rec_off`` -- the address the
    *running* buffer puts that record at, not the one our model of the file
    predicts -- and kept only if the Japanese there hashes to what the span was
    built from.

    That is what makes this survive the m/MS6xxx merge.  A record the merge
    shifted is still found, because the live index says where it went.  A record
    another file replaced fails the hash, because the bytes are not the ones we
    translated, and is dropped rather than served at a plausible-looking
    address.  Neither case needs to know that a merge happened at all.
    """
    idx = live_index(image)
    # Virtual addresses live above the image, so they move when the image does.
    # A merge makes the buffer longer than the file we planned against -- for
    # m/MS6000 c0, 0x1D7B becomes about 0x222C -- and virtual addresses handed
    # out from the old end would then collide with real records that now exist
    # there.  Shifting them by the same amount as the image keeps them above it.
    delta = _live_end(image) - entry.image_end
    out = []
    for s in entry.spans:
        if not 0 <= s.rec_id < 256 or not s.jp_hash:
            continue        # v4, or a span whose Japanese hashes to zero
        off, ln = idx[s.rec_id]
        jp_len = s.end - s.start
        lo = off + s.rec_off
        if s.rec_off + jp_len > ln or lo + jp_len > len(image):
            continue                      # the record is shorter here than we assumed
        if fnv1a(image[lo:lo + jp_len]) != s.jp_hash:
            continue                      # some other file supplied this record
        virt = (s.virt + delta) if s.virt else 0
        if virt and virt + (len(s.data) - (s.cap - s.start if s.cap else jp_len)) > PC_LIMIT:
            continue                      # the shifted tail would run off the top
        moved = SpanEntry(lo, lo + jp_len, virt, s.data, s.rec_id, s.idx,
                          cap=None if s.cap is None else lo + (s.cap - s.start),
                          rec_off=s.rec_off, jp_hash=s.jp_hash)
        out.append(moved)
    out.sort(key=lambda x: x.start)
    return out


class Model:
    """Reference semantics of the exe hook, one fetch at a time."""

    def __init__(self, entry: "Entry | None", image: bytes):
        self.entry = entry
        self.image = image
        # v5 spans are placed against the buffer that is actually running, so a
        # merged image finds them; v4 spans carry no hash to check and are used
        # where they were planned, which is what they have always meant.
        if entry is None:
            self.spans, self.live_end = [], 0
        elif any(s.jp_hash for s in entry.spans):
            self.spans, self.live_end = resolve(entry, image), _live_end(image)
        else:
            self.spans, self.live_end = entry.spans, entry.image_end

    def fetch(self, pc: int) -> "tuple[int, int]":
        """``(byte, next pc)`` exactly as the hooked engine would see them."""
        if self.entry is not None:
            if pc >= self.live_end:
                for s in self.spans:                    # the hook binary-searches; same answer
                    if s.tail and s.virt <= pc < s.vend:
                        k = pc - s.virt
                        return s.data[s.head + k], (s.end if k + 1 == s.tail else pc + 1)
            else:
                for s in self.spans:
                    if s.start <= pc < s.start + s.head:
                        k = pc - s.start
                        if k + 1 == len(s.data):
                            nxt = s.end
                        elif k + 1 == s.head:
                            nxt = s.virt
                        else:
                            nxt = pc + 1
                        return s.data[k], nxt
        return self.image[pc], (pc + 1) & 0xFFFF

    def walk(self, pc: int, stop: int, limit: int = 1 << 20) -> bytes:
        """The byte stream a straight-line walk from ``pc`` to the real ``stop`` sees."""
        out = bytearray()
        while pc != stop and len(out) < limit:
            b, pc = self.fetch(pc)
            out.append(b)
        return bytes(out)
