"""Decide which profile a weigh belongs to.

The scale files every weigh under the slot the hub announced, so the hub
matches on weight. Each profile has a reference weight: the median of its
last few assigned weighs, or the starting weight entered for a new profile.
A weigh is assigned automatically when exactly one profile is within the
tolerance, or when the closest one is clearly closer than the runner-up.
Everything else waits for a manual choice in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

TOLERANCE_KG = 3.0
MARGIN_KG = 1.5
HISTORY = 5


@dataclass(frozen=True)
class Choice:
    profile_id: int | None
    reason: str


def reference_weight(recent: list[float], start_weight: float | None) -> float | None:
    """Median of the most recent assigned weighs (newest first), else the starting weight."""
    if recent:
        return float(median(recent[:HISTORY]))
    return start_weight


def choose_profile(weight: float, references: dict[int, float | None], *, tolerance: float = TOLERANCE_KG, margin: float = MARGIN_KG) -> Choice:
    known = sorted(
        ((abs(weight - ref), pid) for pid, ref in references.items() if ref is not None),
        key=lambda item: item[0],
    )
    if not known:
        return Choice(None, "no profile has a reference weight yet")
    best_diff, best_id = known[0]
    if best_diff > tolerance:
        return Choice(None, f"no profile within {tolerance:g} kg (closest {best_diff:.1f} kg away)")
    if len(known) > 1:
        second_diff = known[1][0]
        if second_diff <= tolerance and second_diff - best_diff < margin:
            return Choice(None, f"two profiles within {tolerance:g} kg and less than {margin:g} kg apart")
    return Choice(best_id, f"closest profile, {best_diff:.1f} kg from its reference")
