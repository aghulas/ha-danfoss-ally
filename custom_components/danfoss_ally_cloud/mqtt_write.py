"""Write DPs of an ISOLATED head over the Tuya cloud MQTT link: validate, publish, confirm.

One place for every entity that writes through the cloud-MQTT channel (setting switches, numbers),
so they all follow the same rule (docs/architecture.md, "Rules for adding a route"):

1. the values are validated before anything is sent (``api.writes.mqtt_write_value``: the DP must be
   open on this channel, and the value of the right type and range);
2. the DPs go out in ONE frame, as the app does;
3. the write is confirmed by the gateway's echo of each DP (inbound protocol-4 report), or failing
   that by one read of the head through the per-device cloud route;
4. otherwise a clear error is raised. No optimistic state is ever set: entities keep showing what
   the cloud returns.

Preheat (DP 1) is the exception to rule 3: the echo and the cloud read may both answer from the
gateway's cache. ``async_mqtt_write`` refuses it; ``async_mqtt_write_preheat`` publishes it, posts
the settings block as the app does, and accepts ONE confirmation only, the head's attribute 0x0025
read through the local tunnel.

Viewing direction (DP 101) and orientation (DP 133) are candidates too (batch C of
docs/zigbee2mqtt-alignment.md), each with its own confirmation and never the echo:
``async_mqtt_write_orientation`` reads the head's flag 0x4014 back through the tunnel;
``async_mqtt_write_viewing_direction`` reads the per-device cloud route (the tunnel does not read
the user-interface cluster), the trial's proof being the head's display
(docs/viewing-orientation-trial.md).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .api import (
    MQTT_CLOUD_CONFIRMED_DPS,
    MQTT_TUNNEL_CONFIRMED_DPS,
    CloudError,
    DanfossDevice,
    mqtt_dp_open,
    mqtt_write_value,
    write_allowed,
)
from .api.local.manager import Head
from .api.mqtt_client import CloudMqttLink
from .const import (
    DATA_CLOUD_MQTT,
    DATA_MQTT_SUPERVISED_DPS,
    DATA_MQTT_SUPERVISED_HEAD,
    DP_AT_HOME_SETPOINT,
    DP_HOLIDAY_SETPOINT,
    DP_LEAVING_HOME_SETPOINT,
    DP_ORIENTATION,
    DP_PREHEAT,
    DP_VIEWING_DIRECTION,
)
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator

_LOGGER = logging.getLogger(__name__)

# How long to wait for the gateway's inbound protocol-4 confirmation after a cloud-MQTT write,
# before falling back to a cloud re-read (and then a clear error if still unconfirmed). Also about
# the time the cloud needs to take a change into account (POST_COMMAND_SETTLE).
MQTT_CONFIRM_TIMEOUT = 15.0

CONFIRMED_BY_ECHO = "echo"
CONFIRMED_BY_CLOUD = "cloud"
CONFIRMED_BY_TUNNEL = "tunnel"
UNCHANGED = "unchanged"  # the head already had the value: nothing was published

# Preheat over cloud MQTT is confirmed by the local tunnel only. The head is read every
# PREHEAT_CONFIRM_INTERVAL seconds until its attribute 0x0025 shows the value, for at most
# PREHEAT_CONFIRM_TIMEOUT seconds. The app's own toggle was seen on the head 20 to 60 s later
# (2026-11-20, three toggles on one head): the head is reprogrammed through the Zigbee tunnel after
# the toggle, which takes that long. Two minutes leaves a margin; past it, the write is the
# "accepted but not applied" failure. One tunnel read takes several seconds, hence the interval;
# the last read starts before the deadline and may end after it, so the error reports the time
# really elapsed.
PREHEAT_CONFIRM_TIMEOUT = 120.0
PREHEAT_CONFIRM_INTERVAL = 10.0

# The app's "Settings" block: after publishing a setting of this block over MQTT, the app also
# posts the WHOLE block through ``settings.change`` (the cloud-side store of the workflow, contract
# §4.2). Keys in the order the app sends them.
SETTINGS_BLOCK_DPS: tuple[int, ...] = (
    DP_PREHEAT,
    DP_AT_HOME_SETPOINT,
    DP_LEAVING_HOME_SETPOINT,
    DP_HOLIDAY_SETPOINT,
)


def settings_block(dev: DanfossDevice, changed: dict[int, Any]) -> dict[str, object]:
    """The whole settings block to post after a write of one of its settings: the head's current
    values, as the cloud holds them, with ``changed`` applied. Raises ``HomeAssistantError`` when a
    value of the block is unknown: the block is sent whole or not at all, never with a guessed
    value."""
    block: dict[str, object] = {}
    for dp in SETTINGS_BLOCK_DPS:
        value = changed.get(dp, dev.dps.get(str(dp)))
        if value is None or value == "":
            raise HomeAssistantError(
                f"write refused: DP {dp} of the head's settings block is unknown, so the block "
                "the app posts with a change of that block cannot be built"
            )
        block[str(dp)] = value
    return block


def supervised_for(entry_data: dict[str, Any], device_id: str) -> frozenset[int]:
    """The candidate DPs opened for a supervised trial ON THIS HEAD: the entry's supervised set for
    the one designated trial head, nothing for every other head. ``entry_data`` is
    ``hass.data[DOMAIN][entry_id]``. Entities must take their supervised set from here, never from
    the entry-wide set, so a trial stays confined to the head it was armed for."""
    head = entry_data.get(DATA_MQTT_SUPERVISED_HEAD)
    if not head or device_id != head:
        return frozenset()
    return entry_data.get(DATA_MQTT_SUPERVISED_DPS) or frozenset()


async def async_mqtt_write(
    coordinator: DanfossCoordinator,
    link: CloudMqttLink,
    dev: DanfossDevice,
    dps: dict[int, Any],
    *,
    supervised: frozenset[int] = frozenset(),
    confirm_dps: Collection[int] | None = None,
) -> str:
    """Publish ``dps`` ({dp: raw value}) to ``dev`` and return how the write was confirmed
    (``CONFIRMED_BY_ECHO`` / ``CONFIRMED_BY_CLOUD``). Raises ``HomeAssistantError`` when a value is
    refused, the publish fails, or nothing confirms the write.

    ``confirm_dps``: the DPs whose confirmation is required (default: all of them). A companion DP
    the app sends along but that the head may overrule at once (``temp_set`` next to the comfort
    setting) is published and validated like the others, without making the write fail when its
    own echo does not come."""
    if not dev.node_id or not dev.mesh_id:
        raise HomeAssistantError(
            "cloud-MQTT write impossible: the head's gateway address is unknown"
        )
    unconfirmable = sorted(MQTT_TUNNEL_CONFIRMED_DPS.intersection(dps))
    if unconfirmable:
        # Never through this function: its confirmation (echo, cloud read) proves nothing for them.
        raise HomeAssistantError(
            f"cloud-MQTT write refused: DP {unconfirmable} can only be confirmed through the "
            "local tunnel"
        )
    echo_untrusted = sorted(MQTT_CLOUD_CONFIRMED_DPS.intersection(dps))
    if echo_untrusted:
        # The echo would be accepted here: these DPs have their own write and confirmation.
        raise HomeAssistantError(
            f"cloud-MQTT write refused: DP {echo_untrusted} is confirmed by its own supervised "
            "write only (the gateway's echo is not accepted)"
        )
    try:
        values = {dp: mqtt_write_value(dp, value, supervised) for dp, value in dps.items()}
    except CloudError as err:
        raise HomeAssistantError(f"cloud-MQTT write refused: {err}") from err

    required = {
        dp: value for dp, value in values.items() if confirm_dps is None or dp in confirm_dps
    }
    # Listen for the echoes before publishing, so a fast gateway cannot answer unheard.
    waiters = [
        asyncio.ensure_future(
            link.await_confirmation(dev.node_id, dp, value, timeout_s=MQTT_CONFIRM_TIMEOUT)
        )
        for dp, value in required.items()
    ]
    await asyncio.sleep(0)
    try:
        await link.publish_dp(dev.mesh_id, dev.node_id, {str(dp): v for dp, v in values.items()})
        echoed = all(await asyncio.gather(*waiters))
    except Exception as err:  # noqa: BLE001 - surface any send failure, never a blind write
        for waiter in waiters:
            waiter.cancel()
        raise HomeAssistantError(f"cloud-MQTT write failed: {err}") from err

    coordinator.note_commanded([dev.id])
    source = CONFIRMED_BY_ECHO
    if not echoed:
        # No echo: read the head once through the per-device route (fresher than the bulk list).
        try:
            fresh = await coordinator.client.async_get_device_dps(dev.id)
        except CloudError as err:
            _LOGGER.debug("cloud-MQTT confirmation read failed (%s)", type(err).__name__)
            fresh = None
        if not fresh or any(fresh.get(str(dp)) != value for dp, value in required.items()):
            await coordinator.async_request_refresh()
            raise HomeAssistantError(
                "cloud-MQTT write not confirmed (no echo from the gateway, the cloud still differs)"
            )
        source = CONFIRMED_BY_CLOUD
    _LOGGER.debug("cloud-MQTT DP(s) %s confirmed by %s", sorted(required), source)
    await coordinator.async_request_refresh()
    return source


async def async_mqtt_write_preheat(
    local: DanfossLocalCoordinator,
    coordinator: DanfossCoordinator,
    link: CloudMqttLink,
    dev: DanfossDevice,
    active: bool,
    *,
    supervised: frozenset[int] = frozenset(),
) -> str:
    """Write preheat on ``dev`` the way the app is understood to (publish ``{"1": active}`` over
    cloud MQTT, then post the whole settings block through ``settings.change``) and confirm it
    through the LOCAL TUNNEL only. Returns ``CONFIRMED_BY_TUNNEL``, or ``UNCHANGED`` when the head
    already had the value (nothing is sent then: an unchanged head would prove nothing).

    Why both calls: the MQTT publish alone changed the cloud's DP 1 and not the head (supervised
    write of 2026-11-20), while the app's toggle is followed by a reprogramming of the head through
    the Zigbee tunnel. The settings block is what the app posts next to the publish for the
    settings of that block; whether that pair is what triggers the reprogramming is NOT proven —
    this function is the trial of it (docs/cloud-mqtt-preheat-proposal.md).

    The gateway's echo and the cloud's DP 1 are deliberately ignored: they showed the new value
    while the head had not moved. So:

    - the settings block is built first; if a value of it is unknown nothing is sent;
    - the head is read through the tunnel BEFORE anything is sent; without an answer nothing is
      sent, since the write could not be confirmed afterwards;
    - after the two calls the head is read again until it shows the value, or a clear error is
      raised. Every read updates the preheat switch, which therefore only ever shows what the head
      itself said (unavailable when it did not answer).

    Limit, by design: this function cannot put the CLOUD's DP 1 back in step with the head. After
    a "not confirmed" (the cloud may have taken the value while the head did not), asking for the
    head's own value again returns ``UNCHANGED`` and sends nothing, because a write the head has no
    reason to react to could not be confirmed by the tunnel. That resynchronisation is done from
    the Danfoss app (docs/first-write-procedure.md, DP 1 sheet)."""
    if not dev.node_id or not dev.mesh_id:
        raise HomeAssistantError(
            "cloud-MQTT write impossible: the head's gateway address is unknown"
        )
    try:
        value = mqtt_write_value(DP_PREHEAT, active, supervised)
    except CloudError as err:
        raise HomeAssistantError(f"cloud-MQTT write refused: {err}") from err
    # Build the HTTP block BEFORE anything is sent: if it cannot be built, nothing goes out.
    block = settings_block(dev, {DP_PREHEAT: value})
    head = Head(dev.id, dev.node_id, dev.mesh_id)

    before = await local.async_refresh_head(head)
    if before is None:
        raise HomeAssistantError(
            "cloud-MQTT preheat write refused: the head does not answer through the local "
            "tunnel, so the write could not be confirmed"
        )
    if before == value:
        return UNCHANGED

    try:
        await link.publish_dp(dev.mesh_id, dev.node_id, {str(DP_PREHEAT): value})
    except Exception as err:  # noqa: BLE001 - surface any send failure, never a blind write
        raise HomeAssistantError(f"cloud-MQTT write failed: {err}") from err
    loop = asyncio.get_running_loop()
    sent_at = loop.time()
    try:
        # ``gwId`` = the head's own devId for this block, as the app sends it.
        await coordinator.client.async_write_setting(dev.id, dev.product_id or "", block)
    except CloudError as err:
        await local.async_refresh_head(head)  # show what the head says, whatever happened
        raise HomeAssistantError(
            "cloud-MQTT preheat write incomplete: the frame was sent, but the settings block "
            f"was refused by the cloud ({err}). The cloud's DP 1 may now differ from the head: "
            "read both again before any other write"
        ) from err

    deadline = sent_at + PREHEAT_CONFIRM_TIMEOUT
    while True:
        await asyncio.sleep(PREHEAT_CONFIRM_INTERVAL)
        if await local.async_refresh_head(head) == value:
            _LOGGER.debug(
                "cloud-MQTT preheat confirmed by the local tunnel after %.0f s",
                loop.time() - sent_at,
            )
            return CONFIRMED_BY_TUNNEL
        if loop.time() >= deadline:
            raise HomeAssistantError(
                "cloud-MQTT preheat write not confirmed: the frame and the settings block were "
                f"sent, and {loop.time() - sent_at:.0f} s later the head's attribute 0x0025, "
                "read through the local tunnel, does not show the value (the gateway's echo and "
                "the cloud are not accepted as confirmation for preheat). The head may still "
                "apply it later, and the cloud's DP 1 may now differ from the head: read both "
                "again before any other write"
            )


class WriteNotConfirmed(HomeAssistantError):
    """A supervised trial write sent its frame (or may have) and nothing confirmed it: what the
    entity showed before can no longer be trusted until the head is read again."""


# --- supervised trials of batch C: viewing direction (DP 101) and orientation (DP 133) ---------

# Orientation: the head's flag 0x4014 is read through the tunnel (two frames, several seconds)
# every ORIENTATION_CONFIRM_INTERVAL seconds, for at most ORIENTATION_CONFIRM_TIMEOUT seconds. No
# delay is known for this setting: the preheat trial's two minutes are used as the margin.
ORIENTATION_CONFIRM_TIMEOUT = 120.0
ORIENTATION_CONFIRM_INTERVAL = 15.0
# Viewing direction: the per-device cloud route is read every VIEWING_CONFIRM_INTERVAL seconds
# for at most VIEWING_CONFIRM_TIMEOUT seconds: four reads at most on the user's account. The
# cloud takes a change into account in about 15 s (POST_COMMAND_SETTLE).
VIEWING_CONFIRM_TIMEOUT = 60.0
VIEWING_CONFIRM_INTERVAL = 15.0

# Meaning of the head's orientation flag (Danfoss attribute 0x4014) as Zigbee2MQTT reads it:
# false = horizontal, true = vertical. NOT established on real hardware here (open question of
# docs/zigbee2mqtt-alignment.md §6). The write therefore refuses to send when the tunnel's flag and
# the cloud's DP 133 disagree under this mapping: one of them, or the mapping, is wrong.
ORIENTATION_FLAG: dict[str, bool] = {"Horizontal": False, "Vertical": True}


def trial_dp_armed(
    entry_data: dict[str, Any], coordinator: DanfossCoordinator, dev: DanfossDevice, dp: int
) -> bool:
    """True if the supervised trial of candidate ``dp`` is armed on ``dev``: the cloud-MQTT option
    is on, ``dev`` is the designated trial head with ``dp`` listed, and it is an isolated head of
    a verified model (the app publishes these settings for an isolated head only). The entities of
    batch C exist only then."""
    return (
        bool(entry_data.get(DATA_CLOUD_MQTT))
        and dev.is_head
        and write_allowed(dev)
        and coordinator.group_of(dev.id) is None
        and mqtt_dp_open(dp, supervised_for(entry_data, dev.id))
    )


async def _publish(link: CloudMqttLink, dev: DanfossDevice, dp: int, value: Any) -> None:
    try:
        await link.publish_dp(dev.mesh_id or "", dev.node_id or "", {str(dp): value})
    except Exception as err:  # noqa: BLE001 - surface any send failure, never a blind write
        # The frame may have left before the failure: treated as sent, not confirmed.
        raise WriteNotConfirmed(f"cloud-MQTT write failed: {err}") from err


def _validated(dp: int, value: Any, supervised: frozenset[int], dev: DanfossDevice) -> Any:
    if not dev.node_id or not dev.mesh_id:
        raise HomeAssistantError(
            "cloud-MQTT write impossible: the head's gateway address is unknown"
        )
    try:
        return mqtt_write_value(dp, value, supervised)
    except CloudError as err:
        raise HomeAssistantError(f"cloud-MQTT write refused: {err}") from err


async def async_mqtt_write_orientation(
    local: DanfossLocalCoordinator,
    coordinator: DanfossCoordinator,
    link: CloudMqttLink,
    dev: DanfossDevice,
    orientation: str,
    *,
    supervised: frozenset[int] = frozenset(),
) -> str:
    """Write the mounting orientation of ``dev`` as the app does (``{"133": "Vertical"}`` or
    ``"Horizontal"`` over cloud MQTT) and confirm it through the LOCAL TUNNEL only: the head's
    flag 0x4014 read back. Returns ``CONFIRMED_BY_TUNNEL``, or ``UNCHANGED`` when the head already
    has the value (nothing is sent). Raises ``HomeAssistantError`` otherwise, nothing optimistic.

    Before anything is sent: the value must be exactly ``"Vertical"`` or ``"Horizontal"``; the head
    must answer through the tunnel with its flag; and when the cloud carries DP 133, the flag and
    the cloud's value must agree under ``ORIENTATION_FLAG`` (they do not when the mapping, the
    cloud or the head is wrong, and a confirmation would then prove nothing)."""
    value = _validated(DP_ORIENTATION, orientation, supervised, dev)
    expected = ORIENTATION_FLAG[str(value)]
    head = Head(dev.id, dev.node_id or "", dev.mesh_id or "")

    before = await local.async_refresh_settings(head)
    flag = None if before is None else before.get("orientation")
    if not isinstance(flag, bool):
        raise HomeAssistantError(
            "cloud-MQTT orientation write refused: the head does not give its orientation flag "
            "(0x4014) through the local tunnel, so the write could not be confirmed"
        )
    cloud = dev.orientation
    if cloud is not None and ORIENTATION_FLAG[cloud] != flag:
        raise HomeAssistantError(
            f"cloud-MQTT orientation write refused: the head's flag 0x4014 is {flag} and the "
            f"cloud's DP 133 is {cloud!r}, which disagree if false means horizontal (Zigbee2MQTT's "
            "reading, not established here). Nothing was sent: settle that first "
            "(docs/viewing-orientation-trial.md)"
        )
    if flag == expected:
        return UNCHANGED

    await _publish(link, dev, DP_ORIENTATION, value)
    coordinator.note_commanded([dev.id])
    loop = asyncio.get_running_loop()
    sent_at = loop.time()
    deadline = sent_at + ORIENTATION_CONFIRM_TIMEOUT
    while True:
        await asyncio.sleep(ORIENTATION_CONFIRM_INTERVAL)
        after = await local.async_refresh_settings(head)
        if after is not None and after.get("orientation") == expected:
            _LOGGER.debug(
                "cloud-MQTT orientation confirmed by the local tunnel after %.0f s",
                loop.time() - sent_at,
            )
            await coordinator.async_request_refresh()
            return CONFIRMED_BY_TUNNEL
        if loop.time() >= deadline:
            await coordinator.async_request_refresh()
            raise WriteNotConfirmed(
                "cloud-MQTT orientation write not confirmed: the frame was sent, and "
                f"{loop.time() - sent_at:.0f} s later the head's flag 0x4014, read through the "
                "local tunnel, does not show the value (the gateway's echo and the cloud are not "
                "accepted as confirmation). The head may still apply it later, and the cloud's "
                "DP 133 may now differ from the head: read both again before any other write"
            )


async def async_mqtt_write_viewing_direction(
    coordinator: DanfossCoordinator,
    link: CloudMqttLink,
    dev: DanfossDevice,
    on: bool,
    *,
    supervised: frozenset[int] = frozenset(),
) -> str:
    """Write the viewing direction of ``dev`` as the app does (``{"101": bool}`` over cloud MQTT)
    and confirm it by the PER-DEVICE cloud route, read until it shows the value. Returns
    ``CONFIRMED_BY_CLOUD``, or ``UNCHANGED`` when the cloud already has the value (nothing is
    sent). Raises ``HomeAssistantError`` otherwise.

    The gateway's echo is not accepted. The tunnel does not read the user-interface cluster where
    the head keeps this setting, so the cloud is the only read source here; it is still the
    gateway's view, and the trial's proof that the head applied it is its display."""
    value = _validated(DP_VIEWING_DIRECTION, on, supervised, dev)
    key = str(DP_VIEWING_DIRECTION)

    async def read() -> Any:
        try:
            fresh = await coordinator.client.async_get_device_dps(dev.id)
        except CloudError as err:
            _LOGGER.debug("viewing direction read failed (%s)", type(err).__name__)
            return None
        return None if not fresh else fresh.get(key)

    before = await read()
    if not isinstance(before, bool):
        raise HomeAssistantError(
            "cloud-MQTT viewing direction write refused: the per-device cloud route does not "
            "give DP 101, so the write could not be confirmed"
        )
    if before == value:
        return UNCHANGED

    await _publish(link, dev, DP_VIEWING_DIRECTION, value)
    coordinator.note_commanded([dev.id])
    loop = asyncio.get_running_loop()
    sent_at = loop.time()
    deadline = sent_at + VIEWING_CONFIRM_TIMEOUT
    while True:
        await asyncio.sleep(VIEWING_CONFIRM_INTERVAL)
        if await read() == value:
            await coordinator.async_request_refresh()
            return CONFIRMED_BY_CLOUD
        if loop.time() >= deadline:
            await coordinator.async_request_refresh()
            raise WriteNotConfirmed(
                "cloud-MQTT viewing direction write not confirmed: the frame was sent, and "
                f"{loop.time() - sent_at:.0f} s later the per-device cloud route does not show "
                "the value (the gateway's echo is not accepted)"
            )
