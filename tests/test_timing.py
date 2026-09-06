"""The tick-counted popup duration.

The patch is one immediate inside one instruction, so the things worth testing
are that the instruction is still the one we reverse-engineered, that only its
immediate changes, and that the call sites which pass an explicit duration are
left alone -- the `jge` above the default skips it for them.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten.exe import patch, timing  # noqa: E402
from giten.exe.pe import PE  # noqa: E402


def _release():
    return patch.apply(open(patch.ORG, "rb").read(), "release")


def test_the_default_is_the_instruction_we_think_it_is():
    img = _release()
    pe = PE(img, "t")
    off = pe.va2off(timing.POPUP_DEFAULT_SITE)
    assert img[off:off + 5] == timing.POPUP_DEFAULT_OLD
    assert img[off] == 0xB8, "not a mov eax, imm32"
    assert struct.unpack_from("<I", img, off + 1)[0] == 15

    # the clamp above it: cmp ax,1 / jge past the mov
    assert img[off - 6:off] == bytes.fromhex("663d01007d05")


def test_only_the_immediate_changes():
    img = _release()
    out = timing.apply(img)
    assert len(out) == len(img)
    diff = [i for i in range(len(img)) if img[i] != out[i]]
    pe = PE(img, "t")
    off = pe.va2off(timing.POPUP_DEFAULT_SITE)
    assert diff == [off + 1], diff          # one byte: 0x0F -> 0x3C
    assert out[off] == 0xB8
    assert struct.unpack_from("<I", out, off + 1)[0] == timing.POPUP_TICKS


def test_the_counter_is_a_u16_so_the_value_must_fit():
    img = _release()
    for bad in (0, -1, 0x8000):
        try:
            timing.apply(img, bad)
        except RuntimeError as exc:
            assert "outside the u16" in str(exc), exc
        else:
            raise AssertionError("%d ticks was accepted" % bad)
    timing.apply(img, 1)
    timing.apply(img, 0x7FFF)


def test_the_call_sites_are_what_the_docstring_claims_and_are_untouched():
    """Only one of the three passes a literal: 0x00406211 asks for 0x3C ticks
    and so never reaches the default.  The other two pass a computed value
    (0x004027E0 the config word at 0x47BB72, which is zero-initialised;
    0x004026CB a local), and reach the default whenever that value is < 1."""
    img = _release()
    pe = PE(img, "t")
    out = timing.apply(img)
    sites = {0x00406211: "6a3c",        # push 0x3C -- explicit, unaffected
             0x004027E0: "0050",        # push eax  -- from the 0x47BB72 getter
             0x004026CB: "0856"}        # push esi
    for va, want in sites.items():
        off = pe.va2off(va)
        assert img[off - 2:off].hex() == want, (hex(va), img[off - 2:off].hex())
        assert out[off - 2:off] == img[off - 2:off], "a call site changed"
    # the explicit caller's value is what we raise the default to
    assert timing.POPUP_TICKS == 0x3C


def test_it_refuses_an_image_whose_default_moved():
    img = bytearray(_release())
    pe = PE(bytes(img), "t")
    img[pe.va2off(timing.POPUP_DEFAULT_SITE)] ^= 0xFF
    try:
        timing.apply(bytes(img))
    except RuntimeError as exc:
        assert "not the original's" in str(exc), exc
    else:
        raise AssertionError("a moved default was accepted")


def test_the_release_exe_carries_it():
    from giten.exe import tracer

    img = tracer.build_image(False)
    pe = PE(img, "rel")
    off = pe.va2off(timing.POPUP_DEFAULT_SITE)
    assert struct.unpack_from("<I", img, off + 1)[0] == timing.POPUP_TICKS
    assert abs(timing.seconds(timing.POPUP_TICKS) - 1.0) < 1e-9
