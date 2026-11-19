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


# Cloud-MQTT isolated-head write path: start with DP 30 (child lock) only. Extend setting by setting
# AFTER a real-hardware validation (see docs/first-write-procedure.md / cloud-mqtt-publish.md §6).
MQTT_WRITE_DPS = frozenset({30})


def mqtt_write_value(dp: int, value: object) -> bool:
    """Validate a value destined for the cloud-MQTT write path. Only DP 30 is allowed for now, and
    it is a boolean. Raises CloudWriteError otherwise (a clear error, never a blind send)."""
    if dp not in MQTT_WRITE_DPS:
        raise CloudWriteError(f"DP {dp} is not enabled on the cloud-MQTT write path (DP 30 only)")
    if not isinstance(value, bool):
        raise CloudWriteError(f"DP {dp} expects a boolean, got {type(value).__name__}")
    return value


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
