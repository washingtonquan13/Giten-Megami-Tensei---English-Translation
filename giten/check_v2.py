"""``check --engine v2``: the validators, with the real engine budgets.

Rules
-----
``identity``   building with every ``en`` empty reproduces all 844 source files
               byte-exactly.  Load-bearing: if it fails, nothing else means
               anything.
``decode``     every rebuilt file still decodes under the *engine's* rule --
               the container chain lands on EOF, each header word equals its
               body length (and therefore seeds the cipher the loader will use),
               and every record parses.  Checked with :mod:`.refdecode`, which
               is a separate transcription of the disassembly.
``tile``       every rebuilt record still tiles with the opcode table, and no
               record that tiled before stops tiling.
``encode``     the ``en`` text is legal: cp932-encodable, well-formed escapes,
               and only inline opcode tokens.
``editable``   an ``en`` on a row the builder will not edit (``@noedit``), where
               it would silently do nothing.
``pname``      a ``p/`` name fits its fixed 16-byte field.
``width``      a line exceeds the 74-column message-box budget.
``page-rows``  a page holds more than 4 lines before a ``<wait>``.
``width-choice`` a menu option exceeds the width its ``1F B1`` declares.
``missing``    a non-empty ``jp`` with an empty ``en``.
``tokens``     the ``en`` **adds** a pool call the ``jp`` does not have, naming a
               record nothing has checked exists.  Dropping one is normal and is
               not reported: an English line spells the word out.

``identity``, ``decode``, ``tile``, ``encode``, ``editable`` and ``pname`` are
errors; the width family, ``missing`` and ``tokens`` are warnings, because the
engine auto-wraps rather than clipping (``docs/format-notes.md`` §3.2) and an
over-wide line is cosmetic.
"""
from __future__ import annotations

import collections
import os

from . import findings as check
from . import script
from . import (build_v2, codec, extract_v2, files, paths, pool, refdecode,
               script, tables, vmops, width)

ERROR, WARN = check.ERROR, check.WARN
Report = check.Report

SKIP_MARKERS = check.SKIP_MARKERS + (script.NOEDIT_NOTE,)


# --- (a) identity -----------------------------------------------------------
def check_identity(report: Report, root=None) -> None:
    total = bad = 0
    for rel in files.all_encoded(root):
        raw = files.read_source(rel, root)
        res = build_v2.build_file(rel, raw, [])
        total += 1
        if res.raw != raw:
            bad += 1
            if bad <= 10:
                report.add("identity", ERROR, rel,
                           "identity rebuild differs (%d -> %d bytes)"
                           % (len(raw), len(res.raw)))
    if bad > 10:
        report.add("identity", ERROR, "(summary)", "%d files differ in total" % bad)
    report.counts["identity_files"] = total


# --- (b) the built tree still decodes and tiles ------------------------------
def _decode_profile(raw: bytes, tab) -> dict:
    """What the *engine's own reading* of a file yields, as a comparable summary.

    Everything here comes from :mod:`.refdecode` -- a separate transcription of
    the disassembly -- so a build that passes has been read by something that
    shares no code with the builder.
    """
    prof = {"containers": 0, "decode_error": None, "records": 0, "tiled": 0,
            "untiled": 0, "untiled_ids": set(), "record_bytes": 0}
    conts = refdecode.decode_file(raw)
    prof["containers"] = len(conts)
    for ci, c in enumerate(conts):
        if c.error:
            prof["decode_error"] = "container %d: %s" % (ci, c.error)
            break
        for order, r in enumerate(c.records):
            if not r.data:
                continue
            prof["records"] += 1
            prof["record_bytes"] += len(r.data)
            try:
                vmops.tokenize(r.data, tab)
            except vmops.TileError:
                prof["untiled"] += 1
                prof["untiled_ids"].add((ci, r.id, order))
            else:
                prof["tiled"] += 1
    return prof


def verify_tree(out_dir: str, root=None, report: "Report | None" = None) -> dict:
    """Reference-decode and re-tile every file of a build, against the source.

    The bar is "decodes and tiles **exactly as well as** the original", not
    "decodes perfectly": four shipped files declare a record count their own body
    cannot hold, and 123 shipped records defeat the opcode table.  A build must
    reproduce those numbers, not improve on them by accident and not regress.
    """
    st = {"files": 0, "chain_ok": 0, "record_files": 0, "records": 0,
          "tiled": 0, "untiled": 0, "decode_fail": [], "regressions": [],
          "src_records": 0, "src_tiled": 0, "src_untiled": 0}
    tab = vmops.table()

    for rel in files.all_encoded(root):
        p = os.path.join(out_dir, *rel.split("/"))
        if not os.path.exists(p):
            st["decode_fail"].append((rel, "missing from the build"))
            continue
        with open(p, "rb") as fh:
            raw = fh.read()
        st["files"] += 1
        src = _decode_profile(files.read_source(rel, root), tab)
        got = _decode_profile(raw, tab)
        st["src_records"] += src["records"]
        st["src_tiled"] += src["tiled"]
        st["src_untiled"] += src["untiled"]
        st["records"] += got["records"]
        st["tiled"] += got["tiled"]
        st["untiled"] += got["untiled"]
        if got["decode_error"] is None:
            st["chain_ok"] += 1
        if got["records"]:
            st["record_files"] += 1

        if got["decode_error"] != src["decode_error"]:
            st["decode_fail"].append(
                (rel, "source: %s / build: %s" % (src["decode_error"] or "clean",
                                                  got["decode_error"] or "clean")))
            continue
        if got["records"] != src["records"]:
            st["decode_fail"].append(
                (rel, "%d records in the source, %d in the build"
                 % (src["records"], got["records"])))
            continue
        for key in sorted(got["untiled_ids"] - src["untiled_ids"]):
            st["regressions"].append((rel, key[0], key[1],
                                      "tiled in the source, not in the build"))

    if report is not None:
        for rel, why in st["decode_fail"]:
            report.add("decode", ERROR, rel, why)
        for rel, ci, rid, why in st["regressions"][:20]:
            report.add("tile", ERROR, "%s %d:%02X" % (rel, ci, rid), why)
    return st


# --- per-row rules ----------------------------------------------------------
def _where(row) -> str:
    return "%s %s[%d]" % (row.file, row.rec, row.idx)

def check_rows(report: Report, rows, pools=None,
               line_columns=width.LINE_COLUMNS, page_rows=width.PAGE_ROWS) -> None:
    # (s) workflow: an en is only real once someone has marked it, and an en that
    # merely copies its ref_en candidate needs a reviewer's word for it.
    for row in rows:
        if row.edited and not row.status:
            report.add("status", check.ERROR, _where(row),
                       "en is set but status is empty (draft or reviewed)")
        elif row.edited and row.ref_en and row.en == row.ref_en and row.status != "reviewed":
            report.add("status", check.ERROR, _where(row),
                       "en equals ref_en; mark it reviewed or change it")

    for r in rows:
        where = "%s %s[%d]" % (r.file, r.rec, r.idx)
        blocked = script.NOEDIT_NOTE in r.note

        if not r.en and codec.strip_tokens(r.jp).strip():
            if not any(m in r.note.lower() for m in SKIP_MARKERS):
                report.add("missing", WARN, where, "untranslated")
            continue
        if not r.edited:
            continue

        if blocked or r.tag == extract_v2.UNTILED_TAG:
            report.add("editable", ERROR, where,
                       "this record is marked non-editable; the builder will "
                       "copy it verbatim and ignore this translation")
            continue

        allow = frozenset() if r.rec == extract_v2.PNAME_REC else codec.INLINE_OPS
        try:
            data = codec.encode(r.en, allow=allow)
        except codec.CodecError as exc:
            report.add("encode", ERROR, where, str(exc))
            continue

        if r.rec == extract_v2.PNAME_REC:
            from . import spans as _spans
            if len(data) > _spans.PNAME_LEN - 1:
                report.add("pname", ERROR, where,
                           "name is %d bytes, the field holds %d plus a NUL"
                           % (len(data), _spans.PNAME_LEN - 1))
            continue

        # Dropping a pool call is normal and correct -- an English line spells
        # the word out instead of splicing a Japanese macro -- so only an
        # *added* call is worth reporting: it names a record the source line
        # never referenced, and nothing has checked that record exists.
        jp_calls = collections.Counter(t for t in codec.control_tokens(r.jp)
                                       if t.startswith("{0"))
        en_calls = collections.Counter(t for t in codec.control_tokens(r.en)
                                       if t.startswith("{0"))
        added = en_calls - jp_calls
        if added:
            report.add("tokens", WARN, where,
                       "adds pool calls the source line does not have: %s"
                       % " ".join(sorted(added.elements())))

        is_choice = r.tag in script.CHOICE_TAGS
        cw = _declared_width(r)
        for rule, msg in width.findings(r.en, is_choice, cw, line_columns,
                                        page_rows, pools):
            report.add(rule, WARN, where, msg)


def _declared_width(row) -> int:
    marker = "declared width "
    if marker in row.note:
        tail = row.note.split(marker, 1)[1]
        digits = ""
        for ch in tail:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            return int(digits)
    return width.CHOICE_COLUMNS


# --- run --------------------------------------------------------------------

CAPTURE_ON, CAPTURE_OFF, CAPTURE_LIMIT = 0x01B, 0x01C, 255


def check_capture(report: Report, rows, root=None) -> None:
    """(c) text-capture regions: opcode ``1B`` turns on a mode in which characters
    are appended to a 256-byte buffer (``0x481120``) with no bound check until
    ``1C``; ``1E9D``/``1E9E`` then render it as a fixed field.  The original's
    largest region is 215 bytes, so English can overflow it.  Sum the bytes the
    build will emit for every span inside a region and refuse more than 255."""
    by_file = {}
    for r in rows:
        if r.edited:
            by_file.setdefault(r.file, {})[(r.rec, r.idx)] = r
    for rel, edited in by_file.items():
        sc = script.parse(rel, files.read_source(rel, root))
        if not sc.ok:
            continue
        for rec in sc.iter_records():
            if rec.tokens is None:
                continue
            key = "%d:%02X" % (rec.ci, rec.id)
            on = None
            for t in rec.tokens:
                if t.kind == "op" and t.idx == CAPTURE_ON:
                    on = t.off
                    continue
                if t.kind == "op" and t.idx == CAPTURE_OFF and on is not None:
                    total = 0
                    for sp in rec.spans:
                        if sp.off >= on and sp.end <= t.off:
                            row = edited.get((key, sp.idx))
                            total += len(codec.encode(row.en)) if row else sp.end - sp.off
                    if total > CAPTURE_LIMIT:
                        report.add("capture", check.ERROR, "%s %s" % (rel, key),
                                   "%d bytes of text between 1B and 1C; the capture "
                                   "buffer holds %d" % (total, CAPTURE_LIMIT))
                    on = None


def check_stale(report: Report, rows, root=None) -> None:
    """(e) a row is addressed by span index, and its ``jp`` must still be what that
    span reads in the source; otherwise the English would land on another line
    (see :func:`build_v2.stale_rows`).  Rows that fail are errors and the builder
    refuses them too; the fix is to re-extract and carry, never to hand-edit."""
    from . import build_v2
    by_file = {}
    for r in rows:
        if r.edited and r.tag != extract_v2.UNTILED_TAG and r.rec != extract_v2.PNAME_REC:
            ci, _, rid = r.rec.partition(":")
            try:
                by_file.setdefault(r.file, {})[(int(ci), int(rid, 16), r.idx)] = r
            except ValueError:
                continue
    for rel, keyed in by_file.items():
        sc = script.parse(rel, files.read_source(rel, root))
        if not sc.ok:
            continue
        for (ci, rid, idx), why in build_v2.stale_rows(sc, keyed):
            report.add("stale", check.ERROR, "%s %d:%02X[%d]" % (rel, ci, rid, idx), why)


def check_overlay(report: Report, rows, root=None) -> None:
    """(f) everything :func:`overlay.plan` refuses: a row it cannot serve at
    runtime (stale, untiled, unencodable, or the file's virtual PC space is
    exhausted -- ``overlay-space``)."""
    from . import overlay
    _, findings = overlay.plan(rows, root)
    for where, msg in findings:
        report.add("overlay", check.ERROR, where, msg)


RECORD_LIMIT = 0x7FFF


def check_record_size(report: Report, rows, root=None) -> None:
    """(d) record size: the loader grows the script buffer by a *signed 16-bit*
    delta per record (``0x43ABC0``), so a record of 0x8000 bytes or more takes
    the shrink path with a garbage count and the game crashes when the file is
    loaded.  The original's largest record is 28,291 bytes (``m/MS006A`` r00);
    the English BBS pushed it to 35,824 and the terminal crashed.  Predict each
    record's built length from the edits and refuse anything over the limit."""
    by_file = {}
    for r in rows:
        if r.edited:
            by_file.setdefault(r.file, {})[(r.rec, r.idx)] = r
    for rel, edited in by_file.items():
        sc = script.parse(rel, files.read_source(rel, root))
        if not sc.ok:
            continue
        for rec in sc.iter_records():
            key = "%d:%02X" % (rec.ci, rec.id)
            size = len(rec.data)
            for sp in rec.spans:
                row = edited.get((key, sp.idx))
                if row:
                    size += len(codec.encode(row.en)) - (sp.end - sp.off)
            if size > RECORD_LIMIT:
                report.add("record-size", check.ERROR, "%s %s" % (rel, key),
                           "would build to %d bytes; the engine cannot load a "
                           "record over %d (source is %d) -- shorten the English "
                           "in this record by %d bytes"
                           % (size, RECORD_LIMIT, len(rec.data), size - RECORD_LIMIT))


def run(root=None, text_dir=None, family="all", skip_identity=False,
        quiet=False, show=200, out_dir=None, verify=False) -> Report:
    text_dir = text_dir or extract_v2.text_v2_dir()
    report = Report()

    if not skip_identity:
        check_identity(report, root)

    rows = []
    for path in tables.iter_tables(text_dir):
        rows.extend(tables.read(path))
    report.counts["rows"] = len(rows)
    check_rows(report, rows, pool.load(root))
    check_capture(report, rows, root)
    check_record_size(report, rows, root)
    check_stale(report, rows, root)
    check_overlay(report, rows, root)

    st = None
    if verify:
        out_dir = out_dir or os.path.join(paths.BUILD_DIR, "ddswin_v2")
        st = verify_tree(out_dir, root, report)

    if not quiet:
        errs, warns = report.errors, report.warnings
        for f in errs[:show]:
            print(f)
        if len(errs) > show:
            print("... and %d more errors" % (len(errs) - show))
        for f in warns[:show]:
            print(f)
        if len(warns) > show:
            print("... and %d more warnings" % (len(warns) - show))
        print("\n%d rows checked over %d files"
              % (report.counts.get("rows", 0), report.counts.get("identity_files", 0)))
        for k, v in sorted(report.counts.items()):
            if k not in ("rows", "identity_files"):
                print("  %-14s %d" % (k, v))
        if st:
            _print_verify(st, out_dir)
        print("%d errors, %d warnings" % (len(errs), len(warns)))
    return report


def _print_verify(st, out_dir) -> None:
    print("\nbuild verification (%s), reference decoder + tokenizer:" % out_dir)
    print("  %d files, %d decode cleanly as a container chain, %d hold records"
          % (st["files"], st["chain_ok"], st["record_files"]))
    print("  records   source %6d   build %6d" % (st["src_records"], st["records"]))
    print("  tiled     source %6d   build %6d" % (st["src_tiled"], st["tiled"]))
    print("  untiled   source %6d   build %6d" % (st["src_untiled"], st["untiled"]))
    print("  %d files decode worse than their source, %d tiling regressions"
          % (len(st["decode_fail"]), len(st["regressions"])))
    for rel, why in st["decode_fail"][:20]:
        print("    DECODE %-22s %s" % (rel, why))
    for rel, ci, rid, why in st["regressions"][:20]:
        print("    TILE   %-22s %d:%02X %s" % (rel, ci, rid, why))
