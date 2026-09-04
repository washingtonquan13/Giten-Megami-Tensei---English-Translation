"""Read/write ``text_v2/exe/strings.tsv``.

TSV, UTF-8, one header row.  Text columns are escaped so a row is always
exactly one physical line: backslash, tab, CR and LF become ``\\\\``, ``\\t``,
``\\r``, ``\\n``.  Control bytes below 0x20 (status-table record ids) become
``\\xNN``.
"""
from __future__ import annotations

import io
import os

COLUMNS = [
    "id",
    "file_off",
    "va",
    "section",
    "slot_bytes",
    "refs",
    "record_width",
    "max_cols",
    "jp",
    "en",
    "note",
]


def esc(s: str) -> str:
    out = []
    for c in s:
        if c == "\\":
            out.append("\\\\")
        elif c == "\t":
            out.append("\\t")
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append("\\r")
        elif ord(c) < 0x20 or ord(c) == 0x7F:
            out.append("\\x%02x" % ord(c))
        else:
            out.append(c)
    return "".join(out)


def unesc(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= len(s):
            out.append("\\")
            break
        k = s[i]
        if k == "\\":
            out.append("\\")
        elif k == "t":
            out.append("\t")
        elif k == "n":
            out.append("\n")
        elif k == "r":
            out.append("\r")
        elif k == "x":
            out.append(chr(int(s[i + 1:i + 3], 16)))
            i += 2
        else:
            raise ValueError("bad escape \\%s in %r" % (k, s))
        i += 1
    return "".join(out)


class Row(dict):
    """One table row.  Ints are parsed lazily via the helpers below."""

    @property
    def off(self):
        return int(self["file_off"], 16)

    @property
    def va(self):
        return int(self["va"], 16)

    @property
    def slot(self):
        return int(self["slot_bytes"])

    @property
    def record_width(self):
        v = self["record_width"].strip()
        return int(v) if v else 0

    @property
    def max_cols(self):
        v = self["max_cols"].strip()
        return int(v) if v else 0

    @property
    def refs(self):
        v = self["refs"].strip()
        return [int(x, 16) for x in v.split(",") if x]

    @property
    def jp(self):
        return unesc(self["jp"])

    @property
    def en(self):
        return unesc(self["en"])

    @property
    def note(self):
        return self["note"]

    def has_flag(self, flag):
        return flag in self["note"]

    def capacity(self):
        """Bytes writable at the row's home location, terminator included."""
        rw = self.record_width
        return min(rw, self.slot) if rw else self.slot


def load(path):
    rows = []
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        header = fh.readline().rstrip("\r\n").split("\t")
        if header != COLUMNS:
            raise ValueError("unexpected header %r" % (header,))
        for lineno, line in enumerate(fh, start=2):
            line = line.rstrip("\r\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != len(COLUMNS):
                raise ValueError("line %d: %d columns, expected %d"
                                 % (lineno, len(parts), len(COLUMNS)))
            r = Row(zip(COLUMNS, parts))
            r["_line"] = lineno
            rows.append(r)
    return rows


def save(path, rows):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            fh.write("\t".join(str(r.get(c, "")) for c in COLUMNS) + "\n")
