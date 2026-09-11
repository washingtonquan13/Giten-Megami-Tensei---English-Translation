"""Build a throwaway Japanese play tree whose opening jumps straight to a record.

The engine is the only tiler we trust: the dev build logs one event per token
dispatch, so running a record once gives its exact instruction boundaries.  A
record no play session has ever reached therefore cannot be checked against the
model at all -- and most of the corpus's untiled residue is in exactly that
position.  This module removes the excuse: it puts the interpreter at any record
of any ``m/MS*`` file within seconds of the title screen, with no save and no
playthrough.

How the jump is made
--------------------
``0C <file> <record>`` is goto-record (``0x00433E70`` -> ``0x00433D70``), and the
first operand is a **u8** file id, so three bytes are enough to send the
interpreter anywhere in ``m/MS00xx``.  The injection point is ``m/MS0017`` r01:
every trace on disk runs ``m/MS002D`` r00,01,02,01,04 and *then* ``m/MS0017``
r01, so patching the later one lets the whole opening initialise first and only
then warps.  The **target file is left byte-identical** -- it is the thing being
measured.

Files with a 16-bit id (``m/MS6200``, ``m/MS6500``) cannot be named by any
script opcode.  Those go through the dev exe's warp cave instead
(:mod:`giten.exe.warp16`), which also supplies an entry *offset* for a record the
engine enters mid-way by design.  The script side is the same three bytes, with
the sentinel file id :data:`SENTINEL_FILE`.

What a tree is
--------------
A complete Japanese install: the original ``m/``, ``et/``, ``p/``, ``s/``,
``fc/``, ``w/`` (hard-linked, so a tree costs a few megabytes rather than 358),
``Config.exe``, the dgVoodoo wrapper copied from the play install, and
``dds_dev_jp.exe`` -- the tracer build with **no** English data patches, which is
what a Japanese install must run (an English exe re-points the item database at
``et/et0102.bin`` and dies on the first frame without it) and what trace work
wants anyway: with no ``overlay.dat`` beside it the overlay hook no-ops, so every
logged program counter is directly comparable with the tokenizer's own output on
those same bytes.
"""
from __future__ import annotations

import os
import shutil

from . import container, files, paths, records

#: the record whose first bytes become the jump
SRC_REL, SRC_REC = "m/MS0017.BIN", 0x01

#: A ``0C``/``0D`` file operand that occurs **nowhere** in the corpus, so the dev
#: exe's warp cave can claim it without shadowing a real jump.  Deliberately
#: below 0xE0: ids 0xE0..0xFF are the demon-merge slots (``0x00433CA8``) and
#: would take a different path in the engine if the cave ever failed to fire.
SENTINEL_FILE = 0xD9

#: what to leave out of a tree: the original exes (the tree runs the dev build)
SKIP_NAMES = frozenset({
    "dds.exe", "dds_org.exe", "Giten Megami Tensei.lnk",
})

#: the dgVoodoo wrapper, copied from the play install so the tree runs on Win11
DGVOODOO = ("D3D8.dll", "D3D9.dll", "D3DImm.dll", "DDraw.dll", "dgVoodoo.conf")

DEV_EXE = "dds_dev_jp.exe"


def play_root() -> str:
    """The sibling play install, the only place the dgVoodoo files live."""
    return os.path.join(os.path.dirname(paths.REPO_ROOT), "play", "en", "ddswin")


# --- the script side --------------------------------------------------------
def warp_bytes(file_id: int, rec_id: int) -> bytes:
    if not 0 <= file_id <= 0xFF or not 0 <= rec_id <= 0xFF:
        raise ValueError("0C takes two u8 operands, got 0x%X 0x%X" % (file_id, rec_id))
    return bytes([0x0C, file_id, rec_id])


def patch_injection(raw: bytes, warp: bytes) -> bytes:
    """``m/MS0017.BIN`` with ``warp`` written over the front of record 1.

    The record keeps its length, so every other record's runtime base is
    unchanged and no branch anywhere in the container moves.  The bytes after
    the jump are dead -- ``0C`` never returns -- which is why overwriting in
    place is sound and re-framing is not needed.
    """
    conts, end = container.split(raw)
    if not conts or end != len(raw):
        raise ValueError("%s is not a clean container chain" % SRC_REL)
    bodies = [c.body for c in conts]
    body = records.parse_body(bodies[0])
    if body.error:
        raise ValueError(body.error)
    if records.serialise_body(body) != bodies[0]:
        raise ValueError("the record layer does not round-trip %s" % SRC_REL)
    rec = next((r for r in body.records if r.id == SRC_REC), None)
    if rec is None:
        raise ValueError("%s has no record 0x%02X" % (SRC_REL, SRC_REC))
    if len(rec.data) < len(warp):
        raise ValueError("r%02X is %d bytes, the warp needs %d"
                         % (SRC_REC, len(rec.data), len(warp)))
    rec.data = warp + rec.data[len(warp):]
    bodies[0] = records.serialise_body(body)
    out = container.join(bodies)
    if len(out) != len(raw):
        raise ValueError("the rebuilt container changed length (%d -> %d)"
                         % (len(raw), len(out)))
    return out


def changed_records(before: bytes, after: bytes) -> "list[int]":
    """Ids whose data differs between two encodings of ``m/MS0017.BIN``."""
    a = records.parse_body(container.split(before)[0][0].body).records
    b = records.parse_body(container.split(after)[0][0].body).records
    return [x.id for x, y in zip(a, b) if x.data != y.data]


# --- the tree ---------------------------------------------------------------
def _link_or_copy(src: str, dst: str) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def materialise(out_dir: str, source: "str | None" = None,
                overrides: "dict[str, bytes] | None" = None) -> int:
    """Hard-link a whole Japanese install into ``out_dir``; write ``overrides``.

    Hard links, not copies: ``fc/`` alone is 324 MB and a warp session is
    throwaway.  Nothing in the game writes to a data file (it only ever creates
    ``trace.bin`` / ``textout.bin``), and every file we *do* change is written
    fresh rather than opened for update, so the links can never reach back into
    ``original/``.
    """
    source = source or paths.ORIGINAL_DDSWIN
    overrides = {k.replace("\\", "/"): v for k, v in (overrides or {}).items()}
    n = 0
    for root, _dirs, names in os.walk(source):
        rel_dir = os.path.relpath(root, source)
        dst_dir = out_dir if rel_dir == "." else os.path.join(out_dir, rel_dir)
        os.makedirs(dst_dir, exist_ok=True)
        for name in names:
            if rel_dir == "." and (name in SKIP_NAMES or name.lower().endswith(".exe")
                                   and name != "Config.exe"):
                continue
            rel = name if rel_dir == "." else "%s/%s" % (rel_dir.replace("\\", "/"), name)
            dst = os.path.join(dst_dir, name)
            if os.path.exists(dst):
                os.remove(dst)
            if rel in overrides:
                with open(dst, "wb") as fh:
                    fh.write(overrides[rel])
            else:
                _link_or_copy(os.path.join(root, name), dst)
            n += 1
    for k, blob in overrides.items():
        dst = os.path.join(out_dir, *k.split("/"))
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(blob)
            n += 1
    return n


def add_runtime(out_dir: str, exe: str) -> "list[str]":
    """Put the dev exe and the dgVoodoo wrapper beside the data."""
    out = []
    dst = os.path.join(out_dir, DEV_EXE)
    shutil.copyfile(exe, dst)
    out.append(DEV_EXE)
    play = play_root()
    for name in DGVOODOO:
        src = os.path.join(play, name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(out_dir, name))
            out.append(name)
    return out


def dev_exe(rebuild: bool = False, cave: "tuple | None" = None,
            out_dir: "str | None" = None) -> str:
    """Path to the Japanese dev exe, built if it is missing or ``rebuild``.

    ``cave`` is ``(file_id, rec_id, entry)`` for a 16-bit warp; it produces a
    separate exe carrying the warp cave, since the cave's target is pinned into
    the image rather than read from the script.
    """
    from .exe import tracer, warp16
    out_dir = out_dir or os.path.join(paths.BUILD_DIR, "exe")
    if cave is not None:
        return warp16.build(cave[0], cave[1], cave[2], out_dir)
    dst = os.path.join(out_dir, DEV_EXE)
    if rebuild or not os.path.exists(dst):
        return tracer.build_dev_jp(out_dir)
    return dst


def build(out_dir: str, file_id: int, rec_id: int, entry: int = 0,
          overrides: "dict[str, bytes] | None" = None,
          rebuild_exe: bool = False, quiet: bool = False) -> dict:
    """Build one warp tree.  Returns a small report dict."""
    cave = None
    if file_id > 0xFF or entry:
        cave = (file_id, rec_id, entry)
        script_warp = warp_bytes(SENTINEL_FILE, 0x00)
    else:
        script_warp = warp_bytes(file_id, rec_id)

    src_raw = files.read_source(SRC_REL, paths.ORIGINAL_DDSWIN)
    patched = patch_injection(src_raw, script_warp)
    diff = changed_records(src_raw, patched)
    if diff != [SRC_REC]:
        raise RuntimeError("the injection moved records %r" % diff)

    over = dict(overrides or {})
    over[SRC_REL] = patched
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    n = materialise(out_dir, overrides=over)
    exe = dev_exe(rebuild_exe, cave)
    added = add_runtime(out_dir, exe)
    rep = {"out": out_dir, "files": n, "exe": os.path.basename(exe),
           "runtime": added, "file_id": file_id, "rec_id": rec_id,
           "entry": entry, "cave": cave is not None,
           "warp": script_warp.hex(" "), "overrides": sorted(over)}
    if not quiet:
        print("%s: %d data files, %s" % (out_dir, n, ", ".join(added)))
        print("   m/MS0017 r%02X starts %s  ->  m/MS%04X.BIN r%02X%s"
              % (SRC_REC, script_warp.hex(" "), file_id, rec_id,
                 " at +0x%X (cave)" % entry if cave else ""))
        for k in sorted(over):
            if k != SRC_REL:
                print("   override %s (%d bytes)" % (k, len(over[k])))
    return rep
