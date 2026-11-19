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


# Cloud-MQTT isolated-head write path, one DP at a time (docs/architecture.md, "Rules for adding a
# route"; procedure: docs/first-write-procedure.md).
#
# - MQTT_WRITE_DPS: PROVEN. A supervised write on real hardware was read back from an independent
#   source. Open as soon as the cloud-MQTT option is on.
# - MQTT_CANDIDATE_DPS: IMPLEMENTED, NOT PROVEN. Closed by default; a candidate opens only when it
#   is explicitly listed for a supervised trial (the ``supervised`` argument below, fed by the
#   integration's ``cloud_mqtt_supervised_dps`` option). After its supervised write succeeds, a DP
#   moves from the second set to the first in a change of its own.
MQTT_WRITE_DPS = frozenset({30})  # child lock, validated 2026-11-19
MQTT_CANDIDATE_DPS = frozenset({116})  # window detection

# Value type of each DP this path knows.
_MQTT_BOOL_DPS = frozenset({30, 116})


def mqtt_dp_open(dp: int, supervised: frozenset[int] = frozenset()) -> bool:
    """True if ``dp`` may be written over cloud MQTT: proven, or a candidate listed in
    ``supervised`` (a supervised trial). A DP that is neither proven nor a candidate is never open,
    whatever ``supervised`` says."""
    return dp in MQTT_WRITE_DPS or (dp in MQTT_CANDIDATE_DPS and dp in supervised)


def mqtt_write_value(dp: int, value: object, supervised: frozenset[int] = frozenset()) -> bool:
    """Validate a value destined for the cloud-MQTT write path and return it as it must be sent.
    Raises CloudWriteError when the DP is not open on this path or the value is not of the DP's
    type (a clear error, never a blind send)."""
    if not mqtt_dp_open(dp, supervised):
        if dp in MQTT_CANDIDATE_DPS:
            raise CloudWriteError(
                f"DP {dp} is not validated on the cloud-MQTT write path yet (closed until its "
                "supervised first write)"
            )
        raise CloudWriteError(f"DP {dp} is not enabled on the cloud-MQTT write path")
    if dp in _MQTT_BOOL_DPS:
        if not isinstance(value, bool):
            raise CloudWriteError(f"DP {dp} expects a boolean, got {type(value).__name__}")
        return value
    raise CloudWriteError(f"DP {dp} has no value rule on the cloud-MQTT write path")


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
