"""Annual cap ("plafon") on the social contribution tax (szocho) of capital income.

Under the Hungarian szocho act the tax on capital income — dividends,
vállalkozásból kivont jövedelem, árfolyamnyereség — is only payable until the
individual's szocho-bearing income for the year reaches 24x the monthly minimum
wage; above that the income stays szocho-free. For 2026 that is
322 800 Ft x 24 = 7 747 200 Ft of base, i.e. at most 1 007 136 Ft of szocho.

Wage income counts against the same cap ahead of the dividend, but neither
`dividend_service` nor `tax_service` models the shareholder's own wage, so the
cap they apply is the full annual one — their szocho figures are therefore an
upper bound. The wage-aware variant lives in the Fizetés Calculator UI, which
does know the planned gross wage.
"""

from __future__ import annotations

SZOCHO_CAP_MULTIPLIER = 24

# Monthly gross minimum wage ("minimálbér") per year, in HUF. Years outside the
# table fall back to the nearest known year, so a new year keeps working with
# the latest published wage until this table is extended.
MONTHLY_MINIMUM_WAGE: dict[int, float] = {
    2024: 266_800.0,
    2025: 290_800.0,
    2026: 322_800.0,
}


def monthly_minimum_wage(year: int) -> float:
    """Return *year*'s monthly minimum wage, clamped to the nearest known year."""
    known = sorted(MONTHLY_MINIMUM_WAGE)
    clamped = min(max(year, known[0]), known[-1])
    return MONTHLY_MINIMUM_WAGE[clamped]


def szocho_cap(year: int) -> float:
    """Return the annual szocho *base* cap for *year* (24x the monthly minimum wage)."""
    return monthly_minimum_wage(year) * SZOCHO_CAP_MULTIPLIER


def capped_szocho(base: float, rate: float, year: int, cap_remaining: float | None = None) -> float:
    """Szocho on *base*, charging only the part that still fits under the annual cap.

    *cap_remaining* lets a caller that splits the year into parts (monthly rows)
    pass the leftover cap; omitted, the full annual cap is available.
    """
    remaining = szocho_cap(year) if cap_remaining is None else cap_remaining
    return max(0.0, min(base, remaining)) * rate
