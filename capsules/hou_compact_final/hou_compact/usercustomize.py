"""Install the per-source fail-closed covariance adapter after sitecustomize loads."""

from __future__ import annotations

import sitecustomize as _sitecustomize

if getattr(_sitecustomize, "_AUGMENT_COVARIANCE_PHASE_PRODUCTS", None) is not None:
    from gaia_covariance_failclosed import augment_covariance_phase_products

    _sitecustomize._AUGMENT_COVARIANCE_PHASE_PRODUCTS = (
        augment_covariance_phase_products
    )
