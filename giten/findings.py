"""Finding / Report types shared by the checkers (formerly in the v1 ``check``).

``SKIP_MARKERS``: a ``note`` containing one of these (case-insensitive) means
"deliberately not translated".  They are ``@``-prefixed so ordinary prose in a
note can never switch a check off by accident.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ERROR, WARN = "error", "warn"
SKIP_MARKERS = ("@keep", "@skip", "@no-tl", "@untranslatable")


@dataclass
class Finding:
    rule: str
    level: str
    where: str
    message: str

    def __str__(self):
        return "%-5s %-8s %-34s %s" % (self.level.upper(), self.rule, self.where,
                                       self.message)


@dataclass
class Report:
    findings: "list[Finding]" = field(default_factory=list)
    counts: dict = field(default_factory=dict)

    def add(self, rule, level, where, message):
        self.findings.append(Finding(rule, level, where, message))
        self.counts[rule] = self.counts.get(rule, 0) + 1

    @property
    def errors(self):
        return [f for f in self.findings if f.level == ERROR]

    @property
    def warnings(self):
        return [f for f in self.findings if f.level == WARN]
