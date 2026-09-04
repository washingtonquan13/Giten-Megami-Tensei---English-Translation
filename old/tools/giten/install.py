"""``install``: copy a build over the game folder, backing up first.

This is the only command in the package that writes outside the repository, so it
is deliberately noisy and defensive:

* every original is copied to ``build/backup/<timestamp>/`` **before** anything is
  overwritten, and the backup is verified by re-reading it;
* a destination file that does not already exist is refused (the pipeline only
  replaces shipped files, it never adds new ones);
* ``--dry-run`` is the default; ``--yes`` is required to actually write.
"""
from __future__ import annotations

import filecmp
import os
import shutil
import time

from . import paths


def run(src: "str | None" = None, dst: "str | None" = None,
        backup_dir: "str | None" = None, dry_run: bool = True,
        quiet: bool = False) -> dict:
    src = os.path.abspath(src or paths.BUILD_DDSWIN)
    dst = os.path.abspath(dst or paths.game_root())
    if not os.path.isdir(src):
        raise SystemExit("nothing to install: %s does not exist (run `build` first)" % src)
    if not os.path.isdir(dst):
        raise SystemExit("destination %s is not a directory" % dst)
    if os.path.normcase(src) == os.path.normcase(dst):
        raise SystemExit("source and destination are the same directory")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(backup_dir or paths.BACKUP_DIR, stamp)

    plan = []
    for base, _dirs, names in os.walk(src):
        for n in sorted(names):
            s = os.path.join(base, n)
            rel = os.path.relpath(s, src)
            d = os.path.join(dst, rel)
            if not os.path.exists(d):
                raise SystemExit(
                    "refusing to install: %s has no counterpart in the game folder"
                    % rel)
            if filecmp.cmp(s, d, shallow=False):
                continue
            plan.append((rel, s, d))

    stats = {"total": len(plan), "copied": 0, "backup": backup, "dry_run": dry_run}
    if not quiet:
        print("%d file(s) differ between %s and %s" % (len(plan), src, dst))
    if dry_run:
        if not quiet:
            for rel, _s, _d in plan[:40]:
                print("  would replace " + rel)
            if len(plan) > 40:
                print("  ... and %d more" % (len(plan) - 40))
            print("dry run: pass --yes to write, originals go to %s" % backup)
        return stats

    for rel, s, d in plan:
        b = os.path.join(backup, rel)
        os.makedirs(os.path.dirname(b), exist_ok=True)
        shutil.copy2(d, b)
        if not filecmp.cmp(d, b, shallow=False):
            raise SystemExit("backup of %s did not verify; aborting" % rel)
        shutil.copy2(s, d)
        stats["copied"] += 1

    if not quiet:
        print("installed %d file(s); originals backed up to %s"
              % (stats["copied"], backup))
    return stats
