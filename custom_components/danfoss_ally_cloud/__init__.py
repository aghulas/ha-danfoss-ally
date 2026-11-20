"""Danfoss Ally (Cloud) integration.

Entry point: sets up the cloud client (path-1a cloud API), the refresh coordinator, the optional
local Zigbee tunnel, the optional Tuya cloud-MQTT link, and the MQTT publisher (see
docs/architecture.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .api import MQTT_CANDIDATE_DPS, CloudClient, GatewayKey, async_fetch_gateway_keys
from .api.local.manager import LocalTunnelManager
from .api.mqtt_client import (
    CloudMqttLink,
    GatewayRef,
    MqttCredentials,
    build_credentials,
)
from .const import (
    CLOUD_MQTT_PROBE_MAX_SECONDS,
    CONF_CH_KEY,
    CONF_CLOUD_MQTT_PROBE,
    CONF_CLOUD_MQTT_SUPERVISED_DPS,
    CONF_CLOUD_MQTT_SUPERVISED_HEAD,
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
    DATA_MQTT_COVERAGE,
    DATA_MQTT_LINK,
    DATA_MQTT_SUPERVISED_DPS,
    DATA_MQTT_SUPERVISED_HEAD,
    DATA_SCHEDULES,
    DATA_VACATION_WRITE,
    DEFAULT_CLOUD_MQTT_PROBE,
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
from .device_links import async_link_heads_to_rooms
from .frontend import async_register_frontend, async_unregister_frontend
from .mqtt_coverage import CoverageStats
from .mqtt_publisher import MqttPublisher
from .repairs import clear_repairs, sync_repairs
from .services import async_register_services
from .websocket_api import async_register as async_register_ws
from .writejob import JobManager

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DanfossRuntimeData:
    """Typed runtime container stored on ``entry.runtime_data``."""

    coordinator: DanfossCoordinator
    local_coordinator: DanfossLocalCoordinator | None
    mqtt_publisher: MqttPublisher | None
    jobs: JobManager
    schedules: dict[str, Any] = field(default_factory=dict)
    vacation_write: bool = False
    head_unbind: bool = False
    cloud_mqtt: bool = False
    mqtt_link: CloudMqttLink | None = None
    mqtt_coverage: CoverageStats | None = None
    mqtt_supervised_dps: frozenset[int] = field(default_factory=frozenset)
    mqtt_supervised_head: str | None = None


DanfossConfigEntry = ConfigEntry[DanfossRuntimeData]


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
    local_coordinator, gateways = await _async_setup_local_and_keys(hass, entry, coordinator)

    # MQTT publishing (optional).
    publisher = await _async_setup_mqtt(hass, entry, coordinator)

    # Cloud-MQTT live link (optional, EXPERIMENTAL). Best-effort; OFF by default. Opened by
    # ``enable_cloud_mqtt`` (write path for isolated heads: a toggle then publishes a DP — the first
    # such write must be supervised; see docs/first-write-procedure.md) and/or by
    # ``cloud_mqtt_probe`` (coverage measure; listen-only when the write option is off).
    mqtt_link, mqtt_coverage = await _async_setup_mqtt_link(
        hass, entry, coordinator, gateways=gateways
    )

    jobs = JobManager()
    schedules: dict[str, Any] = {}
    vacation_write = bool(
        entry.options.get(CONF_ENABLE_VACATION_WRITE, DEFAULT_ENABLE_VACATION_WRITE)
    )
    head_unbind = bool(entry.options.get(CONF_ENABLE_HEAD_UNBIND, DEFAULT_ENABLE_HEAD_UNBIND))
    cloud_mqtt = bool(entry.options.get(CONF_ENABLE_CLOUD_MQTT, DEFAULT_ENABLE_CLOUD_MQTT))
    trial = _supervised_trial(entry)

    entry.runtime_data = DanfossRuntimeData(
        coordinator=coordinator,
        local_coordinator=local_coordinator,
        mqtt_publisher=publisher,
        jobs=jobs,
        schedules=schedules,
        vacation_write=vacation_write,
        head_unbind=head_unbind,
        cloud_mqtt=cloud_mqtt,
        mqtt_link=mqtt_link,
        mqtt_coverage=mqtt_coverage,
        mqtt_supervised_dps=trial[DATA_MQTT_SUPERVISED_DPS],  # type: ignore[arg-type]
        mqtt_supervised_head=trial[DATA_MQTT_SUPERVISED_HEAD],  # type: ignore[arg-type]
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_COORDINATOR: coordinator,
        DATA_LOCAL: local_coordinator,
        DATA_MQTT: publisher,
        DATA_JOBS: jobs,
        DATA_SCHEDULES: schedules,
        DATA_VACATION_WRITE: vacation_write,
        DATA_HEAD_UNBIND: head_unbind,
        DATA_CLOUD_MQTT: cloud_mqtt,
        # Live MQTT link: present only when enable_cloud_mqtt or cloud_mqtt_probe is on (both OFF
        # by default). The switches treat None as "no cloud-MQTT path", and a listen-only link
        # (probe without the write option) refuses every publish.
        DATA_MQTT_LINK: mqtt_link,
        **trial,
        DATA_MQTT_COVERAGE: mqtt_coverage,
    }
    await er.async_migrate_entries(hass, entry.entry_id, _migrate_unique_id)
    _cleanup_orphaned_head_climates(hass, entry, coordinator)
    await _async_cleanup_stale_entities(
        hass, entry, coordinator, has_mqtt_link=mqtt_link is not None
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Head -> room device links (via_device_id), now that the devices exist, then on each
    # update so attach / detach follows.
    async_link_heads_to_rooms(hass, coordinator, entry.entry_id)
    sync_repairs(hass, entry.entry_id, coordinator.data)

    @callback
    def _relink_heads() -> None:
        _cleanup_orphaned_head_climates(hass, entry, coordinator)
        async_link_heads_to_rooms(hass, coordinator, entry.entry_id)
        sync_repairs(hass, entry.entry_id, coordinator.data)

    entry.async_on_unload(coordinator.async_add_listener(_relink_heads))
    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    return True


def _supervised_trial(entry: ConfigEntry) -> dict[str, object]:
    """The supervised trial of this entry: the candidate DPs opened on the cloud-MQTT write path
    (option ``cloud_mqtt_supervised_dps``, empty by default) and the ONE head they open on (option
    ``cloud_mqtt_supervised_head``, empty by default).

    Only real candidates are kept: an unknown entry, or a DP since promoted to proven, is ignored.
    Without a designated head nothing opens anywhere; with one, the candidates open on that head
    only (``mqtt_write.supervised_for``). Nothing opens unless ``enable_cloud_mqtt`` is on as well
    (the switches and numbers check both). The head is never logged."""
    chosen: set[int] = set()
    for raw in entry.options.get(CONF_CLOUD_MQTT_SUPERVISED_DPS) or ():
        try:
            chosen.add(int(raw))
        except (TypeError, ValueError):
            continue
    opened = frozenset(chosen & MQTT_CANDIDATE_DPS)
    head = str(entry.options.get(CONF_CLOUD_MQTT_SUPERVISED_HEAD) or "") or None
    if opened and entry.options.get(CONF_ENABLE_CLOUD_MQTT, DEFAULT_ENABLE_CLOUD_MQTT):
        dps = ", ".join(str(dp) for dp in sorted(opened))
        if head is None:
            _LOGGER.warning(
                "Cloud-MQTT supervised trial: DP(s) %s are listed but no trial head is "
                "designated, so nothing is open.",
                dps,
            )
        else:
            _LOGGER.warning(
                "Cloud-MQTT supervised trial open for DP(s) %s on the designated trial head "
                "only: not validated on real hardware yet, each first write must be supervised "
                "(docs/first-write-procedure.md).",
                dps,
            )
    return {DATA_MQTT_SUPERVISED_DPS: opened, DATA_MQTT_SUPERVISED_HEAD: head}


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


async def _async_setup_local_and_keys(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: DanfossCoordinator
) -> tuple[DanfossLocalCoordinator | None, dict[str, GatewayKey] | None]:
    """Prepare the local tunnel if the option is on, returning ``(local_coordinator, gateways)``.
    Best-effort: returns ``(None, None)`` on failure so the cloud starts anyway."""
    if not entry.options.get(CONF_ENABLE_LOCAL):
        return None, None
    try:
        gateways = await async_fetch_gateway_keys(coordinator.client)
    except Exception as err:  # noqa: BLE001 - le repli local ne bloque jamais le cloud
        _LOGGER.warning("Local fallback unavailable (key fetch): %s", err)
        return None, None
    if not gateways:
        _LOGGER.warning("Local fallback enabled but no gateway with a local key found.")
        return None, gateways
    manager = LocalTunnelManager(gateways)
    local = DanfossLocalCoordinator(hass, manager, coordinator, DEFAULT_LOCAL_SCAN_INTERVAL)
    # First survey in the BACKGROUND, tied to the entry (cancelled on unload and on Home Assistant
    # stop): it reads the heads one by one and can take minutes on a large site, so the entry must
    # not wait for it. Until a head has been read its preheat switch is unavailable, then each one
    # becomes available as soon as it is read.
    entry.async_create_background_task(
        hass, local.async_refresh(), name=f"{DOMAIN} first local survey"
    )
    return local, gateways


async def _async_mqtt_creds_and_gateways(
    entry: ConfigEntry,
    client: CloudClient,
    *,
    context: str,
    gateways: dict[str, GatewayKey] | None = None,
) -> tuple[MqttCredentials, dict[str, GatewayRef]] | None:
    """Build the MQTT credentials (from the integration's OWN session — no secret taken from HA
    storage) and the gateway refs. Reuses the session opened by the first refresh when uid and
    partnerIdentity are already present, otherwise logs in. Reuses ``gateways`` when already
    fetched by ``_async_setup_local_and_keys``. Returns None (logged) if the session is incomplete
    or no gateway has a local key."""
    ident = client.mqtt_identity
    sess = client.session
    if not (ident["uid"] and ident["partner_identity"] and sess["sid"] and sess["ecode"]):
        await client.async_login()
        ident = client.mqtt_identity
        sess = client.session
    if not (ident["uid"] and ident["partner_identity"] and sess["sid"] and sess["ecode"]):
        _LOGGER.warning(
            "Cloud-MQTT %s: session incomplete (uid/partnerIdentity); skipped.", context
        )
        return None
    if gateways is None:
        gateways = await async_fetch_gateway_keys(client)
    if not gateways:
        _LOGGER.warning("Cloud-MQTT %s: no gateway with a local key; skipped.", context)
        return None
    data = entry.data
    creds = build_credentials(
        region=data.get(CONF_REGION, "eu"),
        sign_key=data[CONF_SIGN_KEY],
        sid=sess["sid"],
        ecode=sess["ecode"],
        uid=ident["uid"],
        partner_identity=ident["partner_identity"],
        device_id=data[CONF_DEVICE_ID],
        ch_key=data[CONF_CH_KEY],
    )
    refs = {gw_id: GatewayRef(dev_id=gw_id, local_key=k.local_key) for gw_id, k in gateways.items()}
    return creds, refs


async def _async_setup_mqtt_link(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: DanfossCoordinator,
    *,
    gateways: dict[str, GatewayKey] | None = None,
) -> tuple[CloudMqttLink | None, CoverageStats | None]:
    """Open the live cloud-MQTT link if ``enable_cloud_mqtt`` or ``cloud_mqtt_probe`` is on (both
    OFF by default). Best-effort: returns ``(None, None)`` on failure, never blocks setup. Uses the
    integration's OWN session. One connection per session, so both options share the link.

    - ``enable_cloud_mqtt``: the link can publish, but only the isolated-head switches reach
      ``publish_dp`` (and only when a user toggles one); the first such write must be supervised
      (docs/first-write-procedure.md).
    - ``cloud_mqtt_probe``: every decoded inbound frame feeds a ``CoverageStats`` (aggregates only,
      docs/cloud-mqtt-coverage.md). Without ``enable_cloud_mqtt`` the link is LISTEN-ONLY (no send
      path) and closes itself after ``CLOUD_MQTT_PROBE_MAX_SECONDS``.

    Kill switch: turning the option(s) off reloads the entry, and the link closes on unload.

    Session rotation: the link rebuilds its credentials from the client's current session before
    each reconnection. When the broker refuses them, the link asks for a cloud refresh at once (an
    HTTP call notices an invalidated session and renews it), so the next attempt carries the renewed
    session; if the broker still refuses, the link stops for good after a few attempts
    (``mqtt_client.MAX_AUTH_REFUSALS``) and everything that depends on it is unavailable."""
    client = coordinator.client
    write = bool(entry.options.get(CONF_ENABLE_CLOUD_MQTT, DEFAULT_ENABLE_CLOUD_MQTT))
    probe = bool(entry.options.get(CONF_CLOUD_MQTT_PROBE, DEFAULT_CLOUD_MQTT_PROBE))
    if not (write or probe):
        return None, None
    coverage = CoverageStats() if probe else None
    try:
        built = await _async_mqtt_creds_and_gateways(
            entry, client, context="link", gateways=gateways
        )
        if built is None:
            return None, None

        def _fresh_creds() -> MqttCredentials:
            """Rebuild credentials from the client's current (possibly refreshed) session."""
            ident = client.mqtt_identity
            sess = client.session
            data = entry.data
            return build_credentials(
                region=data.get(CONF_REGION, "eu"),
                sign_key=data[CONF_SIGN_KEY],
                sid=sess["sid"] or "",
                ecode=sess["ecode"] or "",
                uid=ident["uid"] or "",
                partner_identity=ident["partner_identity"] or "",
                device_id=data[CONF_DEVICE_ID],
                ch_key=data[CONF_CH_KEY],
            )

        def _on_auth_refused() -> None:
            """MQTT thread -> event loop: one cloud refresh, which renews an invalidated session."""
            hass.loop.call_soon_threadsafe(
                lambda: hass.async_create_task(coordinator.async_request_refresh())
            )

        link = CloudMqttLink(
            credentials=built[0],
            gateways=built[1],
            creds_provider=_fresh_creds,
            on_auth_refused=_on_auth_refused,
            on_frame=coverage.record if coverage is not None else None,
            listen_only=not write,
        )
    except Exception as err:  # noqa: BLE001 - never break setup
        _LOGGER.warning("Cloud-MQTT link setup failed: %s", type(err).__name__)
        return None, None

    await hass.async_add_executor_job(link.start)
    if write:
        _LOGGER.warning(
            "Cloud-MQTT live link started (EXPERIMENTAL): isolated-head switches may write via "
            "MQTT. A first write must be supervised."
        )
    else:
        _LOGGER.info("Cloud-MQTT link started in listen-only mode (coverage measure).")

    async def _stop_link(_now: object = None) -> None:
        if coverage is not None and not write:
            coverage.mark_stopped()
        # loop_stop() joins the paho thread: never block the event loop.
        await hass.async_add_executor_job(link.stop)

    entry.async_on_unload(_stop_link)
    if not write:
        # A forgotten probe must not keep a broker connection open on the user's account.
        entry.async_on_unload(async_call_later(hass, CLOUD_MQTT_PROBE_MAX_SECONDS, _stop_link))
    return link, coverage


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an entry (close session, tunnel, MQTT publisher)."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        clear_repairs(hass, entry.entry_id)
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


def _live_device_keys(coordinator: DanfossCoordinator) -> set[str]:
    """Identifier values of the devices this entry provides now: heads/relays/sensors of the last
    cloud read, rooms (``group_<id>``) and homes (``home_<gid>``)."""
    keys = set(coordinator.data)
    keys |= {f"group_{group_id}" for group_id in coordinator.rooms}
    keys |= {f"home_{gid}" for gid in coordinator.holidays}
    return keys


# Stale-device removal guard-rails. Removing a device drops its entities with their customised
# ids, names and areas, and whatever refers to them; a cosmetic cleanup must never do that on a
# doubtful read. So: at most this many devices per start, or this share of the entry's devices if
# that is more. Above it nothing is removed and the user decides, device by device.
STALE_DEVICES_MAX = 3
STALE_DEVICES_MAX_SHARE = 0.05


def _homes_store(hass: HomeAssistant, entry: ConfigEntry) -> Store[dict[str, dict[str, int]]]:
    """Per entry: the homes of the last COMPLETE device list and how many devices each held."""
    return Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.homes")


async def _async_device_list_confirmed(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: DanfossCoordinator
) -> bool:
    """True if the device list of this start can be trusted to say a device is GONE.

    ``CloudClient.async_list_devices`` is tolerant: a home answering with something that is not a
    list, or missing from the homes list, just contributes no device. Its result is trusted for a
    removal only when:

    - the client reports the list complete (every home answered with a list); and
    - the picture is STABLE over two starts: the homes and the number of devices in each are
      IDENTICAL to those recorded at the previous complete start.

    A complete flag alone is not enough: a home can answer with a truncated list, non-empty but
    shorter than the real one, and nothing in a single read tells it from devices that left. So
    whenever the picture differs from the record (first start, a home that vanished or answered
    empty, a count that moved in either direction), nothing is removed and the new picture is
    recorded; a device that really left is removed at the next start, once the same picture is
    seen again. One start of delay costs nothing for a cosmetic cleanup.
    """
    client = coordinator.client
    complete = bool(getattr(client, "device_list_complete", False))
    current: dict[str, int] = dict(getattr(client, "device_list_homes", {}) or {})
    store = _homes_store(hass, entry)
    known = ((await store.async_load()) or {}).get("homes")
    if complete and current != known:
        await store.async_save({"homes": current})
    return complete and known is not None and current == known


async def _async_cleanup_stale_devices(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: DanfossCoordinator
) -> int:
    """Remove the DEVICE (and so every entity) of a head, relay or sensor gone from the account.
    Returns how many were removed.

    Room and home devices are never removed here: their presence depends on best-effort reads
    (topology, holidays) that may fail at start-up. For the others, two guard-rails:

    - the device list must be confirmed: complete, and the same picture as at the previous
      complete start (``_async_device_list_confirmed``);
    - proportion: more than ``STALE_DEVICES_MAX`` devices to remove, and more than
      ``STALE_DEVICES_MAX_SHARE`` of the entry's devices, is not a cleanup but an anomaly. Nothing
      is removed, a warning says so, and the user can delete each device from its page
      (``async_remove_config_entry_device``).
    """
    confirmed = await _async_device_list_confirmed(hass, entry, coordinator)
    dev_reg = dr.async_get(hass)
    candidates = [
        device
        for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
        if (keys := {value for domain, value in device.identifiers if domain == DOMAIN})
        and not any(k.startswith(("group_", "home_")) for k in keys)
    ]
    stale = [
        device
        for device in candidates
        if {value for domain, value in device.identifiers if domain == DOMAIN}.isdisjoint(
            coordinator.data
        )
    ]
    if not stale:
        return 0
    if not confirmed:
        _LOGGER.info(
            "%s device(s) absent from the cloud list were kept: the list is not confirmed yet "
            "(incomplete, or different from the previous start). They are removed at a later "
            "start if the list stays the same.",
            len(stale),
        )
        return 0
    limit = max(STALE_DEVICES_MAX, int(len(candidates) * STALE_DEVICES_MAX_SHARE))
    if len(stale) > limit:
        _LOGGER.warning(
            "%s of %s devices are absent from the cloud list: too many for an automatic cleanup "
            "(limit %s), nothing was removed. If they really left the account, delete them from "
            "their device page.",
            len(stale),
            len(candidates),
            limit,
        )
        return 0
    for device in stale:
        dev_reg.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
    return len(stale)


async def _async_cleanup_stale_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: DanfossCoordinator,
    *,
    has_mqtt_link: bool = False,
) -> None:
    """Remove what this entry can no longer provide, instead of leaving it "restored, unavailable"
    for the user to delete by hand (real-hardware finding, 2026-11-19: orphaned preheat switches
    and an orphaned link sensor had to be removed manually).

    Conservative, three exact cases:

    1. the DEVICE of a head, relay or sensor that is gone from the account (unbound, replaced):
       the device and all its entities, under the guard-rails of
       ``_async_cleanup_stale_devices`` (confirmed-complete list, proportion limit);
    2. the PREHEAT switches when the local tunnel option is off: they exist only through the
       tunnel. A tunnel that is enabled but failed to start keeps them (transient);
    3. the cloud-MQTT LINK sensor when the cloud-MQTT option is off and no link was opened (so a
       link opened for another reason keeps its sensor).
    """
    removed = await _async_cleanup_stale_devices(hass, entry, coordinator)

    ent_reg = er.async_get(hass)
    local_on = bool(entry.options.get(CONF_ENABLE_LOCAL))
    cloud_mqtt_on = bool(entry.options.get(CONF_ENABLE_CLOUD_MQTT, DEFAULT_ENABLE_CLOUD_MQTT))
    link_sensor_uid = f"{entry.entry_id}_cloud_mqtt_link"
    for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        stale = (
            not local_on and entity.domain == "switch" and entity.unique_id.endswith("_preheat")
        ) or (
            not cloud_mqtt_on
            and not has_mqtt_link
            and entity.domain == "binary_sensor"
            and entity.unique_id == link_sensor_uid
        )
        if stale:
            ent_reg.async_remove(entity.entity_id)
            removed += 1
    if removed:
        _LOGGER.info("Removed %s stale device(s)/entity(ies) no longer provided.", removed)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Let the user delete a device from the UI when this entry no longer provides it (a room that
    was dissolved, a head that left the account). A device that is still provided cannot be
    deleted: it would come back at the next reload."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not data:
        return False
    live = _live_device_keys(data[DATA_COORDINATOR])
    return not any(value in live for domain, value in device_entry.identifiers if domain == DOMAIN)


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change (MQTT, local, interval)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop this entry's record of known homes; on removal of the LAST entry, also clean up the
    Lovelace resource (contract §6).

    We do not clean up on a simple unload/reload (which only calls `async_unload_entry`), but only
    when no entry remains.
    """
    await _homes_store(hass, entry).async_remove()
    if not hass.config_entries.async_entries(DOMAIN):
        await async_unregister_frontend(hass)
