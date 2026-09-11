"""``install``: copy a build over the game folder, backing up first.

This is the only command in the package that writes outside the repository, so it
is deliberately noisy and defensive:

* every original is copied to ``build/backup/<timestamp>/`` **before** anything is
  overwritten, and the backup is verified by re-reading it;
* a destination file that does not already exist is refused, **unless it is one
  of the handful of files the build deliberately adds** (:data:`ADDED`);
* an ``m/`` file is refused outright when the destination holds ``overlay.dat``
  -- see :data:`ADDED` and the guard below;
* ``--dry-run`` is the default; ``--yes`` is required to actually write.
"""
from __future__ import annotations

import filecmp
import os
import shutil
import time

from . import paths


def _added() -> "frozenset[str]":
    """Paths the build adds rather than replaces, in ``os.sep`` form.

    Exactly ``et/et0102.bin`` today: the English item database, which cannot go
    back into ``et/ET0001.BIN`` because that file is capped at 65,535 bytes
    three ways.  The "no counterpart" rule is otherwise worth keeping -- it is
    what stops a stray file in a build tree becoming a stray file in someone's
    game folder -- so this is an allow-list, not a switch.
    """
    from .build_v2 import ADDED_FILES
    return frozenset(rel.replace("/", os.sep) for rel in ADDED_FILES)


def _overlay_install(dst: str) -> bool:
    """Does this game folder run the runtime text overlay?

    If it does, its ``m/`` files must stay the **originals**: overlay v6 keys a
    translated span on the content of the record it lives in, so installing
    byte-built ``m/`` files over them changes every key and the overlay serves
    nothing.  The two ways of shipping the translation are alternatives, and
    mixing them is strictly worse than either.
    """
    return os.path.exists(os.path.join(dst, "overlay.dat"))


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

    added = _added()
    overlay_here = _overlay_install(dst)

    plan, new = [], []
    for base, _dirs, names in os.walk(src):
        for n in sorted(names):
            s = os.path.join(base, n)
            rel = os.path.relpath(s, src)
            d = os.path.join(dst, rel)
            if not os.path.exists(d):
                if os.path.normcase(rel) not in {os.path.normcase(a) for a in added}:
                    raise SystemExit(
                        "refusing to install: %s has no counterpart in the game "
                        "folder and is not one of the files the build adds (%s)"
                        % (rel, ", ".join(sorted(added)) or "none"))
                new.append((rel, s, d))
                continue
            if overlay_here and rel.split(os.sep)[0] == "m":
                raise SystemExit(
                    "refusing to install: %s holds overlay.dat, so its m/ files "
                    "must stay the originals -- overlay v6 keys each translated "
                    "span on the content of the record it lives in, and a "
                    "byte-built %s would change every key in it.  Install the "
                    "overlay build (dds.exe + overlay.dat + et/) or the byte "
                    "build, not both." % (dst, rel))
            if filecmp.cmp(s, d, shallow=False):
                continue
            plan.append((rel, s, d))
    plan.extend(new)

    stats = {"total": len(plan), "copied": 0, "added": len(new),
             "backup": backup, "dry_run": dry_run}
    if not quiet:
        print("%d file(s) differ between %s and %s" % (len(plan), src, dst))
    if dry_run:
        if not quiet:
            newset = {r for r, _s, _d in new}
            for rel, _s, _d in plan[:40]:
                print("  would %s %s"
                      % ("add" if rel in newset else "replace", rel))
            if len(plan) > 40:
                print("  ... and %d more" % (len(plan) - 40))
            print("dry run: pass --yes to write, originals go to %s" % backup)
        return stats

    for rel, s, d in plan:
        if os.path.exists(d):
            b = os.path.join(backup, rel)
            os.makedirs(os.path.dirname(b), exist_ok=True)
            shutil.copy2(d, b)
            if not filecmp.cmp(d, b, shallow=False):
                raise SystemExit("backup of %s did not verify; aborting" % rel)
        else:
            os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        stats["copied"] += 1

    if not quiet:
        print("installed %d file(s); originals backed up to %s"
              % (stats["copied"], backup))
    return stats
