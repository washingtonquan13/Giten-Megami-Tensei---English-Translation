"""The ``08 nn`` word dictionary stored in ``m/MS7F07.BIN``.

Inside script text, ``08 nn`` is a macro: splice in entry *nn* of the dictionary.
Entries are short Japanese fragments (える, なら, じゃ) and a few proper nouns --
a crude compression scheme for the original Japanese script.

English text never uses it: when a span is translated the pipeline expands every
``08 nn`` into literal bytes, so no dictionary reference survives into the patch.
"""
from __future__ import annotations

import os

from . import container, paths

DICT_FILE = "m/MS7F07.BIN"

_CACHE = None


def _parse_records(body: bytes, start: int = 2):
    """``[id:u8][len:u16 LE][data:len]`` walk, tolerant of junk (used only here)."""
    i = start
    out = []
    n = len(body)
    while i + 3 <= n:
        rid = body[i]
        ln = int.from_bytes(body[i + 1 : i + 3], "little")
        if ln > 0 and i + 3 + ln <= n and body[i + 3 + ln - 1] == 0:
            out.append((rid, body[i + 3 : i + 3 + ln - 1]))
            i += 3 + ln
        else:
            i += 1
    return out


def load(root: "str | None" = None) -> "dict[int, bytes]":
    """Return ``{index: raw bytes}``.  Cached after the first call."""
    global _CACHE
    if _CACHE is not None and root is None:
        return _CACHE
    base = root or paths.game_root()
    p = os.path.join(base, *DICT_FILE.split("/"))
    if not os.path.exists(p):
        raise SystemExit("dictionary %s not found under %s" % (DICT_FILE, base))
    with open(p, "rb") as fh:
        _hdr, body = container.unpack(fh.read())
    table = {}
    for rid, data in _parse_records(body):
        table.setdefault(rid, data)
    if root is None:
        _CACHE = table
    return table
