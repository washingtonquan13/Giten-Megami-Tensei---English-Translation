"""Compile ``giten/exe/hook.c`` into the native driver, and drive it.

Not a test module (``tests/run.py`` only collects ``test_*``).  It exists
because three test files now need the same two things: the real hook.c built as
a 32-bit exe, and a way to feed it a *script* of commands so one process can do
what one play session does -- load a buffer, walk it, swap the buffer under the
same handle, walk again.

``build`` prints ``NOT RUN`` and returns None when the machine refuses to
execute a binary that was linked a moment ago (Defender, ESET and friends).
That is not a result about the hook, so it must not read as one -- but it must
not read as a pass either, hence the line on stdout.  **A green suite carrying a
NOT RUN line is not verification.**
"""
from __future__ import annotations

import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))


def build(tmp: str, what: str = "the C hook"):
    from giten.exe import tracer
    if shutil.which("gcc") is None:
        return None
    exe = os.path.join(tmp, "hook_harness.exe")
    gcc = tracer.short_path(shutil.which("gcc"))
    # no CRT: the mingw driver cannot link its own CRT from a path with spaces
    subprocess.run([gcc, "-O2", "-Wall", "-Werror", "-ffreestanding", "-fno-builtin",
                    "-nostdlib", "-o", exe, tracer.HOOK_SOURCE,
                    os.path.join(HERE, "hook_harness.c"), "-I", HERE,
                    "-lkernel32", "-e", "_start"], check=True)
    try:
        subprocess.run([exe], cwd=tmp, capture_output=True)
    except OSError as exc:
        print("      NOT RUN: this machine will not execute the harness (%s);"
              " %s is UNVERIFIED" % (exc.__class__.__name__, what))
        return None
    return exe


def _parse(stdout: str):
    """``[(bytes, final pc)]``, one pair per ``walk``."""
    kv = [x.split("=", 1) for x in stdout.split()]
    out = []
    for i in range(0, len(kv), 2):
        assert kv[i][0] == "bytes" and kv[i + 1][0] == "pc", stdout[:120]
        out.append((bytes.fromhex(kv[i][1]), int(kv[i + 1][1])))
    return out


def walks(exe: str, tmp: str, lines: "list[str]"):
    """Run a command script through the harness; one result per ``walk`` line."""
    path = os.path.join(tmp, "harness-script.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    r = subprocess.run([exe, "script", path], cwd=tmp, capture_output=True,
                       text=True, check=True)
    return _parse(r.stdout)


def one(exe: str, tmp: str, image: str, handle: int, start: int, stop: int):
    """The five-argument form: one image, one walk, one process."""
    r = subprocess.run([exe, image, "0", str(handle), str(start), str(stop)],
                       cwd=tmp, capture_output=True, text=True, check=True)
    return _parse(r.stdout)[0]


def quoted(path: str) -> str:
    """A path as a script argument -- the temp directory has a space in it."""
    return '"%s"' % path


def synth_trace(table, image, fid: int = 0, recs=None, mutate=None) -> bytes:
    """A v4 trace of an English run over ``image``, from ``overlay.Model``.

    The recorded fixtures this replaces were v4/v5 overlays and a v2 trace, and
    a trace only means anything against the overlay that produced it -- so they
    could not be upgraded, only regenerated.  Generating them instead is
    strictly better: the trace is the model's own answer, so a check that fires
    on it is firing on the thing the hook implements rather than on a recording
    of a build nobody can rebuild.

    One event per *token*, the way ``trace.S`` logs them: the caller fetches the
    character or the opcode head (two bytes for a wide character or an
    ``1D``/``1E``/``1F`` escape), calls ``exec_token``, and the handler consumes
    the operands later -- so ``pc0`` is the program counter just past the head,
    not past the whole token.

    ``mutate(ev)`` may rewrite one event's field tuple before it is packed;
    that is how the fault-injection tests put a byte or a program counter
    somewhere it should not be.
    """
    from giten import overlay, vmops
    from giten.trace import core

    idx = overlay.live_index(image)
    end = overlay.live_end(image)
    out = bytearray(core.HEADER.pack(core.MAGIC, 4, core.RECORD_V4.size))
    n = 0
    for rid in (range(256) if recs is None else recs):
        off, ln = idx[rid]
        if ln <= 1:
            continue
        h = overlay.fnv1a(image[off:off + ln])
        model = overlay.Model(table, image)
        stream, after, pc, steps = bytearray(), [], off, 0
        while pc != off + ln and steps < (1 << 16):
            b, nxt = model.fetch(pc)
            stream.append(b)
            after.append(nxt)
            pc = nxt
            steps += 1
        try:
            toks = vmops.tokenize(bytes(stream))
        except Exception:
            continue                        # a record we cannot tile is not an oracle
        for t in toks:
            heads = []
            if t.kind == "op":
                heads.append((t.off, 1 if t.idx < 0x100 else 2))
            else:
                i = t.off
                while i < t.end:
                    w = 2 if (0x81 <= stream[i] <= 0x9F or 0xE0 <= stream[i] <= 0xFC) else 1
                    w = min(w, t.end - i)
                    heads.append((i, w))
                    i += w
            for start, width in heads:
                ch = int.from_bytes(bytes(stream[start:start + width]), "big")
                pc0 = after[start + width - 1]
                ev = [fid, rid, pc0, ch, 0, 0, 0, off, ln, pc0, 0, 0, h, end]
                if mutate is not None:
                    ev = mutate(list(ev), n) or ev
                out += core.RECORD_V4.pack(*ev)
                n += 1
    return bytes(out)


def pace(exe: str, tmp: str, granularity, total, stall_at=0, stall=0):
    out = subprocess.run([exe, "pace", str(granularity), str(total),
                          str(stall_at), str(stall)],
                         cwd=tmp, capture_output=True, text=True,
                         check=True).stdout.split()
    return dict(x.split("=", 1) for x in out)
