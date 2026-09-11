"""`m/MS6F00` and `m/MS6F1F` are data: nothing opens them, and nothing ran them.

These two files hold the last of the corpus's "untiled" records outside
`m/MS0031`, and they have been filed as "loader unknown" since the reachability
work.  They are not unknown.  Only kind 9 of the router at `0x00402208` produces
the name `m\\ms%.4x.bin`, so the question is exactly "does anything form the ids
`0x6F00` / `0x6F1F` and hand them to it" -- and the answer is a conjunction of
four independent measurements, all asserted here:

1. **No instruction carries the id.**  Neither value appears as a literal in any
   disassembled `.text` instruction.  For `0x6F1F` the two bytes do not occur in
   `.text` at all; for `0x6F00` they occur four times, all inside jump tables.
2. **No table can form it.**  The negotiation merge's widest reach is
   `0x6100 + 0xFF = 0x61FF` (`0x0040EC31 add $0x6100,%edx`, from a `u8` column).
3. **No script can name it.**  Every file-referencing opcode takes a `u8`.
4. **No trace has ever stood in one of their records**, on any session on disk.

None of the four alone is a proof.  Together they are why the census calls these
records `data` rather than `untiled`: the tokenizer's opinion of bytes the
interpreter is never handed is not a defect in the tokenizer.
"""
from __future__ import annotations

import glob
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import container, files, loaders, overlay, paths, records
from giten.trace import core

TRACE_DIRS = (os.path.join(paths.REPO_ROOT, "traces"),
              os.path.join(paths.BUILD_DIR, "traces"))


def test_only_kind_nine_names_a_script_file():
    kinds = loaders.router_kinds()
    assert kinds[loaders.SCRIPT_KIND] == loaders.SCRIPT_KIND_HANDLER
    assert len(set(kinds.values())) == len(kinds), "two kinds share a handler"


def test_no_instruction_in_the_image_carries_either_file_id():
    ids = sorted(loaders.file_id(rel) for rel in loaders.DATA_FILES)
    assert ids == [0x6F00, 0x6F1F], ids
    hits = loaders.instruction_immediates(*ids)
    assert hits == [], hits


def test_the_bytes_that_do_occur_are_jump_table_entries_not_operands():
    """The four `00 6F` byte pairs in .text, run down individually."""
    assert loaders.immediate_sites(0x6F1F) == []
    sites = loaders.immediate_sites(0x6F00)
    assert sites == [0x0040223F, 0x00406E1A, 0x00432363, 0x00459AD3], \
        [hex(s) for s in sites]
    img, pe = loaders._image()

    def dword(va):
        return struct.unpack_from("<I", img, pe.va2off(va))[0]

    text_lo, text_hi = 0x00401000, 0x004632C4
    # three straddle two adjacent entries of a table of .text addresses ...
    for va in (0x0040223F, 0x00432363):
        assert text_lo <= dword(va - 3) < text_hi, hex(va)
        assert text_lo <= dword(va + 1) < text_hi, hex(va)
    # ... one IS a jump table's base address, in `jmp [reg*4+0x406F00]` ...
    assert img[pe.va2off(0x00406E17):pe.va2off(0x00406E1A)] == b"\xFF\x24\x85"
    assert dword(0x00406E1A) == 0x00406F00
    # ... and the last is the high byte of a pointer beside a small count
    assert dword(0x00459AD3 - 3) == 0x004658D8
    assert dword(0x00459AD3 + 1) == 0x0000006F


def test_the_merge_table_cannot_reach_the_six_f_family():
    from giten import warp
    raw = files.read_source(warp.ET0007_REL, paths.ORIGINAL_DDSWIN)
    widest = max(0x6100 + t[2] for t in warp.et0007_rows(raw) if t[2] != 0xFF)
    assert widest <= loaders.MERGE_MAX < 0x6F00, hex(widest)


def _keys_only_these_files_have():
    """Content keys no *loadable* file shares.

    Content addressing names bytes, not files, so a key these two share with a
    file the engine does load says nothing at all: 256 of their 307 distinct
    contents are one-byte and two-byte stubs that half the corpus also holds,
    and the Roppongi session naturally stands in some of them.  Only the 51
    keys that are theirs alone can be evidence in either direction.
    """
    from giten import tile
    out = {}
    for key, hits in tile.record_index().items():
        rels = {h[0] for h in hits}
        if rels and rels <= loaders.DATA_FILES:
            out[key] = sorted(hits)[0][:3]
    return out


def test_no_event_in_any_trace_on_disk_ever_stood_in_one_of_their_records():
    """Content-addressed on v4+, and by the file label on the older captures.

    Ten sessions, 1.5 million events between them.  A hit here would not merely
    move a census row -- it would mean a file with no caller is being loaded
    anyway, which is the one thing the `data` verdict claims cannot happen.
    """
    keys = _keys_only_these_files_have()
    assert len(keys) == 51, len(keys)
    ids = {loaders.file_id(rel) for rel in loaders.DATA_FILES}
    checked = 0
    for d in TRACE_DIRS:
        for path in sorted(glob.glob(os.path.join(d, "*.bin"))):
            if path.endswith("-glyphs.bin") or "textout" in os.path.basename(path):
                continue
            with open(path, "rb") as fh:
                data = fh.read()
            try:
                rs, body = core._pick(data, path)
            except ValueError:
                continue
            checked += 1
            hashed = rs in (core.RECORD_V4, core.RECORD_V5)
            for i in range(len(body) // rs.size):
                f = rs.unpack_from(body, i * rs.size)
                assert f[0] not in ids, (
                    "%s event %d names file 0x%04X" % (path, i, f[0]))
                if hashed:
                    key = (f[1], f[8], f[12])
                    assert key not in keys, (
                        "%s event %d stands in %s" % (path, i, keys[key]))
    assert checked >= 5, "only %d traces were readable" % checked


def test_the_census_calls_every_one_of_their_records_data():
    from giten import tile
    rows = [r for r in tile.census() if r.rel in loaders.DATA_FILES]
    assert rows, "the data files are no longer in the census"
    assert {r.state for r in rows} == {tile.DATA}
