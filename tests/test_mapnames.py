"""English location names.

One hook covers all 109 map files, so the things worth testing are that the
hook lands on the instruction we reverse-engineered, that the table it reads is
laid out where the assembled code expects, and -- the adversarial one -- that
resolving a name the way the *engine* will resolve it gives the English for a
translated map and the Japanese for an untranslated one.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import container, paths  # noqa: E402
from giten.exe import mapnames, patch  # noqa: E402
from giten.exe.pe import PE  # noqa: E402


def _release():
    return patch.apply(open(patch.ORG, "rb").read(), "release")


def test_the_hook_lands_on_the_parsers_name_computation():
    img = _release()
    pe = PE(img, "mn")
    off = pe.va2off(mapnames.HOOK_SITE)
    assert img[off:off + len(mapnames.HOOK_OLD)] == mapnames.HOOK_OLD
    # 66 8b 42 02 = mov ax,[edx+2]; 55 = push ebp; 03 c2 = add eax,edx
    assert mapnames.HOOK_OLD == bytes.fromhex("668b42025503c2")
    # and it is exactly seven bytes, which is what push ebp + call + nop needs
    assert len(mapnames.HOOK_OLD) == 7


def test_every_map_file_yields_a_name():
    jp = mapnames.japanese_names(paths.ORIGINAL_DDSWIN)
    assert len(jp) == 109, len(jp)
    assert all(0 <= mid < mapnames.MAPSLOTS for mid in jp)
    assert jp[0x0000] == "初台ｼｪﾙﾀｰ", jp[0x0000]


def test_names_are_refused_when_they_would_not_fit_or_encode():
    ok, findings = mapnames.plan({0: "Hatsudai Shelter"})
    assert ok == {0: "Hatsudai Shelter"} and not findings

    _ok, findings = mapnames.plan({0: "A" * (mapnames.NAME_CELLS + 1)})
    assert findings and "the bar fits" in findings[0][1]

    _ok, findings = mapnames.plan({0: "café naïve — dash"})
    assert findings, "a non-cp932 name was accepted"

    _ok, findings = mapnames.plan({mapnames.MAPSLOTS: "Too High"})
    assert findings and "outside" in findings[0][1]


def test_applying_the_hook_resolves_names_the_way_the_engine_will():
    img = _release()
    names = mapnames.read_table()
    assert names, "tables/mapnames.tsv has no English"
    out = mapnames.apply(img, names)

    pe = PE(out, "mn2")
    sec = pe.section(".mnm")
    assert sec is not None
    base = pe.imagebase + sec["vaddr"]

    # the call goes into our section, past the table
    off = pe.va2off(mapnames.HOOK_SITE)
    assert out[off] == 0x55 and out[off + 1] == 0xE8 and out[off + 6] == 0x90
    target = (mapnames.HOOK_SITE + 6 + struct.unpack_from("<i", out, off + 2)[0]) & 0xFFFFFFFF
    assert base + mapnames.TABLE_BYTES <= target < base + sec["vsize"]

    # now do what lookup() does: index the table by map id, and fall back to
    # header[1] + body when the slot is zero
    keep, _ = mapnames.plan(names)
    jp = mapnames.japanese_names(paths.ORIGINAL_DDSWIN)
    checked = 0
    for mid, jp_name in sorted(jp.items()):
        slot = struct.unpack_from("<I", out, pe.va2off(base) + mid * 4)[0]
        if mid in keep:
            assert slot, "map %04X has English but an empty slot" % mid
            got = pe.cstring_at_va(slot).decode("cp932")
            assert got == keep[mid], (mid, got, keep[mid])
        else:
            assert slot == 0, "map %04X has no English but a non-zero slot" % mid
            body = container.split(open(os.path.join(
                paths.ORIGINAL_DDSWIN, "m", "M%04X.BIN" % mid), "rb").read())[0][0].body
            o = struct.unpack_from("<H", body, 2)[0]
            assert body[o:body.find(b"\x00", o)].decode("cp932") == jp_name
        checked += 1
    assert checked == 109, checked


def test_the_hook_refuses_an_image_it_does_not_recognise():
    img = bytearray(_release())
    pe = PE(bytes(img), "mn")
    img[pe.va2off(mapnames.HOOK_SITE)] ^= 0xFF
    try:
        mapnames.apply(bytes(img), {0: "Hatsudai Shelter"})
    except RuntimeError as exc:
        assert "moved" in str(exc), exc
    else:
        raise AssertionError("a moved name computation was accepted")


def test_the_stub_has_no_undefined_symbols():
    code, syms = mapnames.assemble(0x01000000)   # raises if anything is undefined
    assert "lookup" in syms and code
