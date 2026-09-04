"""Round-trip pack/unpack for Giten .BIN containers -- thin wrapper.

The implementation lives in ``tools/giten/container.py``.

  unpack(raw)      -> (hdr:int, body:bytes)
  pack(body, hdr)  -> raw   (hdr defaults to len(body))

Run this module directly to re-verify the round trip across the game folder.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from tools.giten import files                           # noqa: E402
from tools.giten.container import pack, unpack          # noqa: E402,F401
from giten import ROOT                                  # noqa: E402,F401

if __name__ == '__main__':
    bad = n = 0
    for rel in files.all_encoded():
        raw = files.read_source(rel)
        h, b = unpack(raw)
        n += 1
        if pack(b, h) != raw:
            bad += 1
            print('ROUNDTRIP FAIL', rel)
    print('round-trip verified on %d files, %d failures' % (n, bad))
