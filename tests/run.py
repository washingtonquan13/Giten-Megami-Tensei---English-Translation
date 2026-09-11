"""Minimal test runner: ``python -m tests.run`` (no pytest required).

Collects every ``test_*`` callable from every ``tests/test_*.py`` module and
runs **all** of them -- there is no fast tier and nothing is ever skipped.

    python -m tests.run                 every test, spread across processes
    python -m tests.run -j1             every test, one process, in order
    python -m tests.run -j4             four worker processes
    python -m tests.run <substring>     only tests whose name contains it

``-j1`` is the original runner, unchanged: one process, definition order, one
``ok``/``FAIL`` line per test with its wall time, every failure's traceback
printed in full at the end.  Anything a test prints -- in particular
``harness.build``'s ``NOT RUN`` line, which is the one thing that can make a
green suite meaningless -- goes to stdout where it always did.

Parallel mode runs the same tests in the same per-module order, in child
processes, one module at a time per child.  A child's output is relayed
verbatim, so a test's own prints and a failure's traceback read exactly as they
do serially; the parent adds nothing but the summary.  Modules are dispatched
longest-first from durations recorded by the previous run
(``build/cache/test-times.json``), which is scheduling only -- it never changes
which tests run or in what order within a module.

Why per *module* and not per test: a test module is the only unit whose tests
are known to be independent of the ones before them.  Several modules here
share state between their tests on purpose (one builds a tree, the next reads
it), so splitting a module across processes would be a correctness change
dressed up as a speed-up.
"""
from __future__ import annotations

import importlib
import json
import os
import pkgutil
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

#: where the previous run's per-module wall times are kept, for scheduling only
TIMES = os.path.join(REPO, "build", "cache", "test-times.json")

#: a worker prints this as its last line; the parent consumes it and does not
#: relay it
DONE = "##DONE"

#: and this one just before its first traceback, so the parent can hold the
#: tracebacks back to the end without having to guess where one starts
FAILURES = "##FAILURES"


def modules():
    """Every ``tests/test_*`` module name, in the order ``pkgutil`` lists them."""
    return [m.name for m in pkgutil.iter_modules([HERE])
            if m.name.startswith("test_")]


def tests_of(modname: str):
    """``[(name, fn)]`` for one module, in definition order."""
    module = importlib.import_module("tests." + modname)
    names = [n for n in vars(module) if n.startswith("test_")]
    names.sort(key=lambda n: getattr(vars(module)[n], "__code__").co_firstlineno)
    return [(n, vars(module)[n]) for n in names]


def collect():
    for modname in modules():
        for name, fn in tests_of(modname):
            yield "tests." + modname, name, fn


# --- running ----------------------------------------------------------------
def run_module(modname: str, pattern: str, out):
    """Run one module's tests in order; return ``(passed, failed, failures)``."""
    passed = failed = 0
    failures = []
    for name, fn in tests_of(modname):
        if pattern and pattern not in name:
            continue
        start = time.time()
        try:
            fn()
        except Exception:
            failed += 1
            failures.append(("tests." + modname, name, traceback.format_exc()))
            out.write("FAIL  %-58s %5.2fs\n" % (name, time.time() - start))
        else:
            passed += 1
            out.write("ok    %-58s %5.2fs\n" % (name, time.time() - start))
        out.flush()
    return passed, failed, failures


def report(failures, passed, failed, elapsed, out):
    for modname, name, tb in failures:
        out.write("\n" + "=" * 72 + "\n")
        out.write("%s.%s\n" % (modname, name))
        out.write("=" * 72 + "\n")
        out.write(tb + "\n")
    out.write("\n%d passed, %d failed in %.1fs\n" % (passed, failed, elapsed))
    out.flush()


def serial(pattern: str) -> int:
    out = sys.stdout
    passed = failed = 0
    failures = []
    t0 = time.time()
    for modname in modules():
        p, f, fs = run_module(modname, pattern, out)
        passed += p
        failed += f
        failures.extend(fs)
    report(failures, passed, failed, time.time() - t0, out)
    return 1 if failed else 0


# --- worker -----------------------------------------------------------------
def worker(modname: str, pattern: str) -> int:
    """One module, in this process, printing exactly what serial mode prints.

    Failures are printed here rather than handed back structured, so the parent
    relays a traceback it never had to re-format -- the whole point being that a
    failure reads the same however the suite was run.
    """
    out = sys.stdout
    passed, failed, failures = run_module(modname, pattern, out)
    if failures:
        out.write("%s\n" % FAILURES)
        for name, tb in [(f[1], f[2]) for f in failures]:
            out.write("\n" + "=" * 72 + "\n")
            out.write("tests.%s.%s\n" % (modname, name))
            out.write("=" * 72 + "\n")
            out.write(tb + "\n")
    out.write("%s %d %d\n" % (DONE, passed, failed))
    out.flush()
    return 1 if failed else 0


# --- parallel ---------------------------------------------------------------
def _load_times():
    try:
        with open(TIMES, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_times(times):
    try:
        os.makedirs(os.path.dirname(TIMES), exist_ok=True)
        tmp = TIMES + ".%d.tmp" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(times, fh, indent=0, sort_keys=True)
        os.replace(tmp, TIMES)
    except OSError:
        pass


def _run_worker(modname: str, pattern: str):
    """Run one module in a child and return everything it said.

    The child's whole output is read in this thread, so a module that prints a
    lot cannot fill its pipe and stall while the parent is busy with another --
    which is why this is a thread per child rather than one polling loop.
    """
    cmd = [sys.executable, "-u", "-m", "tests.run", "--worker", modname]
    if pattern:
        cmd += ["--pattern", pattern]
    started = time.time()
    p = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace",
                         env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    text = p.stdout.read()
    p.wait()
    return modname, text, p.returncode, time.time() - started


def parallel(pattern: str, jobs: int) -> int:
    import concurrent.futures as cf

    known = _load_times()
    # longest first, so the slowest module is not the last thing started.  An
    # unmeasured module is assumed slow, so a new one is never left to the end.
    order = sorted(modules(), key=lambda m: -known.get(m, 1e6))

    out = sys.stdout
    t0 = time.time()
    passed = failed = 0
    tails = []
    times = dict(known)

    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        futures = [ex.submit(_run_worker, m, pattern) for m in order]
        for fut in cf.as_completed(futures):
            modname, text, code, took = fut.result()
            times[modname] = took
            lines, tail, mine = [], [], None
            bucket = lines
            for ln in text.splitlines():
                if ln.startswith(DONE):
                    mine = ln.split()
                elif ln.startswith(FAILURES):
                    bucket = tail
                else:
                    bucket.append(ln)
            if mine is not None:
                passed += int(mine[1])
                failed += int(mine[2])
            else:
                # the child died without reporting.  That is a failure, and its
                # output -- whatever it managed to print -- is the evidence.
                failed += 1
                lines.append("FAIL  %-58s (worker for tests.%s exited %s "
                             "without a result)" % (modname, modname, code))
                tail = lines[-1:] + tail
            for ln in lines:
                out.write(ln + "\n")
            out.flush()
            if tail:
                tails.append("\n".join(tail).strip("\n"))

    for t in tails:
        out.write("\n" + t + "\n")
    _save_times(times)
    out.write("\n%d passed, %d failed in %.1fs\n"
              % (passed, failed, time.time() - t0))
    out.flush()
    return 1 if failed else 0


# --- cli --------------------------------------------------------------------
def _jobs_default() -> int:
    n = os.cpu_count() or 1
    return max(1, min(n, 12))


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if "--worker" in argv:
        i = argv.index("--worker")
        modname = argv[i + 1]
        pattern = ""
        if "--pattern" in argv:
            pattern = argv[argv.index("--pattern") + 1]
        return worker(modname, pattern)

    jobs = _jobs_default()
    pattern = ""
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("-j"):
            rest = a[2:] or (argv[i + 1] if i + 1 < len(argv) else "")
            if not a[2:]:
                i += 1
            jobs = _jobs_default() if rest in ("", "auto") else max(1, int(rest))
        elif not a.startswith("-"):
            pattern = a
        i += 1

    if jobs <= 1:
        return serial(pattern)
    return parallel(pattern, jobs)


if __name__ == "__main__":
    sys.exit(main())
