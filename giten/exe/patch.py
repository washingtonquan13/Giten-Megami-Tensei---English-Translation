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


# --- ascii_digits: 1F 02 number prints in half-width ASCII ------------------
#
# ``1F 02 <expr>`` (handler ``0x00430141`` -> ``0x0043BA30``) prints a number
# (``docs/combat-damage.md`` §1).  The routine is::
#
#     0x0043BA42  _snprintf(buf, 0x20, "%ld", eval(expr))     ; buf on the stack
#     0x0043BA5C  esi = 0x004815A0                             ; output buffer
#     0x0043BA69  loop:  ecx = (u8)buf[i]
#     0x0043BA6D         push ecx
#     0x0043BA6E         call 0x0045B750      <- _mbbtombc: the ONE conversion
#     0x0043BA73         add esp,4
#     0x0043BA76         cmp ax,0xFF ; jbe one
#     0x0043BA7C         [esi++] = ah         ; two-byte result: lead byte first
#     0x0043BA84  one:   [esi++] = al
#                        i++ ; while buf[i]
#     0x0043BAA1  [esi] = 0 ... call 0x0043B920(0x004815A0)    ; run it as text
#
# ``0x0045B750`` is the CRT's ``_mbbtombc``: under code page 932 (which the
# ``locale`` rows select) it maps every byte 0x20..0x7E through the word table
# at ``0x0046E3D0`` -- digits to ``82 4F..82 58`` and the ``-`` of a negative
# number to ``81 7C``.  It has exactly one caller in the image (this one) and no
# pointer to it exists, so nothing else in the game depends on it.
#
# **The patch** replaces that call with ``mov eax,ecx`` and three NOPs.  ``ecx``
# was zero-extended from one byte two instructions earlier, so ``ax <= 0xFF``
# and the ``jbe`` is always taken: each character of the ``%ld`` output --
# digits and the minus sign alike -- is stored as the one byte ``sprintf``
# wrote.  The stack stays balanced (the ``push ecx`` / ``add esp,4`` pair is
# kept); ``edx`` and the two-byte branch become dead, not wrong; the output
# shrinks from ``2n`` to ``n`` bytes, so the 64-byte buffer at ``0x004815A0``
# (the script registers start at ``0x004815E0``) that held at most 23 bytes
# (``-2147483648`` doubled, plus NUL) now holds at most 12, and the NUL write at
# ``0x0043BAA1`` still lands directly after the last character.
#
# The bytes are then executed as a text sub-script (``0x0043B8C0`` copies them
# to a 0x400-byte heap block and calls ``0x00433C50``).  A byte ``>= 0x20`` that
# is not a Shift-JIS lead is a one-byte text token (``docs/opcode-model.md``
# §2), the path every ASCII byte of the English tables already takes, and
# ``0x00451230`` draws bytes ``<= 0xDF`` from the exe's own half-width font.
# The overlay hook never serves that block: it does not begin ``00 04``, so
# ``hook.c``'s ``script_buffer`` rejects it and the original fetch runs.
#
# Why: beside English, full-width digits read as "Next４４３MaccaI'll take it!".
# It is a text-rendering change, applied with the other English passes only
# (``tracer.build_image``); ``dds_dev_jp.exe`` keeps full-width digits.

#: ``call 0x0045B750`` (``_mbbtombc``) inside the ``1F 02`` print loop
DIGITS_SITE = 0x0043BA6E
DIGITS_OLD = bytes.fromhex("e8ddfc0100")
#: ``mov eax,ecx ; nop ; nop ; nop``
DIGITS_NEW = bytes.fromhex("8bc1909090")
#: the loop around the site, asserted whole so the patch cannot land on a
#: routine that merely shares the call: ``xor ecx,ecx / mov cl,[eax] /
#: push ecx / <site> / add esp,4 / cmp ax,0xFF / jbe +8 / xor edx,edx / inc esi
#: / mov dl,ah / mov [esi-1],dl / mov [esi],al / inc esi``
DIGITS_LOOP_VA = 0x0043BA69
DIGITS_LOOP_OLD = bytes.fromhex("33c98a0851" "e8ddfc0100" "83c404663dff007608"
                                "33d2468ad48856ff880646")
#: where the loop writes, and how big that buffer is
DIGITS_OUT_BUF = 0x004815A0
DIGITS_OUT_BUF_SIZE = 0x40


def ascii_digits(image: bytes) -> bytes:
    """Make ``1F 02`` print ASCII digits.  Five bytes, in place.

    Refuses an image whose loop is not the original's -- including one that
    already carries this patch, so applying it twice is an error rather than a
    silent no-op.
    """
    from .pe import PE
    pe = PE(image, "ascii_digits")
    off = pe.va2off(DIGITS_LOOP_VA)
    found = image[off:off + len(DIGITS_LOOP_OLD)]
    if found != DIGITS_LOOP_OLD:
        raise RuntimeError("ascii_digits: the 1F 02 print loop at 0x%08X is not "
                           "the original's (%s)" % (DIGITS_LOOP_VA, found.hex(" ")))
    site = pe.va2off(DIGITS_SITE)
    if image[site:site + len(DIGITS_OLD)] != DIGITS_OLD:
        raise RuntimeError("ascii_digits: no call _mbbtombc at 0x%08X" % DIGITS_SITE)
    out = bytearray(image)
    out[site:site + len(DIGITS_NEW)] = DIGITS_NEW
    return bytes(out)


def build(which: str, out_dir: "str | None" = None) -> str:
    if which in ("dev", "release", "dev-jp", "nopace", "dev-nopace", "dev-x2"):
        from . import tracer
        fn = {"dev": tracer.build_dev, "release": tracer.build_release,
              "dev-jp": tracer.build_dev_jp, "nopace": tracer.build_nopace,
              "dev-nopace": tracer.build_dev_nopace,
              "dev-x2": tracer.build_dev_x2}[which]
        return fn(out_dir)
    out_dir = out_dir or os.path.join(paths.BUILD_DIR, "exe")
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, "dds_%s.exe" % which)
    with open(ORG, "rb") as fh:
        data = fh.read()
    with open(dst, "wb") as fh:
        fh.write(apply(data, which))
    return dst
