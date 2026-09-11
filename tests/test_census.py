"""The tiling census: what is left, pinned so a change to it has to be deliberate.

`giten tile census` is the standing measurement -- every record the model does
not tile cleanly, with its state and the error.  This pins it exactly.  It is a
ratchet, not a target: a change that tiles one more record has to move the list
on purpose, and a change that loses one cannot hide inside a total.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import tile


def test_the_census_residue_is_exactly_what_it_was_measured_to_be():
    """Every record the model does not tile cleanly, pinned.

    Not a target -- a ratchet.  A change that tiles one more record has to move
    this list deliberately, and a change that *loses* one cannot hide.
    """
    rows = tile.census()
    res = [(r.rel, r.ci, r.rec_id, r.state) for r in tile.residue(rows)]
    want = [
        ("m/MS0031.BIN", 0, 0x00, tile.UNTILED),
        ("m/MS0031.BIN", 0, 0x02, tile.STRADDLE),
        ("m/MS0031.BIN", 0, 0x03, tile.STRADDLE),
        ("m/MS0031.BIN", 0, 0x0B, tile.UNTILED),
        ("m/MS0031.BIN", 0, 0x0D, tile.STRADDLE),
        ("m/MS0031.BIN", 0, 0x17, tile.STRADDLE),
        ("m/MS0080.BIN", 0, 0x00, tile.PREFIX),
        ("m/MS0080.BIN", 0, 0x01, tile.PREFIX),
        ("m/MS0080.BIN", 0, 0x02, tile.PREFIX),
        ("m/MS0080.BIN", 0, 0x03, tile.PREFIX),
        ("m/MS0080.BIN", 0, 0x04, tile.PREFIX),
    ]
    got_head = [r for r in res if r[0] in ("m/MS0031.BIN", "m/MS0080.BIN")]
    assert got_head == want, got_head
    counts = {}
    for r in res:
        counts[r[3]] = counts.get(r[3], 0) + 1
    assert counts == CENSUS_COUNTS, counts


#: state -> how many records are in it, over every ``m/`` and ``et/ID`` file.
#: Re-baselined whenever a change moves it; the commit message says why.
CENSUS_COUNTS = {tile.STRADDLE: 44, tile.PREFIX: 5, tile.UNTILED: 9,
                 tile.DATA: 8038}


def test_the_census_covers_every_record_of_every_script_file():
    rows = tile.census()
    assert len(rows) > 20000, len(rows)
    assert {r.state for r in rows} <= {tile.TILED, tile.STRADDLE, tile.PREFIX,
                                       tile.UNTILED, tile.DATA}
    # a `data` row never carries a tiling error: the file is not code, so the
    # tokenizer's opinion of it is not reported at all
    assert all(r.error is None for r in rows if r.state == tile.DATA)
