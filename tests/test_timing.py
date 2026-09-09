"""The tick-counted popup duration.

The patch is one immediate inside one instruction, so the things worth testing
are that the instruction is still the one we reverse-engineered, that only its
immediate changes, and that the call sites which pass an explicit duration are
left alone -- the `jge` above the default skips it for them.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten.exe import patch, timing  # noqa: E402
from giten.exe.pe import PE  # noqa: E402


def _release():
    return patch.apply(open(patch.ORG, "rb").read(), "release")


def test_the_default_is_the_instruction_we_think_it_is():
    img = _release()
    pe = PE(img, "t")
    off = pe.va2off(timing.POPUP_DEFAULT_SITE)
    assert img[off:off + 5] == timing.POPUP_DEFAULT_OLD
    assert img[off] == 0xB8, "not a mov eax, imm32"
    assert struct.unpack_from("<I", img, off + 1)[0] == 15

    # the clamp above it: cmp ax,1 / jge past the mov
    assert img[off - 6:off] == bytes.fromhex("663d01007d05")


def test_only_the_immediate_changes():
    img = _release()
    out = timing.apply(img)
    assert len(out) == len(img)
    diff = [i for i in range(len(img)) if img[i] != out[i]]
    pe = PE(img, "t")
    off = pe.va2off(timing.POPUP_DEFAULT_SITE)
    assert diff == [off + 1], diff          # one byte: 0x0F -> 0x3C
    assert out[off] == 0xB8
    assert struct.unpack_from("<I", out, off + 1)[0] == timing.POPUP_TICKS


def test_the_counter_is_a_u16_so_the_value_must_fit():
    img = _release()
    for bad in (0, -1, 0x8000):
        try:
            timing.apply(img, bad)
        except RuntimeError as exc:
            assert "outside the u16" in str(exc), exc
        else:
            raise AssertionError("%d ticks was accepted" % bad)
    timing.apply(img, 1)
    timing.apply(img, 0x7FFF)


def test_the_call_sites_are_what_the_docstring_claims_and_are_untouched():
    """Only one of the three passes a literal: 0x00406211 asks for 0x3C ticks
    and so never reaches the default.  The other two pass a computed value
    (0x004027E0 the config word at 0x47BB72, which is zero-initialised;
    0x004026CB a local), and reach the default whenever that value is < 1."""
    img = _release()
    pe = PE(img, "t")
    out = timing.apply(img)
    sites = {0x00406211: "6a3c",        # push 0x3C -- explicit, unaffected
             0x004027E0: "0050",        # push eax  -- from the 0x47BB72 getter
             0x004026CB: "0856"}        # push esi
    for va, want in sites.items():
        off = pe.va2off(va)
        assert img[off - 2:off].hex() == want, (hex(va), img[off - 2:off].hex())
        assert out[off - 2:off] == img[off - 2:off], "a call site changed"
    # the explicit caller's value is what we raise the default to
    assert timing.POPUP_TICKS == 0x3C


def test_it_refuses_an_image_whose_default_moved():
    img = bytearray(_release())
    pe = PE(bytes(img), "t")
    img[pe.va2off(timing.POPUP_DEFAULT_SITE)] ^= 0xFF
    try:
        timing.apply(bytes(img))
    except RuntimeError as exc:
        assert "not the original's" in str(exc), exc
    else:
        raise AssertionError("a moved default was accepted")


def test_the_release_exe_carries_it():
    from giten.exe import tracer

    img = tracer.build_image(False)
    pe = PE(img, "rel")
    off = pe.va2off(timing.POPUP_DEFAULT_SITE)
    assert struct.unpack_from("<I", img, off + 1)[0] == timing.POPUP_TICKS
    assert abs(timing.seconds(timing.POPUP_TICKS) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# The background-script divider.
#
# 0x401980 calls 0x43B5E0 once per game tick, and 0x43B5E0 runs the background
# script until it blocks (0x4390F0 = `do exec_token while result >= 0`).  So the
# tick rate is the rate at which scripted actors take their turns, which is why
# enemies in a battle outpace the player at 60 Hz.  Lowering the whole loop was
# tried and rejected: 30 and 40 Hz make walking unbearable.  hook.c divides only
# this one call, so the field keeps its 60 Hz.
# ---------------------------------------------------------------------------

def test_the_background_script_step_is_where_the_documentation_says():
    """Pin the call site against the untouched original, not against a build."""
    import struct
    from giten.exe import patch, tracer
    from giten.exe.pe import PE

    with open(patch.ORG, "rb") as fh:
        img = fh.read()
    pe = PE(img)
    site = tracer.SCRIPT_STEP_SITES[0]
    off = pe.va2off(site)
    assert img[off] == 0xE8, "no call at 0x%X" % site
    rel = struct.unpack_from("<i", img, off + 1)[0]
    assert (site + 5 + rel) & 0xFFFFFFFF == tracer.SCRIPT_STEP, (
        "0x%X no longer calls the background-script step" % site)


def test_the_divider_reaches_the_compiler_and_exports_its_entry_point():
    """`-DSCRIPT_DIV` has to change the code, or the exe would build clean and
    do nothing -- the failure mode this test exists for."""
    from giten.exe import tracer

    va = 0x1000000
    plain, syms1 = tracer.compile_hook_ex(va, script_div=1)
    divided, syms4 = tracer.compile_hook_ex(va, script_div=4)
    assert "script_step" in syms4, syms4
    assert plain != divided, "SCRIPT_DIV did not change the compiled hook"
    # and the hook itself still has to come first, for the fetch redirect
    assert syms1["hook"] == va and syms4["hook"] == va


def test_the_battle_divider_gates_the_state_the_battle_actually_runs_in():
    """The one that matters, and the one the retracted divider got wrong.

    `0x00417160` dispatches one state handler per tick through the table at
    `0x00417288`, and entry 24 is the battle.  Its handler advances one battle
    phase per call, so gating that call site is what slows combat -- while the
    command UI, which is entry 32, keeps running every tick.
    """
    import struct
    from giten.exe import tracer
    from giten.exe.pe import PE

    img = open(tracer.build_release(), "rb").read()
    pe = PE(img, "release")

    # entry 24 of the state table really is a stub that calls the battle handler
    tbl = pe.va2off(0x00417288)
    stub = struct.unpack_from("<I", img, tbl + 24 * 4)[0]
    assert stub == 0x0041720A, "state 24's stub moved: 0x%08X" % stub
    off = pe.va2off(stub)
    assert img[off] == 0xE8, "state 24's stub is no longer a call"
    rel = struct.unpack_from("<i", img, off + 1)[0]
    assert (stub + 5 + rel) & 0xFFFFFFFF == tracer.BATTLE_STEP, (
        "0x%08X no longer calls the battle state handler" % stub)
    assert tracer.BATTLE_STEP_SITES == (stub,)

    # and the command UI is a *different* entry, so dividing one leaves it alone
    ui = struct.unpack_from("<I", img, tbl + 32 * 4)[0]
    assert ui != stub, "the battle and its command UI are the same state?"

    va = 0x1000000
    plain, syms1 = tracer.compile_hook_ex(va, battle_div=1)
    divided, syms4 = tracer.compile_hook_ex(va, battle_div=4)
    assert "battle_step" in syms4, syms4
    assert plain != divided, "BATTLE_DIV did not change the compiled hook"
    assert syms1["hook"] == va and syms4["hook"] == va


def test_the_retracted_script_divider_gates_a_function_that_does_nothing():
    """`build_dev_script_div` builds an exe identical in behaviour to the plain
    dev build, and this is the proof, so nobody trusts it again.

    `0x0043B5E0` compares the background-script slot against -1 and returns when
    it matches.  The slot is only ever set from opcode `1ECB`.
    """
    import glob
    import os
    from giten import files, paths, script

    src = open(os.path.join(paths.REPO_ROOT, "giten", "exe", "tracer.py"),
               encoding="utf-8").read()
    assert "RETRACTED" in src, "the retraction note has gone from tracer.py"

    seen = 0
    for sub in ("m", "et", "p"):
        for p in sorted(glob.glob(os.path.join(paths.game_root(), sub, "*.BIN"))):
            rel = os.path.relpath(p, paths.game_root()).replace(os.sep, "/")
            try:
                sc = script.parse(rel, files.read_source(rel))
            except Exception:
                continue
            if not sc.ok:
                continue
            for c in sc.containers:
                for r in c:
                    for t in (r.tokens or []):
                        if t.idx == 0x200 + 0xCB:      # 1E CB
                            seen += 1
    assert seen == 0, "opcode 1ECB now occurs %d time(s); re-check the retraction" % seen


# ---------------------------------------------------------------------------
# The turn gauge.
#
# 0x0043F510 is one tick of one combatant's ATB wait counter, and it is the
# game's turn order -- there is no initiative sort.  The 1997 PC-9801 release
# has the same routine with `add ax,5` where this one has
# `lea ecx,[eax+eax*1+5]`, so the port doubled the step and nothing else.
# `atb_pc98` puts it back, in the same four bytes.  It is a gameplay change and
# only the comparison build carries it.
# ---------------------------------------------------------------------------

def test_the_step_is_the_instruction_the_pc98_diff_identified():
    """Pin it against the untouched original, and pin the call above it too --
    the `x2` only means what we claim if the value being doubled really is the
    `1 + rand()%speed` the random helper returns."""
    import struct
    from giten.exe.pe import PE

    with open(patch.ORG, "rb") as fh:
        img = fh.read()
    pe = PE(img)
    off = pe.va2off(timing.ATB_STEP_SITE)
    assert img[off:off + 4] == timing.ATB_STEP_DOUBLED

    # ... immediately after `call 0x0040B960`, reached with (1, speed, 0)
    call = off - 5
    assert img[call] == 0xE8, "no call above the step"
    rel = struct.unpack_from("<i", img, call + 1)[0]
    assert (timing.ATB_STEP_SITE - 5 + 5 + rel) & 0xFFFFFFFF == 0x0040B960
    # push 0 / push eax (the speed field) / push 1 -- cdecl pushes right to
    # left, so this is f(1, speed, 0) = 1 + rand()%speed, the value doubled
    assert img[call - 5:call] == bytes.fromhex("6a00506a01"), \
        img[call - 5:call].hex(" ")

    # eax is dead right after, which is what makes dropping an addend safe
    assert img[off + 4:off + 8] == bytes.fromhex("668b4601"), "mov ax,[esi+1]"


def test_restoring_it_changes_exactly_four_bytes():
    img = _release()
    out = timing.atb_pc98(img)
    assert len(out) == len(img)
    pe = PE(img, "t")
    off = pe.va2off(timing.ATB_STEP_SITE)
    assert set(i for i in range(len(img)) if img[i] != out[i]) <= set(range(off, off + 4))
    assert out[off:off + 4] == timing.ATB_STEP_PC98
    assert len(timing.ATB_STEP_PC98) == len(timing.ATB_STEP_DOUBLED) == 4


def test_it_refuses_an_image_that_is_not_the_port_s():
    """Including one that already carries it -- applying twice must not be a
    silent no-op that leaves someone thinking a build was halved when it was."""
    img = _release()
    once = timing.atb_pc98(img)
    for bad in (once,):
        try:
            timing.atb_pc98(bad)
        except RuntimeError as exc:
            assert "is not the port's" in str(exc), exc
        else:
            raise AssertionError("a already-patched image was accepted")


def test_only_the_comparison_build_carries_it():
    """And it keeps the stock popup dwell, so the gauge is the only variable.

    The release and plain dev builds must be unaffected: combat speed is a
    gameplay decision and does not belong in the patch people play.
    """
    import struct
    from giten.exe import tracer
    from giten.exe.pe import PE

    plain = tracer.build_image(False)
    pe = PE(plain, "rel")
    off = pe.va2off(timing.ATB_STEP_SITE)
    pop = pe.va2off(timing.POPUP_DEFAULT_SITE)
    assert plain[off:off + 4] == timing.ATB_STEP_DOUBLED, "the release halved the gauge"
    assert struct.unpack_from("<I", plain, pop + 1)[0] == timing.POPUP_TICKS

    atb = tracer.build_image(True, atb_pc98=True, popup_ticks=15)
    assert atb[off:off + 4] == timing.ATB_STEP_PC98
    assert struct.unpack_from("<I", atb, pop + 1)[0] == 15, "the dwell is not stock"

    # the two builds it is meant to be compared against differ only in these
    dev = tracer.build_image(True)
    assert len(dev) == len(atb)
    diff = set(i for i in range(len(dev)) if dev[i] != atb[i])
    assert diff <= set(range(off, off + 4)) | {pop + 1}, sorted(diff)
