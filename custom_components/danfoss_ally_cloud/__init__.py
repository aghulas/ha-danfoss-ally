"""Danfoss Ally (Cloud) integration.

Entry point: sets up the cloud client (path-1a cloud API), the refresh coordinator, and -
eventually - the local tunnel and the MQTT publisher. Cloud-first; local fallback for the
operations the cloud misses (see docs/architecture.md). v0.1: cloud read only.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .api import CloudClient, async_fetch_gateway_keys
from .api.local.manager import LocalTunnelManager
from .const import (
    CONF_CH_KEY,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_ID,
    CONF_DISTINCT_DEVICE_ID,
    CONF_ENABLE_CLOUD_MQTT,
    CONF_ENABLE_HEAD_UNBIND,
    CONF_ENABLE_LOCAL,
    CONF_ENABLE_VACATION_WRITE,
    CONF_MQTT_BASE_TOPIC,
    CONF_MQTT_MODE,
    CONF_MQTT_SOURCE,
    CONF_PASSWORD,
    CONF_POST_COMMAND_REFRESH,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_SIGN_KEY,
    CONF_USERNAME,
    DATA_CLOUD_MQTT,
    DATA_COORDINATOR,
    DATA_HEAD_UNBIND,
    DATA_JOBS,
    DATA_LOCAL,
    DATA_MQTT,
    DATA_MQTT_LINK,
    DATA_SCHEDULES,
    DATA_VACATION_WRITE,
    DEFAULT_DISTINCT_DEVICE_ID,
    DEFAULT_ENABLE_CLOUD_MQTT,
    DEFAULT_ENABLE_HEAD_UNBIND,
    DEFAULT_ENABLE_VACATION_WRITE,
    DEFAULT_LOCAL_SCAN_INTERVAL,
    DEFAULT_MQTT_BASE_TOPIC,
    DEFAULT_MQTT_MODE,
    DEFAULT_MQTT_SOURCE,
    DEFAULT_POST_COMMAND_REFRESH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator
from .frontend import async_register_frontend, async_unregister_frontend
from .mqtt_publisher import MqttPublisher
from .services import async_register_services
from .websocket_api import async_register as async_register_ws
from .writejob import JobManager

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Integration-wide setup (once per instance).

    Registers the actions and WebSocket commands, serves the embedded frontend and declares its
    Lovelace resource here - never in `async_setup_entry` (contract §6). Best-effort: does not
    prevent startup.
    """
    async_register_services(hass)
    async_register_ws(hass)
    await async_register_frontend(hass)
    return True


def _client_from_entry(entry: ConfigEntry) -> CloudClient:
    data = entry.data
    return CloudClient(
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        country_code=data[CONF_COUNTRY_CODE],
        sign_key=data[CONF_SIGN_KEY],
        device_id=data[CONF_DEVICE_ID],
        ch_key=data[CONF_CH_KEY],
        region=data.get(CONF_REGION, "eu"),
        distinct_device_id=entry.options.get(CONF_DISTINCT_DEVICE_ID, DEFAULT_DISTINCT_DEVICE_ID),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an entry (one Danfoss Ally account)."""
    client = _client_from_entry(entry)
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = DanfossCoordinator(
        hass,
        client,
        scan_interval,
        post_command_refresh=entry.options.get(
            CONF_POST_COMMAND_REFRESH, DEFAULT_POST_COMMAND_REFRESH
        ),
    )
    await coordinator.async_config_entry_first_refresh()

    # Local fallback (optional): best-effort, must never prevent the cloud from starting.
    local_coordinator = await _async_setup_local(hass, entry, coordinator)

    # MQTT publishing (optional).
    publisher = await _async_setup_mqtt(hass, entry, coordinator)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_COORDINATOR: coordinator,
        DATA_LOCAL: local_coordinator,
        DATA_MQTT: publisher,
        DATA_JOBS: JobManager(),
        DATA_SCHEDULES: {},
        DATA_VACATION_WRITE: entry.options.get(
            CONF_ENABLE_VACATION_WRITE, DEFAULT_ENABLE_VACATION_WRITE
        ),
        DATA_HEAD_UNBIND: entry.options.get(CONF_ENABLE_HEAD_UNBIND, DEFAULT_ENABLE_HEAD_UNBIND),
        DATA_CLOUD_MQTT: entry.options.get(CONF_ENABLE_CLOUD_MQTT, DEFAULT_ENABLE_CLOUD_MQTT),
        # Live MQTT link is created only during a supervised, gated connect (not wired yet); the
        # switches treat None as "no cloud-MQTT path", so isolated heads stay as PR #69 left them.
        DATA_MQTT_LINK: None,
    }
    await er.async_migrate_entries(hass, entry.entry_id, _migrate_unique_id)
    _cleanup_orphaned_head_climates(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    return True


async def _async_setup_mqtt(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: DanfossCoordinator
) -> MqttPublisher | None:
    """Start the MQTT publisher if mqtt_mode != off. Best-effort (no broker -> no-op)."""
    mode = entry.options.get(CONF_MQTT_MODE, DEFAULT_MQTT_MODE)
    if mode == "off":
        return None
    publisher = MqttPublisher(
        hass,
        coordinator,
        mode,
        entry.options.get(CONF_MQTT_SOURCE, DEFAULT_MQTT_SOURCE),
        entry.options.get(CONF_MQTT_BASE_TOPIC, DEFAULT_MQTT_BASE_TOPIC),
    )
    await publisher.async_start()
    return publisher


async def _async_setup_local(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: DanfossCoordinator
) -> DanfossLocalCoordinator | None:
    """Prepare the local tunnel if the option is on. Best-effort: returns None on failure."""
    if not entry.options.get(CONF_ENABLE_LOCAL):
        return None
    try:
        gateways = await async_fetch_gateway_keys(coordinator.client)
    except Exception as err:  # noqa: BLE001 - le repli local ne bloque jamais le cloud
        _LOGGER.warning("Local fallback unavailable (key fetch): %s", err)
        return None
    if not gateways:
        _LOGGER.warning("Local fallback enabled but no gateway with a local key found.")
        return None
    manager = LocalTunnelManager(gateways)
    local = DanfossLocalCoordinator(hass, manager, coordinator, DEFAULT_LOCAL_SCAN_INTERVAL)
    # Non-blocking first survey: an unreachable gateway must not prevent startup.
    await local.async_refresh()
    return local


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an entry (close session, tunnel, MQTT publisher)."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data:
            publisher: MqttPublisher | None = data.get(DATA_MQTT)
            if publisher is not None:
                await publisher.async_stop()
            coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
            await coordinator.client.async_close()
    return unloaded


# Entity unique_id slugs were anglicised in the English-base release. The slug is the trailing
# segment of ``{id}_{slug}``; this migration renames existing entities so histories, automations and
# dashboards survive the rename. Longest suffixes first so "_fenetre" never matches
# "_detection_fenetre". Idempotent: new suffixes match none of the old ones.
_UNIQUE_ID_SUFFIX_MIGRATION: tuple[tuple[str, str], ...] = (
    ("_detection_fenetre", "_window_detection"),
    ("_consigne_confort", "_comfort_setpoint"),
    ("_consigne_reduit", "_setback_setpoint"),
    ("_ouverture_vanne", "_valve_opening"),
    ("_verrou_enfant", "_child_lock"),
    ("_pre_chauffage", "_preheat"),
    ("_en_ligne", "_online"),
    ("_batterie", "_battery"),
    ("_fenetre", "_window"),
    ("_defaut", "_fault"),
)


def _migrate_unique_id(entity_entry: er.RegistryEntry) -> dict[str, str] | None:
    """Map an old French-slug unique_id to its English equivalent (else leave it unchanged)."""
    uid = entity_entry.unique_id
    for old, new in _UNIQUE_ID_SUFFIX_MIGRATION:
        if uid.endswith(old):
            return {"new_unique_id": uid[: -len(old)] + new}
    return None


def _cleanup_orphaned_head_climates(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: DanfossCoordinator
) -> None:
    """Remove the old PER-HEAD climates now replaced by the PER-ROOM climate.

    Conservative: removes ONLY ``climate`` entities of THIS entry whose unique_id is the id of a
    now-grouped head (old "one climate per head" model). Isolated heads keep their climate
    (read-only), and nothing else is touched - better to leave an orphan entity than to wrongly
    delete a user-customised one.
    """
    registry = er.async_get(hass)
    for head_id in coordinator.grouped_ids:
        ent_id = registry.async_get_entity_id("climate", DOMAIN, head_id)
        if ent_id is None:
            continue
        entity = registry.async_get(ent_id)
        if entity is not None and entity.config_entry_id == entry.entry_id:
            _LOGGER.debug("Removing old per-head climate %s (room %s)", ent_id, head_id)
            registry.async_remove(ent_id)


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change (MQTT, local, interval)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """On removal of the LAST entry: clean up the Lovelace resource (contract §6).

    We do not clean up on a simple unload/reload (which only calls `async_unload_entry`), but only
    when no entry remains.
    """
    if not hass.config_entries.async_entries(DOMAIN):
        await async_unregister_frontend(hass)
