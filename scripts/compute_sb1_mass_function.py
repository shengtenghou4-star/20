#!/usr/bin/env python3
"""Compute strict SB1 mass functions and minimum companion masses.

This is a triage utility, not a compact-object classifier. It accepts Gaia-style
CSV or ECSV rows, computes the spectroscopic mass function from period, K1 and
eccentricity, and solves the edge-on minimum companion mass for a supplied
primary-mass prior. Source-level output must remain private when used on candidates.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Iterable

G_SI = 6.67430e-11
M_SUN_KG = 1.98847e30
DAY_SECONDS = 86400.0
KM_TO_M = 1000.0
_EXACT_SOURCE_ID = re.compile(r"^[0-9]{10,20}$")
_MISSING = {"", "--", "nan", "NaN", "null", "None"}


class MassFunctionError(RuntimeError):
    """Raised when a row violates the strict SB1 mass-function contract."""


def mass_function_solar(period_days: float, k1_kms: float, eccentricity: float) -> float:
    """Return f(M) in solar masses for a single-lined spectroscopic binary."""

    if not math.isfinite(period_days) or period_days <= 0:
        raise ValueError("period_days must be finite and positive")
    if not math.isfinite(k1_kms) or k1_kms <= 0:
        raise ValueError("k1_kms must be finite and positive")
    if not math.isfinite(eccentricity) or not 0 <= eccentricity < 1:
        raise ValueError("eccentricity must be finite in [0, 1)")
    period_seconds = period_days * DAY_SECONDS
    k1_mps = k1_kms * KM_TO_M
    numerator = period_seconds * k1_mps**3 * (1 - eccentricity**2) ** 1.5
    return numerator / (2 * math.pi * G_SI * M_SUN_KG)


def minimum_companion_mass_solar(
    mass_function: float,
    primary_mass_solar: float,
) -> float:
    """Solve f=M2^3/(M1+M2)^2 for the edge-on minimum M2."""

    if not math.isfinite(mass_function) or mass_function <= 0:
        raise ValueError("mass_function must be finite and positive")
    if not math.isfinite(primary_mass_solar) or primary_mass_solar <= 0:
        raise ValueError("primary_mass_solar must be finite and positive")

    def residual(m2: float) -> float:
        return m2**3 / (primary_mass_solar + m2) ** 2 - mass_function

    lower = 0.0
    upper = max(primary_mass_solar, mass_function, 1.0)
    while residual(upper) < 0:
        upper *= 2
        if upper > 1e6:
            raise MassFunctionError("failed to bracket minimum companion mass")
    for _ in range(200):
        midpoint = (lower + upper) / 2
        if residual(midpoint) < 0:
            lower = midpoint
        else:
            upper = midpoint
    return upper


def _iter_noncomment_lines(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            yield line


def _float(row: dict[str, str], name: str, *, required: bool = True) -> float | None:
    raw = str(row.get(name, "")).strip()
    if raw in _MISSING:
        if required:
            raise MassFunctionError(f"missing required field {name}")
        return None
    try:
        value = float(raw)
    except ValueError as error:
        raise MassFunctionError(f"field {name} is not numeric") from error
    if not math.isfinite(value):
        raise MassFunctionError(f"field {name} is not finite")
    return value


def _primary_mass_prior(row: dict[str, str]) -> tuple[float | None, str | None]:
    precedence = (
        ("binary_mass_m1_lower", "gaia_binary_m1_lower"),
        ("mass_flame_lower", "flame_mass_lower"),
        ("binary_mass_m1", "gaia_binary_m1"),
        ("mass_flame", "flame_mass"),
    )
    for column, label in precedence:
        value = _float(row, column, required=False)
        if value is not None and value > 0:
            return value, label
    return None, None


def _tier(minimum_mass: float | None) -> str:
    if minimum_mass is None:
        return "mass_prior_unavailable"
    if minimum_mass >= 3.0:
        return "minimum_mass_ge_3_bh_regime"
    if minimum_mass >= 2.5:
        return "minimum_mass_ge_2_5_mass_gap"
    if minimum_mass >= 1.4:
        return "minimum_mass_ge_1_4_ns_regime"
    return "minimum_mass_below_1_4"


def compute_table(input_path: Path, output_path: Path, summary_path: Path) -> dict[str, object]:
    lines = list(_iter_noncomment_lines(input_path))
    if not lines:
        raise MassFunctionError("input contains no tabular rows")
    reader = csv.DictReader(lines, strict=True)
    required = {
        "source_id",
        "nss_solution_type",
        "period",
        "semi_amplitude_primary",
    }
    missing = sorted(required - set(reader.fieldnames or []))
    if missing:
        raise MassFunctionError(f"input is missing columns: {missing}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_rows: list[dict[str, object]] = []
    rejected: dict[str, int] = {}
    seen_sources: set[str] = set()
    for row in reader:
        try:
            source_id = str(row.get("source_id", "")).strip()
            if not _EXACT_SOURCE_ID.fullmatch(source_id):
                raise MassFunctionError("source_id is not an exact 10-20 digit token")
            if source_id in seen_sources:
                raise MassFunctionError("duplicate source_id")
            seen_sources.add(source_id)
            solution_type = str(row.get("nss_solution_type", "")).strip()
            if solution_type not in {"SB1", "SB1C"}:
                raise MassFunctionError("unsupported nss_solution_type")
            period = _float(row, "period")
            k1 = _float(row, "semi_amplitude_primary")
            eccentricity = _float(row, "eccentricity", required=False)
            if eccentricity is None:
                if solution_type != "SB1C":
                    raise MassFunctionError("SB1 row is missing eccentricity")
                eccentricity = 0.0
            assert period is not None and k1 is not None
            f_mass = mass_function_solar(period, k1, eccentricity)
            primary_mass, primary_mass_source = _primary_mass_prior(row)
            minimum_mass = (
                minimum_companion_mass_solar(f_mass, primary_mass)
                if primary_mass is not None
                else None
            )
            published_m2_lower = _float(row, "binary_mass_m2_lower", required=False)
            source_rows.append(
                {
                    "source_id": source_id,
                    "nss_solution_type": solution_type,
                    "period_days": f"{period:.12g}",
                    "semi_amplitude_primary_kms": f"{k1:.12g}",
                    "eccentricity": f"{eccentricity:.12g}",
                    "mass_function_solar": f"{f_mass:.12g}",
                    "primary_mass_prior_solar": (
                        f"{primary_mass:.12g}" if primary_mass is not None else ""
                    ),
                    "primary_mass_prior_source": primary_mass_source or "",
                    "minimum_companion_mass_solar": (
                        f"{minimum_mass:.12g}" if minimum_mass is not None else ""
                    ),
                    "gaia_binary_mass_m2_lower_solar": (
                        f"{published_m2_lower:.12g}"
                        if published_m2_lower is not None
                        else ""
                    ),
                    "mass_tier": _tier(minimum_mass),
                }
            )
        except (MassFunctionError, ValueError) as error:
            category = str(error)
            rejected[category] = rejected.get(category, 0) + 1

    fieldnames = [
        "source_id",
        "nss_solution_type",
        "period_days",
        "semi_amplitude_primary_kms",
        "eccentricity",
        "mass_function_solar",
        "primary_mass_prior_solar",
        "primary_mass_prior_source",
        "minimum_companion_mass_solar",
        "gaia_binary_mass_m2_lower_solar",
        "mass_tier",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(source_rows)

    tier_counts: dict[str, int] = {}
    for row in source_rows:
        tier = str(row["mass_tier"])
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    summary = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "accepted_sources": len(source_rows),
        "rejected_rows": sum(rejected.values()),
        "rejection_categories": rejected,
        "tier_counts": tier_counts,
        "claim_boundary": (
            "Mass functions and edge-on minimum companion masses are triage quantities. "
            "They do not exclude luminous companions, bad Gaia orbital solutions, triples, "
            "or survey systematics and therefore do not confirm a compact object."
        ),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = compute_table(args.input, args.output, args.summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
