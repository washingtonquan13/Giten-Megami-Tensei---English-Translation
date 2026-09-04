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
``editable``   no ``en`` on a record marked ``@untiled`` or ``@dupid``.
``pname``      a ``p/`` name fits its fixed 16-byte field.
``width``      a line exceeds the 74-column message-box budget.
``page-rows``  a page holds more than 4 lines before a ``<wait>``.
``width-choice`` a menu option exceeds the width its ``1F B1`` declares.
``missing``    a non-empty ``jp`` with an empty ``en``.
``tokens``     the ``en`` dropped a pool call the ``jp`` had (information only --
               dropping ``{08:1F}`` and writing the English word out is normal).

``identity``, ``decode``, ``tile``, ``encode``, ``editable`` and ``pname`` are
errors; the width family, ``missing`` and ``tokens`` are warnings, because the
engine auto-wraps rather than clipping (``docs/format-notes.md`` §3.2) and an
over-wide line is cosmetic.
"""
from __future__ import annotations

import os

from . import (build_v2, check, codec, extract_v2, files, paths, pool, refdecode,
               script, tables, vmops, width)

ERROR, WARN = check.ERROR, check.WARN
Report = check.Report

SKIP_MARKERS = check.SKIP_MARKERS + (script.UNTILED_NOTE, script.DUPID_NOTE)


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
def check_rows(report: Report, rows, pools=None,
               line_columns=width.LINE_COLUMNS, page_rows=width.PAGE_ROWS) -> None:
    for r in rows:
        where = "%s %s[%d]" % (r.file, r.rec, r.idx)
        blocked = any(m in r.note for m in (script.UNTILED_NOTE, script.DUPID_NOTE))

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

        jp_calls = [t for t in codec.control_tokens(r.jp) if t.startswith("{0")]
        en_calls = [t for t in codec.control_tokens(r.en) if t.startswith("{0")]
        if jp_calls != en_calls:
            report.add("tokens", WARN, where,
                       "pool calls changed: %s -> %s"
                       % (" ".join(jp_calls) or "(none)",
                          " ".join(en_calls) or "(none)"))

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
