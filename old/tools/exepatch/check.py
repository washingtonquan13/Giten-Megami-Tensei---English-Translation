"""``check`` -- validate the table on its own, before anything binary happens.

Errors block a build; warnings do not.
"""
from __future__ import annotations

import os
import re

from . import config, scan, table

SPEC_RE = re.compile(r"%(?:[-+ #0]*)(\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|L|z|j|t)?([diouxXeEfgGaAcspn%])")


def format_specs(text):
    """Ordered list of conversion specifiers, ``%%`` dropped.

    Only the conversion letter and its length modifier matter for ABI safety;
    field width differences (``%6ld`` vs ``%10ld``) are a layout choice, so they
    are compared separately and only warned about.
    """
    return [m.group(0) for m in SPEC_RE.finditer(text) if m.group(2) != "%"]


def spec_kinds(text):
    out = []
    for m in SPEC_RE.finditer(text):
        if m.group(2) == "%":
            continue
        s = m.group(0)
        # strip flags and field width, keep length modifier + conversion
        core = re.sub(r"^%[-+ #0]*(\d+|\*)?(\.(\d+|\*))?", "", s)
        out.append(core)
    return out


def run(args):
    rows = table.load(config.TABLE_PATH)
    errors = []
    warnings = []

    by_table = {}
    for r in rows:
        en = r.en
        jp = r.jp
        rid = r["id"]

        # -- cp932 encodability -------------------------------------------
        for label, text in (("jp", jp), ("en", en)):
            if not text:
                continue
            try:
                text.encode("cp932")
            except UnicodeEncodeError as exc:
                errors.append("%s: %s value %r is not cp932-encodable (%s)"
                              % (rid, label, text, exc))

        if not en:
            # -- empty replacement where the original had text -------------
            if jp and scan.needs_translation(jp) and not r.has_flag("@skip"):
                errors.append("%s: jp %r has no en and no @skip note" % (rid, jp))
            continue

        if r.has_flag("@skip"):
            continue

        # -- format specifiers --------------------------------------------
        if spec_kinds(jp) != spec_kinds(en):
            errors.append("%s: format specifiers differ: jp %s vs en %s"
                          % (rid, format_specs(jp), format_specs(en)))
        elif format_specs(jp) != format_specs(en):
            warnings.append("%s: printf field widths differ: jp %s vs en %s"
                            % (rid, format_specs(jp), format_specs(en)))

        # -- record / slot overflow ---------------------------------------
        try:
            need = len(en.encode("cp932")) + 1
        except UnicodeEncodeError:
            continue
        cap = r.capacity()
        if r.record_width and need > r.record_width:
            errors.append("%s: %r needs %d bytes, record width is %d"
                          % (rid, en, need, r.record_width))
        elif need > cap and not r.refs:
            errors.append("%s: %r needs %d bytes, slot is %d and there is no "
                          "reference to redirect" % (rid, en, need, cap))

        # -- font guard ----------------------------------------------------
        if config.FONT_TABLE_START <= r.off < config.FONT_TABLE_END:
            errors.append("%s: offset 0x%x is inside the bitmap font table" % (rid, r.off))

        # -- rendered width budget ----------------------------------------
        # ``max_cols`` is seeded from the slot, so it only describes a real
        # budget for strings that stay home.  A string long enough to be
        # relocated into .eng has no storage limit left, and its seeded budget
        # would be pure noise -- edit ``max_cols`` by hand when a relocated
        # string does sit in a known-width column.
        budget = r.max_cols
        px_en = scan.display_width(en)
        if budget and need <= cap:
            px_budget = budget * config.ASCII_CELL_PX
            if px_en > px_budget:
                warnings.append("%s: %r renders %d px, slot budget is %d px (%d cols)"
                                % (rid, en, px_en, px_budget, budget))
        px_jp = scan.display_width(jp)
        if jp and px_en - px_jp > 3 * config.ASCII_CELL_PX:
            warnings.append("%s: %r renders %d px, %d px wider than the original"
                            % (rid, en, px_en, px_en - px_jp))

        # -- duplicate en for distinct jp inside one record table ----------
        if r.record_width:
            key = (r.off // 0x1000, r.record_width)
            by_table.setdefault(key, []).append(r)

    for key, group in by_table.items():
        seen = {}
        for r in group:
            en = r.en
            if not en:
                continue
            prev = seen.get(en)
            if prev is not None and prev.jp != r.jp:
                warnings.append("%s and %s share en %r but differ in jp (%r vs %r)"
                                % (prev["id"], r["id"], en, prev.jp, r.jp))
            seen[en] = r

    print("check: %d rows, %s" % (len(rows), os.path.relpath(config.TABLE_PATH, config.REPO_ROOT)))
    for w in warnings:
        print("  warn  " + w)
    for e in errors:
        print("  ERROR " + e)
    print("  %d error(s), %d warning(s)" % (len(errors), len(warnings)))
    return 1 if errors else 0
