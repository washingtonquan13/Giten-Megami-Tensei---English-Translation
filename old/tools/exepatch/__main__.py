"""CLI entry point: ``python -m tools.exepatch <extract|check|build|verify>``."""
from __future__ import annotations

import argparse
import io
import os
import sys


def _force_utf8():
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in ("stdout", "stderr"):
        s = getattr(sys, stream)
        if hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8", errors="backslashreplace")
            except Exception:  # pragma: no cover - very old CPython
                pass


def main(argv=None):
    _force_utf8()
    ap = argparse.ArgumentParser(prog="python -m tools.exepatch",
                                 description="Table-driven string patcher for dds_en.exe")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("extract", help="rebuild text_v2/exe/strings.tsv from the exes")
    p.add_argument("--reseed", action="store_true",
                   help="discard hand-written en/note values and re-read them from the exe")

    sub.add_parser("check", help="validate the table (no binaries touched)")

    p = sub.add_parser("build", help="write build/dds_en.exe")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--force", action="store_true",
                   help="build anyway, skipping rows that failed placement")

    sub.add_parser("verify", help="re-parse build/dds_en.exe and prove the edits landed")

    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2

    if args.cmd == "extract":
        from . import extract
        return extract.run(args)
    if args.cmd == "check":
        from . import check
        return check.run(args)
    if args.cmd == "build":
        from . import build
        return build.run(args)
    if args.cmd == "verify":
        from . import verify
        return verify.run(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
