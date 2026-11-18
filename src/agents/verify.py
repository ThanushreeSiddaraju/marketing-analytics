"""Checks that don't trust the model.

check_claims re-runs the SQL behind every number an agent states and looks the
number up in the fresh result. check_text pulls every number out of a written
summary and makes sure each one traces back to a checked claim.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import pandas as pd

from .sql_tool import SafeSQL


def _decimals(x: float) -> int:
    s = f"{x:.10f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


def close_enough(stated: float, actual: float) -> bool:
    """True if `stated` is `actual`, allowing for rounding to the precision it was
    written with, and for shares written as percentages (0.142 vs 14.2)."""
    if actual is None or (isinstance(actual, float) and math.isnan(actual)):
        return False
    tol = max(0.5 * 10 ** -_decimals(stated), 0.005 * abs(actual), 1e-9)
    return any(abs(stated - a) <= tol for a in (actual, actual * 100))


@dataclass
class ClaimCheck:
    claim: dict
    ok: bool
    actual: float | None
    reason: str


def check_claims(claims: list[dict], sql: SafeSQL) -> list[ClaimCheck]:
    out = []
    cache: dict[str, pd.DataFrame] = {}
    for c in claims:
        qid, col, row = c.get("query_id"), c.get("column"), c.get("row")
        if qid not in sql.ledger:
            out.append(ClaimCheck(c, False, None, f"{qid} is not a query that was run"))
            continue
        df = cache.setdefault(qid, sql.rerun(qid))
        if col not in df.columns:
            out.append(ClaimCheck(c, False, None, f"{qid} has no column {col!r}"))
            continue
        if not isinstance(row, int) or not 0 <= row < len(df):
            out.append(ClaimCheck(c, False, None, f"{qid} has no row {row}"))
            continue
        try:
            actual = float(df[col].iloc[row])
        except (TypeError, ValueError):
            out.append(ClaimCheck(c, False, None, f"{qid}.{col} row {row} isn't a number"))
            continue
        ok = close_enough(float(c["value"]), actual)
        out.append(ClaimCheck(c, ok, actual, "ok" if ok else f"stated {c['value']} but the query gives {actual:.6g}"))
    return out


NUMBER = re.compile(r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|m|%|x)?(?![\w])", re.I)
FREE_NUMBERS = {2024, 2025, 2026}  # years can appear without a source


def numbers_in(text: str) -> list[tuple[str, float]]:
    found = []
    for m in NUMBER.finditer(text):
        v = float(m.group(1).replace(",", ""))
        suffix = (m.group(2) or "").lower()
        if suffix == "k":
            v *= 1_000
        elif suffix == "m":
            v *= 1_000_000
        found.append((m.group(0).strip(), v))
    return found


def check_text(text: str, verified_values: list[float]) -> list[str]:
    """Numbers in `text` that don't match any verified value. Small counts (1-12,
    e.g. "three channels", "top 5") and years are allowed."""
    bad = []
    for raw, v in numbers_in(text):
        if v in FREE_NUMBERS or (v.is_integer() and 0 <= v <= 12):
            continue
        scale = 1_000 if raw.lower().endswith("k") else 1_000_000 if raw.lower().endswith("m") else 1
        stated = v / scale
        if not any(close_enough(stated, a / scale) for a in verified_values):
            bad.append(raw)
    return bad
