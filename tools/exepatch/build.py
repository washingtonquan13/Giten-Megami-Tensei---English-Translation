"""``build`` -- produce ``build/dds_en.exe`` from the game exe plus the table.

Placement rules, in order:

1. ``en`` empty, or identical to what the exe already shows -> nothing to do.
2. Fits its home slot (or its record width, if it lives in a fixed-stride
   table) -> written in place, NUL-padded to the full slot.
3. Otherwise -> appended to a new ``.eng`` section and every imm32 reference to
   the old address is rewritten to point at it.  Identical replacement texts
   share one copy.

Rule 3 needs at least one reference.  A row with no references and no record
width has no reachable way to be redirected, so the build refuses it rather
than writing a patch that silently does nothing.
"""
from __future__ import annotations

import io
import os
import struct

from . import config, scan, table
from .pe import PE


class BuildError(Exception):
    pass


class Placement:
    """Where one row's replacement text ended up (consumed by ``verify``)."""

    def __init__(self, row, kind, text, off=None, va=None, region=None, refs=()):
        self.row = row
        self.kind = kind            # "inplace" | "eng"
        self.text = text
        self.off = off              # file offset of the bytes, in the built exe
        self.va = va                # VA the string is reachable at
        self.region = region        # (start, length) overwritten in place
        self.refs = list(refs)      # file offsets of rewritten imm32 slots


def _current_text(pe, row):
    """What the *base* exe shows for this row right now."""
    for ref_va in row.refs:
        off = pe.va2off(ref_va)
        if off is None:
            continue
        target = struct.unpack_from("<I", pe.data, off)[0]
        if target != row.va:
            raw = pe.cstring_at_va(target)
            if raw is None:
                return None
            text, ok = scan.decode_string(raw)
            return text if ok else None
    end = pe.data.find(b"\0", row.off)
    if end < 0:
        return None
    text, ok = scan.decode_string(pe.data[row.off:end])
    return text if ok else None


def plan(pe, rows):
    """Decide placement for every row.  Returns ``(placements, blob, errors)``."""
    placements = []
    errors = []
    blob = bytearray()
    # SizeOfImage is an RVA-space size; the new section's strings are reachable
    # at ImageBase + that.
    blob_va = pe.imagebase + pe.sizeimage
    pool = {}

    for row in rows:
        en = row.en
        if not en:
            continue
        if row.has_flag("@skip"):
            continue
        cur = _current_text(pe, row)
        if cur == en:
            continue

        if config.FONT_TABLE_START <= row.off < config.FONT_TABLE_END:
            errors.append("%s: refuses to patch inside the bitmap font table" % row["id"])
            continue

        try:
            raw = scan.encode(en) + b"\0"
        except UnicodeEncodeError as exc:
            errors.append("%s: %r is not cp932-encodable (%s)" % (row["id"], en, exc))
            continue

        cap = row.capacity()
        relocated = cur is not None and _is_relocated(pe, row)
        if len(raw) <= cap and not relocated:
            placements.append(Placement(row, "inplace", en, off=row.off,
                                        va=row.va, region=(row.off, row.slot)))
            continue

        if row.record_width:
            errors.append("%s: %r needs %d bytes but record width is %d"
                          % (row["id"], en, len(raw), cap))
            continue
        if not row.refs:
            errors.append("%s: %r needs %d bytes, slot is %d, and the string has "
                          "no imm32 reference to redirect"
                          % (row["id"], en, len(raw), cap))
            continue

        if en in pool:
            off = pool[en]
        else:
            while len(blob) % 4:
                blob.append(0)
            off = len(blob)
            blob.extend(raw)
            pool[en] = off
        ref_offs = []
        bad = False
        for ref_va in row.refs:
            ro = pe.va2off(ref_va)
            if ro is None:
                errors.append("%s: reference VA %08x is not in the image" % (row["id"], ref_va))
                bad = True
                continue
            ref_offs.append(ro)
        if bad:
            continue
        placements.append(Placement(row, "eng", en, va=blob_va + off, refs=ref_offs))

    return placements, bytes(blob), errors


def _is_relocated(pe, row):
    for ref_va in row.refs:
        off = pe.va2off(ref_va)
        if off is None:
            continue
        if struct.unpack_from("<I", pe.data, off)[0] != row.va:
            return True
    return False


def apply(pe, placements, blob):
    """Return the patched image bytes."""
    data = bytearray(pe.data)
    for p in placements:
        if p.kind == "inplace":
            start, length = p.region
            raw = scan.encode(p.text) + b"\0"
            data[start:start + length] = raw.ljust(length, b"\0")
        else:
            for ro in p.refs:
                struct.pack_into("<I", data, ro, p.va)
    out = bytes(data)
    if blob:
        out = PE(out, pe.path).append_section(
            config.ENG_SECTION_NAME, blob, config.ENG_CHARACTERISTICS)
    return out


def run(args):
    with io.open(config.EN_EXE, "rb") as fh:
        base = PE(fh.read(), config.EN_EXE)
    rows = table.load(config.TABLE_PATH)

    placements, blob, errors = plan(base, rows)
    if errors:
        for e in errors:
            print("ERROR " + e)
        if not args.force:
            print("build: aborted (%d placement errors); pass --force to skip them"
                  % len(errors))
            return 1

    out = apply(base, placements, blob)

    if not os.path.isdir(config.BUILD_DIR):
        os.makedirs(config.BUILD_DIR)
    with io.open(config.OUT_EXE, "wb") as fh:
        fh.write(out)

    inplace = [p for p in placements if p.kind == "inplace"]
    eng = [p for p in placements if p.kind == "eng"]
    print("build: %s" % os.path.relpath(config.OUT_EXE, config.REPO_ROOT))
    print("  in place : %d" % len(inplace))
    print("  .eng     : %d rows, %d unique strings, %d bytes, %d pointers rewritten"
          % (len(eng), len(set(p.text for p in eng)), len(blob),
             sum(len(p.refs) for p in eng)))
    print("  size     : %d -> %d bytes" % (len(base.data), len(out)))
    if args.verbose:
        for p in sorted(placements, key=lambda p: p.row["id"]):
            print("    %-14s %-8s %r" % (p.row["id"], p.kind, p.text))
    return 0
