"""Command line entry point: ``python -m tools.giten <cmd>``."""
from __future__ import annotations

import argparse
import os
import sys

from . import build, check, extract, files, install, paths, stats


def _common(p):
    p.add_argument("--root", help="game ddswin/ folder (default: auto / $GITEN_ROOT)")
    p.add_argument("--text", dest="text_dir", help="text tables folder (default: text/)")
    p.add_argument("-q", "--quiet", action="store_true")


def make_parser():
    ap = argparse.ArgumentParser(
        prog="python -m tools.giten",
        description="Giten Megami Tensei translation pipeline "
                    "(extract / build / check / install / stats).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("extract", help="game files -> editable tables under text/")
    p.add_argument("--family", default="all", choices=files.FAMILY_CHOICES)
    _common(p)

    p = sub.add_parser("build", help="tables + game files -> build/ddswin")
    p.add_argument("--out", default=None, help="output folder (default build/ddswin)")
    p.add_argument("--family", default="all", choices=files.FAMILY_CHOICES)
    p.add_argument("--identity", action="store_true",
                   help="ignore the tables entirely (pure round-trip build)")
    _common(p)

    p = sub.add_parser("check", help="run the validators")
    p.add_argument("--family", default="all", choices=files.FAMILY_CHOICES)
    p.add_argument("--width-scale", type=float, default=check.DEFAULT_WIDTH_SCALE,
                   help="line-width budget as a multiple of the source line's "
                        "pixel width (default %(default)s)")
    p.add_argument("--max-line-width", type=int, default=None,
                   help="hard cap in half-width units, if you know one")
    p.add_argument("--skip-identity", action="store_true",
                   help="skip the (slow) byte-exact round-trip test")
    p.add_argument("--show", type=int, default=200, help="findings to print per level")
    _common(p)

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
        extract.run(args.family, args.root, args.text_dir, args.quiet)
        return 0
    if args.cmd == "build":
        st = build.run(args.out, args.family, args.root, args.text_dir,
                       args.quiet, ignore_tables=args.identity)
        return 1 if st["errors"] else 0
    if args.cmd == "check":
        rep = check.run(args.root, args.text_dir, args.family, args.width_scale,
                        args.max_line_width, args.skip_identity, args.quiet,
                        args.show)
        return 1 if rep.errors else 0
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
