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

One container per image
-----------------------
51 files hold 16 containers each (``m/MS6xxx``, ``et/ID*``).  Record ids
**repeat** across the containers of such a file (measured: 35 files have
duplicate ids), so the containers cannot all be installing into one 256-entry
index -- they would overwrite each other.  Each container is therefore treated
as its own runtime image, which is also what ``0x43AA90`` does: it loads exactly
one container per call.  Branch relocation never crosses a container boundary.
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


def image_size(records: "list[Record]") -> int:
    b = bases(records)
    have = {}
    for r in records:
        have.setdefault(r.id, len(r.data))
    return b[255] + have.get(255, ABSENT_LEN)


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


def rebuild(image: FileImage, new_containers: "list[list[Record]]") -> bytes:
    """Records -> a complete ``.BIN``, header words and cipher seeds recomputed."""
    if len(new_containers) != len(image.containers):
        raise RecordError("%s: container count changed (%d -> %d)"
                          % (image.rel, len(image.containers), len(new_containers)))
    return container.join([serialise(recs) for recs in new_containers])
