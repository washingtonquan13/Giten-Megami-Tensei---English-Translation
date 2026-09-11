"""The 16-bit loader, pinned at the four instructions the warp cave rests on.

`docs/limits.md` said for three days that "no loader has been found" for sixteen
`m/MS6xxx` files.  The loader was never missing: `0x00433D70` takes the file id
in a u16 and loads it on a miss.  What is missing is a *caller* that forms those
ids.  Everything the cave does depends on that, so it is asserted against the
shipped image rather than believed:

* the file id is compared as a **word**, so it is not a `u8` anywhere on the path;
* the miss path really does load, through the generic `m\\ms%.4x.bin` router entry;
* the loader reads **one container**, so a 16-bit load gives container 0 -- which
  is the container every record in the residue lives in.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import paths
from giten.exe import patch, warp16
from giten.exe.pe import PE


def _image():
    img = patch.apply(open(patch.ORG, "rb").read(), "release")
    return img, PE(img, "release")


def _at(va, n):
    img, pe = _image()
    off = pe.va2off(va)
    return img[off:off + n]


def test_goto_record_compares_the_file_id_as_a_full_sixteen_bit_word():
    """`cmp di,0xde` -- the special case for file 0xDE, and the proof of width.

    If the id were a u8 anywhere on this path the compare would be `cmp dil,..`
    or a byte test, and a cave passing 0x6200 would silently become 0x00.
    """
    assert _at(0x00433D82, 5) == bytes.fromhex("6681ffde00"), _at(0x00433D82, 5).hex()
    # and the two arguments land where the cave assumes: arg2 -> esi (record),
    # arg1 -> edi (file)
    assert _at(0x00433D79, 4) == bytes.fromhex("8b742414")     # mov esi,[esp+0x14]
    assert _at(0x00433D7E, 4) == bytes.fromhex("8b7c2414")     # mov edi,[esp+0x14]


def test_a_miss_loads_the_file_through_the_generic_script_router_entry():
    """`0x0043AD20(list, id)` = `0x00401DD0(id, kind 9, 0)`, then install, then stamp."""
    img, pe = _image()
    # push 0; push 9; push ebx(id); call 0x401DD0
    assert _at(0x0043AD27, 5) == bytes.fromhex("6a006a0953")
    off = pe.va2off(0x0043AD2C)
    assert img[off] == 0xE8
    rel = struct.unpack_from("<i", img, off + 1)[0]
    assert (0x0043AD2C + 5 + rel) & 0xFFFFFFFF == 0x00401DD0
    # and the id is stamped into the new buffer as a u16: mov WORD PTR [edi],bx
    assert _at(0x0043AD47, 3) == bytes.fromhex("66891f")


def test_the_loader_reads_exactly_one_container_per_call():
    """`0x0043AA90` has one record loop and no container loop.

    That is what makes a 16-bit warp land in container 0: the sixteen-container
    behaviour of the `m/MS6xxx` family comes from `0x0040EB00` calling this
    function sixteen times on one open file, not from the function itself.
    """
    img, pe = _image()
    lo, hi = pe.va2off(0x0043AA90), pe.va2off(0x0043AB0B)
    body = img[lo:hi]
    # the only backward jump in the function is the `jne` that closes the
    # per-record loop at 0x43AB03 -> 0x43AAEE
    backward = []
    i = 0
    while i < len(body) - 1:
        if body[i] in (0x75, 0x74, 0xEB) and body[i + 1] >= 0x80:
            backward.append(0x0043AA90 + i)
        i += 1
    assert backward == [0x0043AB03], [hex(b) for b in backward]


def test_the_router_table_has_one_script_entry_and_the_cave_knows_which():
    from giten import loaders
    kinds = loaders.router_kinds()
    assert len(kinds) == loaders.ROUTER_KINDS == 16
    assert kinds[loaders.SCRIPT_KIND] == loaders.SCRIPT_KIND_HANDLER
    # `cmp eax,0xF; ja` is what bounds the table
    assert _at(0x00401E20, 3) == bytes.fromhex("83f80f")


def test_the_cave_targets_the_addresses_this_file_pinned():
    assert warp16.GOTO_RECORD == 0x00433D70
    assert warp16.SET_PC == 0x00433C40
    # set_pc is `mov ecx,[0x491160]; mov ax,[esp+4]; mov [ecx+0x0E],ax; ret`
    assert _at(warp16.SET_PC, 16) == bytes.fromhex(
        "8b0d60114900"      # mov ecx, ds:0x491160   -- the script context
        "668b442404"        # mov ax, [esp+4]        -- the new pc, a u16
        "6689410e"          # mov [ecx+0x0E], ax
        "c3")               # ret
