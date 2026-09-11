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


# --- the negotiation variant ------------------------------------------------
#: ``et/ET0007.BIN``: a 2-byte length word, then 25 rows of three bytes, read in
#: the clear (``0x00401D90`` freads the word and then the body, with no
#: decryption).  ``0x0040EB70`` merges, per row, ``m/MS6000`` always, then
#: ``0x6000 + t0``, ``0x6000 + t1`` and ``0x6100 + t2``, each unless the column
#: is ``0xFF``, then the demon's own ``et/ID%04X``.
ET0007_REL = "et/ET0007.BIN"
ET0007_ROWS = 25

#: Which row a demon uses is a field of its own ``p/P####.BIN`` record: the u16
#: at ``0x73``.  (The engine reads it as the merge descriptor's ``+0x77``, and
#: the descriptor's ``+0x04`` is a copy of the 122-byte ``p/`` record.)
DEMON_ROW_OFFSET = 0x73


def et0007_rows(raw: bytes) -> "list[tuple]":
    n = int.from_bytes(raw[:2], "little")
    if n != len(raw) - 2 or n % 3:
        raise ValueError("%s is not 3-byte rows behind a length word" % ET0007_REL)
    return [tuple(raw[2 + i * 3:5 + i * 3]) for i in range(n // 3)]


def et0007_with(raw: bytes, row: int, t2: int) -> bytes:
    """``et/ET0007.BIN`` with one row's third column set.

    Only the third column, and only one row: the merge *adds* a file rather than
    replacing one, so the demon's own conversation files are all still loaded and
    the only difference is that `m/MS61<t2>` is merged on top of them.
    """
    rows = et0007_rows(raw)
    if not 0 <= row < len(rows):
        raise ValueError("row %d is outside the %d-row table" % (row, len(rows)))
    out = bytearray(raw)
    out[2 + row * 3 + 2] = t2
    return bytes(out)


def demons_in_row(row: int, root: "str | None" = None) -> "list[tuple]":
    """``[(record id, name, level)]`` for every demon that uses one table row."""
    import glob
    import struct

    from . import container
    root = root or paths.ORIGINAL_DDSWIN
    out = []
    for p in sorted(glob.glob(os.path.join(root, "p", "*.BIN"))):
        body = container.split(open(p, "rb").read())[0][0].body
        if len(body) < 0x7A:
            continue
        if struct.unpack_from("<H", body, DEMON_ROW_OFFSET)[0] != row:
            continue
        name = body[0x36:0x36 + 26].split(b"\0")[0].decode("cp932", "replace")
        out.append((os.path.basename(p)[:-4], name, body[0x47]))
    return sorted(out, key=lambda r: r[2])


# --- building a tree --------------------------------------------------------
def dev_exe(rebuild: bool = False, cave: "dict | None" = None,
            out_dir: "str | None" = None) -> str:
    """Path to the Japanese dev exe, built if it is missing or ``rebuild``.

    ``cave`` produces a separate exe carrying the warp cave, since the cave's
    target is pinned into the image rather than read from the script.
    """
    from .exe import tracer, warp16
    out_dir = out_dir or os.path.join(paths.BUILD_DIR, "exe")
    if cave is not None:
        return warp16.build(out_dir=out_dir, **cave)
    dst = os.path.join(out_dir, DEV_EXE)
    if rebuild or not os.path.exists(dst):
        return tracer.build_dev_jp(out_dir)
    return dst


def build(out_dir: str, file_id: int, rec_id: int, entry: int = 0,
          overrides: "dict[str, bytes] | None" = None,
          rebuild_exe: bool = False, quiet: bool = False,
          match: "tuple | None" = None) -> dict:
    """Build one warp tree.  Returns a small report dict.

    ``match`` is ``(file, rec)`` -- a jump the game already makes, which the cave
    rewrites to the target.  With it, **no script is patched at all**: the tree's
    ``m/MS0017`` is the original, and the warp fires wherever the engine itself
    performs that jump.  That is the only way into a record nothing names.
    """
    from .exe import warp16
    cave = None
    script_warp = None
    if file_id is None:
        # no jump at all: a tree that differs from the original only in its data
        # overrides.  What `et/ET0007` needs -- the player has to reach the
        # scene by playing, and the merge does the rest.
        pass
    elif match is not None:
        cave = {"file_id": file_id, "rec_id": rec_id, "entry": entry,
                "sentinel": match[0], "match_rec": match[1],
                "name": "dds_dev_warp_%02X%02X_to_%04X%02X.exe"
                        % (match[0], match[1], file_id, rec_id)}
    elif file_id > 0xFF or entry:
        cave = {"file_id": file_id, "rec_id": rec_id, "entry": entry,
                "sentinel": SENTINEL_FILE, "match_rec": warp16.ANY_REC,
                "name": "dds_dev_warp_%04X_%02X.exe" % (file_id, rec_id)}
        script_warp = warp_bytes(SENTINEL_FILE, 0x00)
    else:
        script_warp = warp_bytes(file_id, rec_id)

    over = dict(overrides or {})
    if script_warp is not None:
        src_raw = files.read_source(SRC_REL, paths.ORIGINAL_DDSWIN)
        patched = patch_injection(src_raw, script_warp)
        diff = changed_records(src_raw, patched)
        if diff != [SRC_REC]:
            raise RuntimeError("the injection moved records %r" % diff)
        over[SRC_REL] = patched

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    n = materialise(out_dir, overrides=over)
    exe = dev_exe(rebuild_exe, cave)
    added = add_runtime(out_dir, exe)
    rep = {"out": out_dir, "files": n, "exe": os.path.basename(exe),
           "runtime": added, "file_id": file_id, "rec_id": rec_id,
           "entry": entry, "cave": cave is not None, "match": match,
           "warp": script_warp.hex(" ") if script_warp else None,
           "overrides": sorted(over)}
    if not quiet:
        print("%s: %d data files, %s" % (out_dir, n, ", ".join(added)))
        if file_id is None:
            print("   no jump: the tree differs from the original only in its "
                  "data overrides")
        elif script_warp is not None:
            print("   m/MS0017 r%02X starts %s  ->  m/MS%04X.BIN r%02X%s"
                  % (SRC_REC, script_warp.hex(" "), file_id, rec_id,
                     " at +0x%X (cave)" % entry if cave else ""))
        else:
            print("   no script patched; the cave rewrites 0C %02X %02X -> "
                  "0C %02X %02X%s" % (match[0], match[1], file_id, rec_id,
                                      " at +0x%X" % entry if entry else ""))
        for k in sorted(over):
            if k != SRC_REL:
                print("   override %s (%d bytes)" % (k, len(over[k])))
    return rep
