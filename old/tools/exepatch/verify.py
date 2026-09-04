"""``verify`` -- prove the built exe says what the table asked for, and nothing
else changed.

Four independent checks:

* the PE is still parseable, has the expected sections, and every section's raw
  range lies inside the file;
* every patched row is reachable and reads back exactly as ``en`` -- for
  relocated rows that means following the rewritten imm32, not trusting it;
* every byte that differs from the base exe falls inside a region the plan
  authorised (a patched slot, a rewritten pointer, the PE header fields, the new
  section header, or the appended section itself);
* the 8x16 bitmap font table and the ``SHIFTJIS_CHARSET`` push are untouched.
"""
from __future__ import annotations

import io
import os
import struct

from . import build as build_mod
from . import config, scan, table
from .pe import PE, SECTION_HEADER_SIZE


class Problem(Exception):
    pass


def _authorised_ranges(base, placements):
    """Byte ranges in the built image that the plan is allowed to change."""
    ranges = []
    for p in placements:
        if p.kind == "inplace":
            start, length = p.region
            ranges.append((start, start + length))
        else:
            for ro in p.refs:
                ranges.append((ro, ro + 4))
    # PE header fields the section append rewrites.
    ranges.append((base.file_header_off + 2, base.file_header_off + 4))      # NumberOfSections
    ranges.append((base.opt_off + 10, base.opt_off + 14))                    # SizeOfInitializedData
    ranges.append((base.opt_off + 56, base.opt_off + 60))                    # SizeOfImage
    hdr = base.sectbl_off + base.numsec * SECTION_HEADER_SIZE
    ranges.append((hdr, hdr + SECTION_HEADER_SIZE))                          # new section header
    ranges.sort()
    return ranges


def _in_ranges(off, ranges):
    for lo, hi in ranges:
        if lo <= off < hi:
            return True
    return False


def run(args):
    with io.open(config.EN_EXE, "rb") as fh:
        base = PE(fh.read(), config.EN_EXE)
    if not os.path.exists(config.OUT_EXE):
        print("verify: %s does not exist -- run build first" % config.OUT_EXE)
        return 1
    with io.open(config.OUT_EXE, "rb") as fh:
        built_bytes = fh.read()

    rows = table.load(config.TABLE_PATH)
    placements, blob, errors = build_mod.plan(base, rows)
    problems = []
    for e in errors:
        problems.append("plan: " + e)

    # ---------------------------------------------------------------- PE shape
    try:
        built = PE(built_bytes, config.OUT_EXE)
    except Exception as exc:
        print("verify: built image does not parse: %s" % exc)
        return 1

    expect_sections = base.numsec + (1 if blob else 0)
    if built.numsec != expect_sections:
        problems.append("section count is %d, expected %d" % (built.numsec, expect_sections))
    for s in built.sections:
        if s["rawptr"] + s["rawsize"] > len(built_bytes):
            problems.append("section %s raw range runs past EOF" % s["name"])
    for a, b in zip(base.sections, built.sections):
        for k in ("name", "vaddr", "vsize", "rawptr", "rawsize", "flags"):
            if a[k] != b[k]:
                problems.append("section %s field %s changed" % (a["name"], k))
    if blob:
        eng = built.section(config.ENG_SECTION_NAME)
        if eng is None:
            problems.append("no %s section in the built image" % config.ENG_SECTION_NAME)
        else:
            if eng["vaddr"] != base.sizeimage:
                problems.append(".eng vaddr %08x != old SizeOfImage %08x"
                                % (eng["vaddr"], base.sizeimage))
            if eng["flags"] != config.ENG_CHARACTERISTICS:
                problems.append(".eng characteristics %08x" % eng["flags"])
            if eng["vsize"] != len(blob):
                problems.append(".eng vsize %d != blob %d" % (eng["vsize"], len(blob)))
            want = eng["vaddr"] + (len(blob) + built.secalign - 1) // built.secalign * built.secalign
            if built.sizeimage != want:
                problems.append("SizeOfImage %08x, expected %08x" % (built.sizeimage, want))

    # ------------------------------------------------------- strings read back
    checked = 0
    for p in placements:
        want = p.text
        if p.kind == "inplace":
            end = built_bytes.find(b"\0", p.off)
            got_raw = built_bytes[p.off:end]
        else:
            for ro in p.refs:
                target = struct.unpack_from("<I", built_bytes, ro)[0]
                if target != p.va:
                    problems.append("%s: pointer at file 0x%x is %08x, expected %08x"
                                    % (p.row["id"], ro, target, p.va))
            got_raw = built.cstring_at_va(p.va)
            if got_raw is None:
                problems.append("%s: VA %08x does not resolve to a string" % (p.row["id"], p.va))
                continue
        try:
            got = got_raw.decode("cp932")
        except UnicodeDecodeError:
            problems.append("%s: bytes at target do not decode" % p.row["id"])
            continue
        if got != want:
            problems.append("%s: reads back %r, expected %r" % (p.row["id"], got, want))
        checked += 1

    # ------------------------------------------------------- byte-level diff
    ranges = _authorised_ranges(base, placements)
    n = min(len(base.data), len(built_bytes))
    unauthorised = []
    i = 0
    while i < n:
        if base.data[i] != built_bytes[i]:
            if not _in_ranges(i, ranges):
                unauthorised.append(i)
                if len(unauthorised) > 32:
                    break
        i += 1
    if unauthorised:
        problems.append("%d unauthorised byte change(s), first at 0x%x"
                        % (len(unauthorised), unauthorised[0]))
    if len(built_bytes) < len(base.data):
        problems.append("built image is shorter than the base image")
    tail_start = len(base.data)
    if blob:
        eng = built.section(config.ENG_SECTION_NAME)
        if eng and eng["rawptr"] != tail_start:
            problems.append(".eng raw data does not start at the old EOF")

    # --------------------------------------------------------- font / charset
    fs, fe = config.FONT_TABLE_START, config.FONT_TABLE_END
    if built_bytes[fs:fe] != base.data[fs:fe]:
        problems.append("bitmap font table 0x%x..0x%x CHANGED" % (fs, fe))
    co = config.CHARSET_OFFSET
    if built_bytes[co:co + len(config.CHARSET_BYTES)] != config.CHARSET_BYTES:
        problems.append("SHIFTJIS_CHARSET push at 0x%x changed" % co)

    # ----------------------------------------------------------------- report
    print("verify: %s" % os.path.relpath(config.OUT_EXE, config.REPO_ROOT))
    print("  sections           : %d (%s)" % (built.numsec, ", ".join(s["name"] for s in built.sections)))
    print("  SizeOfImage        : %08x" % built.sizeimage)
    print("  strings checked    : %d (%d in place, %d via .eng)"
          % (checked,
             sum(1 for p in placements if p.kind == "inplace"),
             sum(1 for p in placements if p.kind == "eng")))
    print("  pointers rewritten : %d" % sum(len(p.refs) for p in placements if p.kind == "eng"))
    print("  bytes outside plan : %d" % len(unauthorised))
    print("  font table         : %s" % ("UNCHANGED" if built_bytes[fs:fe] == base.data[fs:fe] else "CHANGED"))
    print("  charset byte       : %s" % ("UNCHANGED" if built_bytes[co:co + 2] == config.CHARSET_BYTES else "CHANGED"))
    if problems:
        print("  PROBLEMS: %d" % len(problems))
        for p in problems:
            print("    - " + p)
        return 1
    print("  OK")
    return 0
