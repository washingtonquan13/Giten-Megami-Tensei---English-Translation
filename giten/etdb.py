"""Two more offset-table databases: the skills (``ET0004``) and the map
object labels (``ET0101``).

Both are the shape ``itemdb`` already documents -- ``u16 count``, ``u16
offset[count]`` into the container body, then variable-length records reached
only through the table -- but neither needs any of that module's machinery,
because neither has a *type* byte and so neither has a variable header:

``et/ET0004.BIN`` -- the skill / magic database, 309 records::

    20 bytes binary  ||  name \\0  ||  description \\0

    The 20 is fixed and checked: every one of the 309 records splits into
    exactly ``name \\0 desc \\0`` at that offset with no control byte inside
    either string, so there is no jump table to walk the way ``itemdb`` had to.

``et/ET0101.BIN`` -- what the 3D view prints in green when you face something,
96 records::

    \\0  ||  label \\0

    A leading NUL, then the string.  Records 8 and 9 (and others) are a bare
    ``00 00``: an empty slot, kept as an empty label.

**Neither has a cap to lift.** ``ET0001`` needed three separate patches because
it was already at the 64 KB ceiling; these bodies are 18,416 and 588 bytes, and
even a generous English pass leaves both far below the ``u16`` limit that the
offset table and the container header impose. :func:`build` refuses rather than
truncating if that ever stops being true.

So, like ``et/ET0000.BIN`` (``racenames``), the file is simply rebuilt. Nothing
in the exe changes and an unpatched exe still reads the original.
"""
from __future__ import annotations

import io
import os
import struct
from dataclasses import dataclass

from . import container, paths

#: a container body addressed by ``u16`` offsets cannot exceed this
U16_CEILING = 0x10000


class EtDbError(RuntimeError):
    pass


@dataclass
class Spec:
    """How one of these files is laid out and where its table lives."""
    rel: str                 # game file, relative to ddswin/
    header: int              # fixed binary bytes before the first string
    fields: int              # strings per record (name, or name + description)
    table: str               # tables/<name>.tsv
    columns: tuple


SKILLS = Spec("et/ET0004.BIN", 20, 2,
              os.path.join(paths.REPO_ROOT, "tables", "skills.tsv"),
              ("index", "jp_name", "en_name", "jp_desc", "en_desc", "status", "note"))

MAPLABELS = Spec("et/ET0101.BIN", 1, 1,
                 os.path.join(paths.REPO_ROOT, "tables", "maplabels.tsv"),
                 ("index", "jp", "en", "status", "note"))

SPECS = {"skills": SKILLS, "maplabels": MAPLABELS}


@dataclass
class Record:
    index: int
    head: bytes                  # the binary prefix, carried through untouched
    strings: "list[bytes]"       # `fields` of them, raw cp932
    tail: bytes                  # anything after the last NUL, carried through

    def text(self, i: int) -> str:
        try:
            return self.strings[i].decode("cp932")
        except (UnicodeDecodeError, IndexError):
            return ""


def source(spec: Spec, ddswin: "str | None" = None) -> bytes:
    ddswin = ddswin or paths.ORIGINAL_DDSWIN
    path = os.path.join(ddswin, spec.rel.replace("/", os.sep))
    conts, end = container.split(open(path, "rb").read())
    if len(conts) != 1:
        raise EtDbError("%s: %d containers, expected 1" % (spec.rel, len(conts)))
    return conts[0].body


def parse(spec: Spec, body: bytes) -> "list[Record]":
    if len(body) < 2:
        raise EtDbError("%s: body is %d bytes" % (spec.rel, len(body)))
    count = struct.unpack_from("<H", body, 0)[0]
    table_end = 2 + count * 2
    if table_end > len(body):
        raise EtDbError("%s: count %d does not fit the body" % (spec.rel, count))
    offs = [struct.unpack_from("<H", body, 2 + i * 2)[0] for i in range(count)]
    if offs and offs[0] != table_end:
        raise EtDbError("%s: first record at %d, table ends at %d"
                        % (spec.rel, offs[0], table_end))
    if any(a > b for a, b in zip(offs, offs[1:])):
        raise EtDbError("%s: offsets are not monotonic" % spec.rel)

    out = []
    for i in range(count):
        lo = offs[i]
        hi = offs[i + 1] if i + 1 < count else len(body)
        rec = body[lo:hi]
        if len(rec) < spec.header:
            raise EtDbError("%s: record %d is %d bytes, header is %d"
                            % (spec.rel, i, len(rec), spec.header))
        head, rest = rec[:spec.header], rec[spec.header:]
        strings, at = [], 0
        for _ in range(spec.fields):
            j = rest.find(b"\x00", at)
            if j < 0:
                raise EtDbError("%s: record %d has %d strings, expected %d"
                                % (spec.rel, i, len(strings), spec.fields))
            strings.append(rest[at:j])
            at = j + 1
        out.append(Record(i, head, strings, rest[at:]))
    return out


def build(spec: Spec, records: "list[Record]",
          english: "dict[tuple[int, int], str] | None" = None) -> bytes:
    """Rebuild the container body, substituting any English that was given."""
    english = english or {}
    count = len(records)
    blob, offs = bytearray(), []
    at = 2 + count * 2
    for r in records:
        offs.append(at)
        rec = bytearray(r.head)
        for k in range(spec.fields):
            en = english.get((r.index, k))
            raw = r.strings[k] if en is None else en.encode("cp932")
            if b"\x00" in raw:
                raise EtDbError("%s: record %d field %d contains a NUL"
                                % (spec.rel, r.index, k))
            rec += raw + b"\x00"
        rec += r.tail
        blob += rec
        at += len(rec)
    if at > U16_CEILING:
        raise EtDbError("%s: the rebuilt body is %d bytes; the offset table and "
                        "the container header are both u16, so it must stay "
                        "under %d" % (spec.rel, at, U16_CEILING))
    out = bytearray(struct.pack("<H", count))
    for o in offs:
        out += struct.pack("<H", o)
    return bytes(out + blob)


def pack_file(spec: Spec, body: bytes) -> bytes:
    """One container holding ``body``, plus the terminator, as the game reads it."""
    return container.join([body])


# ---------------------------------------------------------------- tables ----

def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def _unesc(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append({"n": "\n", "t": "\t", "\\": "\\"}.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def read_table(spec: Spec) -> "dict[tuple[int, int], str]":
    """``(record index, field) -> English``, only where something was written."""
    if not os.path.exists(spec.table):
        return {}
    out = {}
    with io.open(spec.table, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            cells = line.rstrip("\n").split("\t")
            row = dict(zip(spec.columns, cells))
            idx = int(row["index"])
            if spec.fields == 2:
                for k, col in ((0, "en_name"), (1, "en_desc")):
                    v = _unesc(row.get(col, ""))
                    if v:
                        out[(idx, k)] = v
            else:
                v = _unesc(row.get("en", ""))
                if v:
                    out[(idx, 0)] = v
    return out


def write_table(spec: Spec, records: "list[Record]") -> int:
    """Refresh the table, keeping every English cell already written."""
    old = read_table(spec)
    status = {}
    if os.path.exists(spec.table):
        with io.open(spec.table, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#") or not line.strip():
                    continue
                row = dict(zip(spec.columns, line.rstrip("\n").split("\t")))
                status[int(row["index"])] = (row.get("status", ""), row.get("note", ""))

    lines = ["# %s -- rebuilt by `python -m giten etdb`" % spec.rel,
             "# Edit the en_* cells.  Leave one empty to keep the Japanese.",
             "# " + "\t".join(spec.columns)]
    for r in records:
        st, note = status.get(r.index, ("", ""))
        if spec.fields == 2:
            cells = [str(r.index), _esc(r.text(0)), _esc(old.get((r.index, 0), "")),
                     _esc(r.text(1)), _esc(old.get((r.index, 1), "")), st, note]
        else:
            cells = [str(r.index), _esc(r.text(0)),
                     _esc(old.get((r.index, 0), "")), st, note]
        lines.append("\t".join(cells))
    os.makedirs(os.path.dirname(spec.table), exist_ok=True)
    with io.open(spec.table, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return len(records)
