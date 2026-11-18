"""Writer agent: turns checked answers into a short brief.

It only gets answers that passed every check, and the text it writes is
scanned for numbers afterwards. Any number that doesn't match one of the
checked values gets sent back once with a note; if it still doesn't match,
the brief is marked as not checked rather than published.
"""
from __future__ import annotations

from dataclasses import dataclass

from .analyst import Answer
from .llm import obj_schema, run_agent
from .verify import check_text

SYSTEM = """\
You write a short weekly marketing brief for Lumora's founders from findings an analyst has already checked.

Rules:
- Use only the numbers given to you, written the same way or rounded (e.g. 101390.95 can be "$101.4k" or "about $101k"; a share of 0.142 can be "14%"). Don't calculate new numbers, totals or differences.
- Plain, direct sentences. No hype, no bullet lists in the paragraphs, no headings inside paragraphs.
- Lead with what someone should do differently, then the evidence.
- A headline of under 12 words and two to four short paragraphs.
"""

OUTPUT = obj_schema({"headline": {"type": "string"}, "paragraphs": {"type": "array", "items": {"type": "string"}}})


@dataclass
class Brief:
    headline: str
    paragraphs: list[str]
    unsupported_numbers: list[str]

    @property
    def checked(self) -> bool:
        return not self.unsupported_numbers

    def markdown(self) -> str:
        return f"# {self.headline}\n\n" + "\n\n".join(self.paragraphs) + "\n"


def write_brief(client, answers: list[Answer], effort: str = "medium") -> Brief:
    good = [a for a in answers if a.verified]
    values = [float(c.actual) for a in good for c in a.checks if c.actual is not None]
    findings = []
    for a in good:
        nums = "; ".join(f"{c.claim['statement']} = {c.actual:.6g}" for c in a.checks)
        findings.append(f"Q: {a.question}\nA: {a.answer}\nChecked numbers: {nums}")
    messages = [{"role": "user", "content": "Findings:\n\n" + "\n\n".join(findings)}]

    for attempt in range(2):
        out = run_agent(client, system=SYSTEM, messages=messages, output_schema=OUTPUT, effort=effort).output
        bad = check_text(out["headline"] + "\n" + "\n".join(out["paragraphs"]), values)
        if not bad:
            break
        messages.append({"role": "user", "content":
                         f"These numbers don't match any checked value: {', '.join(bad)}. "
                         "Remove them or use the checked numbers exactly, and send the whole brief again."})
    return Brief(out["headline"], out["paragraphs"], bad)
