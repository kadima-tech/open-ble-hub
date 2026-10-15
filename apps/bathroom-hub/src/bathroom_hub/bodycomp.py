"""Body composition from weight and foot-to-foot impedance.

Body fat uses Jebb et al. 2000 (Br J Nutr 83:115-122), the equation derived
for a foot-to-foot (Tanita) analyser against a four-compartment model:

    %fat = -156.1 - 89.1 ln(H) + 45.6 ln(W) + 0.120 age + 0.0494 Z
           (+ 19.6 ln(H) for women)

The paper labels height as centimetres, but only metres gives physiological
values (centimetres yields about -380 %), so H is in metres here. Residual SD
in the paper: 4.8 % for men, 3.3 % for women.

Lean mass is weight minus fat mass. Muscle, bone and water are not derived:
foot-to-foot impedance does not support them well.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

MIN_FAT_PCT = 3.0
MAX_FAT_PCT = 70.0


@dataclass(frozen=True)
class Composition:
    fat_pct: float
    fat_kg: float
    lean_kg: float
    bmi: float


def age_on(birth: date, when: date) -> int:
    years = when.year - birth.year
    if (when.month, when.day) < (birth.month, birth.day):
        years -= 1
    return years


def jebb2000_fat_pct(
    *, male: bool, age: int, height_cm: float, weight_kg: float, impedance: float
) -> float:
    height_m = height_cm / 100.0
    fat = (
        -156.1
        - 89.1 * math.log(height_m)
        + 45.6 * math.log(weight_kg)
        + 0.120 * age
        + 0.0494 * impedance
    )
    if not male:
        fat += 19.6 * math.log(height_m)
    return fat


def composition(
    *,
    male: bool,
    birth: date,
    height_cm: float,
    weight_kg: float,
    impedance: float | None,
    when: date,
) -> Composition | None:
    """Return body composition, or None when there is no usable impedance."""
    if not impedance or impedance <= 0 or weight_kg <= 0 or height_cm <= 0:
        return None
    age = age_on(birth, when)
    fat_pct = jebb2000_fat_pct(
        male=male,
        age=age,
        height_cm=height_cm,
        weight_kg=weight_kg,
        impedance=impedance,
    )
    fat_pct = min(MAX_FAT_PCT, max(MIN_FAT_PCT, fat_pct))
    fat_kg = weight_kg * fat_pct / 100.0
    bmi = weight_kg / (height_cm / 100.0) ** 2
    return Composition(
        fat_pct=round(fat_pct, 1),
        fat_kg=round(fat_kg, 1),
        lean_kg=round(weight_kg - fat_kg, 1),
        bmi=round(bmi, 1),
    )
