"""Filesystem locations used by the Giten translation pipeline.

Nothing here ever writes into the game folder; ``GAME_ROOT`` is treated as
strictly read-only by every module in this package.
"""
from __future__ import annotations

import os

# tools/giten/paths.py -> tools/giten -> tools -> <repo root>
_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))

TEXT_DIR = os.path.join(REPO_ROOT, "text")
BUILD_DIR = os.path.join(REPO_ROOT, "build")
BUILD_DDSWIN = os.path.join(BUILD_DIR, "ddswin")
BACKUP_DIR = os.path.join(BUILD_DIR, "backup")


def _inside_repo(path: str) -> bool:
    """Is ``path`` inside the repository?

    ``build/ddswin`` is a ``ddswin`` directory too, and once a build exists it
    would otherwise shadow the real game folder in the search below -- silently
    turning every later command (including the identity test) into a tautology
    that compares a build against itself.  The game folder is always outside the
    repo, so anything inside it is skipped.
    """
    a = os.path.normcase(os.path.abspath(path))
    b = os.path.normcase(os.path.abspath(REPO_ROOT))
    return a == b or a.startswith(b + os.sep)


def find_game_root() -> str:
    """Locate the game's ``ddswin/`` folder.

    Resolution order:

    1. ``$GITEN_ROOT`` (must point straight at the ``ddswin`` directory),
    2. a ``ddswin`` directory found by walking up from the repository root,
       checking each ancestor *and* its immediate children -- the game folder is
       normally a sibling of the repo, one level up.  Candidates inside the repo
       (i.e. ``build/ddswin``) are never accepted.
    """
    env = os.environ.get("GITEN_ROOT")
    if env:
        if not os.path.isdir(env):
            raise SystemExit("GITEN_ROOT=%r is not a directory" % env)
        return os.path.abspath(env)

    d = REPO_ROOT
    for _ in range(8):
        candidates = [os.path.join(d, "ddswin")]
        try:
            candidates += [os.path.join(d, sub, "ddswin")
                           for sub in sorted(os.listdir(d))]
        except OSError:
            pass
        for cand in candidates:
            if os.path.isdir(cand) and not _inside_repo(cand):
                return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    raise SystemExit(
        "ddswin/ not found. Set GITEN_ROOT to the game's ddswin folder."
    )


_GAME_ROOT = None


def game_root() -> str:
    """Cached :func:`find_game_root`."""
    global _GAME_ROOT
    if _GAME_ROOT is None:
        _GAME_ROOT = find_game_root()
    return _GAME_ROOT


def game_path(rel: str) -> str:
    """Absolute path inside the game folder for a ``dir/FILE.BIN`` key."""
    return os.path.join(game_root(), *rel.split("/"))
