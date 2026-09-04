"""``extract --engine v2``: game files -> tables under ``tables/``.

Row identity is ``(file, rec, idx)`` as before, but ``rec`` now names a real
place in the format rather than a guess::

    "0:3A"    container 0, record id 0x3A      (m/MS*, et/ID*)
    "NAME"    the fixed 16-byte name field     (p/P*)

and ``idx`` is the span's index *within that record*.  ``off`` is the span's byte
offset inside the record's data.

What ends up in ``jp``
----------------------
The rendered token stream (:mod:`.codec`): literal text, ``\\n``, ``<wait>``, and
pool calls as ``{01:03}`` / ``{08:1F}`` with their operand folded in.  Operand
bytes are never text.  The v1 artefacts are gone by construction --
``{DICT:92}`` was a resync error and cannot recur, and a leaked condition byte
like ``{0B}ｼ`` is now the opcode ``0B`` (which ends the span) followed by clean
text.

Records that cannot be tiled (``@untiled``) or whose container repeats a record
id (``@dupid``) get rows so their text can be *read*, marked non-editable; the
builder copies them through verbatim.
"""
from __future__ import annotations

import os

from . import (codec, container, files, paths, pool, script, spans, tables,
               vmops)

#: ``tables/`` -- the staging directory, kept apart from the ``text/`` tables
#: five translators are editing concurrently.
TEXT_V2_DIRNAME = "tables"

UNTILED_TAG = "UNTILED"
PNAME_REC = "NAME"


def text_v2_dir() -> str:
    return os.path.join(paths.REPO_ROOT, TEXT_V2_DIRNAME)


def _note(parts) -> str:
    return "; ".join(p for p in parts if p)


def _prefill(jp: str) -> str:
    """Pre-fill ``en`` when the source already reads as English."""
    return "" if codec.has_japanese(jp) else jp


def script_rows(rel: str, sc: script.Script, pools) -> "list[tables.Row]":
    rows = []
    for rec in sc.iter_records():
        if rec.untiled:
            if not rec.data:
                continue
            jp = script.untiled_text(rec)
            if not jp.strip():
                continue
            rows.append(tables.Row(
                rel, rec.key, 0, 0, UNTILED_TAG, jp.replace("\t", " "), "",
                note=_note([script.NOEDIT_NOTE, script.UNTILED_NOTE,
                       "record does not tile (%s); read-only, copied verbatim"
                       % rec.tile_error])))
            continue
        for sp in rec.spans:
            jp = script.span_text(rec, sp)
            notes = []
            if rec.blocked:
                notes.append(script.NOEDIT_NOTE)
                notes.append(rec.blocked)
                notes.append("record is not editable; copied verbatim")
            for f in rec.flags:
                notes.append(f)
                if f == script.PARTIAL_NOTE:
                    notes.append("container's record count word disagrees with its "
                                 "body; editable, but verify this file in game")
                elif f == script.DUPID_NOTE:
                    notes.append("two records share this id in one container; "
                                 "editable because nothing here branches")
            if rec.unimplemented:
                notes.append("record reaches an engine no-op opcode; verify in game")
            if pool.has_calls(jp):
                # `jp` stays byte-faithful, so a macro call reads as {08:25}.
                # The note carries the same line with every call expanded --
                # what a Japanese reader actually sees on screen.
                notes.append("reads: " + pool.reading(jp, pools))
            if sp.is_choice and sp.choice_width:
                notes.append("menu option, declared width %d columns" % sp.choice_width)
            rows.append(tables.Row(rel, sp.rec_key, sp.idx, sp.off, sp.tag,
                                   jp, _prefill(jp), note=_note(notes)))
    return rows


def pname_rows(rel: str, raw: bytes) -> "list[tables.Row]":
    """The one fixed-width display-name field of a ``p/P%04X.BIN`` record."""
    conts, end = container.split(raw)
    if not conts or end != len(raw) or conts[0].short:
        return []
    body = conts[0].body
    if len(body) < spans.PNAME_OFF + spans.PNAME_LEN:
        return []
    raw_name = body[spans.PNAME_OFF:spans.PNAME_OFF + spans.PNAME_LEN]
    raw_name = raw_name.split(b"\x00", 1)[0]
    try:
        jp = codec.render(raw_name, vmops.tokenize(raw_name))
    except vmops.TileError:
        return []
    if not jp.strip():
        return []
    return [tables.Row(rel, PNAME_REC, 0, spans.PNAME_OFF, spans.PNAME_TAG,
                       jp, _prefill(jp),
                       note="fixed %d-byte field: at most %d bytes plus a NUL"
                       % (spans.PNAME_LEN, spans.PNAME_LEN - 1))]


def rows_for(rel: str, raw: bytes, pools) -> "list[tables.Row]":
    if rel.startswith("p/"):
        return pname_rows(rel, raw)
    sc = script.parse(rel, raw)
    if not sc.ok:
        return []
    return script_rows(rel, sc, pools)


def run(family: str = "all", root: "str | None" = None,
        text_dir: "str | None" = None, quiet: bool = False) -> dict:
    text_dir = text_dir or text_v2_dir()
    pools = pool.load(root)
    fams = files.expand_family(family)

    by_table, order = {}, []
    st = {"files": 0, "rows": 0, "tables": 0, "untiled": 0, "blocked": 0,
          "nonscript": 0}

    for rel in files.iter_files(fams, root):
        raw = files.read_source(rel, root)
        rows = rows_for(rel, raw, pools)
        st["files"] += 1
        if not rows:
            if not rel.startswith("p/"):
                st["nonscript"] += 1
            continue
        st["rows"] += len(rows)
        st["untiled"] += sum(1 for r in rows if script.UNTILED_NOTE in r.note)
        st["blocked"] += sum(1 for r in rows if script.DUPID_NOTE in r.note)
        path = files.table_path(rel, text_dir)
        if path not in by_table:
            by_table[path] = []
            order.append(path)
        by_table[path].extend(rows)

    for path in order:
        rows = by_table[path]
        old = {r.key: r for r in tables.read(path)}
        for r in rows:
            prev = old.get(r.key)
            if prev is None:
                continue
            if prev.en and prev.en != prev.jp:
                r.en = prev.en                  # a real translation survives
            elif prev.en:
                r.en = r.jp                     # a stale pre-fill: refresh it
            if prev.note and prev.note != r.note:
                extra = [p for p in prev.note.split("; ")
                         if p and p not in r.note]
                if extra:
                    r.note = _note([r.note] + extra)
        tables.write(path, rows)
        st["tables"] += 1
        if not quiet:
            print("%-42s %6d rows" % (os.path.relpath(path, paths.REPO_ROOT),
                                      len(rows)))

    if not quiet:
        print("\n%d rows from %d files into %d tables under %s"
              % (st["rows"], st["files"] - st["nonscript"], st["tables"],
                 os.path.relpath(text_dir, paths.REPO_ROOT)))
        print("  %d rows are @untiled (read-only), %d are @dupid, "
              "%d files have no text layer this pipeline understands"
              % (st["untiled"], st["blocked"], st["nonscript"]))
    return st
