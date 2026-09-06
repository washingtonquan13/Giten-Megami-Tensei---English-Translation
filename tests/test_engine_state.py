"""The rule that would have caught the Earth-Dragon-door crash.

Our injected code reads engine state through absolute addresses.  A POINTER the
engine legitimately nulls, or an INDEX used to compute an address, must be
guarded before use -- otherwise the fault is an access violation in a state the
engine considers normal, which is what killed the tracer.

These tests check the *built artifacts*, not the source, so they hold whatever
the compiler decides to emit.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten.exe import engine_state as es  # noqa: E402
from giten.exe import mapnames, patch, tracer  # noqa: E402
from giten.exe.pe import PE  # noqa: E402


def test_null_is_a_state_the_engine_chooses_not_corruption():
    """The proof the guard is required: the original exe has a function whose
    whole body nulls the script context."""
    img = patch.apply(open(patch.ORG, "rb").read(), "release")
    pe = PE(img, "o")
    for addr, (va, _desc) in es.KNOWN_NULLERS.items():
        off = pe.va2off(va)
        # c7 05 <addr> 00 00 00 00   mov dword ptr [addr], 0
        assert img[off:off + 2] == bytes.fromhex("c705"), img[off:off + 2].hex()
        assert struct.unpack_from("<I", img, off + 2)[0] == addr
        assert struct.unpack_from("<I", img, off + 6)[0] == 0
        assert img[off + 10] == 0xC3, "expected a ret right after"


def test_the_tracer_guards_every_pointer_and_index_it_reads():
    code = tracer.assemble()
    for addr in es.pointers() + es.indexes():
        bad = es.unguarded(code, addr)
        assert not bad, ("trace.S loads 0x%08X unguarded at %s"
                         % (addr, ["+0x%02X" % b for b in bad]))


def test_the_mapnames_hook_bounds_the_map_id():
    code, _syms = mapnames.assemble(0x01000000)
    bad = es.unguarded(code, mapnames.SYMBOLS["MAPID"])
    assert not bad, "mapnames.S indexes MAPTABLE without bounding the map id"
    # and the bound is the table size, not something larger
    assert es.INDEX_BOUND[mapnames.SYMBOLS["MAPID"]] == mapnames.MAPSLOTS


def test_the_release_hook_bounds_the_handle_before_indexing():
    """hook.c: `0x47605C + handle*8` computes an address, so the index has to
    be checked *before* the load -- there is no pointer to null-check after."""
    src = open(os.path.join(os.path.dirname(tracer.HOOK_SOURCE), "hook.c"),
               encoding="utf-8").read()
    assert "HANDLE_MAX" in src, "the handle bound is gone"
    i = src.index("HANDLE_BASE(handle)")
    before = src[:i]
    assert "handle >= HANDLE_MAX" in before, \
        "HANDLE_BASE(handle) is reached without bounding handle first"
    bound = int(src.split("#define HANDLE_MAX")[1].split()[0], 0)
    assert bound == es.INDEX_BOUND[0x0047605C]

    # the bound must keep the computed address inside .data
    img = patch.apply(open(patch.ORG, "rb").read(), "release")
    pe = PE(img, "o")
    data = pe.section(".data")
    top = 0x0047605C + bound * 8
    assert top <= pe.imagebase + data["vaddr"] + data["vsize"], \
        "handle bound 0x%X reads past .data" % bound


def test_every_address_in_the_registry_is_inside_the_image():
    img = patch.apply(open(patch.ORG, "rb").read(), "release")
    pe = PE(img, "o")
    for addr, (kind, desc, who) in es.ENGINE_STATE.items():
        sec = pe.sec_for_rva(addr - pe.imagebase)
        assert sec is not None, "0x%08X (%s) is not in any section" % (addr, desc)
        assert sec["name"] in (".data", ".rdata"), (hex(addr), sec["name"], desc)
        assert kind in (es.VALUE, es.POINTER, es.INDEX)
        assert who and desc


def test_unguarded_detects_a_missing_guard():
    """The detector has to actually detect -- check it against the real bug."""
    ctx = 0x00491160
    packed = struct.pack("<I", ctx)
    broken = bytes.fromhex("8b0d") + packed + bytes.fromhex("668b410e")
    assert es.unguarded(broken, ctx) == [2], es.unguarded(broken, ctx)

    fixed = bytes.fromhex("8b0d") + packed + bytes.fromhex("31c085c97404668b410e")
    assert es.unguarded(fixed, ctx) == []
