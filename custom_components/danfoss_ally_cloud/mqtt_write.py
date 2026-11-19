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
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .api import CloudError, DanfossDevice, mqtt_write_value
from .api.mqtt_client import CloudMqttLink
from .coordinator import DanfossCoordinator

_LOGGER = logging.getLogger(__name__)

# How long to wait for the gateway's inbound protocol-4 confirmation after a cloud-MQTT write,
# before falling back to a cloud re-read (and then a clear error if still unconfirmed). Also about
# the time the cloud needs to take a change into account (POST_COMMAND_SETTLE).
MQTT_CONFIRM_TIMEOUT = 15.0

CONFIRMED_BY_ECHO = "echo"
CONFIRMED_BY_CLOUD = "cloud"


async def async_mqtt_write(
    coordinator: DanfossCoordinator,
    link: CloudMqttLink,
    dev: DanfossDevice,
    dps: dict[int, Any],
    *,
    supervised: frozenset[int] = frozenset(),
) -> str:
    """Publish ``dps`` ({dp: raw value}) to ``dev`` and return how the write was confirmed
    (``CONFIRMED_BY_ECHO`` / ``CONFIRMED_BY_CLOUD``). Raises ``HomeAssistantError`` when a value is
    refused, the publish fails, or nothing confirms the write."""
    if not dev.node_id or not dev.mesh_id:
        raise HomeAssistantError(
            "cloud-MQTT write impossible: the head's gateway address is unknown"
        )
    try:
        values = {dp: mqtt_write_value(dp, value, supervised) for dp, value in dps.items()}
    except CloudError as err:
        raise HomeAssistantError(f"cloud-MQTT write refused: {err}") from err

    # Listen for the echoes before publishing, so a fast gateway cannot answer unheard.
    waiters = [
        asyncio.ensure_future(
            link.await_confirmation(dev.node_id, dp, value, timeout_s=MQTT_CONFIRM_TIMEOUT)
        )
        for dp, value in values.items()
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
        if not fresh or any(fresh.get(str(dp)) != value for dp, value in values.items()):
            await coordinator.async_request_refresh()
            raise HomeAssistantError(
                "cloud-MQTT write not confirmed (no echo from the gateway, the cloud still differs)"
            )
        source = CONFIRMED_BY_CLOUD
    _LOGGER.debug("cloud-MQTT DP(s) %s confirmed by %s", sorted(values), source)
    await coordinator.async_request_refresh()
    return source
