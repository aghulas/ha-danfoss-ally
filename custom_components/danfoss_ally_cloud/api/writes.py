"""Write safety: value validation and a model guard-rail (path 1a).

Different from the MCP: no prepare->confirm token here. Safety comes from VALIDATING the values
before sending and from entities being unavailable rather than lying (see CLAUDE.md).
"""

from __future__ import annotations

from .client import CloudWriteError
from .const import WRITE_VERIFIED_PRODUCTS
from .decode import DanfossDevice


def write_allowed(dev: DanfossDevice) -> bool:
    """True if the write mechanism is wired for this product (model guard-rail)."""
    return bool(dev.product_id) and dev.product_id in WRITE_VERIFIED_PRODUCTS


def encode_setpoint(celsius, low: float, high: float, step: float = 0.5) -> int:
    """Setpoint °C -> DP value (tenths), rounded to the step and clamped. Raises CloudWriteError."""
    try:
        c = float(celsius)
    except (TypeError, ValueError) as err:
        raise CloudWriteError(f"non-numeric setpoint: {celsius!r}") from err
    c = round(c / step) * step
    if not low <= c <= high:
        raise CloudWriteError(f"setpoint out of range: {c} °C (expected {low}-{high} °C)")
    return int(round(c * 10))
