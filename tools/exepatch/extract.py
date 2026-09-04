"""``extract`` -- rebuild the string table from the two reference exes.

The table is keyed on the *original* 1999 layout (``dds_org.exe``): every row is
one NUL-terminated string found in ``.rdata``/``.data`` there.  The ``en``
column reports what that same slot currently says in ``dds_en.exe``, following
the pointer if the v0.05 patch relocated the string into its ``.rsrc`` cave.

Re-running ``extract`` merges: hand-written ``en`` and ``note`` values already
in the table win over the freshly scanned ones, so regenerating never destroys
translation work.  ``--reseed`` throws that away and takes the exe's word.
"""
from __future__ import annotations

import io
import os
import struct

from . import config, scan, table
from .pe import PE
from .table import Row, esc


def _load(path):
    with io.open(path, "rb") as fh:
        return PE(fh.read(), path)


def _row_id(section, off):
    return "%s_%06x" % (section.lstrip("."), off)


def current_en_text(org_pe, en_pe, found, refs):
    """What ``dds_en.exe`` renders for this string today.

    If every reference was repointed away from the original VA, follow it -- the
    v0.05 patch parked eight character names in a cave at the end of ``.rsrc``
    and left the Japanese bytes stranded in place, so reading the home offset
    would wrongly report them as untranslated.
    """
    targets = set()
    for ref_off in refs:
        if ref_off + 4 <= len(en_pe.data):
            targets.add(struct.unpack_from("<I", en_pe.data, ref_off)[0])
    relocated = None
    if targets and found.va not in targets and len(targets) == 1:
        relocated = next(iter(targets))

    if relocated is not None:
        raw = en_pe.cstring_at_va(relocated)
        if raw is None:
            return "", None
        text, ok = scan.decode_string(raw)
        return (text if ok else ""), relocated

    end = en_pe.data.find(b"\0", found.off)
    raw = en_pe.data[found.off:end]
    text, ok = scan.decode_string(raw)
    return (text if ok else ""), None


DEBUG_MARKERS = (
    "でない場合は連絡して下さい",  # ...でない場合は連絡して下さい
    "お知らせください",                                # お知らせください
)


def default_note(found, record_width, refs, en_text):
    """Auto-notes.  ``@skip`` means ``check`` stops demanding a translation and
    ``build`` never touches the row.

    Three cases earn it automatically: bytes inside the bitmap font table (they
    only *look* like text), the developers' ``...でない場合は連絡して下さい``
    assertions, and strings with neither an imm32 reference nor a record width,
    which have no reachable slot to patch at all.
    """
    notes = []
    if config.FONT_TABLE_START <= found.off < config.FONT_TABLE_END:
        notes.append("@skip @font-guard")
    if any(m in found.text for m in DEBUG_MARKERS):
        notes.append("@skip debug-assert")
    if not refs and not record_width:
        notes.append("@skip unreachable")
    return " ".join(notes)


def run(args):
    org_pe = _load(config.ORG_EXE)
    en_pe = _load(config.EN_EXE)

    founds = scan.find_strings(org_pe)
    ref_index = scan.build_ref_index(org_pe)
    widths = scan.detect_record_widths(founds, ref_index)

    old = {}
    if os.path.exists(config.TABLE_PATH) and not args.reseed:
        for r in table.load(config.TABLE_PATH):
            old[r["id"]] = r

    rows = []
    for f in founds:
        rid = _row_id(f.section, f.off)
        refs = ref_index.get(f.va, [])
        ref_vas = [org_pe.off2va(o) for o in refs]
        ref_vas = [v for v in ref_vas if v is not None]
        rw = widths.get(f.off, 0)
        cur_text, relocated = current_en_text(org_pe, en_pe, f, refs)
        # An `en` value means "the English text".  If dds_en.exe still shows
        # Japanese here, the row is untranslated and the column stays empty.
        en_text = "" if scan.needs_translation(cur_text) else cur_text

        cap = (min(rw, f.slot) if rw else f.slot) - 1
        r = Row()
        r["id"] = rid
        r["file_off"] = "%08x" % f.off
        r["va"] = "%08x" % f.va
        r["section"] = f.section
        r["slot_bytes"] = str(f.slot)
        r["refs"] = ",".join("%08x" % v for v in ref_vas)
        r["record_width"] = str(rw) if rw else ""
        r["max_cols"] = str(cap)
        r["jp"] = esc(f.text)
        r["en"] = esc(en_text)
        r["note"] = default_note(f, rw, refs, en_text)
        if relocated is not None:
            r["note"] = (r["note"] + " @reloc=%08x" % relocated).strip()

        prev = old.get(rid)
        if prev is not None:
            # Hand-written translation and notes survive a re-extract.
            if prev["en"] != r["en"]:
                r["en"] = prev["en"]
            keep = [t for t in prev["note"].split() if t.startswith("@") or t]
            merged = []
            for tok in keep:
                if tok.startswith("@reloc="):
                    continue
                merged.append(tok)
            for tok in r["note"].split():
                if tok not in merged:
                    merged.append(tok)
            r["note"] = " ".join(merged)
            if prev["max_cols"].strip():
                r["max_cols"] = prev["max_cols"]
        rows.append(r)

    table.save(config.TABLE_PATH, rows)

    jp_rows = [r for r in rows if scan.needs_translation(r.jp)]
    print("extract: %d strings (%d Japanese) -> %s"
          % (len(rows), len(jp_rows), os.path.relpath(config.TABLE_PATH, config.REPO_ROOT)))
    print("  record-table rows: %d" % sum(1 for r in rows if r.record_width))
    print("  rows with no refs: %d" % sum(1 for r in rows if not r.refs))
    todo = [r for r in jp_rows if not r.en]
    print("  Japanese still showing in dds_en.exe: %d" % len(todo))
    return 0
