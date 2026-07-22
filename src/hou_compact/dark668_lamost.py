"""Strict LAMOST per-spectrum joining for Dark-668 RV analysis."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hou_compact.lamost import join_lrs_spectrum_uncertainties


def join_and_standardize_tap_rv(
    epochs: pd.DataFrame,
    tap_rows: pd.DataFrame,
    *,
    maximum_rv_difference_kms: float = 1.0,
) -> pd.DataFrame:
    """Join exact obsids and emit the common HOU-COMPACT epoch schema.

    A row becomes scorable only when the LAMOST multiple-epoch RV and the selected
    per-spectrum product agree, the quoted uncertainty is finite and positive, and
    the per-spectrum ``fibermask`` is present and zero.  Missing quality metadata
    fails closed rather than being silently treated as clean.
    """

    joined = join_lrs_spectrum_uncertainties(
        epochs,
        tap_rows,
        maximum_rv_difference_kms=maximum_rv_difference_kms,
    )
    if "source_id" not in joined.columns:
        raise KeyError("joined epochs have no Gaia DR3 source_id column")

    output = joined.copy()
    initial_scorable = output["lamost_epoch_status"].eq("scorable")
    if "fibermask" in output.columns:
        fiber = pd.to_numeric(output["fibermask"], errors="coerce")
        missing_fiber = fiber.isna()
        bad_fiber = fiber.notna() & fiber.ne(0)
        output["fiberstatus"] = fiber.fillna(1).astype("int64")
        output.loc[initial_scorable & missing_fiber, "lamost_epoch_status"] = (
            "missing_fibermask"
        )
        output.loc[initial_scorable & bad_fiber, "lamost_epoch_status"] = (
            "fibermask_nonzero"
        )
    else:
        output["fiberstatus"] = 1
        output.loc[initial_scorable, "lamost_epoch_status"] = "missing_fibermask"

    output["success"] = output["lamost_epoch_status"].eq("scorable")
    output["rvs_warn"] = np.where(output["success"], 0, 1)
    output["sn_b"] = pd.to_numeric(
        output["snrg"] if "snrg" in output.columns else np.nan,
        errors="coerce",
    )
    output["sn_r"] = pd.to_numeric(
        output["snri"] if "snri" in output.columns else np.nan,
        errors="coerce",
    )
    output["sn_z"] = np.nan
    output["program"] = "lamost_lrs_dr8_v1_tap"
    output["survey"] = "lamost_dr8"
    output["expid"] = pd.to_numeric(output["obsid"], errors="raise").astype("int64")
    output["source_id"] = pd.to_numeric(
        output["source_id"], errors="raise"
    ).astype("int64")
    return output.sort_values(
        ["source_id", "mjd", "obsid"], kind="stable"
    ).reset_index(drop=True)


def candidate_safe_join_summary(rows: pd.DataFrame) -> dict[str, Any]:
    status = rows.get("lamost_epoch_status", pd.Series(dtype=str))
    success = rows.get("success", pd.Series(False, index=rows.index)).astype(bool)
    clean = rows.loc[success].copy()
    visits = (
        clean.groupby("source_id", sort=False).size()
        if not clean.empty and "source_id" in clean.columns
        else pd.Series(dtype=int)
    )
    return {
        "epoch_rows": int(len(rows)),
        "epoch_status_counts": {
            str(key): int(value) for key, value in status.value_counts().items()
        },
        "scorable_epoch_rows": int(success.sum()),
        "scorable_source_count": int(len(visits)),
        "scorable_source_visit_threshold_counts": {
            "ge_2": int(visits.ge(2).sum()),
            "ge_3": int(visits.ge(3).sum()),
            "ge_5": int(visits.ge(5).sum()),
            "ge_10": int(visits.ge(10).sum()),
        },
        "claim_boundary": (
            "Exact RV/error and quality joining only. Scorable means eligible for "
            "statistical analysis, not evidence of binarity or a compact companion."
        ),
    }
