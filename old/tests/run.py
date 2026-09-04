"""Minimal test runner: `python -m tests.run` (no pytest required).

Collects every ``test_*`` callable from every ``tests/test_*.py`` module, runs
them in definition order, and prints a one-line summary per test.
"""
from __future__ import annotations

import importlib
import os
import pkgutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def collect():
    for mod in pkgutil.iter_modules([HERE]):
        if not mod.name.startswith("test_"):
            continue
        module = importlib.import_module("tests." + mod.name)
        names = [n for n in vars(module) if n.startswith("test_")]
        # definition order, not alphabetical
        names.sort(key=lambda n: getattr(vars(module)[n], "__code__").co_firstlineno)
        for n in names:
            yield module.__name__, n, vars(module)[n]


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    pattern = argv[0] if argv else ""
    passed = failed = 0
    failures = []
    t0 = time.time()
    for modname, name, fn in collect():
        if pattern and pattern not in name:
            continue
        start = time.time()
        try:
            fn()
        except Exception:
            failed += 1
            failures.append((modname, name, traceback.format_exc()))
            print("FAIL  %-58s %5.2fs" % (name, time.time() - start))
        else:
            passed += 1
            print("ok    %-58s %5.2fs" % (name, time.time() - start))
    for modname, name, tb in failures:
        print("\n" + "=" * 72)
        print("%s.%s" % (modname, name))
        print("=" * 72)
        print(tb)
    print("\n%d passed, %d failed in %.1fs" % (passed, failed, time.time() - t0))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
