"""Byte patches for the exe, driven by ``docs/exe-patches.md``.

Every patch names its *old* bytes; the applier refuses to write unless they are
present, so a patch can never land on the wrong build or be applied twice.
"""
from __future__ import annotations

import os
import re

from .. import paths

TABLE = os.path.join(paths.REPO_ROOT, "docs", "exe-patches.md")
ORG = os.path.join(paths.ORIGINAL_DDSWIN, "dds_org.exe")

SETS = {"base": ("xp",), "release": ("xp", "locale"), "dev": ("xp", "locale", "dev"),
        "dev-jp": ("xp", "locale", "dev")}


def load(table: str = TABLE):
    """``[(set, offset, old, new, note)]`` from the markdown table."""
    out = []
    for ln in open(table, encoding="utf-8"):
        m = re.match(r"\| *(\w+) *\| *(0x[0-9A-Fa-f]+) *\| *`([0-9a-f]*)` *\| *`([0-9a-f]*)` *\| *(.*?) *\|$", ln.strip())
        if m:
            out.append((m.group(1), int(m.group(2), 16), bytes.fromhex(m.group(3)),
                        bytes.fromhex(m.group(4)), m.group(5)))
    return out


def apply(data: bytes, which: str, table: str = TABLE) -> bytes:
    buf = bytearray(data)
    for pset, off, old, new, note in load(table):
        if pset not in SETS[which]:
            continue
        if len(old) != len(new):
            raise ValueError("patch at 0x%X changes length" % off)
        if bytes(buf[off:off + len(old)]) != old:
            raise ValueError("patch at 0x%X: expected %s, found %s (%s)"
                             % (off, old.hex(), bytes(buf[off:off + len(old)]).hex(), note))
        buf[off:off + len(new)] = new
    return bytes(buf)


def build(which: str, out_dir: "str | None" = None) -> str:
    if which in ("dev", "release", "dev-jp"):
        from . import tracer
        fn = {"dev": tracer.build_dev, "release": tracer.build_release,
              "dev-jp": tracer.build_dev_jp}[which]
        return fn(out_dir)
    out_dir = out_dir or os.path.join(paths.BUILD_DIR, "exe")
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, "dds_%s.exe" % which)
    with open(ORG, "rb") as fh:
        data = fh.read()
    with open(dst, "wb") as fh:
        fh.write(apply(data, which))
    return dst
