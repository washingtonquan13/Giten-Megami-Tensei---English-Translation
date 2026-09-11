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


#: Openings of every note part this module generates.  Anything matching one of
#: these is re-derived on each extract and must not be carried forward from the
#: previous table, or a marker that has stopped applying sticks forever.
#:
#: A note is joined with ``"; "`` and split on the same string, so a generated
#: note of two clauses arrives here as **two** parts and both halves need an
#: entry.  They did not have one until 2026-09-11, which is why rows carried
#: "copied verbatim" and "editable because nothing here branches" long after the
#: sentences they came from had been rewritten.
_GENERATED_NOTE_PREFIXES = (
    "record is not editable",
    "record does not tile",
    "record tiles only to byte",
    "record's last token reads",
    "container's record count word",
    "two records share this id",
    "this container installs record",
    "record reaches an engine no-op",
    script.NO_OVERLAY_PREFIX,
    "reads: ",
    "menu option, declared width",
    "fixed ",
    # second halves of the above
    "copied verbatim",
    "read-only, copied verbatim",
    "this span is verified in-bounds",
    "spans are complete and overlay-safe",
    "editable, but verify this file in game",
    "editable because nothing here branches",     # the pre-2026-09-11 wording
    "the loader keeps the last copy",
    "these are the bytes of the earlier one",
    "verify in game",
)


#: Markers this module derives from the record each time.  Anything else that
#: starts with "@" is a persistent annotation written by another pass and must
#: survive a re-extract -- ``@refalign``/``@refalign-joined``/``@refalign-merged``
#: record which rows refalign placed and how, and blanket-dropping every "@" part
#: destroyed 11,100 of them on 2026-09-06 before this was noticed.
_GENERATED_MARKERS = frozenset({
    script.NOEDIT_NOTE, script.UNTILED_NOTE, script.DUPID_NOTE,
    script.PARTIAL_NOTE, script.PREFIX_NOTE, script.STRADDLE_NOTE,
})


def _generated(part: str) -> bool:
    part = part.strip()
    return part in _GENERATED_MARKERS or part.startswith(_GENERATED_NOTE_PREFIXES)


def _prefill(jp: str) -> str:
    """Pre-fill ``en`` when the source already reads as English."""
    return "" if codec.has_japanese(jp) else jp


#: The losing copy of a repeated record id.  Its rows exist so the bytes can be
#: read, and they must never be keyed like the winner's -- ``('m/MS6012.BIN',
#: '4:14', 0)`` named two different rows until 2026-09-11, so ``tables.read``
#: kept whichever came last and ``stale_rows``/``plan`` compared the survivor
#: against the other record's spans.
LOSER_SUFFIX = "~"

#: On the **head** of a span a branch target cut in two: this row's English was
#: written for the whole line, before the split, and someone has to decide how
#: much of it belongs here and how much on the tail.  ``check`` reports it as
#: ``split-pending``.  Written once, by the extract that performs the split, and
#: carried forward like any other human note.
SPLIT_NOTE = "@split:"

#: On every **tail**: which row it continues.  Re-derived from the spans on each
#: extract, so it follows the head's index when numbering moves.
SPLIT_TAIL_NOTE = "@split-tail of"


def _rec_key(rec, key: str) -> str:
    """The table's ``rec`` column for a record: ``0:3A``, or ``0:3A~``."""
    return key + LOSER_SUFFIX if rec.dup_loser else key


def script_rows(rel: str, sc: script.Script, pools) -> "list[tables.Row]":
    rows = []
    for rec in sc.iter_records():
        # A straddling record is `untiled` for every other consumer -- it must
        # never be byte-rebuilt -- but its spans are fully determined, so take
        # them before the untiled branch claims the record.
        if rec.untiled and rec.blocked == script.STRADDLE_NOTE and rec.spans:
            pass
        elif rec.untiled:
            if not rec.data:
                continue
            jp = script.untiled_text(rec)
            if not jp.strip():
                continue
            rows.append(tables.Row(
                rel, _rec_key(rec, rec.key), 0, 0, UNTILED_TAG,
                jp.replace("\t", " "), "",
                note=_note([script.NOEDIT_NOTE, script.UNTILED_NOTE,
                       "record does not tile (%s); read-only, copied verbatim"
                       % rec.tile_error])))
            continue
        for sp in rec.spans:
            jp = script.span_text(rec, sp)
            notes = []
            if rec.no_overlay:
                # The overlay will refuse this row, so the table has to say so:
                # `check`'s `editable` rule keys on @noedit, and a row nobody can
                # serve must not look translatable.  One predicate
                # (`script._mark_overlay_refusals`), so the two cannot disagree.
                notes.append(script.NOEDIT_NOTE)
                notes.append(rec.no_overlay)
            if rec.blocked == script.STRADDLE_NOTE:
                # Also deliberately NOT @noedit.  The record tiles *completely*;
                # only its last token continues into the next record, which the
                # engine does legally (contiguous records, unbounded byte fetch).
                # Every span here is therefore fully determined and safe to
                # overlay -- safer than the @prefix case, which needs a kernel.
                # The byte builder still refuses it via ``rec.blocked``.
                notes.append(script.STRADDLE_NOTE)
                notes.append("record's last token reads %d byte(s) into the next "
                             "record; spans are complete and overlay-safe, but "
                             "the record must never be byte-rebuilt"
                             % rec.straddle)
            elif rec.blocked:
                if script.NOEDIT_NOTE not in notes:
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
                                 "the loader keeps the last copy (measured), so "
                                 "the layout is known and this is advisory")
            if sp.split_head is not None:
                # The second (or third) half of a line a branch lands inside.
                # It gets no English of its own at extract time; see the `@split`
                # migration in `run`.
                notes.append("%s [%d]" % (SPLIT_TAIL_NOTE, sp.split_head))
            if sp.cut_inside is not None:
                notes.append("a branch in this record lands at +0x%04X, inside "
                             "this span and not on a token boundary, so the "
                             "overlay refuses it" % sp.cut_inside)
            if rec.unimplemented:
                notes.append("record reaches an engine no-op opcode; verify in game")
            if pool.has_calls(jp):
                # `jp` stays byte-faithful, so a macro call reads as {08:25}.
                # The note carries the same line with every call expanded --
                # what a Japanese reader actually sees on screen.
                notes.append("reads: " + pool.reading(jp, pools))
            if sp.is_choice and sp.choice_width:
                notes.append("menu option, declared width %d columns" % sp.choice_width)
            row = tables.Row(rel, _rec_key(rec, sp.rec_key), sp.idx,
                             sp.off, sp.tag, jp, _prefill(jp), note=_note(notes))
            row.split_head = sp.split_head
            rows.append(row)
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
        text_dir: "str | None" = None, quiet: bool = False,
        only: "list[str] | None" = None) -> dict:
    """Re-extract ``family`` into ``text_dir``.

    ``only`` is a list of ``fnmatch`` patterns against the ``dir/FILE.BIN`` key,
    exactly as ``build_v2.run`` takes: a file that does not match is not read and
    its table is not rewritten, so a change that can only affect a named handful
    of files can be shown to have touched only those tables.
    """
    text_dir = text_dir or text_v2_dir()
    pools = pool.load(root)
    fams = files.expand_family(family)
    wanted = None
    if only:
        import fnmatch
        wanted = [rel for rel in files.iter_files(fams, root)
                  if any(fnmatch.fnmatch(rel, pat) for pat in only)]
        # One table may hold several files (``p/_P_NAMES``).  Rewriting it from
        # a subset would silently drop the rest, so refuse instead.
        picked = {files.table_path(rel, text_dir) for rel in wanted}
        clash = [rel for rel in files.iter_files(fams, root)
                 if rel not in set(wanted)
                 and files.table_path(rel, text_dir) in picked]
        if clash:
            raise ValueError("--only would rewrite %s, which also holds %s"
                             % (files.table_path(clash[0], text_dir), clash[0]))

    by_table, order = {}, []
    splits: "list[tuple]" = []
    st = {"files": 0, "rows": 0, "tables": 0, "untiled": 0, "blocked": 0,
          "nonscript": 0, "reanchored": 0, "unanchored": 0, "split": 0}

    for rel in (wanted if wanted is not None else files.iter_files(fams, root)):
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
        old_rows = tables.read(path)
        old = {r.key: r for r in old_rows}
        # Span numbering is a property of the tokenizer, so it moves whenever the
        # opcode model improves -- and a table is addressed by span index.
        # Carrying `en` forward on the index alone would put a translation on a
        # neighbouring line, silently.  (1F 0D/0E/0F, 2026-09-06: two records
        # renumbered and five translations would have slid by one.)  `jp` is the
        # row's fingerprint: if it still matches, the index is trustworthy; if it
        # does not, re-anchor on the Japanese, and only when that is unambiguous.
        # build_v2.stale_rows protects the *builder* the same way.
        by_content: "dict[tuple, list]" = {}
        by_rec: "dict[str, list]" = {}
        for o in old_rows:
            if o.en or o.ref_en or o.status:
                by_content.setdefault((o.rec, o.jp), []).append(o)
                by_rec.setdefault(o.rec, []).append(o)
        for r in rows:
            prev = old.get(r.key)
            if prev is None or prev.jp != r.jp:
                # Either the index moved under this line, or the record grew and
                # this index did not exist before.  Both are answered the same
                # way: find the old row whose Japanese is this row's, and only
                # when that is unambiguous.
                # The losing copy of a duplicate id was keyed like the winner
                # until 2026-09-11 and is keyed `<rec>~` now, so look under both
                # -- otherwise every such row loses its reference translation on
                # the extract that renames it.
                cands = (by_content.get((r.rec, r.jp))
                         or by_content.get((r.rec.rstrip(LOSER_SUFFIX), r.jp))
                         or [])
                # "Unambiguous" means the candidates *agree*, not that there is
                # only one of them.  A record often repeats a line verbatim --
                # the same narration for each party member, say -- and every
                # copy carries the same English, so refusing on count alone
                # threw away hundreds of translations that were never in doubt.
                # Disagreement is still refused: that is a real ambiguity.
                picked = None
                if cands:
                    vals = {(c.en, c.ref_en, c.status) for c in cands}
                    if len(vals) == 1:
                        picked = cands[0]
                if picked is None and r.split_head is None:
                    # A span that a branch target has just cut in two.  The head
                    # is what is left of the old row's Japanese, so its `jp` is a
                    # proper prefix of exactly one old `jp` in the same record;
                    # give it that row's English and say where it came from.  The
                    # tail deliberately gets nothing: the old English translates
                    # the whole line, and putting it on the tail would print the
                    # line twice on the jump path.  On screen this is what
                    # shipped before -- English if you read through, Japanese if
                    # you jump -- until the pair is re-authored.
                    split = [o for o in by_rec.get(r.rec, ())
                             if len(o.jp) > len(r.jp) and o.jp.startswith(r.jp)]
                    if len(split) == 1:
                        picked = split[0]
                        r.note = _note([r.note, SPLIT_NOTE + " was " + picked.jp])
                        st["split"] += 1
                        splits.append((r, picked, rows))
                if prev is not None:            # there *was* a row here
                    st["reanchored" if picked else "unanchored"] += 1
                prev = picked
            if prev is None:
                continue
            if prev.en and prev.en != prev.jp:
                r.en = prev.en                  # a real translation survives
            elif prev.en:
                r.en = r.jp                     # a stale pre-fill: refresh it
            # ref_en / ref_src / status were never carried at all, so every
            # re-extract used to drop 35,000 reference translations on the floor
            if prev.ref_en and not r.ref_en:
                r.ref_en, r.ref_src = prev.ref_en, prev.ref_src
            if prev.status and not r.status:
                r.status = prev.status
            if prev.note and prev.note != r.note:
                # Carry a human's own note forward, never a generated marker.
                # A marker can stop applying -- a record that used to be
                # `@noedit` because it would not tile now tiles -- and carrying
                # the old one left the row saying both "@straddle, overlay-safe"
                # and "@noedit, not editable", which kept 81 rows locked that the
                # extractor had just unlocked.
                extra = [p for p in prev.note.split("; ")
                         if p and p not in r.note and not _generated(p)]
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
        if st["reanchored"] or st["unanchored"]:
            print("  span numbering moved: %d row(s) re-anchored on their "
                  "Japanese, %d could not be matched and kept nothing"
                  % (st["reanchored"], st["unanchored"]))
    if splits:
        st["split_report"] = write_split_report(splits)
        if not quiet:
            print("  %d row(s) split at a branch target; the head kept the old "
                  "English and the tail is empty.  %s"
                  % (st["split"], os.path.relpath(st["split_report"],
                                                  paths.REPO_ROOT)))
    return st


SPLIT_REPORT = os.path.join(paths.BUILD_DIR, "split-report.tsv")


def write_split_report(splits, path: str = SPLIT_REPORT) -> str:
    """One line per (head, tail) pair a branch target created, for the translator.

    The head carries the old row's English, which translates the *whole* line;
    the tail is empty on purpose, because putting the whole line on it would
    print it twice on the jump path.  Re-authoring the pair is a reading job, and
    this is the worklist for it.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ["file\trecord\thead_idx\ttail_idx\tjp_head\tjp_tail\told_en"]
    for head, old, rows in splits:
        tails = [r for r in rows
                 if r.rec == head.rec and r.file == head.file
                 and r.split_head == head.idx]
        for t in tails or [None]:
            lines.append("\t".join([
                head.file, head.rec, str(head.idx),
                "" if t is None else str(t.idx),
                head.jp, "" if t is None else t.jp,
                old.en or old.ref_en or ""]))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path
