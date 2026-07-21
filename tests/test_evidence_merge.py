import pandas as pd
import pytest

from hou_compact.evidence_merge import merge_claim_evidence


def _base() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_id": [1, 2],
            "solution_id": [10, 20],
            "triage_rank": [5, 5],
            "blockers": ["", ""],
            "orbit_status": ["scored", "scored"],
            "mass_status": ["scored", "scored"],
            "gaia_contamination_status": [
                "no_gaia_side_signal_detected",
                "no_gaia_side_signal_detected",
            ],
        }
    )


def _complete_tables() -> dict[str, pd.DataFrame]:
    keys = {"source_id": [1, 2], "solution_id": [10, 20]}
    return {
        "spectral": pd.DataFrame(
            {
                **keys,
                "spectral_evidence_status": [
                    "no_two_component_preference",
                    "no_two_component_preference",
                ],
            }
        ),
        "sed": pd.DataFrame(
            {
                **keys,
                "sed_evidence_status": [
                    "no_composite_sed_preference",
                    "no_composite_sed_preference",
                ],
            }
        ),
        "primary": pd.DataFrame(
            {
                **keys,
                "independent_primary_status": [
                    "independent_primary_mass_scored",
                    "independent_primary_mass_scored",
                ],
            }
        ),
        "alternatives": pd.DataFrame(
            {
                **keys,
                "hierarchy_audit_status": [
                    "hierarchy_disfavored",
                    "hierarchy_disfavored",
                ],
                "stripped_star_audit_status": [
                    "stripped_star_disfavored",
                    "stripped_star_disfavored",
                ],
            }
        ),
        "novelty": pd.DataFrame(
            {
                **keys,
                "novelty_audit_status": [
                    "no_prior_compact_object_claim_found",
                    "known_binary_without_compact_object_claim",
                ],
            }
        ),
    }


def test_complete_evidence_merge_reaches_ready_state() -> None:
    result = merge_claim_evidence(_base(), _complete_tables())
    assert len(result.frame) == 2
    assert set(result.frame["claim_readiness_status"]) == {
        "claim_audit_ready_not_classified"
    }
    assert result.coverage["spectral"]["matched_base_rows"] == 2
    assert result.frame["novelty_row_present"].all()


def test_missing_evidence_row_is_preserved_and_blocks_readiness() -> None:
    tables = _complete_tables()
    tables["sed"] = tables["sed"].iloc[:1].copy()
    result = merge_claim_evidence(_base(), tables)
    second = result.frame.loc[result.frame["source_id"] == 2].iloc[0]
    assert not second["sed_row_present"]
    assert second["claim_readiness_status"] == "claim_audit_incomplete"
    assert "composite_sed_audit_missing" in second["claim_readiness_blockers"]
    assert result.coverage["sed"]["missing_base_rows"] == 1


def test_duplicate_rows_are_rejected() -> None:
    tables = _complete_tables()
    tables["spectral"] = pd.concat(
        [tables["spectral"], tables["spectral"].iloc[:1]],
        ignore_index=True,
    )
    with pytest.raises(ValueError, match="duplicate"):
        merge_claim_evidence(_base(), tables)


def test_ambiguous_column_overlap_is_rejected() -> None:
    tables = _complete_tables()
    tables["spectral"]["triage_rank"] = 5
    with pytest.raises(ValueError, match="overlapping columns"):
        merge_claim_evidence(_base(), tables)


def test_invalid_table_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid evidence table name"):
        merge_claim_evidence(_base(), {"bad name": pd.DataFrame()})
