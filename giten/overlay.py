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
where ``head = min(len(en), len(jp))``, the hook returns ``en[PC - start]`` at
the real address.  If the English is longer, the remaining ``tail = len(en) -
head`` bytes live in a virtual range ``[virt, virt + tail)`` above the image;
the last in-place byte hands the PC to ``virt``, the last tail byte hands it to
``span.end``.  If the English is shorter, the last byte hands the PC to
``span.end`` directly.  Virtual space is therefore only ever spent on the
*excess* of English over Japanese, and serving is a pure function of the PC:

* start <= PC < start + head     -> en[PC - start]; next: PC+1, or virt (head done, tail exists), or end
* virt <= PC < virt + tail       -> en[head + PC - virt]; next: PC+1, or end

Every write the engine makes to the PC is a plain value store (jump, call
frame push/pop, menu rescanner), so a virtual PC survives all of them.

``overlay.dat`` layout (little-endian)
--------------------------------------
::

    header   4s magic "GTOV", u32 version (3), u32 nfiles, u32 reserved
    dir      nfiles x { u16 fid, u16 pad, u32 fp, u16 image_end, u16 nspans, u32 spans_off,
                        u16 ntails, u16 pad, u32 tails_off }
    spans    per file, sorted by start:   { u16 start, u16 end, u16 virt, u16 len, u32 data_off }
             (virt == 0 when the English fits in place)
    tails    per file, sorted by virt, one per span with an excess:
             { u16 start = virt, u16 end, u16 virt, u16 len = tail bytes, u32 data_off (of the tail) }
             -- the same struct, so one range search serves both arrays
    data     the English bytes (codec-encoded: inline opcodes included)

``fid`` is the engine's current-file id (``0x4911B0``); ``fp`` is FNV-1a over
the engine's own 0x400-byte record index at the start of the buffer, which
tells the containers of a multi-container file apart (the hook only hashes a
buffer whose entry 0 sits at 0x400, i.e. a script buffer).
The hook (``giten/exe/hook.c``) and :class:`Model` implement the same rules;
``tests/test_overlay.py`` runs both over the same data and demands the same
bytes.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import build_v2, codec, extract_v2, files, records, script

MAGIC = b"GTOV"
VERSION = 3
FP_BYTES = 0x400                # the whole record index (two MS610B containers agree on 32 entries)
PC_LIMIT = 0x10000

HDR = struct.Struct("<4sIII")
DIR = struct.Struct("<HHIHHIHHI")
SPAN = struct.Struct("<HHHHI")


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

    @property
    def head(self) -> int:
        """Bytes served in place: as many as the Japanese occupied, at most."""
        return min(len(self.data), self.end - self.start)

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


def _fid(rel: str) -> int:
    return int(rel[4:8], 16)


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
            seen = set()
            for rec in cont:
                if rec.id in seen or rec.tokens is None:
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
                    ent.spans.append(SpanEntry(base[rec.id] + sp.off, base[rec.id] + sp.end,
                                               0, data, rec.id, sp.idx))
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
    dir_off = HDR.size
    spans_off = dir_off + DIR.size * len(entries)
    data_off = spans_off + SPAN.size * sum(len(e.spans) + len(e.tails) for e in entries)
    dirs, spans, data = bytearray(), bytearray(), bytearray()
    for e in entries:
        soff = spans_off + len(spans)
        doffs = {}
        for s in e.spans:
            doffs[id(s)] = data_off + len(data)
            spans += SPAN.pack(s.start, s.end, s.virt, len(s.data), doffs[id(s)])
            data += s.data
        toff = spans_off + len(spans)
        tails = e.tails
        for s in tails:
            spans += SPAN.pack(s.virt, s.end, s.virt, s.tail, doffs[id(s)] + s.head)
        dirs += DIR.pack(e.fid, 0, e.fp, e.image_end, len(e.spans), soff, len(tails), 0, toff)
    return HDR.pack(MAGIC, VERSION, len(entries), 0) + bytes(dirs) + bytes(spans) + bytes(data)


def parse(blob: bytes) -> "list[Entry]":
    magic, version, nfiles, _ = HDR.unpack_from(blob, 0)
    if magic != MAGIC or version != VERSION:
        raise ValueError("not an overlay.dat")
    out = []
    for i in range(nfiles):
        fid, _, fp, iend, n, soff, nt, _, toff = DIR.unpack_from(blob, HDR.size + i * DIR.size)
        e = Entry("m/MS%04X.BIN" % fid, -1, fid, fp, iend)
        for k in range(n):
            start, end, virt, ln, doff = SPAN.unpack_from(blob, soff + k * SPAN.size)
            e.spans.append(SpanEntry(start, end, virt, blob[doff:doff + ln]))
        # the tails array is derived from the spans; check it says the same thing
        for k in range(nt):
            vstart, end, virt, tlen, doff = SPAN.unpack_from(blob, toff + k * SPAN.size)
            s = next(s for s in e.spans if s.virt == virt and s.tail)
            assert (vstart, end, tlen, blob[doff:doff + tlen]) == (s.virt, s.end, s.tail, s.data[s.head:])
        out.append(e)
    return out


class Model:
    """Reference semantics of the exe hook, one fetch at a time."""

    def __init__(self, entry: "Entry | None", image: bytes):
        self.entry = entry
        self.image = image

    def fetch(self, pc: int) -> "tuple[int, int]":
        """``(byte, next pc)`` exactly as the hooked engine would see them."""
        e = self.entry
        if e is not None:
            if pc >= e.image_end:
                for s in e.spans:                       # the hook binary-searches; same answer
                    if s.tail and s.virt <= pc < s.vend:
                        k = pc - s.virt
                        return s.data[s.head + k], (s.end if k + 1 == s.tail else pc + 1)
            else:
                for s in e.spans:
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
