"""Dev exe: the release image plus the interpreter trace hook.

``exec_token`` (VA ``0x439020``) has exactly three callers -- ``E8`` at VA
``0x4390C4``, ``0x439103`` and ``0x43913C`` (verified by scanning the whole
``.text`` for ``call`` instructions that land there).  Redirecting those three
rel32 operands to a wrapper in a new ``.trc`` section is the entire hook: three
4-byte diffs plus an appended section, all reversible.

The wrapper is ``trace.S``, assembled here with GNU ``as --32`` and extracted
with ``objcopy -O binary``.  It is position-independent, so it needs no linker
and no knowledge of where the section lands; the addresses it *does* need --
the real ``exec_token``, two IAT slots, four engine globals -- are passed as
``--defsym`` so this file is the only place they are written down.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile

from .. import paths
from . import patch
from .pe import PE

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "trace.S")
TEXTLOG_SOURCE = os.path.join(HERE, "textlog.S")
HOOK_SOURCE = os.path.join(HERE, "hook.c")
HOOK_LD = os.path.join(HERE, "hook.ld")

#: the interpreter's byte fetch (``giten/overlay.py``) and its five call sites
FETCH = 0x438E50
FETCH_SITES = (0x438E8D, 0x438E9B, 0x438F0D, 0x438F32, 0x438FAD)

#: the main loop's tick gate (``hook.c`` pace()): at 0x45108A the original does
#: ``call [timeGetTime]; cmp eax,edi; jbe 0x45104E`` -- one tick per millisecond.
#: It becomes ``call pace; test eax,eax; je 0x45104E; nop``: one tick per 1/60 s.
#: the per-tick background-script step (``hook.c`` script_step()).  0x401980
#: calls 0x43B5E0 once a tick, and 0x43B5E0 runs the background script until
#: it blocks -- so this call is the rate at which scripted actors take their
#: turns.  Redirected only when a divider greater than 1 is asked for.
SCRIPT_STEP = 0x43B5E0
SCRIPT_STEP_SITES = (0x401985,)

#: the battle state machine (``hook.c`` battle_step()).  0x00417160 dispatches
#: one state handler per tick through the table at 0x00417288; entry 24 is the
#: battle, and its handler advances one battle phase per call.  Dividing this
#: one call site slows combat and nothing else -- the command UI is state 32.
BATTLE_STEP = 0x42B6A0
BATTLE_STEP_SITES = (0x41720A,)

PACE_SITE = 0x45108A
PACE_OLD = bytes.fromhex("ff15d84146003bc776ba")
PACE_NEW_TAIL = bytes.fromhex("85c074bb90")          # test eax,eax; je -0x45; nop
CFLAGS = ["-m32", "-O2", "-ffreestanding", "-nostdlib", "-fno-builtin",
          "-fno-stack-protector", "-fno-asynchronous-unwind-tables", "-fno-ident",
          "-mno-stack-arg-probe", "-fno-pic", "-fcf-protection=none",
          "-mpreferred-stack-boundary=2", "-Wall", "-Werror"]

#: main-loop ticks per second.  hook.c keeps deadlines in thirds of a
#: millisecond, so a rate has to divide 3000 evenly.
DEFAULT_HZ = 60

EXEC_TOKEN = 0x439020
#: VA of each ``E8`` that calls exec_token (the rel32 follows at +1)
CALL_SITES = (0x4390C4, 0x439103, 0x43913C)

#: The game does NOT draw text with TextOutA -- it never calls it.  Every
#: character is blitted by 0x451230, which reads a built-in half-width font at
#: 0x0046C230 and falls back to GetGlyphOutlineA (its only call site) for the
#: rest.  ``textlog.S`` has the whole path; these are its six callers' `call`
#: instructions, which the dev build redirects to log what gets drawn.
DRAWGLYPH = 0x451230
GLYPH_SITES = (0x4516E0, 0x4517E7, 0x4518EC, 0x451A1F, 0x451C24, 0x451D28)

#: The six draw-string variants that walk a ``char*`` calling DRAWGLYPH per
#: character.  This is the level a menu overlay would hook, since each takes
#: the string as an argument -- but each has a *different* signature, so which
#: argument that is has to be established before anything dereferences it.
#: The dev build logs their arguments to settle that from a play session.
DRAWSTRING = (0x451650, 0x451750, 0x451850, 0x451950, 0x451B20, 0x451CB0)


def drawstring_sites(image: bytes) -> "dict[int, tuple]":
    """``{variant VA: (call site VAs,)}`` -- every ``E8`` that lands on one.

    Found by scanning rather than written down: there are seventy-odd of them
    across the game and a list that drifted would be worse than no list.
    """
    pe = PE(image, "scan")
    text = [s for s in pe.sections if s["name"] == ".text"][0]
    lo, hi = text["rawptr"], text["rawptr"] + text["rawsize"]
    want = {va: [] for va in DRAWSTRING}
    # Seek to each 0xE8 with bytes.find rather than walking 400 KB one index at
    # a time in Python: the loop version cost ~80 s per dev build once this was
    # called for six targets, and the build is exercised several times by the
    # test suite.
    at = image.find(b"\xE8", lo, hi - 5)
    while at >= 0:
        rel = struct.unpack_from("<i", image, at + 1)[0]
        tgt = (pe.off2va(at) + 5 + rel) & 0xFFFFFFFF
        if tgt in want:
            want[tgt].append(pe.off2va(at))
        at = image.find(b"\xE8", at + 1, hi - 5)
    return {k: tuple(v) for k, v in want.items()}

SYMBOLS = {
    "EXEC_TOKEN": EXEC_TOKEN,
    "CREATEFILE_IAT": 0x464074,     # kernel32!CreateFileA
    "WRITEFILE_IAT": 0x4640AC,      # kernel32!WriteFile
    "CTX": 0x491160,                # -> script context; PC is a u16 at +0x0E
    "FILEID": 0x4911B0,             # current script file id (u16)
    "RECID": 0x4911B2,              # current record id (u16)
    "CAPFLAG": 0x481224,            # text-capture mode (u16, non-zero = on)
    "CAPBUF": 0x481120,             # the 256-byte capture buffer
    "HANDLE_TABLE": 0x47605C,       # [HANDLE_TABLE + handle*8] = buffer base (0x4045F0)
    "DRAWGLYPH": 0x451230,          # the engine's own per-character blitter
    "DRAWSTR1": 0x451650,         # draw-string variant 1
    "DRAWSTR2": 0x451750,         # draw-string variant 2
    "DRAWSTR3": 0x451850,         # draw-string variant 3
    "DRAWSTR4": 0x451950,         # draw-string variant 4
    "DRAWSTR5": 0x451B20,         # draw-string variant 5
    "DRAWSTR6": 0x451CB0,         # draw-string variant 6
}

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE
TRC_CHARACTERISTICS = 0xE0000060

#: file, rec, pc, ch, r, capflag, caplen, idx_off, idx_len, pc0, flags
#: (v2; behind an 8-byte "GTRC" header.  giten/trace/core.py decodes v1 too.)
RECORD = struct.Struct("<HHHHhBBHHHH")
RECORD_SIZE = RECORD.size
TRACE_MAGIC = b"GTRC"
TRACE_VERSION = 2
TRACE_HEADER_SIZE = 8


def assemble(source: str = SOURCE, symbols: bool = False):
    """``trace.S`` -> raw bytes of its ``.text`` (and its symbol offsets).

    ``symbols=True`` also returns ``{name: offset}`` read back from the object
    with ``nm``.  ``textlog.S`` needs it: its six draw-string stubs are entry
    points the builder has to redirect call sites to, and counting instruction
    bytes by hand to find them is exactly the kind of arithmetic that ships a
    jump into the middle of an instruction.
    """
    for tool in ("as", "objcopy"):
        if shutil.which(tool) is None:
            raise RuntimeError("%s not found (GNU binutils are required to build the "
                               "dev exe)" % tool)
    tmp = tempfile.mkdtemp(prefix="giten-trace-")
    try:
        obj = os.path.join(tmp, "trace.o")
        binp = os.path.join(tmp, "trace.bin")
        defs = []
        for k, v in SYMBOLS.items():
            defs += ["--defsym", "%s=0x%X" % (k, v)]
        subprocess.run(["as", "--32", *defs, "-o", obj, source], check=True)
        subprocess.run(["objcopy", "-O", "binary", "-j", ".text", obj, binp], check=True)
        with open(binp, "rb") as fh:
            blob = fh.read()
        syms = {}
        if symbols:
            out = subprocess.run(["nm", "--format=posix", obj],
                                 check=True, capture_output=True, text=True).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[1] in ("t", "T"):
                    syms[parts[0]] = int(parts[2], 16)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not blob or len(blob) > 0x1000:
        raise RuntimeError("unexpected cave size %d" % len(blob))
    return (blob, syms) if symbols else blob


def short_path(p: str) -> str:
    """8.3 form of a path: the mingw driver mis-splits its own lib paths on spaces."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024):
            return buf.value
    except Exception:
        pass
    return p


def compile_hook_ex(cave_va: int, hz: int = DEFAULT_HZ, script_div: int = 1,
                    battle_div: int = 1):
    """``hook.c`` -> (flat blob linked at ``cave_va`` per ``hook.ld``, hook first;
    the VA of every global function in it, e.g. ``hook`` and ``pace``).

    ``hz`` sets the main loop's tick rate.  ``hook.c`` keeps deadlines in
    thirds of a millisecond, so the per-tick advance is ``3000 // hz`` and
    only rates that divide 3000 evenly stay drift-free.
    """
    if 3000 % hz:
        raise ValueError("%d Hz does not divide the 1/3 ms clock evenly" % hz)
    if script_div < 1:
        raise ValueError("script_div must be at least 1, got %r" % script_div)
    if battle_div < 1:
        raise ValueError("battle_div must be at least 1, got %r" % battle_div)
    for tool in ("gcc", "ld", "objcopy", "nm"):
        if shutil.which(tool) is None:
            raise RuntimeError("%s not found (GNU binutils + gcc are required)" % tool)
    gcc = short_path(shutil.which("gcc"))
    tmp = tempfile.mkdtemp(prefix="giten-hook-")
    try:
        obj, pe_, binp = (os.path.join(tmp, n) for n in ("hook.o", "hook.pe", "hook.bin"))
        subprocess.run([gcc, *CFLAGS, "-DGAME", "-DTICK3=%d" % (3000 // hz),
                        "-DSCRIPT_DIV=%d" % script_div,
                        "-DBATTLE_DIV=%d" % battle_div,
                        "-c", HOOK_SOURCE, "-o", obj], check=True)
        undef = subprocess.run(["nm", "-u", obj], check=True, capture_output=True, text=True).stdout.split()
        if undef:
            raise RuntimeError("hook.c needs symbols the game cannot supply: %s" % undef)
        subprocess.run(["ld", "-m", "i386pe", "-T", HOOK_LD, "--defsym", "CAVE_VA=0x%X" % cave_va,
                        "-o", pe_, obj], check=True)
        subprocess.run(["objcopy", "-O", "binary", "-j", ".text", pe_, binp], check=True)
        with open(binp, "rb") as fh:
            blob = fh.read()
        syms = {}
        for ln in subprocess.run(["nm", pe_], check=True, capture_output=True, text=True).stdout.splitlines():
            parts = ln.split()
            if len(parts) == 3 and parts[1] == "T":
                syms[parts[2].lstrip("_")] = int(parts[0], 16)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not blob or len(blob) > 0x2000:
        raise RuntimeError("unexpected hook size %d" % len(blob))
    if syms.get("hook") != cave_va or "pace" not in syms:
        raise RuntimeError("hook.c layout: %r" % syms)
    if script_div > 1 and "script_step" not in syms:
        raise RuntimeError("hook.c has no script_step: %r" % syms)
    if battle_div > 1 and "battle_step" not in syms:
        raise RuntimeError("hook.c has no battle_step: %r" % syms)
    return blob, syms


def compile_hook(cave_va: int) -> bytes:
    """``hook.c`` -> a flat blob linked at ``cave_va`` (``hook.ld``), hook first."""
    return compile_hook_ex(cave_va)[0]


def _pace(image: bytearray, pace_va: int) -> None:
    """Point the main loop's tick gate at pace() (see PACE_SITE)."""
    pe = PE(bytes(image), "image")
    off = pe.va2off(PACE_SITE)
    if bytes(image[off:off + len(PACE_OLD)]) != PACE_OLD:
        raise RuntimeError("main loop at 0x%X is not the original's" % PACE_SITE)
    image[off:off + len(PACE_OLD)] = b"\xE8" + struct.pack("<i", pace_va - (PACE_SITE + 5)) + PACE_NEW_TAIL


def _redirect(image: bytearray, sites, old_target: int, new_target: int) -> None:
    pe = PE(bytes(image), "image")
    for site in sites:
        off = pe.va2off(site)
        if image[off] != 0xE8:
            raise RuntimeError("no call at 0x%X" % site)
        old = struct.unpack_from("<i", image, off + 1)[0]
        if (site + 5 + old) & 0xFFFFFFFF != old_target:
            raise RuntimeError("call at 0x%X does not target 0x%X" % (site, old_target))
        struct.pack_into("<i", image, off + 1, new_target - (site + 5))


def build_image(trace: bool, english: bool = True, pace: bool = True,
                hz: int = DEFAULT_HZ, script_div: int = 1,
                battle_div: int = 1, atb_pc98: bool = False,
                popup_ticks: "int | None" = None) -> bytes:
    """Release image (locale patches) + the overlay hook, + the tracer if ``trace``.

    ``english=False`` skips the four data-table patches.  They are not optional
    decoration: ``database.apply`` re-points the engine's item-database load at
    ``et/et0102.bin``, and if that file is absent the router returns NULL, the
    next record lookup dereferences a null base and **the game dies on the first
    frame** -- deliberately, per ``database.S``.  So an English exe cannot run
    against a Japanese install, which has no ``et0102.bin``.  The tracer, the
    overlay hook and the pacing stay, so a Japanese dev build differs from the
    English one only in the strings, and their traces stay comparable.
    """
    with open(patch.ORG, "rb") as fh:
        image = patch.apply(fh.read(), "release")
    pe = PE(image, "dds_release")
    ovl_va = pe.imagebase + pe.sizeimage             # where append_section will put it
    blob, syms = compile_hook_ex(ovl_va, hz, script_div, battle_div)
    image = bytearray(pe.append_section(".ovl", blob, TRC_CHARACTERISTICS))
    _redirect(image, FETCH_SITES, FETCH, ovl_va)
    if pace:
        _pace(image, syms["pace"])
    if script_div > 1:
        _redirect(image, SCRIPT_STEP_SITES, SCRIPT_STEP, syms["script_step"])
    if battle_div > 1:
        _redirect(image, BATTLE_STEP_SITES, BATTLE_STEP, syms["battle_step"])
    from . import database, mapnames, menus, names, timing
    if english:
        image = bytearray(names.apply(bytes(image)))     # English character names (.nam)
        image = bytearray(menus.apply(bytes(image)))     # English menu strings (.men)
        image = bytearray(database.apply(bytes(image)))  # the item database, uncapped (.idb)
        image = bytearray(mapnames.apply(bytes(image)))  # English location names (.mnm)
    # tick-counted popup duration; `popup_ticks` lets a comparison build keep
    # the stock 15 so the message lockout is not a second variable
    image = bytearray(timing.apply(bytes(image),
                                   timing.POPUP_TICKS if popup_ticks is None
                                   else popup_ticks))
    if atb_pc98:
        image = bytearray(timing.atb_pc98(bytes(image)))   # the PC-98 turn-gauge step
    if trace:
        pe = PE(bytes(image), "dds_ovl")
        trc_va = pe.imagebase + pe.sizeimage
        image = bytearray(pe.append_section(".trc", assemble(), TRC_CHARACTERISTICS))
        _redirect(image, CALL_SITES, EXEC_TOKEN, trc_va)
        pe = PE(bytes(image), "dds_trc")
        tlg_va = pe.imagebase + pe.sizeimage
        blob, tsyms = assemble(TEXTLOG_SOURCE, symbols=True)
        sites = drawstring_sites(bytes(image))
        image = bytearray(pe.append_section(".tlg", blob, TRC_CHARACTERISTICS))
        _redirect(image, GLYPH_SITES, DRAWGLYPH, tlg_va)
        for i, target in enumerate(DRAWSTRING, start=1):
            stub = tsyms.get("str%d" % i)
            if stub is None:
                raise RuntimeError("textlog.S has no str%d entry point" % i)
            _redirect(image, sites[target], target, tlg_va + stub)
    return bytes(image)


def _write(out_dir, name, trace, english=True, pace=True, hz=DEFAULT_HZ,
           script_div=1, battle_div=1, atb_pc98=False, popup_ticks=None):
    out_dir = out_dir or os.path.join(paths.BUILD_DIR, "exe")
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, name)
    with open(dst, "wb") as fh:
        fh.write(build_image(trace, english, pace, hz, script_div, battle_div,
                             atb_pc98, popup_ticks))
    return dst


def build_dev_nopace(out_dir: "str | None" = None) -> str:
    """``dds_dev_nopace.exe``: the tracer, without the 60 Hz tick gate.

    The pairing that makes a pacing A/B produce evidence rather than an
    impression.  ``dds_nopace.exe`` has no tracer, so running it answers "does
    it feel different" and nothing else; this one records the session too, so a
    route played on both builds can be compared token for token.
    """
    return _write(out_dir, "dds_dev_nopace.exe", True, True, pace=False)


def build_nopace(out_dir: "str | None" = None) -> str:
    """``dds_nopace.exe``: the release build with the 60 Hz tick gate left out.

    A control, not a shipping build.  The gate is one of only two changes in the
    release exe that are not translation, and the main loop's per-tick update
    also drives the battle clock (``docs/exe-patches.md``), so it changes battle
    timing by construction.  When play-testing reports a pacing problem this is
    what says whether the gate is the cause: everything else -- locale, overlay,
    English data -- is identical, so any difference between the two builds is
    the gate and nothing else.

    Expect it to run *too fast* rather than correctly: without the gate the loop
    free-runs at whatever the driver allows, which is the problem the gate was
    added to fix.  The useful comparison is which way each build is wrong.
    """
    return _write(out_dir, "dds_nopace.exe", False, True, pace=False)


def build_release(out_dir: "str | None" = None) -> str:
    """``dds.exe``: locale fixes + the runtime overlay + 60 Hz pacing.  What players run."""
    return _write(out_dir, "dds.exe", False)


def build_dev(out_dir: "str | None" = None) -> str:
    """``dds_dev.exe``: the release plus the interpreter tracer."""
    return _write(out_dir, "dds_dev.exe", True)


def build_dev_jp(out_dir: "str | None" = None) -> str:
    """``dds_dev_jp.exe``: the tracer with no English data patches.

    What a Japanese install must run.  The English build hard-requires
    ``et/et0102.bin`` (see :func:`build_image`), which a Japanese install does not
    have, so it dies on the first frame there.  This is also the right build for
    trace work: with no ``overlay.dat`` beside it the overlay hook no-ops, so the
    engine executes the file's own bytes and every logged PC is directly
    comparable with what the tokenizer produces from those same bytes.
    """
    return _write(out_dir, "dds_dev_jp.exe", True, english=False)


def build_dev_atb(out_dir: "str | None" = None) -> str:
    """``dds_dev_atb.exe``: the tracer, 60 Hz, the PC-98 turn-gauge step.

    The A/B partner for ``dds_dev.exe``.  Two differences from it, both
    deliberate:

    * the turn gauge steps by ``1 + rand()%speed + 5`` instead of the port's
      ``2*(1 + rand()%speed) + 5`` -- the 1997 release's own arithmetic, restored
      in four bytes at ``0x0043F52F`` (``giten/exe/timing.atb_pc98``);
    * **the popup dwell stays at the stock 15 ticks**, not the 60 the release
      raises it to.  An open message window hard-disables the command UI
      (``docs/combat-pacing.md`` §2), so our longer dwell is itself a pacing
      change; leaving it at 15 keeps the gauge the only variable under test.
      English battle messages will flash past in this build.  That is the cost
      of a clean comparison, and it is why this is a dev exe and not a release.

    Everything else -- the English tables, the tracer, the 60 Hz loop -- matches
    ``dds_dev.exe``, so a route played on both is comparable token for token.
    """
    return _write(out_dir, "dds_dev_atb.exe", True, atb_pc98=True, popup_ticks=15)


def build_dev_hz(hz: int, out_dir: "str | None" = None) -> str:
    """``dds_dev_<hz>hz.exe``: the tracer at a chosen main-loop tick rate.

    For finding a playable rate by trying, rather than arguing about what the
    original did.  Everything counted in ticks moves together, so a rate that
    fixes battle and makes walking sluggish has still told us something: that
    the battle clock wants a different divider from the rest, not that the
    whole loop is mistimed.
    """
    return _write(out_dir, "dds_dev_%dhz.exe" % hz, True, True, hz=hz)


def build_dev_script_div(div: int, out_dir: "str | None" = None) -> str:
    """RETRACTED -- this builds an exe that behaves exactly like ``dds_dev.exe``.

    It divides the once-per-tick call to ``0x0043B5E0``, which was believed to be
    the clock scripted actors take their turns on.  ``0x0043B5E0`` returns
    immediately, always: it compares the background-script slot words
    ``[0x00469828]`` / ``[0x0046982C]`` against -1 and returns when either
    matches, they start at ``FFFF FFFF``, three of the four writers store -1, and
    the only one that can set a real value is reached from opcode ``1ECB``, which
    occurs **0 times in 20,690 records**.

    Kept only so the retraction has somewhere to live.  Use
    :func:`build_dev_battle_div`, which divides the battle state machine -- the
    thing that actually paces combat.
    """
    return _write(out_dir, "dds_dev_bat%d.exe" % div, True, script_div=div)


def build_dev_battle_div(div: int, out_dir: "str | None" = None) -> str:
    """``dds_dev_btl<div>.exe``: the tracer, 60 Hz, the battle machine divided.

    ``0x00417160`` runs one state handler per tick.  State 24 is the battle, and
    its handler is a nine-way sub-state machine whose every branch begins by
    advancing itself (``0x00416AD0`` = ``set_substate(cur + 1)``).  So the battle
    takes one phase per tick -- sixty a second -- while the player's command UI
    is a *different* top-level state, 32.  That is why a party of three facing
    one enemy got zero actions to its six in the 2026-09-08 session.

    Dividing the state-24 call site alone slows combat and nothing else: the
    field, the menus and the command UI are other states and still run every
    tick.  ``div=4`` gives the battle one phase per 1/15 s.
    """
    return _write(out_dir, "dds_dev_btl%d.exe" % div, True, battle_div=div)
