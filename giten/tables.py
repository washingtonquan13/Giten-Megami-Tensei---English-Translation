"""Reading and writing the editable text tables.

Format: UTF-8 TSV, LF line endings, one header row, ``#`` comment lines ignored.

    file    rec     idx     off     tag     jp      en      note

``file``   game-relative key, e.g. ``m/MS0000.BIN`` (redundant in a per-file
           table, but it makes ``grep`` across ``text/`` self-describing and lets
           the ``p/`` family share one table).
``rec``    frame identity -- ``AA#7`` for record 7 (id 0xAA) of a record pool,
           ``-`` for a file with no record framing.
``idx``    index of the span within its frame.  ``(file, rec, idx)`` is the row
           identity and is stable across re-extraction; merge on it.
``off``    byte offset of the span in the decoded body.  Informational only.
``tag``    ``1FD3``, ``1FB2``, ``DATA``, ``NAME``, ...
``jp``     the source text, dictionary-expanded and escaped (see :mod:`.tokens`).
``en``     the translation.  Empty, or equal to ``jp``, means "use the source
           bytes unchanged".
``note``   free-form; the extractor pre-fills warnings here.

No column may contain a raw tab, CR or LF -- :mod:`.tokens` escapes all three.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

COLUMNS = ("file", "rec", "idx", "off", "tag", "jp", "en", "ref_en", "ref_src", "status", "note")

HEADER_COMMENT = (
    "# Giten Megami Tensei translation table -- see docs/pipeline.md\n"
    "# Edit the 'en' column only.  Leave it empty (or equal to 'jp') to keep the\n"
    "# original bytes.  Escapes: \\n newline, <wait> page-wait, {XX} control byte\n"
    "# (keep them, in order), \\\\ \\{ \\< literal backslash / brace / angle.\n"
)


@dataclass
class Row:
    file: str
    rec: str
    idx: int
    off: int
    tag: str
    jp: str
    en: str = ""
    ref_en: str = ""      # a candidate translation, never applied by the builder
    ref_src: str = ""     # where it came from: ours / v005
    status: str = ""      # "" | draft | reviewed -- required once en is set
    note: str = ""

    @property
    def key(self) -> "tuple[str, str, int]":
        return (self.file, self.rec, self.idx)

    @property
    def edited(self) -> bool:
        """Does this row change anything?  An ``en`` equal to ``jp`` is a no-op."""
        return bool(self.en) and self.en != self.jp

    def to_tsv(self) -> str:
        cells = [self.file, self.rec, str(self.idx), str(self.off), self.tag,
                 self.jp, self.en, self.ref_en, self.ref_src, self.status, self.note]
        for c in cells:
            if "\t" in c or "\n" in c or "\r" in c:
                raise ValueError("un-escaped whitespace in row %r" % (self.key,))
        return "\t".join(cells)


def write(path: str, rows: "list[Row]") -> None:
    """Write a table.  Every row is serialised *before* the file is opened, so
    a bad row raises without touching the file (a half-written table once
    silently lost 350 rows)."""
    lines = [r.to_tsv() for r in rows]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="
") as fh:
        fh.write(HEADER_COMMENT)
        for line in lines:
            fh.write(line + "
")


def read(path: str) -> "list[Row]":
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.rstrip("\n").rstrip("\r")
            if not line or line.startswith("#"):
                continue
            cells = line.split("\t")
            if cells[0] == "file":
                continue                     # header row
            if len(cells) == 8:
                # the old 8-column layout (old/text*): note was the last cell
                cells = cells[:7] + ["", "", ""] + cells[7:]
            if len(cells) < len(COLUMNS):
                cells += [""] * (len(COLUMNS) - len(cells))
            elif len(cells) > len(COLUMNS):
                raise SystemExit("%s:%d: %d columns, expected %d"
                                 % (path, lineno, len(cells), len(COLUMNS)))
            try:
                idx, off = int(cells[2]), int(cells[3])
            except ValueError:
                raise SystemExit("%s:%d: non-numeric idx/off" % (path, lineno))
            rows.append(Row(cells[0], cells[1], idx, off, cells[4],
                            cells[5], cells[6], cells[7], cells[8], cells[9], cells[10]))
    return rows


def read_for(rel: str, path: str) -> "dict[tuple[str, int], Row]":
    """Rows of ``path`` belonging to game file ``rel``, keyed by ``(rec, idx)``."""
    out = {}
    for r in read(path):
        if r.file == rel:
            out[(r.rec, r.idx)] = r
    return out


#: Sub-directories of a text tree that hold game-file tables.  Anything else --
#: ``tables/exe/strings.tsv`` is the one that exists -- belongs to a different
#: tool with a different column set, and walking into it made ``check`` abort
#: with "11 columns, expected 8" before it had looked at a single game file.
GAME_DIRS = frozenset({"m", "et", "p"})


def iter_tables(text_dir: str):
    """Yield every game-file ``.tsv`` under ``text/``.

    Only tables that sit in a :data:`GAME_DIRS` sub-directory are game-file
    tables; other tools keep their own tables in the same tree.
    """
    for base, _dirs, names in os.walk(text_dir):
        if os.path.basename(base) not in GAME_DIRS:
            continue
        for n in sorted(names):
            if n.endswith(".tsv"):
                yield os.path.join(base, n)
