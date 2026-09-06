"""The race / lineage / title tables in ``et/ET0000.BIN``.

The status screen's "Race" and "Title" lines are not in the exe -- they are
four small string tables bundled into ``et/ET0000.BIN``.  The loader at
``0x0040FF30`` opens the file once and calls ``0x00401C30`` **six times**, once
per container, storing the six handles at ``ds:0x0047B0D0``..\\ ``0x0047B0E4``::

    container 0  1730 bytes  binary, not touched here
    container 1    51 bytes  race index -> group index, one byte each
    container 2   393 bytes  51 races      (人 = Human is index 33)
    container 3   303 bytes  23 lineages   (X神族, the pantheon a demon belongs to)
    container 4    53 bytes  7 titles      (愚者 Fool .. 神 God)
    container 5   148 bytes  16 major race groups

Each string container is ``u16 count; u16 offset[count]; strings``, and the
accessors (e.g. ``0x00410180`` for the titles) read it exactly that way::

    mov eax,[0x47B0E0] ; call 0x404680      ; handle -> base
    movsx ecx,word [esp+8]                  ; index
    mov dx, word [eax+ecx*2+2]              ; offset[index], the +2 skips count
    push edx ; push eax ; call 0x40B840     ; base + (offset & 0xFFFF)

Because ``0x00401C30`` sizes its allocation from each container's own ``u16``
header, the containers are self-sizing and the only ceiling is that 16-bit
mask: 65,535 bytes per container against a current maximum of 1,730.  So unlike
the item database (``docs/format-notes.md`` section 6.3) this one needs no exe
patch at all -- the file is simply rebuilt with longer strings.

Widths are in half-width cells.  ``0x00441C30`` picks the title table for a
human and the race table for a demon and draws either through the *same*
``strcpy``-then-draw path with no ``printf`` field width, so both share one
budget: the widest thing the game already draws there, ``イシュタル信者`` at 14.
"""
from __future__ import annotations

import os
import struct

from . import container, paths

TABLE = os.path.join(paths.REPO_ROOT, "tables", "racenames.tsv")

#: container index -> what it holds.  Containers 0 and 1 are binary and are
#: copied through untouched.
KINDS = {2: "race", 3: "lineage", 4: "title", 5: "group"}

#: the loader calls 0x00401C30 exactly this many times, so the count is fixed
CONTAINERS = 6

#: per-container display budget in half-width cells (see the module docstring)
BUDGET = {2: 14, 3: 16, 4: 14, 5: 10}

#: 0x00401C30 allocates from a u16 header and 0x0040B840 masks the offset to
#: 16 bits, so a container may not reach 64 KB
CONTAINER_MAX = 0xFFFF

TABLE_HEADER = ("kind", "index", "jp", "en", "status", "note")


class RaceNameError(RuntimeError):
    pass


def cells(s: str) -> int:
    """Display width in half-width cells."""
    return sum(1 if (ord(c) < 0x80 or 0xFF61 <= ord(c) <= 0xFF9F) else 2 for c in s)


def source(ddswin: str = None) -> bytes:
    return open(os.path.join(ddswin or paths.ORIGINAL_DDSWIN, "et", "ET0000.BIN"), "rb").read()


def split_table(body: bytes) -> "list[str]":
    """``u16 count; u16 offset[count]; strings`` -> the strings."""
    n = struct.unpack_from("<H", body, 0)[0]
    offs = struct.unpack_from("<%dH" % n, body, 2)
    if offs[0] != 2 + 2 * n:
        raise RaceNameError("offset[0] is %d, expected %d" % (offs[0], 2 + 2 * n))
    out = []
    for o in offs:
        e = body.find(b"\x00", o)
        if e < 0:
            raise RaceNameError("unterminated string at %d" % o)
        out.append(body[o:e].decode("cp932"))
    return out


def join_table(strings: "list[str]") -> bytes:
    """The inverse of :func:`split_table`."""
    n = len(strings)
    body = bytearray(struct.pack("<H", n) + b"\x00" * (2 * n))
    for i, s in enumerate(strings):
        # checked here rather than on the finished body: the offset for string
        # i is written before string i is appended, so an overlong table breaks
        # at the first string past the ceiling, not at the end
        if len(body) > CONTAINER_MAX:
            raise RaceNameError("string %d starts at %d; the u16 offsets stop at %d"
                                % (i, len(body), CONTAINER_MAX))
        struct.pack_into("<H", body, 2 + 2 * i, len(body))
        body += s.encode("cp932") + b"\x00"
    if len(body) > CONTAINER_MAX:
        raise RaceNameError("container is %d bytes, the u16 offsets stop at %d"
                            % (len(body), CONTAINER_MAX))
    return bytes(body)


def parse(raw: bytes) -> "dict[int, list[str]]":
    """``{container index: strings}`` for the four string tables."""
    cs = container.split(raw)[0]
    if len(cs) != CONTAINERS:
        raise RaceNameError("ET0000 has %d containers, the loader reads %d"
                            % (len(cs), CONTAINERS))
    return {i: split_table(cs[i].body) for i in KINDS}


def read_table(path: str = TABLE) -> "dict[tuple[str, int], str]":
    """``{(kind, index): english}`` for every row with English."""
    out = {}
    if not os.path.exists(path):
        return out
    for ln in open(path, encoding="utf-8"):
        if ln.startswith("#") or not ln.strip():
            continue
        f = ln.rstrip("\n").split("\t")
        if len(f) < 4 or f[0] == "kind":
            continue
        if f[3].strip():
            out[(f[0], int(f[1]))] = f[3]
    return out


def write_table(raw: bytes, path: str = TABLE) -> int:
    """Refresh the TSV from the original, keeping any English already in it."""
    have = read_table(path)
    tables = parse(raw)
    lines = ["# Giten race / lineage / title tables (et/ET0000.BIN)",
             "# Edit the 'en' column.  Leave it empty to keep the Japanese.",
             "# Budgets in half-width cells: %s" % ", ".join(
                 "%s %d" % (KINDS[i], BUDGET[i]) for i in sorted(KINDS)),
             "\t".join(TABLE_HEADER)]
    n = 0
    for i in sorted(KINDS):
        kind = KINDS[i]
        for j, jp in enumerate(tables[i]):
            lines.append("\t".join([kind, str(j), jp, have.get((kind, j), ""), "", ""]))
            n += 1
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return n


def plan(raw: bytes, english: "dict[tuple[str, int], str]"):
    """``(per-container replacement strings, findings)`` after the checks."""
    tables = parse(raw)
    out, findings = {}, []
    for i in sorted(KINDS):
        kind = KINDS[i]
        rows = list(tables[i])
        for j, jp in enumerate(tables[i]):
            en = english.get((kind, j), "")
            if not en:
                continue
            if cells(en) > BUDGET[i]:
                findings.append((kind, j, "%d cells, the field draws %d: %r"
                                 % (cells(en), BUDGET[i], en)))
                continue
            try:
                en.encode("cp932")
            except UnicodeEncodeError:
                findings.append((kind, j, "not cp932-encodable: %r" % en))
                continue
            rows[j] = en
        out[i] = rows
    return out, findings


def build(raw: bytes, english: "dict[tuple[str, int], str]" = None) -> bytes:
    """The original file with the four string tables rebuilt in English.

    Containers 0 and 1 are copied through byte-for-byte, and the container
    count is unchanged, because the loader hard-codes six reads.
    """
    english = read_table() if english is None else english
    rows, findings = plan(raw, english)
    if findings:
        raise RaceNameError("racenames: %s" % findings[:3])
    cs = container.split(raw)[0]
    bodies = [c.body for c in cs]
    for i, strings in rows.items():
        bodies[i] = join_table(strings)
    return container.join(bodies)
