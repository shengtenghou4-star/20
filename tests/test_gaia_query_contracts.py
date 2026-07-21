from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _query(name: str) -> str:
    return (ROOT / "queries" / name).read_text(encoding="utf-8")


def test_v7_uses_official_astrophysical_parameters_join_and_alias_order() -> None:
    query = _query("gaia_sb1_contamination_pilot_v7.adql")
    assert "SELECT TOP 5000" in query
    assert "LEFT OUTER JOIN gaiadr3.astrophysical_parameters AS ap" in query
    assert "ap.radius_gspphot" in query
    assert "AS pk1_cubed_proxy" in query
    assert "ORDER BY pk1_cubed_proxy DESC" in query
    assert "ORDER BY n.period *" not in query


def test_v8_is_bounded_but_preserves_v7_scientific_contract() -> None:
    v7 = _query("gaia_sb1_contamination_pilot_v7.adql")
    v8 = _query("gaia_sb1_contamination_pilot_v8.adql")
    assert "SELECT TOP 500" in v8
    assert "SELECT TOP 5000" not in v8
    required_fragments = (
        "n.nss_solution_type IN ('SB1', 'SB1C')",
        "n.significance >= 5",
        "LEFT OUTER JOIN gaiadr3.astrophysical_parameters AS ap",
        "n.bit_index",
        "n.corr_vec",
        "AS pk1_cubed_proxy",
        "ORDER BY pk1_cubed_proxy DESC",
    )
    for fragment in required_fragments:
        assert fragment in v7
        assert fragment in v8
