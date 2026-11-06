"""India market-pack interpretation of neutral product codes.

The neutral request carries an opaque ``ProductCode``. The India pack owns
the vocabulary that gives it meaning: its existing ``ProductType`` values.
Unknown codes fail closed; the pack defines no implicit default, so absent
product selection stays absent and existing compatibility behavior remains
the broker adapter's documented migration path.
"""

from __future__ import annotations

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.value_objects import ProductCode

from .domain import ProductType

_INDIA_PRODUCT_CODES: frozenset[str] = frozenset(product.value for product in ProductType)


def india_product_type(product_code: ProductCode) -> ProductType:
    """Resolve one neutral product code within the India pack, or fail closed."""
    normalized = product_code.value.strip().upper()
    if normalized not in _INDIA_PRODUCT_CODES:
        raise ValueError(f"unsupported India product code: {normalized}")
    return ProductType(normalized)


def india_request_product(request: ApprovedExecutionRequest) -> ProductType | None:
    """Return the request's India product, or None when the request omits one.

    Absence is not AUTO and not a default: the caller decides whether the
    applicable product/rule contract requires an explicit selection.
    """
    if request.product is None:
        return None
    return india_product_type(request.product)


__all__ = ["india_product_type", "india_request_product"]
