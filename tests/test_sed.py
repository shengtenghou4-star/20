import numpy as np
import pytest

from hou_compact.sed import compare_single_and_composite_sed, fit_single_sed


def _library() -> tuple[np.ndarray, tuple[str, ...]]:
    templates = np.array(
        [
            [1.00, 0.90, 0.75, 0.55, 0.35, 0.20],
            [0.30, 0.50, 0.75, 0.95, 1.00, 0.90],
            [0.80, 0.85, 0.90, 0.92, 0.88, 0.78],
        ],
        dtype=float,
    )
    return templates, ("hot", "cool", "flat")


def test_single_template_sed_prefers_one_component() -> None:
    templates, labels = _library()
    flux = 2.5 * templates[0]
    errors = np.full(flux.size, 0.02)
    evidence = compare_single_and_composite_sed(
        flux,
        errors,
        templates,
        labels,
    )
    assert evidence.single.template_labels == ("hot",)
    assert evidence.single.coefficients[0] == pytest.approx(2.5)
    assert evidence.evidence_status == "no_composite_sed_preference"
    assert evidence.delta_bic_single_minus_composite < 0


def test_composite_sed_is_recovered() -> None:
    templates, labels = _library()
    flux = 1.4 * templates[0] + 0.8 * templates[1]
    errors = np.full(flux.size, 0.01)
    evidence = compare_single_and_composite_sed(
        flux,
        errors,
        templates,
        labels,
        minimum_secondary_flux_fraction=0.05,
    )
    assert evidence.evidence_status == "strong_composite_sed_evidence"
    assert evidence.composite.template_labels == ("hot", "cool")
    assert evidence.composite.coefficients == pytest.approx((1.4, 0.8), rel=1e-8)
    assert evidence.secondary_flux_fraction == pytest.approx(0.8 / 2.2)
    assert evidence.delta_bic_single_minus_composite > 10.0


def test_negligible_secondary_scale_is_not_called_strong() -> None:
    templates, labels = _library()
    flux = 1.0 * templates[0] + 0.01 * templates[1]
    errors = np.full(flux.size, 0.001)
    evidence = compare_single_and_composite_sed(
        flux,
        errors,
        templates,
        labels,
        minimum_secondary_flux_fraction=0.05,
    )
    assert evidence.evidence_status != "strong_composite_sed_evidence"


def test_labels_are_checked() -> None:
    templates, _ = _library()
    with pytest.raises(ValueError, match="template_labels"):
        fit_single_sed(
            templates[0],
            np.ones(templates.shape[1]),
            templates,
            ["only_one"],
        )


def test_fewer_than_four_bands_is_rejected() -> None:
    with pytest.raises(ValueError, match="four photometric bands"):
        compare_single_and_composite_sed(
            np.ones(3),
            np.ones(3),
            np.ones((2, 3)),
        )
