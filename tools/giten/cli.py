"""Command line entry point: ``python -m tools.giten <cmd>``."""
from __future__ import annotations

import argparse
import os
import sys

from . import (audit, build, build_v2, check, check_v2, extract, extract_v2,
               files, install, migrate, paths, rebase, stats)


def _common(p):
    p.add_argument("--root", help="game ddswin/ folder (default: auto / $GITEN_ROOT)")
    p.add_argument("--text", dest="text_dir", help="text tables folder (default: "
                                                   "text/ for v1, text_v2/ for v2)")
    p.add_argument("-q", "--quiet", action="store_true")


def _engine(p):
    p.add_argument("--engine", choices=("v1", "v2"), default="v2",
                   help="v1: the original span scanner over text/ (default, kept "
                        "alive while translators work in text/). "
                        "v2: the opcode-aware pipeline over text_v2/ "
                        "(multi-container, rel16 relocation, real width budgets)")


def make_parser():
    ap = argparse.ArgumentParser(
        prog="python -m tools.giten",
        description="Giten Megami Tensei translation pipeline "
                    "(extract / build / check / install / stats).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("extract", help="game files -> editable text tables")
    p.add_argument("--family", default="all", choices=files.FAMILY_CHOICES)
    _engine(p)
    _common(p)

    p = sub.add_parser("build", help="tables + game files -> a build tree")
    p.add_argument("--out", default=None,
                   help="output folder (default build/ddswin, or build/ddswin_v2)")
    p.add_argument("--family", default="all", choices=files.FAMILY_CHOICES)
    p.add_argument("--identity", action="store_true",
                   help="ignore the tables entirely (pure round-trip build)")
    p.add_argument("--only", action="append", default=None, metavar="GLOB",
                   help="apply tables only to files matching this dir/FILE.BIN "
                        "glob (repeatable); everything else builds as identity")
    _engine(p)
    _common(p)

    p = sub.add_parser("check", help="run the validators")
    p.add_argument("--family", default="all", choices=files.FAMILY_CHOICES)
    p.add_argument("--width-scale", type=float, default=check.DEFAULT_WIDTH_SCALE,
                   help="v1 only: line-width budget as a multiple of the source "
                        "line's pixel width (default %(default)s)")
    p.add_argument("--max-line-width", type=int, default=None,
                   help="v1 only: hard cap in half-width units, if you know one")
    p.add_argument("--skip-identity", action="store_true",
                   help="skip the (slow) byte-exact round-trip test")
    p.add_argument("--verify", action="store_true",
                   help="v2 only: also run the reference decoder and the "
                        "tokenizer over a build tree (--out)")
    p.add_argument("--out", default=None, help="build tree for --verify")
    p.add_argument("--show", type=int, default=200, help="findings to print per level")
    _engine(p)
    _common(p)

    p = sub.add_parser("migrate",
                       help="carry finished translations from one table set to "
                            "a freshly extracted one (text -> text_v2)")
    p.add_argument("--from", dest="src", default=None, help="default text/")
    p.add_argument("--to", dest="dst", default=None, help="default text_v2/")
    p.add_argument("--report", default=None,
                   help="where to write the full report "
                        "(default build/migrate-report.txt)")
    p.add_argument("--root", help="game ddswin/ folder")
    p.add_argument("-q", "--quiet", action="store_true")

    p = sub.add_parser("rebase",
                       help="carry translations from v0.05-based tables onto "
                            "tables extracted from the Japanese original")
    p.add_argument("--from", dest="src", default=None, help="default text_v2/")
    p.add_argument("--to", dest="dst", default=None, help="default text_v3/")
    p.add_argument("--report", default=None, help="default build/rebase-report.txt")
    p.add_argument("-q", "--quiet", action="store_true")

    p = sub.add_parser("verify",
                       help="reference-decode and re-tile every file of a build")
    p.add_argument("--dir", dest="out_dir", default=None,
                   help="build tree to verify (default build/ddswin_v2)")
    p.add_argument("--root", help="game ddswin/ folder")
    p.add_argument("-q", "--quiet", action="store_true")

    p = sub.add_parser("audit",
                       help="prove a build still runs the same script as the "
                            "source: structural opcodes, branch targets, "
                            "branches into edited text, runtime image size")
    p.add_argument("--dir", dest="build_dir", default=None,
                   help="build tree to audit (default build/ddswin_v2)")
    p.add_argument("--root", help="game ddswin/ folder")
    p.add_argument("--show", type=int, default=40, help="findings to print")
    p.add_argument("-q", "--quiet", action="store_true")

    p = sub.add_parser("install", help="copy a build over the game folder")
    p.add_argument("--from", dest="src", default=None)
    p.add_argument("--to", dest="dst", default=None)
    p.add_argument("--yes", action="store_true",
                   help="actually write (default is a dry run)")
    p.add_argument("-q", "--quiet", action="store_true")

    p = sub.add_parser("stats", help="translated / remaining counts")
    p.add_argument("--no-per-file", dest="per_file", action="store_false")
    p.add_argument("--text", dest="text_dir", default=None)
    p.add_argument("-q", "--quiet", action="store_true")

    sub.add_parser("where", help="print the resolved game and repo paths")
    return ap


def main(argv=None) -> int:
    args = make_parser().parse_args(argv)
    if args.cmd == "extract":
        mod = extract_v2 if args.engine == "v2" else extract
        mod.run(args.family, args.root, args.text_dir, args.quiet)
        return 0
    if args.cmd == "build":
        mod = build_v2 if args.engine == "v2" else build
        st = mod.run(args.out, args.family, args.root, args.text_dir,
                     args.quiet, ignore_tables=args.identity,
                     **({"only": args.only} if args.engine == "v2" else {}))
        return 1 if st["errors"] else 0
    if args.cmd == "check":
        if args.engine == "v2":
            rep = check_v2.run(args.root, args.text_dir, args.family,
                               args.skip_identity, args.quiet, args.show,
                               args.out, args.verify)
        else:
            rep = check.run(args.root, args.text_dir, args.family,
                            args.width_scale, args.max_line_width,
                            args.skip_identity, args.quiet, args.show)
        return 1 if rep.errors else 0
    if args.cmd == "migrate":
        migrate.run(args.src, args.dst, args.root, args.quiet, args.report)
        return 0
    if args.cmd == "rebase":
        rebase.run(args.src, args.dst, args.quiet, args.report)
        return 0
    if args.cmd == "verify":
        out_dir = args.out_dir or os.path.join(paths.BUILD_DIR, "ddswin_v2")
        st = check_v2.verify_tree(out_dir, args.root)
        if not args.quiet:
            check_v2._print_verify(st, out_dir)
        return 1 if (st["decode_fail"] or st["regressions"]) else 0
    if args.cmd == "audit":
        rep = audit.run(args.build_dir, args.root, args.quiet, args.show)
        return 1 if rep.findings else 0
    if args.cmd == "install":
        install.run(args.src, args.dst, dry_run=not args.yes, quiet=args.quiet)
        return 0
    if args.cmd == "stats":
        stats.run(args.text_dir, args.per_file, args.quiet)
        return 0
    if args.cmd == "where":
        print("game (read-only): %s" % paths.game_root())
        print("repo            : %s" % paths.REPO_ROOT)
        print("tables          : %s" % paths.TEXT_DIR)
        print("build output    : %s" % paths.BUILD_DDSWIN)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
