import numpy as np
import pytest

from hou_compact.spectral import (
    compare_single_and_double_templates,
    relativistic_doppler_factor,
    shift_template,
)


def _template() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    template_wavelength = np.linspace(4990.0, 5110.0, 6000)
    template_flux = np.ones_like(template_wavelength)
    for center, depth, width in (
        (5015.0, 0.30, 0.18),
        (5040.0, 0.18, 0.25),
        (5062.0, 0.25, 0.16),
        (5087.0, 0.20, 0.22),
    ):
        template_flux -= depth * np.exp(
            -0.5 * ((template_wavelength - center) / width) ** 2
        )
    wavelength = np.linspace(5000.0, 5100.0, 3000)
    return wavelength, template_wavelength, template_flux


def test_relativistic_doppler_factor_is_reversible() -> None:
    positive = relativistic_doppler_factor(100.0)
    negative = relativistic_doppler_factor(-100.0)
    assert positive * negative == pytest.approx(1.0, rel=1e-12)


def test_single_spectrum_prefers_one_component() -> None:
    wavelength, template_wavelength, template_flux = _template()
    shifted = shift_template(
        wavelength,
        template_wavelength,
        template_flux,
        60.0,
    )
    flux = 1.0 - 0.8 * (1.0 - shifted)
    inverse_variance = np.full_like(flux, 40000.0)
    velocity_grid = np.arange(-160.0, 161.0, 20.0)
    evidence = compare_single_and_double_templates(
        wavelength,
        flux,
        inverse_variance,
        template_wavelength,
        template_flux,
        velocity_grid,
        minimum_separation_kms=60.0,
    )
    assert evidence.single.velocities_kms[0] == pytest.approx(60.0)
    assert evidence.evidence_status == "no_two_component_preference"
    assert evidence.delta_bic_single_minus_double < 0


def test_double_lined_spectrum_has_strong_two_component_evidence() -> None:
    wavelength, template_wavelength, template_flux = _template()
    first = shift_template(
        wavelength,
        template_wavelength,
        template_flux,
        -80.0,
    )
    second = shift_template(
        wavelength,
        template_wavelength,
        template_flux,
        100.0,
    )
    flux = 1.0 - 0.65 * (1.0 - first) - 0.35 * (1.0 - second)
    inverse_variance = np.full_like(flux, 40000.0)
    velocity_grid = np.arange(-160.0, 161.0, 20.0)
    evidence = compare_single_and_double_templates(
        wavelength,
        flux,
        inverse_variance,
        template_wavelength,
        template_flux,
        velocity_grid,
        minimum_separation_kms=60.0,
    )
    assert evidence.evidence_status == "strong_two_component_spectral_evidence"
    assert evidence.double.velocities_kms == pytest.approx((-80.0, 100.0))
    assert evidence.delta_bic_single_minus_double > 10.0
    assert evidence.secondary_to_primary_amplitude == pytest.approx(
        0.35 / 0.65, rel=1e-3
    )


def test_low_secondary_amplitude_is_not_called_strong() -> None:
    wavelength, template_wavelength, template_flux = _template()
    first = shift_template(wavelength, template_wavelength, template_flux, -80.0)
    second = shift_template(wavelength, template_wavelength, template_flux, 100.0)
    flux = 1.0 - 0.98 * (1.0 - first) - 0.02 * (1.0 - second)
    inverse_variance = np.full_like(flux, 40000.0)
    velocity_grid = np.arange(-160.0, 161.0, 20.0)
    evidence = compare_single_and_double_templates(
        wavelength,
        flux,
        inverse_variance,
        template_wavelength,
        template_flux,
        velocity_grid,
        minimum_separation_kms=60.0,
        minimum_secondary_ratio=0.10,
    )
    assert evidence.evidence_status != "strong_two_component_spectral_evidence"


def test_invalid_spectrum_is_rejected() -> None:
    wavelength = np.arange(10.0)
    with pytest.raises(ValueError, match="at least 20"):
        compare_single_and_double_templates(
            wavelength,
            np.ones(10),
            np.ones(10),
            np.linspace(0.0, 20.0, 30),
            np.ones(30),
            np.array([-10.0, 0.0, 10.0]),
        )
