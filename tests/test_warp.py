"""`giten warp`: the jump, the tree, and the dev cave that makes it 16-bit.

Three things have to hold for a warp trace to be evidence about the *original*
bytes:

1. the injection changes `m/MS0017` r01 and nothing else, in place, so no
   record's runtime base moves;
2. the target file is untouched;
3. the cave that carries a 16-bit file id claims a byte no real script uses, and
   reads no engine state without the guard `engine_state` requires.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import files, paths, script, warp
from giten.exe import engine_state, warp16


def test_the_injection_changes_one_record_in_place():
    raw = files.read_source(warp.SRC_REL, paths.ORIGINAL_DDSWIN)
    out = warp.patch_injection(raw, warp.warp_bytes(0x31, 0x00))
    assert len(out) == len(raw), (len(out), len(raw))
    assert warp.changed_records(raw, out) == [warp.SRC_REC]


def test_the_injected_jump_tiles_as_one_goto_record_token():
    raw = files.read_source(warp.SRC_REL, paths.ORIGINAL_DDSWIN)
    out = warp.patch_injection(raw, warp.warp_bytes(0x31, 0x17))
    sc = script.parse(warp.SRC_REL, out)
    assert sc.ok, sc.error
    rec = next(r for r in sc.containers[0] if r.id == warp.SRC_REC)
    t = rec.tokens[0]
    assert (t.kind, t.idx, t.size) == ("op", 0x00C, 3), (t.kind, t.idx, t.size)
    assert rec.data[:3] == bytes([0x0C, 0x31, 0x17])


def test_the_sentinel_file_byte_is_used_by_no_script_in_the_corpus():
    """The cave may only claim a `0C`/`0D` operand nothing real can emit.

    Also checked: it is below 0xE0.  Ids 0xE0..0xFF take the demon-merge arm at
    `0x00433CA8`, where an id the merge has not filled walks a table of null
    pointers -- so a cave that failed to fire on one of those would not fall
    back, it would crash.
    """
    assert warp.SENTINEL_FILE < 0xE0
    assert warp.SENTINEL_FILE == warp16.SENTINEL
    for rel in files.iter_files(("ms", "id")):
        sc = script.parse(rel, files.read_source(rel))
        if not sc.ok:
            continue
        for ci, cont in enumerate(sc.containers):
            for r in cont:
                toks = r.span_tokens
                if not toks:
                    continue
                for t in toks:
                    if t.kind == "op" and t.idx in (0x00C, 0x00D):
                        if t.off + 2 < len(r.data):
                            assert r.data[t.off + 1] != warp.SENTINEL_FILE, (
                                "%s c%d r%02X @0x%X emits the warp sentinel"
                                % (rel, ci, r.id, t.off))


def test_the_cave_guards_the_only_engine_pointer_it_reads():
    blob = warp16.assemble(0x6200, 0x16, 9)
    assert engine_state.unguarded(blob, 0x00491160) == [], (
        "the cave dereferences the script context without a null check")
    # and it reads nothing else
    for addr, (kind, _d, _w) in engine_state.ENGINE_STATE.items():
        if addr == 0x00491160:
            continue
        assert struct.pack("<I", addr) not in blob, (
            "the cave reads 0x%08X, which is not declared for it" % addr)


def test_every_absolute_call_the_cave_makes_is_a_registered_engine_function():
    """`mov eax, <imm32>; call eax` is the only call form the cave uses."""
    blob = warp16.assemble(0x6200, 0x16, 0)
    targets = set()
    i = blob.find(b"\xB8")
    while i >= 0:
        if blob[i + 5:i + 7] == b"\xFF\xD0":
            targets.add(struct.unpack_from("<I", blob, i + 1)[0])
        i = blob.find(b"\xB8", i + 1)
    assert targets == {warp16.GOTO_RECORD, warp16.SET_PC}, sorted(targets)
    for t in targets:
        assert t in engine_state.ENGINE_CALLS, (
            "0x%08X is called but not declared in ENGINE_CALLS" % t)


def test_the_cave_bytes_are_pinned():
    """The whole cave, byte for byte, for one fixed target.

    Pinned the way `tests/test_restart.py` pins `trace.S`: this is code that
    runs inside the game on a path the game takes constantly, so a change to it
    has to be deliberate.  If this fails, read the new bytes before re-baselining.
    """
    blob = warp16.assemble(0x6200, 0x16, 0, sentinel=warp.SENTINEL_FILE,
                           match_rec=warp16.ANY_REC)
    want = bytes.fromhex(
        "8b442404"              # mov eax,[esp+4]          -- the file id
        "663dd900"              # cmp ax,0xD9              -- WARP_SENTINEL
        "7554"                  # jne passthrough
        "baffff0000"            # mov edx,0xFFFF           -- WARP_MATCH_REC
        "6683faff"              # cmp dx,0xFFFF            -- 0xFFFF = any record
        "7407"                  # je fire
        "663b542408"            # cmp dx,word [esp+8]      -- the record
        "7542"                  # jne passthrough
        "b800620000"            # fire: mov eax,0x6200     -- WARP_FILE
        "6683f8ff"              # cmp ax,0xFFFF            -- no target pinned?
        "7437"                  # je  passthrough
        "6a16"                  # push 0x16                -- WARP_REC
        "50"                    # push eax
        "b8703d4300" "ffd0"     # mov eax,0x433D70; call eax
        "83c408"                # add esp,8
        "b800000000"            # mov eax,0                -- WARP_ENTRY
        "6685c0"                # test ax,ax
        "741f"                  # je done
        "8b0d60114900"          # mov ecx,ds:0x491160      -- CTX (POINTER)
        "85c9"                  # test ecx,ecx             -- the guard
        "7415"                  # je done
        "0fb7510e"              # movzx edx,word [ecx+0x0E]
        "6601c2"                # add dx,ax
        "0fb7d2"                # movzx edx,dx
        "52"                    # push edx
        "b8403c4300" "ffd0"     # mov eax,0x433C40; call eax
        "83c404"                # add esp,4
        "c3"                    # done: ret
        "8b442408"              # passthrough: mov eax,[esp+8]
        "8b4c2404"              # mov ecx,[esp+4]
        "50" "51"               # push eax; push ecx
        "b8703d4300" "ffd0"     # mov eax,0x433D70; call eax
        "83c408"                # add esp,8
        "c3")                   # ret
    assert blob[:len(want)] == want, blob.hex(" ")
    assert set(blob[len(want):]) <= {0x90}, "unexpected tail: %s" % blob[len(want):].hex()


def test_the_cave_claims_every_call_to_goto_record_and_no_other():
    """The list of call sites is scanned for, not trusted.

    One site would do for a `0C` a script executes, but the negotiation is
    entered by the engine (`0x00438D70`), so a cave that hooked only the `0C`
    handler could never rewrite that jump -- which is how `m/MS610D` c0 r1B and
    c3 rCE are reached at all, since nothing in the data names them.
    """
    org = os.path.join(paths.ORIGINAL_DDSWIN, "dds_org.exe")
    if not os.path.exists(org):
        raise AssertionError("original exe missing: %s" % org)
    from giten.exe.pe import PE
    image = open(org, "rb").read()
    pe = PE(image, "dds_org")
    text = [s for s in pe.sections if s["name"] == ".text"][0]
    lo, hi = text["rawptr"], text["rawptr"] + text["rawsize"]
    found = []
    at = image.find(b"\xE8", lo, hi - 5)
    while at >= 0:
        rel = struct.unpack_from("<i", image, at + 1)[0]
        if (pe.off2va(at) + 5 + rel) & 0xFFFFFFFF == warp16.GOTO_RECORD:
            found.append(pe.off2va(at))
        at = image.find(b"\xE8", at + 1, hi - 5)
    assert sorted(found) == sorted(warp16.CALL_SITES), [hex(f) for f in found]
    assert warp16.CALL_SITE in warp16.CALL_SITES


def test_a_tree_hardlinks_the_data_and_overrides_only_what_it_must():
    import tempfile
    tmp = tempfile.mkdtemp(prefix="giten-warp-")
    tree = os.path.join(tmp, "t")
    try:
        raw = files.read_source(warp.SRC_REL, paths.ORIGINAL_DDSWIN)
        over = {warp.SRC_REL: warp.patch_injection(raw, warp.warp_bytes(0x31, 0x00))}
        n = warp.materialise(tree, overrides=over)
        assert n > 2000, n
        got = open(os.path.join(tree, "m", "MS0017.BIN"), "rb").read()
        assert got == over[warp.SRC_REL]
        assert (open(os.path.join(tree, "m", "MS0031.BIN"), "rb").read()
                == files.read_source("m/MS0031.BIN", paths.ORIGINAL_DDSWIN))
        # the original exes are not in a warp tree; the dev build is added later
        assert not os.path.exists(os.path.join(tree, "dds.exe"))
        assert os.path.exists(os.path.join(tree, "Config.exe"))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_installing_the_cave_repoints_every_goto_record_call_and_nothing_else():
    """On the real image: five calls moved, the target function untouched."""
    from giten.exe import patch
    from giten.exe.pe import PE
    base = patch.apply(open(patch.ORG, "rb").read(), "release")
    pe0 = PE(base, "release")
    cave_va = pe0.imagebase + pe0.sizeimage
    out = warp16.install(base, 0x6200, 0x16, 0)
    pe = PE(out, "warp")
    for site in warp16.CALL_SITES:
        off = pe.va2off(site)
        rel = struct.unpack_from("<i", out, off + 1)[0]
        assert (site + 5 + rel) & 0xFFFFFFFF == cave_va, hex(site)
    # goto-record itself is not patched: the cave calls the original
    assert out[pe.va2off(warp16.GOTO_RECORD):
               pe.va2off(warp16.GOTO_RECORD) + 8] == \
        base[pe0.va2off(warp16.GOTO_RECORD):pe0.va2off(warp16.GOTO_RECORD) + 8]
    # and the cave itself is there, at the end
    assert warp16.assemble(0x6200, 0x16, 0) in out


# --- the negotiation variant (m/MS610D) -------------------------------------
def test_et0007_is_twenty_five_three_byte_rows_read_in_the_clear():
    """The table `0x0040EB70` merges from, and the one thing it never names.

    Read straight out of the file with no decryption, because `0x00401D90`
    freads the length word and then the body: two `fread`s, no call to the
    cipher.  If this ever needed `container.split`, every row below would be
    different bytes and the whole variant would be aimed at the wrong file.
    """
    raw = files.read_source(warp.ET0007_REL, paths.ORIGINAL_DDSWIN)
    rows = warp.et0007_rows(raw)
    assert len(rows) == warp.ET0007_ROWS == 25
    t2 = {r[2] for r in rows if r[2] != 0xFF}
    assert t2 == {0x00, 0x06, 0x07, 0x08, 0x09, 0x0B, 0x0C}, sorted(t2)
    assert 0x0D not in t2, "the shipped table now names m/MS610D by itself"


def test_the_variant_changes_exactly_one_byte_and_that_byte_names_ms610d():
    raw = files.read_source(warp.ET0007_REL, paths.ORIGINAL_DDSWIN)
    out = warp.et0007_with(raw, 5, 0x0D)
    assert len(out) == len(raw)
    diff = [i for i, (a, b) in enumerate(zip(raw, out)) if a != b]
    assert diff == [2 + 5 * 3 + 2], diff
    assert warp.et0007_rows(out)[5][2] == 0x0D
    # the demon's own files are still merged: only the third column moved
    assert warp.et0007_rows(out)[5][:2] == warp.et0007_rows(raw)[5][:2]


def test_the_chosen_row_is_the_one_pixie_uses():
    """Row 5 is picked because its cheapest member is the game's first demon.

    The row a demon uses is the u16 at 0x73 of its own `p/P####.BIN` record --
    the merge descriptor copies that record to +0x04 and reads the field at
    +0x77 (`0x0040E9BB`).
    """
    members = warp.demons_in_row(5)
    assert members, "row 5 has no demons; the field offset has moved"
    lowest = members[0]
    assert lowest[0] == "P20C7" and lowest[2] == 3, lowest
    assert lowest[1] == "\u30d4\u30af\u30b7\u30fc", lowest[1]      # ピクシー
