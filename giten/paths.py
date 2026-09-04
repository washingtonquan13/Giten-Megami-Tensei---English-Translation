"""Filesystem locations used by the Giten translation pipeline.

Nothing here ever writes into the game folder; ``GAME_ROOT`` is treated as
strictly read-only by every module in this package.
"""
from __future__ import annotations

import os

# giten/paths.py -> giten -> <repo root>
_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)

TEXT_DIR = os.path.join(REPO_ROOT, "tables")
BUILD_DIR = os.path.join(REPO_ROOT, "build")
BUILD_DDSWIN = os.path.join(BUILD_DIR, "ddswin")
BACKUP_DIR = os.path.join(BUILD_DIR, "backup")


ORIGINAL_DDSWIN = os.path.join(REPO_ROOT, "original", "ddswin")


def find_game_root() -> str:
    """The game folder is always ``original/ddswin``: a read-only copy of the
    untouched Japanese release, checked against ``original/MANIFEST.sha256``.

    The old resolver walked up from the repo and accepted the first ``ddswin``
    it met; with a dozen play-test installs as siblings it could silently pick
    the wrong game.  ``$GITEN_ROOT`` is honoured only as an explicit override.
    """
    env = os.environ.get("GITEN_ROOT")
    root = os.path.abspath(env) if env else ORIGINAL_DDSWIN
    if not os.path.isdir(root):
        raise SystemExit("game folder not found: %s" % root)
    return root


_GAME_ROOT = None


def game_root() -> str:
    global _GAME_ROOT
    if _GAME_ROOT is None:
        _GAME_ROOT = find_game_root()
    return _GAME_ROOT


def game_path(rel: str) -> str:
    return os.path.join(game_root(), *rel.split("/"))
