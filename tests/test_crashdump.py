"""Crash triage.

The point of this module is to answer one question fast: is a fault in the
original game or in code we appended?  Getting that backwards cost a lot of
guessing, so both directions are tested against the real exe.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import crashdump  # noqa: E402
from giten.exe import patch, timing, tracer  # noqa: E402
from giten.exe.pe import PE  # noqa: E402

BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "build", "exe", "dds_dev.exe")


def _dev_exe():
    if not os.path.exists(BUILD):
        os.makedirs(os.path.dirname(BUILD), exist_ok=True)
        with open(BUILD, "wb") as fh:
            fh.write(tracer.build_image(True))
    return BUILD


def test_a_fault_in_the_original_text_is_reported_as_the_games():
    exe = _dev_exe()
    where = crashdump.locate(timing.POPUP_DEFAULT_SITE, exe)
    assert ".text +" in where, where
    assert not any((" %s +" % s) in where for s in crashdump.OURS)


def test_a_fault_in_an_appended_section_is_reported_as_ours():
    exe = _dev_exe()
    pe = PE(open(exe, "rb").read(), "t")
    for name in (".ovl", ".trc", ".men", ".mnm", ".idb", ".nam"):
        sec = pe.section(name)
        assert sec is not None, name
        va = pe.imagebase + sec["vaddr"] + 0x10
        where = crashdump.locate(va, exe)
        assert ("%s + 0x10" % name) in where, (name, where)
        assert name in crashdump.OURS


def test_the_instruction_that_crashed_the_tracer_maps_to_trc():
    """The regression this whole exercise came from: EIP 0x01040074."""
    exe = _dev_exe()
    pe = PE(open(exe, "rb").read(), "t")
    trc = pe.section(".trc")
    va = pe.imagebase + trc["vaddr"] + 0x74
    where = crashdump.locate(va, exe)
    assert ".trc + 0x74" in where, where


def _synthetic_dump(code=0xC0000005, params=(0, 0x0E), eip=0x01040074):
    """A minimal MINIDUMP with just an exception stream + x86 context."""
    ctx = bytearray(0xCC)
    struct.pack_into("<I", ctx, 0xB8, eip)          # Eip
    struct.pack_into("<I", ctx, 0xAC, 0)            # Ecx = 0
    struct.pack_into("<I", ctx, 0xC4, 0x001AFE60)   # Esp

    hdr = 32
    dir_off = hdr
    stream_off = dir_off + 12
    exc = bytearray(8 + 32 + 15 * 8 + 8)
    struct.pack_into("<I", exc, 0, 1234)                      # thread id
    struct.pack_into("<IIQQII", exc, 8, code, 0, 0, eip, len(params), 0)
    for i, p in enumerate(params):
        struct.pack_into("<Q", exc, 8 + 32 + i * 8, p)
    ctx_rva = stream_off + len(exc)
    struct.pack_into("<II", exc, 8 + 32 + 15 * 8, len(ctx), ctx_rva)

    blob = bytearray(b"\x00" * stream_off)
    struct.pack_into("<4sIII", blob, 0, b"MDMP", 42899, 1, dir_off)
    struct.pack_into("<III", blob, dir_off, crashdump.EXCEPTION_STREAM,
                     len(exc), stream_off)
    blob += exc + ctx
    return bytes(blob)


def test_reading_a_dump_recovers_the_fault_and_the_registers(tmp=None):
    import tempfile

    path = os.path.join(tempfile.mkdtemp(prefix="giten-dmp-"), "x.dmp")
    with open(path, "wb") as fh:
        fh.write(_synthetic_dump())
    d = crashdump.read(path)
    assert d["code"] == 0xC0000005
    assert d["params"] == [0, 0x0E]
    assert d["regs"]["Eip"] == 0x01040074
    assert d["regs"]["Ecx"] == 0

    text = crashdump.explain(path, _dev_exe())
    assert "ACCESS_VIOLATION" in text
    assert "read of 0x0000000E" in text
    assert "null pointer" in text
    assert ".trc + 0x74" in text
    assert "OUR injected code" in text


def test_a_dump_that_is_not_a_dump_is_refused():
    import tempfile

    path = os.path.join(tempfile.mkdtemp(prefix="giten-dmp-"), "no.dmp")
    with open(path, "wb") as fh:
        fh.write(b"not a dump at all")
    try:
        crashdump.read(path)
    except crashdump.DumpError as exc:
        assert "not a minidump" in str(exc), exc
    else:
        raise AssertionError("garbage was accepted as a dump")
