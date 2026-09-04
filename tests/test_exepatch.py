# -*- coding: utf-8 -*-
"""Tests for tools/exepatch.

The structural tests build a tiny synthetic PE32 in memory, so they run with no
game files present.  The two end-to-end tests at the bottom exercise the real
``dds_en.exe`` and quietly no-op when the game folder is not installed.
"""
from __future__ import annotations

import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.exepatch import build as build_mod
from tools.exepatch import check as check_mod
from tools.exepatch import config, scan, table
from tools.exepatch.pe import PE, PEError

IMAGE_BASE = 0x400000
SEC_ALIGN = 0x1000
FILE_ALIGN = 0x200


# --------------------------------------------------------------------------
# A synthetic PE32 with .text / .rdata / .data, laid out like the real image
# (section table followed by zeroed header slack, raw data file-aligned).
# --------------------------------------------------------------------------

def make_pe(text=b"", rdata=b"", data=b""):
    e_lfanew = 0x80
    sizeopt = 0xE0
    numsec = 3
    sectbl = e_lfanew + 4 + 20 + sizeopt
    assert sectbl + numsec * 40 <= 0x400

    secs = [
        (b".text", 0x1000, 0x400, text, 0x60000020),
        (b".rdata", 0x2000, 0x600, rdata, 0x40000040),
        (b".data", 0x3000, 0x800, data, 0xC0000040),
    ]
    size_image = 0x4000
    img = bytearray(0xA00)
    img[0:2] = b"MZ"
    struct.pack_into("<I", img, 0x3C, e_lfanew)
    img[e_lfanew:e_lfanew + 4] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", img, e_lfanew + 4,
                     0x14C, numsec, 0, 0, 0, sizeopt, 0x010F)
    oh = e_lfanew + 24
    struct.pack_into("<H", img, oh, 0x10B)
    struct.pack_into("<BBIIIIIII", img, oh + 2,
                     6, 0, 0x200, 0x400, 0, 0x1000, 0x1000, 0x2000, IMAGE_BASE)
    struct.pack_into("<II", img, oh + 32, SEC_ALIGN, FILE_ALIGN)
    struct.pack_into("<II", img, oh + 56, size_image, 0x400)
    struct.pack_into("<I", img, oh + 64, 0)            # CheckSum
    struct.pack_into("<I", img, oh + 92, 16)           # NumberOfRvaAndSizes
    for i, (name, vaddr, rawptr, payload, flags) in enumerate(secs):
        base = sectbl + i * 40
        struct.pack_into("<8sIIIIIIHHI", img, base,
                         name.ljust(8, b"\0"), 0x200, vaddr, 0x200, rawptr,
                         0, 0, 0, 0, flags)
        img[rawptr:rawptr + len(payload)] = payload
    return bytes(img)


def mkrow(**kw):
    r = table.Row()
    for col in table.COLUMNS:
        r[col] = kw.pop(col, "")
    assert not kw, kw
    return r


def data_row(off, jp, en, slot, refs=(), record_width="", note=""):
    return mkrow(id="data_%06x" % off,
                 file_off="%08x" % off,
                 va="%08x" % (IMAGE_BASE + 0x3000 + (off - 0x800)),
                 section=".data",
                 slot_bytes=str(slot),
                 refs=",".join("%08x" % v for v in refs),
                 record_width=str(record_width),
                 max_cols=str(slot - 1),
                 jp=table.esc(jp),
                 en=table.esc(en),
                 note=note)


# --------------------------------------------------------------------------
# table escaping
# --------------------------------------------------------------------------

def test_table_escape_round_trip():
    for s in ["plain", "tab\there", "line\nbreak", "back\\slash",
              "\x12Confus", "属性　 %c/%c\n", ""]:
        got = table.unesc(table.esc(s))
        assert got == s, (s, table.esc(s), got)
    # every escaped form is a single physical line with no stray tabs
    assert "\t" not in table.esc("a\tb")
    assert "\n" not in table.esc("a\nb")


# --------------------------------------------------------------------------
# in-place writes
# --------------------------------------------------------------------------

def test_inplace_write_pads_the_whole_slot_with_nuls():
    data = b"abcdefg\0\0\0\0\0LIVE\0"
    pe = PE(make_pe(data=data))
    row = data_row(0x800, "abcdefg", "hi", slot=12, refs=(0x401000,))
    placements, blob, errors = build_mod.plan(pe, [row])
    assert errors == [], errors
    assert blob == b"", "a shorter string must not reach .eng"
    assert [p.kind for p in placements] == ["inplace"]

    out = build_mod.apply(pe, placements, blob)
    assert out[0x800:0x80C] == b"hi\0\0\0\0\0\0\0\0\0\0"
    # the live neighbour after the slot is untouched
    assert out[0x80C:0x811] == b"LIVE\0"
    # and the image is otherwise byte-identical
    assert out[:0x800] == pe.data[:0x800]
    assert out[0x811:] == pe.data[0x811:]


def test_inplace_respects_record_width_over_a_longer_nul_run():
    # A status-table style record: id byte, name, padding -- the slot run reaches
    # into the next record, but the record width is the real budget.
    data = b"\x01ab\0\0\0\0\0\x02cd\0\0\0\0\0"
    pe = PE(make_pe(data=data))
    row = data_row(0x800, "\x01ab", "\x01Dead", slot=8, record_width=8,
                   refs=())
    placements, blob, errors = build_mod.plan(pe, [row])
    assert errors == [], errors
    out = build_mod.apply(pe, placements, blob)
    assert out[0x800:0x808] == b"\x01Dead\0\0\0"
    assert out[0x808:0x810] == b"\x02cd\0\0\0\0\0"

    # one byte too many for the record is refused, not silently truncated
    row2 = data_row(0x800, "\x01ab", "\x01Deceased", slot=8, record_width=8)
    _, _, errors2 = build_mod.plan(pe, [row2])
    assert len(errors2) == 1 and "record width" in errors2[0]


# --------------------------------------------------------------------------
# relocation into .eng
# --------------------------------------------------------------------------

def test_pointer_rewrite_round_trip():
    string_va = IMAGE_BASE + 0x3000
    # .text holds `push <string va>` twice; both must be repointed.
    text = b"\x68" + struct.pack("<I", string_va) + b"\x90" * 3 \
           + b"\x68" + struct.pack("<I", string_va) + b"\xc3"
    data = b"ab\0\0"
    pe = PE(make_pe(text=text, data=data))

    ref_vas = (IMAGE_BASE + 0x1001, IMAGE_BASE + 0x1009)
    for va in ref_vas:
        assert struct.unpack_from("<I", pe.data, pe.va2off(va))[0] == string_va

    row = data_row(0x800, "ab", "a considerably longer replacement",
                   slot=4, refs=ref_vas)
    placements, blob, errors = build_mod.plan(pe, [row])
    assert errors == [], errors
    assert [p.kind for p in placements] == ["eng"]
    out_bytes = build_mod.apply(pe, placements, blob)

    out = PE(out_bytes)
    eng = out.section(config.ENG_SECTION_NAME)
    assert eng is not None
    new_va = placements[0].va
    assert new_va == IMAGE_BASE + pe.sizeimage
    for va in ref_vas:
        got = struct.unpack_from("<I", out.data, out.va2off(va))[0]
        assert got == new_va, (hex(got), hex(new_va))
    assert out.cstring_at_va(new_va) == b"a considerably longer replacement"
    # the original bytes are left where they were -- only the pointers moved
    assert out.data[0x800:0x804] == b"ab\0\0"


def test_identical_replacements_share_one_copy_in_eng():
    string_a = IMAGE_BASE + 0x3000
    string_b = IMAGE_BASE + 0x3008
    text = b"\x68" + struct.pack("<I", string_a) + b"\x68" + struct.pack("<I", string_b) + b"\xc3"
    data = b"aa\0\0\0\0\0\0bb\0\0"
    pe = PE(make_pe(text=text, data=data))
    rows = [
        data_row(0x800, "aa", "the same long text", slot=8, refs=(IMAGE_BASE + 0x1001,)),
        data_row(0x808, "bb", "the same long text", slot=4, refs=(IMAGE_BASE + 0x1006,)),
    ]
    placements, blob, errors = build_mod.plan(pe, rows)
    assert errors == [], errors
    assert len(placements) == 2
    assert placements[0].va == placements[1].va
    assert blob.count(b"the same long text") == 1


def test_relocation_without_a_reference_is_refused():
    pe = PE(make_pe(data=b"ab\0\0"))
    row = data_row(0x800, "ab", "far too long for this slot", slot=4, refs=())
    placements, blob, errors = build_mod.plan(pe, [row])
    assert placements == [] and blob == b""
    assert len(errors) == 1 and "no imm32 reference" in errors[0]


# --------------------------------------------------------------------------
# section append
# --------------------------------------------------------------------------

def test_append_section_keeps_the_pe_parseable_and_every_other_byte_identical():
    pe = PE(make_pe(data=b"hello\0"))
    blob = b"NEW STRING\0"
    out_bytes = pe.append_section(".eng", blob, config.ENG_CHARACTERISTICS)
    out = PE(out_bytes)

    assert out.numsec == pe.numsec + 1
    eng = out.section(".eng")
    assert eng["vaddr"] == pe.sizeimage
    assert eng["vsize"] == len(blob)
    assert eng["rawptr"] == len(pe.data)
    assert eng["rawsize"] == FILE_ALIGN
    assert eng["flags"] == config.ENG_CHARACTERISTICS
    assert out.sizeimage == pe.sizeimage + SEC_ALIGN
    assert out.rva2off(eng["vaddr"]) == eng["rawptr"]
    assert out_bytes[eng["rawptr"]:eng["rawptr"] + len(blob)] == blob

    # Every pre-existing section header is untouched.
    for a, b in zip(pe.sections, out.sections):
        assert a == b

    # Only three header fields and the new section header may differ.
    allowed = set()
    allowed.update(range(pe.file_header_off + 2, pe.file_header_off + 4))
    allowed.update(range(pe.opt_off + 10, pe.opt_off + 14))
    allowed.update(range(pe.opt_off + 56, pe.opt_off + 60))
    hdr = pe.sectbl_off + pe.numsec * 40
    allowed.update(range(hdr, hdr + 40))
    diff = [i for i in range(len(pe.data)) if pe.data[i] != out_bytes[i]]
    assert set(diff) <= allowed, [hex(i) for i in diff if i not in allowed]

    # And the appended raw data is exactly blob + file-alignment padding.
    assert out_bytes[len(pe.data):] == blob.ljust(FILE_ALIGN, b"\0")


def test_append_section_refuses_when_the_header_slack_is_occupied():
    raw = bytearray(make_pe())
    pe = PE(bytes(raw))
    hdr = pe.sectbl_off + pe.numsec * 40
    raw[hdr] = 0x41
    try:
        PE(bytes(raw)).append_section(".eng", b"x\0", config.ENG_CHARACTERISTICS)
    except PEError as exc:
        assert "slack" in str(exc)
    else:
        raise AssertionError("expected a PEError")


# --------------------------------------------------------------------------
# validators
# --------------------------------------------------------------------------

def test_format_specifier_validator():
    same = [
        ("属性　 %c/%c\n", "Align  %c/%c\n"),
        ("合計 %10ld   ", "Total %10ld   "),
        ("と%sを付け替えた", " replaced %s"),
        ("100%% sure", "100%% sure"),
    ]
    for jp, en in same:
        assert check_mod.spec_kinds(jp) == check_mod.spec_kinds(en), (jp, en)

    differ = [
        ("%s and %d", "%d and %s"),          # reordered -> wrong argument types
        ("%d/%d", "%d"),                     # dropped an argument
        ("%s", "%ld"),                       # changed the conversion
        ("合計 %10ld", "Total %10d"),  # dropped the length modifier
    ]
    for jp, en in differ:
        assert check_mod.spec_kinds(jp) != check_mod.spec_kinds(en), (jp, en)

    # A field-width change keeps the same kinds but is still reported as a diff.
    assert check_mod.spec_kinds("%10ld") == check_mod.spec_kinds("%6ld")
    assert check_mod.format_specs("%10ld") != check_mod.format_specs("%6ld")


def test_width_budget_uses_eight_pixels_per_ascii_cell():
    assert scan.display_width("HP") == 2 * config.ASCII_CELL_PX
    assert scan.display_width("ＨＰ") == 2 * config.WIDE_CELL_PX
    # printf specifiers and newlines do not contribute
    assert scan.display_width("HP     %d/%d\n") == len("HP     /") * config.ASCII_CELL_PX
    # a leading status-table record id is not rendered
    assert scan.display_width("\x12Confus") == 6 * config.ASCII_CELL_PX


def test_font_table_and_charset_guard():
    # A row that lands inside the bitmap font table is refused by the planner,
    # whatever the table says.
    pe = PE(make_pe(data=b"ab\0\0"))
    row = data_row(0x800, "ab", "xy", slot=4, refs=(0x401000,))
    old = (config.FONT_TABLE_START, config.FONT_TABLE_END)
    config.FONT_TABLE_START, config.FONT_TABLE_END = 0x7F0, 0x810
    try:
        placements, blob, errors = build_mod.plan(pe, [row])
    finally:
        config.FONT_TABLE_START, config.FONT_TABLE_END = old
    assert placements == []
    assert len(errors) == 1 and "font table" in errors[0]

    # Outside the guard the same row patches normally.
    placements, _, errors = build_mod.plan(pe, [row])
    assert errors == [] and [p.kind for p in placements] == ["inplace"]

    # The charset guard is a fixed two-byte signature, not a moving target.
    assert config.CHARSET_BYTES == b"\x6a\x80"
    assert config.CHARSET_VALUE_OFFSET == config.CHARSET_OFFSET + 1


def test_skip_note_stops_the_planner():
    pe = PE(make_pe(data=b"ab\0\0"))
    row = data_row(0x800, "ab", "xy", slot=4, refs=(0x401000,), note="@skip debug-menu")
    placements, blob, errors = build_mod.plan(pe, [row])
    assert placements == [] and errors == []


# --------------------------------------------------------------------------
# end-to-end, only when the game is actually installed
# --------------------------------------------------------------------------

def _have_game():
    return os.path.exists(config.EN_EXE) and os.path.exists(config.TABLE_PATH)


def test_real_table_passes_check():
    if not _have_game():
        print("      (skipped: %s not found)" % config.EN_EXE)
        return
    import argparse
    assert check_mod.run(argparse.Namespace()) == 0


def test_real_build_verifies():
    if not _have_game():
        print("      (skipped: %s not found)" % config.EN_EXE)
        return
    import argparse
    from tools.exepatch import verify as verify_mod
    assert build_mod.run(argparse.Namespace(verbose=False, force=False)) == 0
    assert verify_mod.run(argparse.Namespace()) == 0

    with open(config.OUT_EXE, "rb") as fh:
        out = fh.read()
    with open(config.EN_EXE, "rb") as fh:
        base = fh.read()
    fs, fe = config.FONT_TABLE_START, config.FONT_TABLE_END
    assert out[fs:fe] == base[fs:fe]
    co = config.CHARSET_OFFSET
    assert out[co:co + 2] == config.CHARSET_BYTES
