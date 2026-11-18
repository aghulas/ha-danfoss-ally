"""Danfoss Ally access layer - reusable library, with no Home Assistant dependency.

This folder IS the `pydanfoss-cloud` library (see README.md here): the repo's `pyproject.toml`
packages it under the name `pydanfoss_cloud` without moving the files. The integration "vendors" it
by relative import (`from .api import …`) to stay self-contained for HACS; the MCP connector can
depend on it via PyPI once published, then the integration will switch to manifest.json ->
requirements.

Reuse (see docs/reuse.md):
  - client and app signature     : ~/dev/danfoss-ally-signing-re
  - key fetching, DPs            : ~/dev/danfoss-ally-mcp (tuya/pilote_tuya.py)
  - Zigbee tunnel DP 198/199     : ~/dev/danfoss-ally-mcp (local.py)
"""

from __future__ import annotations

from . import schedule
from .client import (
    CloudAuthError,
    CloudClient,
    CloudError,
    CloudWriteError,
    ScheduleValidationError,
    UnknownTargetError,
)
from .decode import (
    DanfossDevice,
    decode_device,
    decode_operation,
    head_state,
    holiday_temperature,
)
from .keys import GatewayKey, async_fetch_gateway_keys
from .schedule import Schedule, count_transitions, validate_days
from .writes import encode_setpoint, write_allowed

__all__ = [
    "CloudAuthError",
    "CloudClient",
    "CloudError",
    "CloudWriteError",
    "DanfossDevice",
    "GatewayKey",
    "Schedule",
    "ScheduleValidationError",
    "UnknownTargetError",
    "async_fetch_gateway_keys",
    "count_transitions",
    "decode_device",
    "decode_operation",
    "encode_setpoint",
    "head_state",
    "holiday_temperature",
    "schedule",
    "validate_days",
    "write_allowed",
]
