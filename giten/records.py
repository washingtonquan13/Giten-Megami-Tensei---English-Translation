"""The record layer that lives inside a container body.

Verified model (``docs/format-notes.md`` §0 / §2.6, engine 0x43AA90 / 0x43AB10 /
0x43AA30)::

    body   := u16 record_count , record * record_count
    record := u8 id , u16 len , len bytes                       (len != 0xFFFF)
            | u8 id , 0xFFFF , u8 cond , u8 param , u16 len , len bytes

The ``0xFFFF`` form is a *conditional* record; none occur in the shipped data
(measured: 0 of 20 226), but the parser understands them so a future one is not
silently mis-framed.

Runtime buffer (0x43AA30, 0x500 bytes)::

    0x000..0x3FF   256 entries of { u16 data_offset, u16 length }
    0x400..0x4FF   256 zero bytes -- every absent record is one 0x00

Records are copied into the blob **in id order, not file order**, and the script
PC is a u16 offset into that whole buffer.  So::

    base(id) = 0x400 + sum(length(j) for j < id)      length(j) = 1 when absent

That is the coordinate space every ``rel16`` branch is measured in, which is why
:mod:`.relocate` needs it and why changing a record's length shifts every record
with a higher id.

One container per image -- true for m/MS00xx, FALSE for m/MS6xxx
----------------------------------------------------------------
51 files hold 16 containers each (``m/MS6xxx``, ``et/ID*``).  Record ids
**repeat** across the containers of such a file (measured: 35 files have
duplicate ids), so the containers cannot all be installing into one 256-entry
index -- they would overwrite each other.  Each container is therefore its own
runtime image, and ``0x43AA90`` does load exactly one container per call.
Branch relocation never crosses a container boundary.

What does not follow, and what this file wrongly concluded until 2026-09-07, is
that one container equals one *file*.  ``0x0040EB00`` calls ``0x0043AA90``
sixteen times on one open file -- once per container slot -- and ``0x0040EB70``
calls ``0x0040EB00`` up to five times with **different files**, merging them
into the same sixteen buffers::

    0x0040EB00(row, 0x6000, kind 9, slots 0..15)     # m/MS6000, always
    t = table[id * 3]                                # et/ET0007.BIN, 25 rows
    0x0040EB00(row, 0x6000 + t[0], 9, 0..15)         # each unless 0xFF
    0x0040EB00(row, 0x6000 + t[1], 9, 0..15)
    0x0040EB00(row, 0x6100 + t[2], 9, 0..15)
    0x0040EB00(row, [row + 0x38], kind 14, 0..15)    # et/ID%04X.BIN

``0x0043ABC0`` installs each record by id and resizes the buffer by
``new_len - old_len``, so a later file **replaces** an earlier one's record and
shifts every record with a higher id.  ``0x0040EB57`` stamps the descriptor's
id with ``slot - 0x20``, which is why the engine reports these images as file
ids ``0xE0..0xEF`` and no filename maps to them.

The image is therefore not a static property of any one file, and it is not
fully static at all: for slot 0 the merge accounts for 12 of the 15 index
entries a play session logged, and the three it misses are one record (0x97,
976 bytes at runtime against 82 on disk) plus the two it displaces.  See
``tests/test_negotiation_image.py``, which pins all of this.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import container

INDEX_SIZE = 0x400          # the 256-entry {offset, length} table
ABSENT_LEN = 1              # an absent record is a single 0x00


class RecordError(ValueError):
    pass


@dataclass
class Record:
    id: int
    data: bytes
    cond: "int | None" = None
    param: "int | None" = None
    order: int = 0          # position within the container, as stored

    @property
    def header_len(self) -> int:
        return 7 if self.cond is not None else 3

    @property
    def stored_len(self) -> int:
        return self.header_len + len(self.data)


@dataclass
class Body:
    """One container body, parsed into records.

    ``count`` is the declared record-count word, preserved **verbatim**.  It is
    normally ``len(records)``, but four shipped files disagree -- ``m/MS600A``
    container 4 declares 217 records in a body that holds exactly 163, and
    ``et/ID00A2`` / ``et/ID00A3`` declare 169 where 1 fits.  The engine's loop is
    ``for i in range(count)``, so it would read past the container into the next
    one; nothing here can fix that, and rewriting the word would only change
    which garbage it reads.  It is copied through and the body is flagged
    ``short_count``.

    ``tail`` is whatever follows the last record (``m/MS610B`` container 15 has
    4 158 such bytes).  Also copied through verbatim.
    """

    count: int
    records: "list[Record]"
    tail: bytes = b""
    short_count: bool = False
    error: "str | None" = None


def parse_body(body: bytes) -> Body:
    """Parse one decrypted container body into records, tolerantly.

    Stops at the end of the body rather than trusting ``count``, and keeps any
    trailing bytes, so the four odd files above still frame correctly.  A record
    header that *straddles* the end of the body is a real failure and is
    reported.
    """
    if len(body) < 2:
        return Body(0, [], b"", False, "body shorter than the record count word")
    count = int.from_bytes(body[0:2], "little")
    p = 2
    out: "list[Record]" = []
    n = len(body)
    for k in range(count):
        if p >= n:
            break                            # body exhausted before `count` records
        if p + 3 > n:
            return Body(count, out, b"", True,
                        "record %d header straddles the end of the body" % k)
        rid = body[p]
        ln = int.from_bytes(body[p + 1:p + 3], "little")
        cond = param = None
        hl = 3
        if ln == 0xFFFF:
            if p + 7 > n:
                return Body(count, out, b"", True,
                            "conditional record %d header straddles the end" % k)
            cond, param = body[p + 3], body[p + 4]
            ln = int.from_bytes(body[p + 5:p + 7], "little")
            hl = 7
        if p + hl + ln > n:
            return Body(count, out, b"", False,
                        "record %d (id 0x%02X) overruns the body" % (k, rid))
        out.append(Record(rid, body[p + hl:p + hl + ln], cond, param, k))
        p += hl + ln
    return Body(count, out, body[p:], len(out) != count, None)


def is_record_layer(bodies: "list[Body]") -> bool:
    """Do these container bodies really hold a record list?

    The tolerant parse above will happily "succeed" on a body it does not
    understand -- ``m/M0000.BIN`` decodes to a count word of 0 followed by 6 006
    bytes of map geometry, which is zero records and a very long tail.  Two
    conditions separate a real record list from that:

    * at least one record somewhere in the file, and
    * no container that has a tail *and* no records -- i.e. every container
      either is a record list or is the empty ``count = 0`` placeholder that the
      16-container files use for unused slots.

    Applied across the corpus this accepts exactly ``m/MS*`` (200 of 200) and
    ``et/ID*`` (17 of 17) -- the two families the format notes identify as script
    records -- and rejects ``m/M*``, ``et/CA*``, ``et/ET*`` and ``p/P*``.  It is
    two files better than the strict reading in the notes (§0), which rejected
    ``m/MS600A`` / ``m/MS610B`` / ``et/ID00A2`` / ``et/ID00A3`` over a record
    count word that overstates its own body.
    """
    if any(b.error for b in bodies):
        return False
    if not any(b.records for b in bodies):
        return False
    return not any(b.tail and not b.records for b in bodies)


def parse(body: bytes) -> "tuple[list[Record], int, str | None]":
    """Back-compatible view of :func:`parse_body`: ``(records, end, error)``."""
    b = parse_body(body)
    end = len(body) - len(b.tail) if b.error is None else 0
    return b.records, end, b.error


def serialise_body(b: Body) -> bytes:
    """A :class:`Body` -> container bytes, count word and tail kept verbatim."""
    out = bytearray((b.count & 0xFFFF).to_bytes(2, "little"))
    _emit(out, b.records)
    out += b.tail
    return bytes(out)


def serialise(records: "list[Record]") -> bytes:
    """Records -> a container body with a freshly computed count word."""
    out = bytearray(len(records).to_bytes(2, "little"))
    _emit(out, records)
    return bytes(out)


def _emit(out: bytearray, records: "list[Record]") -> None:
    for r in records:
        if not 0 <= r.id <= 0xFF:
            raise RecordError("record id 0x%X out of range" % r.id)
        if len(r.data) > 0xFFFE:
            raise RecordError("record 0x%02X is %d bytes, the u16 length field "
                              "holds at most 0xFFFE" % (r.id, len(r.data)))
        out.append(r.id)
        if r.cond is not None:
            out += b"\xff\xff" + bytes([r.cond, r.param])
        out += len(r.data).to_bytes(2, "little")
        out += r.data


def bases(records: "list[Record]") -> "dict[int, int]":
    """``{record id: runtime offset}`` for one container's records.

    Every id 0..255 gets an entry; ids with no record are one byte long, which
    is what the loader pre-initialises them to.  Duplicate ids inside a single
    container would be ambiguous; the first one wins and the caller is expected
    to have reported the duplicate.
    """
    have = {}
    for r in records:
        have.setdefault(r.id, len(r.data))
    off = INDEX_SIZE
    out = {}
    for i in range(256):
        out[i] = off
        off += have.get(i, ABSENT_LEN)
    return out



# --- whole-file convenience -------------------------------------------------
@dataclass
class FileImage:
    """Every container of one ``.BIN``, parsed into records."""

    rel: str
    raw: bytes
    containers: "list[list[Record]]"
    ok: bool
    error: "str | None" = None
    bodies: "list[Body]" = None

    def iter_records(self):
        for ci, recs in enumerate(self.containers):
            for r in recs:
                yield ci, r


def load(rel: str, raw: bytes) -> FileImage:
    """Parse a ``.BIN`` into containers of records.

    ``ok`` is False (with ``error`` set) when either the container chain does not
    land on EOF or a container's body is not a record list -- the 890 files of
    the ``m/M*``, ``et/CA*``, ``et/ET*`` and ``p/P*`` families, which put a
    different structure inside the same container.  Those are copied through
    verbatim by the v2 builder.
    """
    conts, end = container.split(raw)
    if not conts or end != len(raw) or any(c.short for c in conts):
        return FileImage(rel, raw, [], False, "not a clean container chain")
    bodies = [parse_body(c.body) for c in conts]
    bad = next((b for b in bodies if b.error), None)
    if bad is not None:
        return FileImage(rel, raw, [], False, bad.error)
    if not is_record_layer(bodies):
        return FileImage(rel, raw, [], False, "no record layer in this file")
    img = FileImage(rel, raw, [b.records for b in bodies], True)
    img.bodies = bodies
    return img




def layout_is_ambiguous(recs: "list[Record]") -> bool:
    """Does a duplicate record id leave this container's runtime layout undecided?

    A container may hold two records with the same id.  :func:`bases` and
    :func:`overlay.engine_index` both take the **first**, but which one the
    loader actually keeps has never been observed, so the honest question is not
    "is there a duplicate" -- it is whether the answer would change anything.

    It only can when the copies differ in length: the image is laid out by id,
    so keeping a 24-byte record instead of a 4-byte one shifts every later id.
    Two copies of the same length leave every base identical either way and
    there is nothing to be ambiguous about.

    Measured over the corpus, this matters both ways.  `m/MS6000` c0 and c1
    duplicate ids whose copies are one byte each and identical -- **0 of 256
    bases differ** -- yet were blocked, holding 502 characters and 109 finished
    translations.  `m/MS6012` c4 duplicates a 12-byte record with a 28-byte one
    -- **235 of 256 bases differ, by up to 16 bytes** -- and was *not* blocked,
    because the old test asked whether the container contained a `rel16`.  That
    is the wrong question: an overlay span's runtime address is
    ``base(id) + offset`` whether or not anything branches.
    """
    by_id = {}
    for r in recs:
        by_id.setdefault(r.id, []).append(r)
    dups = [v for v in by_id.values() if len(v) > 1]
    if not dups:
        return False
    # Same length but different bytes would leave the *content* at that base
    # undecided even though the layout is fine.  No such case exists in the
    # corpus today, but the predicate has to be right, not merely lucky.
    if any(len({bytes(x.data) for x in v}) > 1 and len({len(x.data) for x in v}) == 1
           for v in dups):
        return True
    first = bases(recs)
    have = {}
    for r in recs:
        have[r.id] = len(r.data)                  # last wins
    off, last = INDEX_SIZE, {}
    for i in range(256):
        last[i] = off
        off += have.get(i, ABSENT_LEN)
    return first != last
