"""Strict LAMOST DR8 multiple-epoch parsing for HOU-COMPACT.

The initial contract targets the LAMOST DR8 v1.0 low-resolution multiple-epoch
catalogue because its ``gaia_source_id`` is explicitly documented as a Gaia DR2
identifier. Identifiers are parsed from text without floating-point conversion.
Rows are measurements only until an exact per-spectrum ``obsid`` join supplies a
finite positive radial-velocity uncertainty and passes the frozen quality gates.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

_INT_TEXT = re.compile(r"^[+]?[0-9]+(?:[.]0+)?$")
_FLOAT_TEXT = re.compile(r"^[+]?(?:[0-9]+(?:[.][0-9]*)?|[.][0-9]+)$")
_UTC_OFFSET_DAYS = 8.0 / 24.0


class LamostContractError(ValueError):
    """Raised when a LAMOST row violates the frozen release contract."""


def parse_exact_int_text(value: object, *, name: str) -> int:
    """Parse an integer identifier without accepting lossy floating values.

    LAMOST DR8 v1.0 documents Gaia DR2 identifiers in a nominal floating field.
    A dataframe that has already converted such values to binary float cannot prove
    preservation above 2**53 and is therefore rejected.
    """
    if isinstance(value, (bool, np.bool_)):
        raise LamostContractError(f"{name} must not be boolean")
    if isinstance(value, (int, np.integer)):
        result = int(value)
    elif isinstance(value, (float, np.floating)):
        raise LamostContractError(
            f"{name} arrived as floating point; reload the catalogue with dtype=str"
        )
    else:
        text = str(value).strip()
        if not _INT_TEXT.fullmatch(text):
            raise LamostContractError(
                f"{name} is not an exact non-exponent integer string: {text!r}"
            )
        result = int(text.split(".", 1)[0])
    if not 0 <= result <= 2**63 - 1:
        raise LamostContractError(f"{name} lies outside signed 64-bit range")
    return result


def parse_exact_int_list(value: object, *, name: str) -> list[int]:
    """Parse a hyphen-delimited list of non-negative integer identifiers."""
    text = str(value).strip()
    if not text:
        return []
    pieces = text.split("-")
    if any(piece.strip() == "" for piece in pieces):
        raise LamostContractError(f"{name} contains an empty integer token")
    return [
        parse_exact_int_text(piece, name=f"{name}[{index}]")
        for index, piece in enumerate(pieces)
    ]


def parse_hyphen_numeric_list(value: object, *, name: str) -> list[float]:
    """Parse LAMOST's hyphen-joined numeric lists, including negative values.

    Joining values with ``-`` represents a negative following value with a doubled
    hyphen. For example, ``12.0--8.5-3.0`` becomes ``[12.0, -8.5, 3.0]``.
    Exponent notation is rejected because its sign would be ambiguous with the
    catalogue delimiter.
    """
    text = str(value).strip()
    if not text:
        return []
    raw = text.split("-")
    output: list[float] = []
    negative_next = False
    for piece in raw:
        token = piece.strip()
        if token == "":
            if negative_next:
                raise LamostContractError(
                    f"{name} contains ambiguous consecutive signs"
                )
            negative_next = True
            continue
        lowered = token.lower()
        if lowered in {"nan", "null", "none"}:
            number = float("nan")
        else:
            if not _FLOAT_TEXT.fullmatch(token):
                raise LamostContractError(
                    f"{name} contains unsupported numeric token {token!r}"
                )
            number = float(token)
        if negative_next:
            number = -number
            negative_next = False
        output.append(number)
    if negative_next:
        raise LamostContractError(f"{name} ends with an incomplete sign")
    return output


def lamost_lmjm_to_utc_mjd(lmjm: int | np.integer) -> float:
    """Convert LAMOST local modified Julian minute to continuous UTC MJD.

    LAMOST records local time at UTC+8. Dividing LMJM by 1440 gives the local
    MJD-like minute count; subtracting 8/24 day returns UTC MJD. This relation is
    verified against official header examples containing LMJM and DATE-BEG.
    """
    if isinstance(lmjm, (bool, np.bool_)) or not isinstance(
        lmjm,
        (int, np.integer),
    ):
        raise TypeError("lmjm must be an integer")
    if int(lmjm) <= 0:
        raise LamostContractError("lmjm must be positive")
    return int(lmjm) / 1440.0 - _UTC_OFFSET_DAYS


@dataclass(frozen=True)
class LamostEpoch:
    """One exploded LAMOST low-resolution observation."""

    dr2_source_id: int
    lamost_source_id: str
    obsid: int
    lmjm: int
    mjd: float
    vrad_list_kms: float
    rv_list_status: str
    observation_index: int
    observation_count: int
    source_match_mode: str = "lamost_dr8_v1_gaia_dr2_exact"

    def to_record(self) -> dict[str, object]:
        return {
            "dr2_source_id": self.dr2_source_id,
            "lamost_source_id": self.lamost_source_id,
            "obsid": self.obsid,
            "lmjm": self.lmjm,
            "mjd": self.mjd,
            "vrad_list_kms": self.vrad_list_kms,
            "rv_list_status": self.rv_list_status,
            "observation_index": self.observation_index,
            "observation_count": self.observation_count,
            "source_match_mode": self.source_match_mode,
        }


def _rv_status(value: float) -> str:
    if not math.isfinite(value) or value <= -9000:
        return "missing_or_sentinel"
    return "measured_without_uncertainty"


def explode_lrs_multiple_epoch_row(
    row: Mapping[str, object],
) -> pd.DataFrame:
    """Explode one DR8 v1.0 LRS multiple-epoch row with strict list alignment."""
    required = {
        "source_id",
        "gaia_source_id",
        "obs_number",
        "obsid_list",
        "midmjm_list",
        "rv_list",
    }
    missing = sorted(required - set(row))
    if missing:
        raise KeyError(f"LAMOST multiple-epoch row is missing columns: {missing}")

    dr2_source_id = parse_exact_int_text(
        row["gaia_source_id"],
        name="gaia_source_id",
    )
    observation_count = parse_exact_int_text(
        row["obs_number"],
        name="obs_number",
    )
    if observation_count < 2:
        raise LamostContractError("multiple-epoch row must have obs_number >= 2")
    obsids = parse_exact_int_list(row["obsid_list"], name="obsid_list")
    lmjms = parse_exact_int_list(row["midmjm_list"], name="midmjm_list")
    velocities = parse_hyphen_numeric_list(row["rv_list"], name="rv_list")
    lengths = {len(obsids), len(lmjms), len(velocities), observation_count}
    if len(lengths) != 1:
        raise LamostContractError(
            "obs_number, obsid_list, midmjm_list, and rv_list lengths disagree: "
            f"obs_number={observation_count}, obsid={len(obsids)}, "
            f"midmjm={len(lmjms)}, rv={len(velocities)}"
        )
    if len(set(obsids)) != len(obsids):
        raise LamostContractError("obsid_list contains duplicate observation IDs")

    lamost_source_id = str(row["source_id"]).strip()
    if not lamost_source_id:
        raise LamostContractError("source_id must not be empty")
    records = [
        LamostEpoch(
            dr2_source_id=dr2_source_id,
            lamost_source_id=lamost_source_id,
            obsid=obsid,
            lmjm=lmjm,
            mjd=lamost_lmjm_to_utc_mjd(lmjm),
            vrad_list_kms=velocity,
            rv_list_status=_rv_status(velocity),
            observation_index=index,
            observation_count=observation_count,
        ).to_record()
        for index, (obsid, lmjm, velocity) in enumerate(
            zip(obsids, lmjms, velocities, strict=True)
        )
    ]
    return pd.DataFrame.from_records(records)


def explode_lrs_multiple_epoch_catalog(
    rows: Iterable[Mapping[str, object]],
) -> pd.DataFrame:
    """Explode multiple catalogue rows and return deterministic epoch ordering."""
    frames = [explode_lrs_multiple_epoch_row(row) for row in rows]
    if not frames:
        return pd.DataFrame(columns=list(LamostEpoch.__dataclass_fields__))
    output = pd.concat(frames, ignore_index=True)
    duplicate = output.duplicated(["dr2_source_id", "obsid"])
    if duplicate.any():
        raise LamostContractError(
            f"catalogue contains {int(duplicate.sum())} duplicate DR2-source/obsid rows"
        )
    return output.sort_values(
        ["dr2_source_id", "mjd", "obsid"],
        kind="stable",
    ).reset_index(drop=True)


def join_lrs_spectrum_uncertainties(
    epochs: pd.DataFrame,
    spectra: pd.DataFrame,
    *,
    maximum_rv_difference_kms: float = 1.0,
) -> pd.DataFrame:
    """Join per-spectrum RV uncertainties by exact obsid and audit RV agreement.

    The per-spectrum table must be loaded with identifier columns as text before
    normalization. Its `rv` and `rv_err` values are used for scoring only when the
    exact obsid is unique, the uncertainty is finite and positive, and the spectrum
    RV agrees with the multiple-epoch list within the frozen tolerance.
    """
    invalid_tolerance = (
        not math.isfinite(maximum_rv_difference_kms)
        or maximum_rv_difference_kms < 0
    )
    if invalid_tolerance:
        raise ValueError("maximum_rv_difference_kms must be finite and non-negative")
    required_epochs = {
        "dr2_source_id",
        "obsid",
        "vrad_list_kms",
        "rv_list_status",
    }
    required_spectra = {"obsid", "rv", "rv_err"}
    missing_epochs = sorted(required_epochs - set(epochs.columns))
    missing_spectra = sorted(required_spectra - set(spectra.columns))
    if missing_epochs:
        raise KeyError(f"epochs is missing columns: {missing_epochs}")
    if missing_spectra:
        raise KeyError(f"spectra is missing columns: {missing_spectra}")

    spectrum = spectra.copy()
    spectrum["obsid"] = [
        parse_exact_int_text(value, name="spectrum.obsid")
        for value in spectrum["obsid"]
    ]
    if spectrum["obsid"].duplicated().any():
        raise LamostContractError("per-spectrum table contains duplicate obsid rows")
    spectrum["catalog_vrad_kms"] = pd.to_numeric(
        spectrum["rv"],
        errors="coerce",
    )
    spectrum["catalog_vrad_err_kms"] = pd.to_numeric(
        spectrum["rv_err"],
        errors="coerce",
    )
    optional = [
        column
        for column in ("snrg", "snri", "class", "subclass", "fibermask")
        if column in spectrum.columns
    ]
    joined = epochs.merge(
        spectrum[["obsid", "catalog_vrad_kms", "catalog_vrad_err_kms", *optional]],
        on="obsid",
        how="left",
        validate="many_to_one",
    )
    joined["rv_difference_kms"] = (
        pd.to_numeric(joined["vrad_list_kms"], errors="coerce")
        - joined["catalog_vrad_kms"]
    ).abs()
    has_spectrum = joined["catalog_vrad_kms"].notna()
    finite_error = np.isfinite(joined["catalog_vrad_err_kms"])
    positive_error = joined["catalog_vrad_err_kms"].gt(0)
    agrees = joined["rv_difference_kms"].le(maximum_rv_difference_kms)
    measured = joined["rv_list_status"].eq("measured_without_uncertainty")

    joined["lamost_epoch_status"] = "missing_spectrum_obsid_join"
    joined.loc[has_spectrum & ~finite_error, "lamost_epoch_status"] = (
        "missing_or_nonfinite_rv_uncertainty"
    )
    nonpositive = has_spectrum & finite_error & ~positive_error
    joined.loc[nonpositive, "lamost_epoch_status"] = "nonpositive_rv_uncertainty"
    joined.loc[
        has_spectrum & finite_error & positive_error & ~measured,
        "lamost_epoch_status",
    ] = "multiple_epoch_rv_missing"
    joined.loc[
        has_spectrum & finite_error & positive_error & measured & ~agrees,
        "lamost_epoch_status",
    ] = "rv_product_disagreement"
    clean = has_spectrum & finite_error & positive_error & measured & agrees
    joined.loc[clean, "lamost_epoch_status"] = "scorable"
    joined["vrad"] = joined["catalog_vrad_kms"]
    joined["vrad_err"] = joined["catalog_vrad_err_kms"]
    return joined.sort_values(
        ["dr2_source_id", "mjd", "obsid"],
        kind="stable",
    ).reset_index(drop=True)
