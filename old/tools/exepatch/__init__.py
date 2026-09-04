"""Table-driven string patcher for Giten Megami Tensei's ``dds_en.exe``.

Sub-commands (``python -m tools.exepatch <cmd>``):

``extract``  rebuild ``text_v2/exe/strings.tsv`` from the two reference exes
``check``    validate the table without touching any binary
``build``    write ``build/dds_en.exe`` from the game exe + the table
``verify``   re-parse the built exe and prove every edit landed as intended

Nothing in this package ever writes inside the game folder.
"""

__all__ = ["config", "pe", "table", "scan", "extract", "build", "check", "verify"]
