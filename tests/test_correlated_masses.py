import numpy as np
import pytest

from hou_compact.correlated_masses import (
    draw_gaia_correlated_mass_posterior,
    draw_standard_gaia_correlated_products,
)
from hou_compact.physics import spectroscopic_mass_function


def test_zero_covariance_sb1_recovers_exact_edge_on_mass() -> None:
    primary = 1.0
    companion = 3.0
    mass_function = companion**3 / (primary + companion) ** 2
    base = spectroscopic_mass_function(10.0, 1.0, 0.2)
    k1 = (mass_function / base) ** (1.0 / 3.0)
    result = draw_gaia_correlated_mass_posterior(
        solution_type="SB1",
        bit_index=127,
        corr_vec=np.zeros(15),
        period_days=10.0,
        period_error_days=0.0,
        k1_kms=k1,
        k1_error_kms=0.0,
        eccentricity=0.2,
        eccentricity_error=0.0,
        primary_mass_solar=primary,
        primary_mass_error_solar=0.0,
        n_draws=1000,
        inclination_mode="edge_on",
        random_seed=8,
    )
    assert np.allclose(result.samples.companion_mass_solar, companion, rtol=1e-9)
    assert result.acceptance_fraction > 0
    assert result.orbital_covariance.bit_index == 127


def test_gaia_correlation_block_is_preserved() -> None:
    vector = np.zeros(15)
    vector[1] = 0.7  # period-K1 correlation
    result = draw_gaia_correlated_mass_posterior(
        solution_type="SB1",
        bit_index=127,
        corr_vec=vector,
        period_days=20.0,
        period_error_days=2.0,
        k1_kms=40.0,
        k1_error_kms=4.0,
        eccentricity=0.1,
        eccentricity_error=0.02,
        primary_mass_solar=1.0,
        primary_mass_error_solar=0.1,
        n_draws=2000,
        random_seed=17,
    )
    correlation = result.orbital_covariance.correlation
    assert correlation[0, 1] == pytest.approx(0.7)
    assert result.samples.companion_mass_solar.size == 2000


def test_fixed_length_sparse_gaia_vector_is_supported() -> None:
    compact = np.linspace(0.01, 0.15, 15)
    fixed = np.full(231, np.nan)
    fixed[np.linspace(0, 230, 15, dtype=int)] = compact
    result = draw_gaia_correlated_mass_posterior(
        solution_type="SB1",
        bit_index=127,
        corr_vec=fixed,
        period_days=20.0,
        period_error_days=0.2,
        k1_kms=40.0,
        k1_error_kms=0.4,
        eccentricity=0.1,
        eccentricity_error=0.01,
        primary_mass_solar=1.0,
        primary_mass_error_solar=0.1,
        n_draws=1000,
        random_seed=18,
    )
    assert result.orbital_covariance.decoding_mode == "gaia_sparse_nonzero"
    assert result.orbital_covariance.raw_vector_length == 231


def test_sb1c_uses_zero_eccentricity() -> None:
    result = draw_gaia_correlated_mass_posterior(
        solution_type="SB1C",
        bit_index=31,
        corr_vec=np.zeros(6),
        period_days=5.0,
        period_error_days=0.1,
        k1_kms=30.0,
        k1_error_kms=1.0,
        eccentricity=None,
        eccentricity_error=None,
        primary_mass_solar=0.8,
        primary_mass_error_solar=0.1,
        n_draws=1000,
        random_seed=19,
    )
    assert result.orbital_covariance.parameter_names == (
        "period",
        "semi_amplitude_primary",
    )


def test_wrong_solution_bit_index_is_rejected() -> None:
    with pytest.raises(ValueError, match="unexpected bit_index"):
        draw_gaia_correlated_mass_posterior(
            solution_type="SB1C",
            bit_index=127,
            corr_vec=np.zeros(6),
            period_days=5.0,
            period_error_days=0.1,
            k1_kms=30.0,
            k1_error_kms=1.0,
            eccentricity=None,
            eccentricity_error=None,
            primary_mass_solar=0.8,
            primary_mass_error_solar=0.1,
            n_draws=1000,
            random_seed=20,
        )


def test_standard_correlated_products_are_labelled() -> None:
    products = draw_standard_gaia_correlated_products(
        solution_type="SB1C",
        bit_index=31,
        corr_vec=np.zeros(6),
        period_days=5.0,
        period_error_days=0.1,
        k1_kms=30.0,
        k1_error_kms=1.0,
        eccentricity=None,
        eccentricity_error=None,
        primary_mass_solar=0.8,
        primary_mass_error_solar=0.1,
        n_draws=1000,
        random_seed=21,
    )
    minimum = products["minimum_mass"]
    assert "bit-index-validated" in minimum["interpretation"]
    assert minimum["bit_index"] == 31
    assert minimum["corr_vec_decoding_mode"] == "compact"
    assert "not selection-corrected" in products["isotropic_sensitivity"][
        "interpretation"
    ]
