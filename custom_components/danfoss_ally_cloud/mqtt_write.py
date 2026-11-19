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
gateway's cache. ``async_mqtt_write`` refuses it; ``async_mqtt_write_preheat`` publishes it and
accepts ONE confirmation only, the head's attribute 0x0025 read through the local tunnel.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .api import MQTT_TUNNEL_CONFIRMED_DPS, CloudError, DanfossDevice, mqtt_write_value
from .api.local.manager import Head
from .api.mqtt_client import CloudMqttLink
from .const import DATA_MQTT_SUPERVISED_DPS, DATA_MQTT_SUPERVISED_HEAD
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

DP_PREHEAT = 1
# Preheat over cloud MQTT is confirmed by the local tunnel only. The head is read every
# PREHEAT_CONFIRM_INTERVAL seconds until its attribute 0x0025 shows the value, for at most
# PREHEAT_CONFIRM_TIMEOUT seconds (the stop rule of docs/first-write-procedure.md: an independent
# source that does not show the change within about a minute is the "accepted but not applied"
# failure). One tunnel read takes several seconds, hence the interval; the last read starts before
# the deadline and may end after it, so the error reports the time really elapsed.
PREHEAT_CONFIRM_TIMEOUT = 60.0
PREHEAT_CONFIRM_INTERVAL = 10.0


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
    link: CloudMqttLink,
    dev: DanfossDevice,
    active: bool,
    *,
    supervised: frozenset[int] = frozenset(),
) -> str:
    """Publish preheat (``{"1": active}``) to ``dev`` over cloud MQTT and confirm it through the
    LOCAL TUNNEL only. Returns ``CONFIRMED_BY_TUNNEL``, or ``UNCHANGED`` when the head already had
    the value (nothing is published then: an unchanged head would prove nothing).

    The gateway's echo and the cloud's DP 1 are deliberately ignored: over HTTP, DP 1 only changed
    the gateway cache while the head's real preheat (attribute 0x0025, bit 1) did not move. So:

    - the head is read through the tunnel BEFORE the publish; without an answer nothing is sent,
      since the write could not be confirmed afterwards;
    - after the publish the head is read again until it shows the value, or a clear error is
      raised. Every read updates the preheat switch, which therefore only ever shows what the head
      itself said (unavailable when it did not answer).

    Limit, by design: this function cannot put the CLOUD's DP 1 back in step with the head. After
    a "not confirmed" (the gateway cache may have taken the value while the head did not), asking
    for the head's own value again returns ``UNCHANGED`` and publishes nothing, because a publish
    the head has no reason to react to could not be confirmed by the tunnel. That resynchronisation
    is done from the Danfoss app (docs/first-write-procedure.md, DP 1 sheet)."""
    if not dev.node_id or not dev.mesh_id:
        raise HomeAssistantError(
            "cloud-MQTT write impossible: the head's gateway address is unknown"
        )
    try:
        value = mqtt_write_value(DP_PREHEAT, active, supervised)
    except CloudError as err:
        raise HomeAssistantError(f"cloud-MQTT write refused: {err}") from err
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
                "cloud-MQTT preheat write not confirmed: the frame was sent, and "
                f"{loop.time() - sent_at:.0f} s later the head's attribute 0x0025, read through "
                "the local tunnel, does not show the value (the gateway's echo and the cloud are "
                "not accepted as confirmation for preheat). The head may still apply it later, "
                "and the cloud's DP 1 may now differ from the head: read both again before "
                "any other write"
            )
