"""``check``: the validators.

Rules, in the order the task defines them:

(a) ``identity``   -- building with every ``en`` empty reproduces every source
                      file byte-exactly.  This is the load-bearing one: if it
                      fails, nothing else the pipeline reports means anything.
(b) ``dict``       -- no ``{DICT:nn}`` macro reference survives in an English span.
(c) ``format``     -- printf-style specifiers match between ``jp`` and ``en``.
(d) ``width``      -- per line, and per choice option, against the width budget.
(e) ``missing``    -- a non-empty ``jp`` with an empty ``en`` (unless marked).
(f) ``cp932``      -- the English text is encodable in the game's code page.
(g) ``pname``      -- ``p/`` names fit the fixed 16-byte field (15 bytes + NUL).
(h) ``tokens``     -- ``{XX}`` runtime-insert tokens match ``jp`` in the same order.

Plus one rule the format work turned up:

(i) ``resize``     -- an edit changes the byte length of a span that lives in a
                      frame with no known length field.  See :mod:`.framing`.

(a) (b) (c) (f) (g) (h) are errors; (d) (e) (i) are warnings.
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field

from . import (build as build_mod, container, dictionary, files, paths, spans,
               tables, tokens)

ERROR, WARN = "error", "warn"

#: A ``note`` containing one of these markers (case-insensitive) means
#: "deliberately not translated" and silences rule (e).  They are ``@``-prefixed
#: so that ordinary prose in a note -- including the extractor's own hints --
#: can never switch a check off by accident.
SKIP_MARKERS = ("@keep", "@skip", "@no-tl", "@untranslatable")

_FORMAT_RE = re.compile(r"%[-+ #0]*[0-9]*(?:\.[0-9]+)?[a-zA-Z%]")

#: Multiplier applied to the widest source line to get the English budget.
#: 1.0 == "the English line may be as wide in pixels as the Japanese one was".
#: Because a full-width glyph is 16 px and a half-width one 8 px, that is exactly
#: the "2x the Japanese character count" budget the format notes call for.  The
#: real per-window budget is not known yet; raise or lower this once it is.
DEFAULT_WIDTH_SCALE = 1.0


@dataclass
class Finding:
    rule: str
    level: str
    where: str
    message: str

    def __str__(self):
        return "%-5s %-8s %-34s %s" % (self.level.upper(), self.rule, self.where,
                                       self.message)


@dataclass
class Report:
    findings: "list[Finding]" = field(default_factory=list)
    counts: dict = field(default_factory=dict)

    def add(self, rule, level, where, message):
        self.findings.append(Finding(rule, level, where, message))
        self.counts[rule] = self.counts.get(rule, 0) + 1

    @property
    def errors(self):
        return [f for f in self.findings if f.level == ERROR]

    @property
    def warnings(self):
        return [f for f in self.findings if f.level == WARN]


# --- (a) identity -----------------------------------------------------------
def check_identity(report: Report, root=None) -> None:
    dic = dictionary.load(root)
    bad = 0
    total = 0
    for rel in files.all_encoded(root):
        raw = files.read_source(rel, root)
        res = build_mod.build_file(rel, raw, dic, {})
        total += 1
        if res.raw != raw:
            bad += 1
            if bad <= 10:
                report.add("identity", ERROR, rel,
                           "rebuild differs from source (%d -> %d bytes)"
                           % (len(raw), len(res.raw)))
    if bad > 10:
        report.add("identity", ERROR, "(summary)",
                   "%d files in total differ" % bad)
    report.counts["identity_files"] = total


# --- per-row rules ----------------------------------------------------------
def _budget(row: tables.Row, scale: float) -> int:
    return int(round(scale * max((tokens.display_width(l)
                                  for l in tokens.lines_of(row.jp)), default=0)))


def check_rows(report: Report, rows, width_scale=DEFAULT_WIDTH_SCALE,
               max_line_width=None) -> None:
    for r in rows:
        where = "%s %s[%d]" % (r.file, r.rec, r.idx)

        # (e) missing translation
        if not r.en and tokens.strip_tokens(r.jp).strip():
            if not any(m in r.note.lower() for m in SKIP_MARKERS):
                report.add("missing", WARN, where, "untranslated")
            continue
        if not r.edited:
            continue                     # en == jp: shipped text, nothing to check

        # (f) cp932 + (b) dictionary refs + escape well-formedness
        try:
            data = tokens.encode(r.en)
        except tokens.SpanEncodeError as exc:
            rule = "dict" if "dictionary reference" in str(exc) else "cp932"
            report.add(rule, ERROR, where, str(exc))
            continue

        # (b) belt and braces: a literal 08 nn must not survive re-encoding
        if b"\x08" in data:
            report.add("dict", ERROR, where,
                       "encoded English still contains an 08 dictionary escape")

        # (h) runtime-insert tokens preserved, in order
        jp_toks = [t for t in tokens.control_tokens(r.jp) if not t.startswith("{DICT")]
        en_toks = [t for t in tokens.control_tokens(r.en) if not t.startswith("{DICT")]
        if jp_toks != en_toks:
            report.add("tokens", ERROR, where,
                       "control tokens changed: %s -> %s"
                       % (" ".join(jp_toks) or "(none)", " ".join(en_toks) or "(none)"))

        # (c) format specifiers
        jp_fmt = _FORMAT_RE.findall(r.jp)
        en_fmt = _FORMAT_RE.findall(r.en)
        if jp_fmt != en_fmt:
            report.add("format", ERROR, where,
                       "format specifiers changed: %s -> %s"
                       % (" ".join(jp_fmt) or "(none)", " ".join(en_fmt) or "(none)"))

        # (g) fixed-width p/ names
        if r.tag == spans.PNAME_TAG:
            if len(data) > spans.PNAME_LEN - 1:
                report.add("pname", ERROR, where,
                           "name is %d bytes, the field holds %d + NUL"
                           % (len(data), spans.PNAME_LEN - 1))
            continue                    # width budget is meaningless for a name field

        # (d) width budget
        budget = _budget(r, width_scale)
        for i, line in enumerate(tokens.lines_of(r.en)):
            w = tokens.display_width(line)
            cap = budget if max_line_width is None else min(budget, max_line_width)
            if cap and w > cap:
                rule = "width" if r.tag != "1FB2" else "width-choice"
                report.add(rule, WARN, where,
                           "line %d is %d half-width units, budget %d: %r"
                           % (i + 1, w, cap, line[:60]))


# --- (i) resize in an unframed region ---------------------------------------
def check_resize(report: Report, root=None, family="all", text_dir=None) -> None:
    # A throwaway build: we only want the diagnostics, not the artefacts, and
    # writing them next to a real build/ddswin would be confusing.
    with tempfile.TemporaryDirectory() as tmp:
        stats = build_mod.run(out_dir=tmp, family=family, root=root,
                              text_dir=text_dir, quiet=True)
    for e in stats["errors"]:
        report.add("encode", ERROR, "(build)", e)
    if stats["unframed_resize"]:
        report.add("resize", WARN, "(build)",
                   "%d edited spans changed byte length inside a frame with no "
                   "known length field; verify these in game"
                   % stats["unframed_resize"])
    report.counts["build_changed_spans"] = stats["changed_spans"]


def run(root=None, text_dir=None, family="all", width_scale=DEFAULT_WIDTH_SCALE,
        max_line_width=None, skip_identity=False, quiet=False,
        show=200) -> Report:
    text_dir = text_dir or paths.TEXT_DIR
    report = Report()

    if not skip_identity:
        check_identity(report, root)

    rows = []
    for path in tables.iter_tables(text_dir):
        rows.extend(tables.read(path))
    report.counts["rows"] = len(rows)
    check_rows(report, rows, width_scale, max_line_width)

    if rows:
        check_resize(report, root, family, text_dir)

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
        by_rule = sorted((k, v) for k, v in report.counts.items()
                         if k not in ("rows", "identity_files", "build_changed_spans"))
        for k, v in by_rule:
            print("  %-14s %d" % (k, v))
        print("%d errors, %d warnings" % (len(errs), len(warns)))
    return report
