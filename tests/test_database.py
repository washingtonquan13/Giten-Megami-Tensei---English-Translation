"""Lifting the 64 KB ceiling off the item database: the three exe patches, and
the file they teach the game to read.

The patches assert the bytes they replace, so these tests are mostly about the
things an assertion cannot catch -- that we claim a file id the original does
not use, that the widened offset load is the instruction we think it is, and
that the chain we emit reassembles into exactly the body the builder produced.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import container, itemdb, paths  # noqa: E402
from giten.exe import database, patch  # noqa: E402
from giten.exe.pe import PE  # noqa: E402


def _release():
    return patch.apply(open(patch.ORG, "rb").read(), "release")


def test_the_file_id_we_claim_is_free():
    database.check_free(os.path.join(paths.ORIGINAL_DDSWIN, "et"))
    # and it must be positive: the router does `movsx ecx, bx` before %.4x,
    # so a high id would sign-extend and name a file that cannot exist
    assert 0 < database.ET_ID < 0x8000


def test_patches_land_on_the_instructions_we_reverse_engineered():
    img = _release()
    pe = PE(img, "db")
    off = pe.va2off(database.INIT_SITE)
    assert img[off:off + len(database.INIT_OLD)] == database.INIT_OLD
    off = pe.va2off(database.OFFSET_SITE)
    assert img[off:off + 5] == database.OFFSET_OLD
    # 66 8b 54 48 02 = mov dx, word [eax+ecx*2+2]; 8b 54 88 02 = the u32 form
    assert database.OFFSET_OLD == bytes.fromhex("668b544802")
    assert database.OFFSET_NEW[:4] == bytes.fromhex("8b548802")
    assert database.OFFSET_NEW[4] == 0x90 and len(database.OFFSET_NEW) == 5
    off = pe.va2off(database.RESOLVE_SITE)
    assert img[off] == 0xE8
    rel = struct.unpack_from("<i", img, off + 1)[0]
    assert (database.RESOLVE_SITE + 5 + rel) & 0xFFFFFFFF == database.RESOLVE_OLD_TARGET


def test_applying_the_patches_redirects_both_calls_into_our_section():
    img = _release()
    out = database.apply(img)
    pe = PE(out, "db2")
    sec = pe.section(".idb")
    assert sec is not None
    lo = pe.imagebase + sec["vaddr"]
    hi = lo + sec["vsize"]
    for site in (database.INIT_SITE, database.RESOLVE_SITE):
        off = pe.va2off(site)
        assert out[off] == 0xE8
        tgt = (site + 5 + struct.unpack_from("<i", out, off + 1)[0]) & 0xFFFFFFFF
        assert lo <= tgt < hi, "0x%08X -> 0x%08X is outside .idb" % (site, tgt)
    # the rest of the replaced run is padding, not stale code
    off = pe.va2off(database.INIT_SITE)
    assert out[off + 5:off + len(database.INIT_OLD)] == b"\x90" * (len(database.INIT_OLD) - 5)
    off = pe.va2off(database.OFFSET_SITE)
    assert out[off:off + 5] == database.OFFSET_NEW


def test_the_patches_refuse_an_image_they_do_not_recognise():
    img = bytearray(_release())
    pe = PE(bytes(img), "db")
    img[pe.va2off(database.OFFSET_SITE)] ^= 0xFF
    try:
        database.apply(bytes(img))
    except RuntimeError as exc:
        assert "offset load" in str(exc), exc
    else:
        raise AssertionError("a moved offset load was accepted")


def test_et0102_chain_reassembles_into_the_wide_body():
    recs = itemdb.parse(itemdb.source_body(paths.ORIGINAL_DDSWIN))
    blob = itemdb.pack_file(recs)
    cs, end = container.split(blob)
    assert end == len(blob), "the chain does not land on EOF"
    assert len(cs) > 1, "the point of the exercise is to need more than one container"
    assert all(c.hdr <= 0xFFFF for c in cs)
    assert b"".join(c.body for c in cs) == itemdb.build(recs, wide=True)
    # and the loader has room for it
    assert len(b"".join(c.body for c in cs)) <= itemdb.BUF_SIZE == database.BUF_SIZE


def test_the_wide_table_is_what_the_patched_load_instruction_reads():
    """u32 entries starting at +2, which is `[eax + ecx*4 + 2]`."""
    recs = itemdb.parse(itemdb.source_body(paths.ORIGINAL_DDSWIN))
    body = itemdb.build(recs, wide=True)
    count = struct.unpack_from("<H", body, 0)[0]
    for i in (1, 2, 300, count - 1):
        off = struct.unpack_from("<I", body, 2 + i * 4)[0]
        end = struct.unpack_from("<I", body, 2 + (i + 1) * 4)[0] if i + 1 < count else len(body)
        assert body[off:end] == recs[i].pack(), i


def test_the_allocator_cannot_be_asked_for_more_than_64k_in_one_argument():
    """0x00449640 masks *both* arguments to 16 bits and multiplies them.

    Asking for BUF_SIZE in one argument asks for (BUF_SIZE & 0xFFFF) -- zero,
    for a 0x20000 buffer -- and the loader then writes the whole database into
    it.  That is the crash this test exists to stop coming back: it is a fourth
    64 KB limit, and unlike the other three it is invisible until the game runs.
    """
    assert database.BUF_CHUNK <= 0xFFFF, database.BUF_CHUNK
    assert database.BUF_COUNT <= 0xFFFF, database.BUF_COUNT
    assert database.BUF_CHUNK * database.BUF_COUNT == database.BUF_SIZE
    assert (database.BUF_SIZE & 0xFFFF) != database.BUF_SIZE, \
        "BUF_SIZE now fits in 16 bits; the split is no longer load-bearing"

    # and the loader really does pass the pair, not the product
    src = open(database.SOURCE, encoding="utf-8").read()
    assert "push    BUF_COUNT" in src and "push    BUF_CHUNK" in src
    assert "push    BUF_SIZE" not in src, "the size is being passed in one argument again"


def test_the_loader_has_no_undefined_symbols_and_no_memory_operands():
    """An undefined --defsym does not fail the build, it silently becomes [0].

    `as` has no link step here: it emits a relocation, objcopy drops it, and
    the immediate is left as zero -- so `add ebx, BUF_SIZE` with BUF_SIZE
    missing from SYMBOLS assembles into `add ebx, dword ptr [0]`, which is a
    null dereference on the opening frame.  assemble() now refuses that; this
    pins it, and also checks the loader touches no absolute memory operand
    other than the one ds slot it is supposed to write.
    """
    from capstone import CS_ARCH_X86, CS_MODE_32, CS_OP_MEM, Cs

    blob, syms = database.assemble(0x01000000)          # raises on undefined symbols
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    absolute = []
    for ins in md.disasm(blob, 0x01000000):
        for op in ins.operands:
            if op.type == CS_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                absolute.append((ins.address, ins.mnemonic, ins.op_str, op.mem.disp))
    assert all(d == database.SYMBOLS["DEST"] for _, _, _, d in absolute), absolute
    assert absolute, "expected the store to ds:0x4800E8"
