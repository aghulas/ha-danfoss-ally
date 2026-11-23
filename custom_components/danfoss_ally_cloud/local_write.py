"""Write Danfoss head settings through the LOCAL TUNNEL, under supervised trial only.

Zigbee2MQTT writes these manufacturer attributes of the thermostat cluster (0x0201, code 0x1246);
the local tunnel speaks the same Zigbee attributes, so it can write them too. None of these writes
is proven on real hardware: each is CLOSED by default and opens only for a supervised trial
(docs/first-write-procedure.md), on ONE designated head, while ``enable_local`` is on:

======================  =================  =====================================================
Trial key               Attribute          Value
======================  =================  =====================================================
``radiator_covered``    0x4016 (boolean)   on / off
``setpoint_offset``     0x404B (int8)      -2.5 to 2.5 °C by 0.1, in tenths (scale NOT confirmed)
``regulation_speed``    0x4020 (uint8)     1 to 10 (Zigbee2MQTT ``algorithm_scale_factor``)
``valve_exercise``      0x4010 / 0x4011    day (enum8) and time (minutes): the descale service's
                                           write, the two attributes written together
======================  =================  =====================================================

Every write follows the same rule (docs/architecture.md, "Rules for adding a route"):

1. the value is validated before anything is sent (type, range, step);
2. the attribute is written through the tunnel;
3. the head is read back through the tunnel (``DanfossLocalCoordinator.async_refresh_settings``)
   and the entity shows what the head said, never the value written;
4. a clear error is raised when the head rejects the write, when the read-back disagrees, or
   when the head does not answer the read-back (the entity is then unavailable until the head is
   read again, rather than showing a value that can no longer be trusted).

The tunnel read-back is not fully independent of the channel written (same tunnel): the trial
procedure adds the Danfoss app and the head itself as sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import DanfossDevice, write_allowed
from .api.local import tunnel
from .api.local.manager import Head
from .const import DATA_LOCAL_SUPERVISED_HEAD, DATA_LOCAL_SUPERVISED_SETTINGS
from .coordinator import DanfossLocalCoordinator


@dataclass(frozen=True)
class LocalTrialSetting:
    """A head setting with a local-tunnel write under trial: the attribute(s) it reads back."""

    key: str
    attributes: tuple[str, ...]  # names given by ``tunnel.name_attributes``


LOCAL_TRIAL_SETTINGS: dict[str, LocalTrialSetting] = {
    s.key: s
    for s in (
        LocalTrialSetting("radiator_covered", ("radiator_covered",)),
        LocalTrialSetting("setpoint_offset", ("setpoint_offset",)),
        LocalTrialSetting("regulation_speed", ("control_speed",)),
        LocalTrialSetting("valve_exercise", ("descale_day", "descale_time")),
        LocalTrialSetting("external_room_sensor", ("external_room_sensor",)),
        LocalTrialSetting("window_open_external", ("window_open_external",)),
        LocalTrialSetting("load_balancing", ("load_balancing",)),
        # 0x404E ``adaptation_run_settings``: enable/disable the automatic nightly adaptation run
        # (a boolean). NOT the command attribute 0x404C ``adaptation_run_control``.
        LocalTrialSetting("adaptation_run_settings", ("adaptation_setting",)),
    )
}


class LocalWriteRefused(HomeAssistantError):
    """Nothing was sent: invalid value, gateway unknown or unreachable, head unreadable."""


class LocalWriteNotConfirmed(HomeAssistantError):
    """A frame may have reached the head, and no read-back says what the head now holds."""


class LocalWriteRejected(HomeAssistantError):
    """The head was read back: it rejected the write, or holds another value than the one
    written. The entity shows that read."""


def local_trial_for(entry_data: dict[str, Any], device_id: str) -> frozenset[str]:
    """The settings opened for a local-tunnel trial ON THIS HEAD: the entry's set for the one
    designated head, nothing for every other head. ``entry_data`` is
    ``hass.data[DOMAIN][entry_id]``."""
    head = entry_data.get(DATA_LOCAL_SUPERVISED_HEAD)
    if not head or device_id != head:
        return frozenset()
    return entry_data.get(DATA_LOCAL_SUPERVISED_SETTINGS) or frozenset()


def tunnel_head(local: DanfossLocalCoordinator | None, dev: DanfossDevice | None) -> Head | None:
    """The tunnel address of a head the tunnel can reach (node id, gateway key fetched)."""
    if local is None or dev is None or not dev.is_head or not dev.node_id or not dev.mesh_id:
        return None
    if dev.mesh_id not in local.manager.gateway_ids:
        return None
    return Head(dev.id, dev.node_id, dev.mesh_id)


def local_setting_armed(
    entry_data: dict[str, Any],
    local: DanfossLocalCoordinator | None,
    dev: DanfossDevice,
    setting: str,
) -> bool:
    """True if the local-tunnel trial of ``setting`` is armed on ``dev``: the local tunnel is on and
    can address the head, the head is of a verified model, it is the designated trial head and
    ``setting`` is listed. The write entities exist only then."""
    return (
        write_allowed(dev)
        and tunnel_head(local, dev) is not None
        and setting in local_trial_for(entry_data, dev.id)
    )


def local_trial_split(
    entry_data: dict[str, Any],
    devices: Any,
    local: DanfossLocalCoordinator | None,
    setting: str,
    unique_suffix: str,
) -> tuple[list[str], list[str]]:
    """For one setting's write entity: the ids of the heads it is armed on, and the unique ids of
    the heads it is not (whose registry entries are to be removed: trial disarmed, moved to another
    head, or no local tunnel). ``devices``: the cloud coordinator's devices."""
    armed: list[str] = []
    closed: list[str] = []
    for dev in devices:
        if not dev.is_head:
            continue
        if local_setting_armed(entry_data, local, dev, setting):
            armed.append(dev.id)
        else:
            closed.append(f"{dev.id}_{unique_suffix}")
    return armed, closed


def _check(
    read: dict[str, Any] | None, expected: dict[str, Any], status: int | None
) -> dict[str, Any]:
    """Return the read-back if it holds ``expected`` and the head accepted (or did not answer the
    write itself: the read-back then decides); raise otherwise."""
    if read is None:
        raise LocalWriteNotConfirmed(
            "the head did not answer the tunnel read-back: what it holds now is unknown "
            "(the entity stays unavailable until the head is read again)"
        )
    got = {name: read.get(name) for name in expected}
    if status not in (0, None):
        raise LocalWriteRejected(
            f"the head rejected the write (ZCL status 0x{status:02x}); it reads {got}"
        )
    missing = sorted(name for name, value in got.items() if value is None)
    if missing:
        # Partial read-back (e.g. the head answered the first settings frame, not the one that
        # carries the setpoint offset): what it holds for these is unknown, not a rejection.
        raise LocalWriteNotConfirmed(
            f"the tunnel read-back did not give {', '.join(missing)}: what the head holds now "
            "is unknown (the entity stays unavailable until the head is read again)"
        )
    if got != expected:
        raise LocalWriteRejected(
            f"the tunnel read-back disagrees: written {expected}, the head reads {got}"
        )
    return read


async def _run(hass: HomeAssistant, func: Any, *args: Any) -> Any:
    try:
        return await hass.async_add_executor_job(func, *args)
    except (tunnel.LocalError, tunnel.LocalUnavailable) as err:
        # Raised before any frame is sent (validation, unknown gateway, link not opened, head
        # unreadable before a valve exercise write).
        raise LocalWriteRefused(f"local setting write refused, nothing was sent: {err}") from err
    except Exception as err:  # noqa: BLE001 - mid-write failure: the frame may have left
        raise LocalWriteNotConfirmed(f"local setting write failed: {err}") from err


async def async_local_write_setting(
    hass: HomeAssistant,
    local: DanfossLocalCoordinator,
    head: Head,
    setting: str,
    value: Any,
) -> dict[str, Any]:
    """Write ONE tunnel setting (``radiator_covered``, ``setpoint_offset`` in °C,
    ``regulation_speed``, ``external_room_sensor`` in °C, ``window_open_external``,
    ``load_balancing``, ``adaptation_run_settings``), read the head back and return what it holds
    now.

    Raises ``LocalWriteRefused`` (nothing sent), ``LocalWriteNotConfirmed`` (no read-back) or
    ``LocalWriteRejected`` (the head said no, or holds another value)."""
    (attribute,) = LOCAL_TRIAL_SETTINGS[setting].attributes
    try:
        raw = tunnel.setting_raw(attribute, value)
    except tunnel.LocalError as err:
        raise LocalWriteRefused(f"value refused, nothing was sent: {err}") from err
    # The read-back is compared to what ``tunnel.name_attributes`` returns: booleans come back as
    # bool, everything else as the raw integer written (the external sensor stays raw hundredths).
    expected = {attribute: bool(raw) if attribute in tunnel._BOOLEANS else raw}
    status = await _run(hass, local.manager.write_setting, head, attribute, value)
    return _check(await local.async_refresh_settings(head), expected, status)


async def async_local_write_valve_exercise(
    hass: HomeAssistant,
    local: DanfossLocalCoordinator,
    head: Head,
    *,
    day: str | None = None,
    hour: str | None = None,
) -> dict[str, Any]:
    """Change the valve exercise day OR time (the other one is read from the head first), read
    the head back and return what it holds now. Same errors as ``async_local_write_setting``."""
    status, new_day, new_hour = await _run(
        hass, local.manager.write_valve_exercise, head, day, hour
    )
    read = await local.async_refresh_settings(head)
    return _check(read, {"descale_day": new_day, "descale_time": new_hour}, status)
