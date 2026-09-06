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
``name-macro`` the ``en`` drops a pool call that prints a runtime name
``tokens``     the ``en`` **adds** a pool call the ``jp`` does not have, naming a
               record nothing has checked exists.  Dropping one is normal and is
               not reported: an English line spells the word out.
``japanese``   the row still puts Japanese on screen once its pool calls are
               expanded *with the English column*.  A row can be "translated"
               and still fail this: its own full-width colon beside a call that
               does render English (`{08:03}：` -> "Emi："), or a pool entry
               translated to itself, which 80 rows inherited from one such entry.
               Expanding with :func:`pool.reading` instead -- the Japanese pool --
               cannot see any of it, and wrongly condemns 199 working Yes/No
               prompts whose English is the bare call ``{08:26}``.

``identity``, ``decode``, ``tile``, ``encode``, ``editable`` and ``pname`` are
errors; the width family, ``missing``, ``tokens`` and ``japanese`` are warnings,
because the engine auto-wraps rather than clipping (``docs/format-notes.md`` §3.2) and an
over-wide line is cosmetic.
"""
from __future__ import annotations

import collections
import os
import re
import sys

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


def _say(line) -> None:
    """Print a finding that may quote Japanese, on a console that cannot show it.

    A plain Windows console encodes stdout as cp1252, so a finding quoting the
    row's own text raises ``UnicodeEncodeError`` and takes the entire run down
    with it -- losing 1,500 findings to make a point about one.  Substituting
    the characters the console cannot draw costs a few glyphs in one message.
    """
    text = str(line)
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        text.encode(enc)
    except (UnicodeEncodeError, LookupError):
        text = text.encode(enc, "replace").decode(enc, "replace")
    print(text)


# --- per-row rules ----------------------------------------------------------
def _where(row) -> str:
    return "%s %s[%d]" % (row.file, row.rec, row.idx)

#: a pool call, `{01:2D}` .. `{08:7F}`
_CALL = re.compile(r"\{(0[1-8]):([0-9A-F]{2})\}")
#: kana and CJK, plus the full-width punctuation that reads as Japanese on screen
_JAPANESE = re.compile("[぀-ヿ㐀-鿿ｦ-ﾟ"
                       "！？：；‥、。]")
#: pool index -> the file holding it; pool 1 is m/MS7F00, pool 8 is m/MS7F07
_POOL_FILE = {"%02d" % (i + 1): "m/MS7F%02X.BIN" % i for i in range(8)}
_POOL_REL = {v: k for k, v in _POOL_FILE.items()}


def english_pool(rows) -> dict:
    """``{(pool, entry): text}`` -- what each pool call puts on screen.

    The English column when it has one, the Japanese when it does not, because
    that is what the player sees either way.
    """
    out = {}
    for r in rows:
        pi = _POOL_REL.get(r.file)
        if pi is None:
            continue
        out[(pi, r.rec.split(":")[-1])] = r.en or r.jp
    return out


def render_english(text: str, epool: dict, depth: int = 0) -> str:
    """Expand every pool call the way the ENGINE will, using English entries.

    Not to be confused with :func:`pool.reading`, which expands with the
    *Japanese* pool -- that answers "what does a Japanese player see" and cannot
    answer "does this still show Japanese".  Reading rows the Japanese way once
    made 199 working Yes/No prompts look broken: their English is the bare call
    ``{08:26}``, and the pool renders it "Yes".
    """
    if depth > 6:
        return text
    def sub(m):
        e = epool.get((m.group(1), m.group(2)))
        return m.group(0) if e is None else render_english(e, epool, depth + 1)
    return _CALL.sub(sub, text)


_NAME_MACROS: dict = {}


def name_macros(root=None) -> set:
    """The pool calls that print a runtime name.

    A pool record holding a ``1F01`` prints a party-member name when the engine
    expands the call -- ``m/MS7F03`` r05 is three of them around one ideographic
    space.  ``pool.reading`` shows only the literal text, so such an entry reads
    as `　` and looks like decoration; thirteen battle lines lost their actor's
    name to an English `" "` before this rule existed.  Ten entries qualify,
    all in pool 4.
    """
    if root not in _NAME_MACROS:
        out = set()
        for i in range(8):
            rel = "m/MS7F%02X.BIN" % i
            try:
                sc = script.parse(rel, files.read_source(rel, root))
            except Exception:
                continue
            if not sc.ok or not sc.containers:
                continue
            for rec in sc.containers[0]:
                if not rec.data:
                    continue
                try:
                    toks = vmops.tokenize(rec.data)
                except Exception:
                    continue
                if any(t.kind == "op"
                       and vmops.table().encoding(t.idx).replace(" ", "") == "1F01"
                       for t in toks):
                    out.add("{%02d:%02X}" % (i + 1, rec.id))
        _NAME_MACROS[root] = out
    return _NAME_MACROS[root]


def check_rows(report: Report, rows, pools=None,
               line_columns=width.LINE_COLUMNS, page_rows=width.PAGE_ROWS,
               root=None) -> None:
    # (s) workflow: an en is only real once someone has marked it, and an en that
    # merely copies its ref_en candidate needs a reviewer's word for it.
    for row in rows:
        if row.edited and not row.status:
            report.add("status", check.ERROR, _where(row),
                       "en is set but status is empty (draft or reviewed)")
        elif row.edited and row.ref_en and row.en == row.ref_en and row.status != "reviewed":
            report.add("status", check.ERROR, _where(row),
                       "en equals ref_en; mark it reviewed or change it")

    epool = english_pool(rows)
    for r in rows:
        where = "%s %s[%d]" % (r.file, r.rec, r.idx)
        blocked = script.NOEDIT_NOTE in r.note

        if not r.en and codec.strip_tokens(r.jp).strip():
            if not any(m in r.note.lower() for m in SKIP_MARKERS):
                report.add("missing", WARN, where, "untranslated")
            continue

        # What actually reaches the screen.  Checked BEFORE the `edited` gate:
        # a row whose en merely copies its jp is not "edited", and those are
        # exactly the ones that ship Japanese.  A row can also be genuinely
        # translated and still fail -- its own full-width colon beside a call
        # that does render English (`{08:03}：` -> "Emi：") -- or inherit the
        # fault from a pool entry translated to itself, as 80 rows did from
        # m/MS7F07 0:72 (`‥‥` -> `‥‥`).
        if r.en and not blocked and r.tag != extract_v2.UNTILED_TAG:
            shown = render_english(r.en, epool)
            stray = _JAPANESE.findall(shown)
            if stray:
                report.add("japanese", WARN, where,
                           "reaches the screen as %r -- still shows %s"
                           % (shown[:48], " ".join(sorted(set(stray)))))

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

        # ...with one exception: a call that prints a runtime *name* is not
        # decoration to spell out, it is the name.  Dropping one is silent --
        # the line still reads, it just has nobody in it -- which is how a
        # battle table ended up saying " is charmed" with no one charmed.
        lost = name_macros(root) & set(jp_calls) - set(en_calls)
        if lost:
            report.add("name-macro", ERROR, where,
                       "drops %s, which prints a runtime name; the line would "
                       "have no one in it" % " ".join(sorted(lost)))

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
    check_rows(report, rows, pool.load(root), root=root)
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
            _say(f)
        if len(errs) > show:
            print("... and %d more errors" % (len(errs) - show))
        for f in warns[:show]:
            _say(f)
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
