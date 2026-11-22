"""End-to-end tests for the v2.x Bridge + Companion architecture (Batches 2.2 -> 2.6)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components import mqtt as mqtt_mod
from homeassistant.core import HomeAssistant

from custom_components.danfoss_ally_cloud import ops_views
from custom_components.danfoss_ally_cloud.api import DanfossDevice
from custom_components.danfoss_ally_cloud.api.bridge_daemon import (
    StandaloneDanfoss2MqttDaemon,
)
from custom_components.danfoss_ally_cloud.api.bridge_daemon import (
    main as daemon_main,
)
from custom_components.danfoss_ally_cloud.api.rooms import Room, aggregate_room
from custom_components.danfoss_ally_cloud.bridge_mqtt import Danfoss2MqttBridge
from custom_components.danfoss_ally_cloud.companion_adapter import build_companion_store
from custom_components.danfoss_ally_cloud.companion_rooms import (
    CompanionRoomConfig,
    CompanionRoomManager,
)
from custom_components.danfoss_ally_cloud.mqtt_companion import MqttCompanionCoordinator


def _head(
    dev_id: str = "h-d2m-1",
    name: str = "B-0 Chapelle 1",
    temp: float = 19.5,
    setpoint: float = 20.0,
    valve: float = 40.0,
    online: bool = True,
) -> DanfossDevice:
    return DanfossDevice(
        id=dev_id,
        name=name,
        category="head",
        product_id="03wvrwpv",
        node_id="abcd1234",
        mesh_id="gw1",
        online=online,
        temperature=temp,
        setpoint=setpoint,
        setpoints={"comfort": 20.0, "setback": 17.0},
        mode="at_home",
        state="Heat" if valve > 0 else "NoHeat",
        battery=90.0,
        valve_opening=valve,
        heat_request=valve > 0,
        window_open=False,
        window_detection=True,
        child_lock=False,
        schedule_active=True,
        preheat=True,
    )


def _sensor(dev_id: str = "s-1", name: str = "A-0 Sonde", temp: float = 20.2) -> DanfossDevice:
    return DanfossDevice(
        id=dev_id,
        name=name,
        category="sensor",
        product_id="mxzo5rhf",
        online=True,
        temperature=temp,
        humidity=48.0,
        battery=96.0,
    )


def _relay(dev_id: str = "r-1", name: str = "Boiler Relay", on: bool = True) -> DanfossDevice:
    return DanfossDevice(
        id=dev_id,
        name=name,
        category="relay",
        product_id="ypieax1h",
        online=True,
        relay_on=on,
    )


# --- Batch 2.2: Danfoss2MqttBridge -------------------------------------------------------------


async def test_batch_2_2_danfoss2mqtt_bridge_publish_and_commands(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Danfoss2MqttBridge publishes fleet + rooms and handles +/set and bridge/request/+."""
    published: dict[str, str] = {}
    subscriptions: dict[str, Any] = {}

    async def fake_publish(_hass: Any, topic: str, payload: str, **kw: Any) -> None:
        published[topic] = payload

    async def fake_subscribe(_hass: Any, topic: str, cb: Any, **kw: Any) -> Any:
        subscriptions[topic] = cb
        return lambda: subscriptions.pop(topic, None)

    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr(mqtt_mod, "async_publish", fake_publish)
    monkeypatch.setattr(mqtt_mod, "async_subscribe", fake_subscribe)

    h1 = _head()
    s1 = _sensor()
    r1 = _relay()
    topo_room = Room(
        group_id="g1", name="B-0 Chapelle", pid="03wvrwpv", home_gid="home-1", members=(h1.id,)
    )
    room_state = aggregate_room(topo_room, [h1])
    coordinator = MagicMock()
    coordinator.data = {h1.id: h1, s1.id: s1, r1.id: r1}
    coordinator.rooms = {"g1": room_state}
    coordinator._rooms_topology = {"g1": topo_room}
    coordinator.device_home = {h1.id: "home-1"}
    coordinator.holidays = {"home-1": {"active": False}}
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)

    local_coord = SimpleNamespace(settings={h1.id: {"regulation_speed": 5}})
    set_calls: list[tuple[str, dict[str, Any]]] = []

    async def on_set(dev: DanfossDevice, payload: dict[str, Any]) -> None:
        set_calls.append((dev.id, payload))
        if "occupied_heating_setpoint" in payload:
            dev.setpoint = float(payload["occupied_heating_setpoint"])

    async def on_req(action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action == "fail":
            raise RuntimeError("refused")
        return {"action": action, "received": payload.get("value")}

    bridge = Danfoss2MqttBridge(
        hass,
        coordinator,
        "danfoss2mqtt",
        local_coordinator=local_coord,
        on_device_set=on_set,
        on_bridge_request=on_req,
    )
    assert bridge.base_topic == "danfoss2mqtt"
    await bridge.async_start()

    assert published["danfoss2mqtt/bridge/state"] == "online"
    devs = json.loads(published["danfoss2mqtt/bridge/devices"])
    assert len(devs) == 3
    rooms = json.loads(published["danfoss2mqtt/bridge/rooms"])
    assert rooms[0]["group_id"] == "g1" and rooms[0]["home_id"] == "home-1"
    h1_state = json.loads(published["danfoss2mqtt/B-0 Chapelle 1"])
    assert h1_state["algorithm_scale_factor"] == 5

    # Command on <base>/<friendly_name>/set -> updates after handler completes
    await bridge._async_process_device_set(
        "danfoss2mqtt/B-0 Chapelle 1/set",
        json.dumps({"occupied_heating_setpoint": 21.5}),
    )
    assert set_calls == [(h1.id, {"occupied_heating_setpoint": 21.5})]
    assert json.loads(published["danfoss2mqtt/B-0 Chapelle 1"])["occupied_heating_setpoint"] == 21.5

    # Unknown target & invalid JSON on /set are ignored safely
    await bridge._async_process_device_set("danfoss2mqtt/Unknown/set", "{}")
    await bridge._async_process_device_set("danfoss2mqtt/B-0 Chapelle 1/set", "not-json")
    assert len(set_calls) == 1

    # Bridge RPC request -> response with transaction correlation
    await bridge._async_process_bridge_request(
        "danfoss2mqtt/bridge/request/room_set",
        json.dumps({"value": 42, "transaction": "tx-1"}),
    )
    resp = json.loads(published["danfoss2mqtt/bridge/response/room_set"])
    assert resp == {
        "status": "ok",
        "data": {"action": "room_set", "received": 42},
        "transaction": "tx-1",
    }

    # Failing RPC request & invalid JSON RPC request
    await bridge._async_process_bridge_request(
        "danfoss2mqtt/bridge/request/fail", json.dumps({"transaction": "tx-2"})
    )
    assert json.loads(published["danfoss2mqtt/bridge/response/fail"])["status"] == "error"
    await bridge._async_process_bridge_request("danfoss2mqtt/bridge/request/bad", "{bad")
    assert json.loads(published["danfoss2mqtt/bridge/response/bad"])["status"] == "error"

    await bridge.async_stop()
    assert published["danfoss2mqtt/bridge/state"] == "offline"


# --- Batches 2.3, 2.4 & 2.5: Unified Companion + Rooms + Lovelace Adapter ----------------------


async def test_batches_2_3_to_2_5_unified_companion_z2m_and_danfoss2mqtt(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Companion merges z2m + danfoss2mqtt devices, syncs 014G2480, and feeds ops_views."""
    sent_mqtt: list[tuple[str, dict[str, Any]]] = []

    async def fake_publish(_hass: Any, topic: str, payload: str, **kw: Any) -> None:
        sent_mqtt.append((topic, json.loads(payload)))

    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr(mqtt_mod, "async_subscribe", AsyncMock(return_value=lambda: None))
    monkeypatch.setattr(mqtt_mod, "async_publish", fake_publish)

    companion = MqttCompanionCoordinator(hass, prefixes=("zigbee2mqtt", "danfoss2mqtt"))
    updates = 0
    unsub = companion.async_add_listener(lambda: None)
    companion.async_add_listener(lambda: nonlocal_inc())

    def nonlocal_inc() -> None:
        nonlocal updates
        updates += 1

    await companion.async_start()

    # 1) zigbee2mqtt announces 2 Danfoss heads (014G2461), 1 Danfoss room sensor (014G2480),
    #    and 1 non-Danfoss Sonoff plug (which must be ignored).
    z2m_devices = [
        {
            "friendly_name": "A-0 Classe 1 #1",
            "ieee_address": "0x00158d0001111111",
            "definition": {"vendor": "Danfoss", "model": "014G2461"},
        },
        {
            "friendly_name": "A-0 Classe 1 #2",
            "ieee_address": "0x00158d0002222222",
            "definition": {"vendor": "Danfoss", "model": "014G2461"},
        },
        {
            "friendly_name": "A-0 Sonde Classe 1",
            "ieee_address": "0x00158d0003333333",
            "definition": {"vendor": "Danfoss", "model": "014G2480"},
        },
        {
            "friendly_name": "Prise Sonoff",
            "ieee_address": "0x9999",
            "definition": {"vendor": "SONOFF", "model": "S26R2ZB"},
        },
    ]
    companion.process_mqtt_message("zigbee2mqtt/bridge/state", "online")
    companion.process_mqtt_message("zigbee2mqtt/bridge/devices", json.dumps(z2m_devices))
    companion.process_mqtt_message(
        "zigbee2mqtt/A-0 Classe 1 #1",
        json.dumps(
            {
                "local_temperature": 21.0,
                "occupied_heating_setpoint": 20.0,
                "pi_heating_demand": 30,
                "running_state": "heat",
                "heat_required": True,
                "battery": 85,
            }
        ),
    )
    companion.process_mqtt_message(
        "zigbee2mqtt/A-0 Classe 1 #2",
        json.dumps(
            {
                "local_temperature": 21.4,
                "occupied_heating_setpoint": 20.0,
                "pi_heating_demand": 50,
                "running_state": "heat",
                "heat_required": True,
                "battery": 82,
            }
        ),
    )
    companion.process_mqtt_message(
        "zigbee2mqtt/A-0 Sonde Classe 1",
        json.dumps({"temperature": 19.6, "humidity": 52.0, "battery": 98}),
    )

    # 2) danfoss2mqtt announces 1 head + 1 native room
    d2m_head = _head("d2m-h1", "B-0 Chapelle 1", temp=18.5, setpoint=19.0, valve=0.0)
    bridge = Danfoss2MqttBridge(hass, SimpleNamespace(data={d2m_head.id: d2m_head}, rooms={}))
    companion.process_mqtt_message("danfoss2mqtt/bridge/state", '{"state": "online"}')
    companion.process_mqtt_message(
        "danfoss2mqtt/bridge/devices", json.dumps(bridge.bridge_devices_payload())
    )
    companion.process_mqtt_message(
        "danfoss2mqtt/B-0 Chapelle 1",
        json.dumps(
            {"local_temperature": 18.5, "occupied_heating_setpoint": 19.0, "pi_heating_demand": 0}
        ),
    )
    companion.process_mqtt_message(
        "danfoss2mqtt/bridge/rooms",
        json.dumps(
            [
                {
                    "group_id": "g-chapelle",
                    "name": "B-0 Chapelle",
                    "pid": "03wvrwpv",
                    "members": ["d2m-h1"],
                }
            ]
        ),
    )
    companion.process_mqtt_message(
        "danfoss2mqtt/bridge/holidays", json.dumps({"home-1": {"active": True}})
    )

    # All 4 Danfoss devices (3 on z2m + 1 on danfoss2mqtt) are in the unified fleet; Sonoff is not.
    assert set(companion.data) == {
        "0x00158d0001111111",
        "0x00158d0002222222",
        "0x00158d0003333333",
        "d2m-h1",
    }
    assert companion.bridge_online == {"zigbee2mqtt": True, "danfoss2mqtt": True}

    # 3) Batch 2.4: CompanionRoomManager groups the 2 z2m heads + 1 z2m room sensor
    room_mgr = CompanionRoomManager(companion)
    room_mgr.add_virtual_room(
        CompanionRoomConfig(
            room_id="z2m-classe-1",
            name="A-0 Classe 1",
            head_ids=["0x00158d0001111111", "0x00158d0002222222"],
            sensor_id="0x00158d0003333333",
        )
    )

    rooms = room_mgr.build_rooms()
    assert set(rooms) == {"g-chapelle", "z2m-classe-1"}
    # Virtual room temperature comes from linked 014G2480 sensor (19.6 °C), not head mean
    assert rooms["z2m-classe-1"].temperature == 19.6

    # Sync telemetry pushes external_measured_room_sensor (1960) and load_room_mean (40)
    stats = await room_mgr.async_sync_telemetry(now=100.0)
    assert stats == {"external_sensor_writes": 2, "load_mean_writes": 2}
    assert ("zigbee2mqtt/A-0 Classe 1 #1/set", {"external_measured_room_sensor": 1960}) in sent_mqtt
    assert ("zigbee2mqtt/A-0 Classe 1 #2/set", {"load_room_mean": 40}) in sent_mqtt

    # Second sync 10s later with no change is a no-op
    sent_mqtt.clear()
    assert await room_mgr.async_sync_telemetry(now=110.0) == {
        "external_sensor_writes": 0,
        "load_mean_writes": 0,
    }

    # If the 014G2480 sensor goes offline, Companion disables external sensor (-8000)
    companion.process_mqtt_message("zigbee2mqtt/A-0 Sonde Classe 1/availability", "offline")
    stats_off = await room_mgr.async_sync_telemetry(now=120.0)
    assert stats_off["external_sensor_writes"] == 2
    assert (
        "zigbee2mqtt/A-0 Classe 1 #1/set",
        {"external_measured_room_sensor": -8000},
    ) in sent_mqtt

    # Room setpoint fan-out & weekly schedule fan-out
    sent_mqtt.clear()
    assert await room_mgr.async_set_room_setpoint("z2m-classe-1", 21.0) == 2
    assert ("zigbee2mqtt/A-0 Classe 1 #1/set", {"occupied_heating_setpoint": 21.0}) in sent_mqtt
    assert ("zigbee2mqtt/A-0 Classe 1 #2/set", {"occupied_heating_setpoint": 21.0}) in sent_mqtt

    sent_mqtt.clear()
    n_sched = await room_mgr.async_set_room_schedule(
        "z2m-classe-1",
        {"monday": [{"start": "08:00", "end": "17:00"}]},
        comfort_c=21.0,
        setback_c=16.5,
    )
    assert n_sched == 2
    sched_msg = sent_mqtt[0][1]["weekly_schedule"]
    assert sched_msg["dayofweek"] == 0x02 and sched_msg["num_of_transitions"] == 3

    # Boiler demand across both bridges
    calling = room_mgr.rooms_calling_for_heat()
    assert [c["room_id"] for c in calling] == ["z2m-classe-1"]

    # 4) Batch 2.5: Companion store feeds ops_views (rooms_payload & overview_payload) directly
    store = build_companion_store(companion, room_mgr)
    rp = ops_views.rooms_payload(store)
    assert {r["id"] for r in rp["rooms"]} == {"g-chapelle", "z2m-classe-1"}
    ov = ops_views.overview_payload(store)
    assert ov["totals"]["heads"] == 3

    unsub()
    await companion.async_stop()
    assert updates > 0


# --- Batch 2.6: StandaloneDanfoss2MqttDaemon & CLI ---------------------------------------------


def test_batch_2_6_standalone_daemon_and_cli() -> None:
    """StandaloneDanfoss2MqttDaemon runs without Home Assistant over MqttTransport."""
    published: dict[str, tuple[str, bool]] = {}
    subs: dict[str, Any] = {}

    class FakeTransport:
        def publish(self, topic: str, payload: str, *, retain: bool = False) -> None:
            published[topic] = (payload, retain)

        def subscribe(self, topic: str, callback: Any) -> None:
            subs[topic] = callback

    set_received: list[tuple[str, dict[str, Any]]] = []
    daemon = StandaloneDanfoss2MqttDaemon(
        FakeTransport(),
        "danfoss2mqtt",
        on_device_set=lambda dev, p: set_received.append((dev.id, p)),
        on_bridge_request=lambda act, p: {"ok": act},
    )
    daemon.start()
    assert published["danfoss2mqtt/bridge/state"] == ("online", True)

    h = _head("h1", "Classe 1")
    r_state = aggregate_room(Room("g1", "Classe 1", "03wvrwpv", "home-1", ("h1",)), [h])
    daemon.publish_fleet([h], rooms=[r_state])
    assert "danfoss2mqtt/bridge/devices" in published
    assert "danfoss2mqtt/bridge/rooms" in published
    assert "danfoss2mqtt/Classe 1" in published

    # Simulate inbound /set and bridge/request
    subs["danfoss2mqtt/+/set"]("danfoss2mqtt/Classe 1/set", '{"occupied_heating_setpoint": 20.5}')
    assert set_received == [("h1", {"occupied_heating_setpoint": 20.5})]

    subs["danfoss2mqtt/bridge/request/+"](
        "danfoss2mqtt/bridge/request/ping", '{"transaction": "t1"}'
    )
    resp = json.loads(published["danfoss2mqtt/bridge/response/ping"][0])
    assert resp == {"status": "ok", "data": {"ok": "ping"}, "transaction": "t1"}

    daemon.stop()
    assert published["danfoss2mqtt/bridge/state"] == ("offline", True)
    assert daemon_main(["--mqtt-host", "127.0.0.1", "--mqtt-port", "1883"]) == 0


async def test_v2_edge_cases_and_migration(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Covers device migration (stale cleanup), view helpers, and daemon/bridge error branches."""
    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=False))

    # Broker unavailable at start is a safe no-op for both bridge and companion
    bridge_no_mqtt = Danfoss2MqttBridge(hass, SimpleNamespace(data={}, rooms={}))
    await bridge_no_mqtt.async_start()

    companion = MqttCompanionCoordinator(hass, prefixes=("zigbee2mqtt", "danfoss2mqtt"))
    await companion.async_start()

    # Ingest 2 devices on z2m, then re-ingest with only 1 (stale removal) and updated metadata
    d1 = {
        "friendly_name": "H1",
        "ieee_address": "0x1111",
        "definition": {"vendor": "Danfoss", "model": "014G2461"},
    }
    d2 = {
        "friendly_name": "H2",
        "ieee_address": "0x2222",
        "definition": {"vendor": "Danfoss", "model": "014G2461"},
    }
    companion.process_mqtt_message("zigbee2mqtt/bridge/devices", json.dumps([d1, d2, "skip"]))
    assert set(companion.data) == {"0x1111", "0x2222"}

    # Re-publish bridge/devices with only d1 (renamed) -> d2 is removed
    d1_renamed = {**d1, "friendly_name": "H1_bis"}
    companion.process_mqtt_message("zigbee2mqtt/bridge/devices", json.dumps([d1_renamed]))
    assert set(companion.data) == {"0x1111"}
    assert companion.data["0x1111"].name == "H1_bis"

    # Malformed payloads on bridge topics & device topics are ignored safely
    for topic, bad in (
        ("other/topic", "{}"),
        ("zigbee2mqtt/bridge/state", ""),
        ("zigbee2mqtt/bridge/state", "invalid"),
        ("zigbee2mqtt/bridge/devices", "{bad"),
        ("zigbee2mqtt/bridge/devices", '{"not": "a list"}'),
        ("zigbee2mqtt/bridge/rooms", "{bad"),
        ("zigbee2mqtt/bridge/rooms", '{"not": "a list"}'),
        ("zigbee2mqtt/bridge/holidays", "{bad"),
        ("zigbee2mqtt/bridge/holidays", "[1, 2]"),
        ("zigbee2mqtt/bridge/other", "{}"),
        ("zigbee2mqtt/H1_bis/set", "{}"),
        ("zigbee2mqtt/sub/nested/availability", "online"),
        ("zigbee2mqtt/H1_bis", "{bad"),
        ("zigbee2mqtt/H1_bis", "[1, 2]"),
        ("zigbee2mqtt/Unknown", '{"local_temperature": 20}'),
    ):
        companion.process_mqtt_message(topic, bad)

    # Unknown device on async_send_device_set / async_send_raw_device_set
    with pytest.raises(KeyError):
        await companion.async_send_device_set("missing", setpoint=20.0)
    with pytest.raises(KeyError):
        await companion.async_send_raw_device_set("missing", {})

    # CompanionRoomManager edge cases: remove_virtual_room, unknown room, invalid day, 00:00 window
    room_mgr = CompanionRoomManager(companion)
    room_mgr.add_virtual_room(
        CompanionRoomConfig(room_id="r-empty", name="Empty", head_ids=["ghost"])
    )
    assert "r-empty" not in room_mgr.build_rooms()
    room_mgr.remove_virtual_room("r-empty")

    room_mgr.add_virtual_room(CompanionRoomConfig(room_id="r1", name="R1", head_ids=["0x1111"]))
    with pytest.raises(KeyError):
        await room_mgr.async_set_room_setpoint("unknown", 20.0)
    with pytest.raises(KeyError):
        await room_mgr.async_set_room_schedule("unknown", {})
    with pytest.raises(ValueError, match="Invalid day"):
        await room_mgr.async_set_room_schedule("r1", {"funday": []})

    monkeypatch.setattr(mqtt_mod, "async_publish", AsyncMock())
    await room_mgr.async_set_room_schedule("r1", {"monday": [{"start": "00:00", "end": "24:00"}]})

    # CompanionCoordinatorView helpers
    store = build_companion_store(companion, room_mgr)
    view = store["coordinator"]
    assert view.grouped_ids == {"0x1111"}
    assert view.room_retired("r1") is False and view.room_retired("missing") is True
    assert view.home_of("missing") is None
    view.device_home["0x1111"] = "custom-home"
    assert view.head_home("0x1111") == "custom-home"
    unsub = view.async_add_listener(lambda: None)
    unsub()

    # StandaloneDanfoss2MqttDaemon error branches
    published: dict[str, str] = {}

    class SimpleTransport:
        def publish(self, topic: str, payload: str, *, retain: bool = False) -> None:
            published[topic] = payload

        def subscribe(self, topic: str, callback: Any) -> None:
            pass

    daemon_bare = StandaloneDanfoss2MqttDaemon(SimpleTransport())
    assert daemon_bare.base_topic == "danfoss2mqtt"
    daemon_bare.publish_fleet(
        [
            _relay("r-none", on=False),
            DanfossDevice(id="r-null", name="RN", category="relay", relay_on=None),
        ],
        local_attrs={},
    )
    daemon_bare._handle_set("danfoss2mqtt/x/set", "{}")  # no on_device_set configured
    daemon_bare._handle_bridge_request("danfoss2mqtt/bridge/request/act", "{bad")
    assert json.loads(published["danfoss2mqtt/bridge/response/act"])["status"] == "error"
    daemon_bare._handle_bridge_request("danfoss2mqtt/bridge/request/act", '{"transaction": "t"}')
    assert json.loads(published["danfoss2mqtt/bridge/response/act"])["status"] == "error"

    def fail_req(_act: str, _p: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("boom")

    daemon_err = StandaloneDanfoss2MqttDaemon(
        SimpleTransport(),
        on_device_set=lambda _d, _p: None,
        on_bridge_request=fail_req,
    )
    daemon_err.publish_fleet([_head("h1", "Classe 1")])
    daemon_err._handle_set("wrong/topic", "{}")
    daemon_err._handle_set("danfoss2mqtt/Unknown/set", "{}")
    daemon_err._handle_set("danfoss2mqtt/Classe 1/set", "{bad")
    daemon_err._handle_set("danfoss2mqtt/Classe 1/set", "[1, 2]")
    daemon_err._handle_bridge_request("wrong/topic", "{}")
    daemon_err._handle_bridge_request("danfoss2mqtt/bridge/request/act", "[1, 2]")
    daemon_err._handle_bridge_request("danfoss2mqtt/bridge/request/act", "{}")
    assert json.loads(published["danfoss2mqtt/bridge/response/act"])["error"] == "boom"


async def test_step_1_companion_config_flow_setup_unload_and_storage(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Companion MQTT config flow, HA entry setup/unload, and persistent virtual rooms Store."""
    from homeassistant.config_entries import SOURCE_USER
    from homeassistant.data_entry_flow import FlowResultType
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.danfoss_ally_cloud.const import (
        CONF_CONNECTION_MODE,
        CONF_MQTT_PREFIXES,
        CONNECTION_MODE_MQTT_COMPANION,
        DOMAIN,
    )

    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr(mqtt_mod, "async_subscribe", AsyncMock(return_value=lambda: None))
    monkeypatch.setattr(mqtt_mod, "async_publish", AsyncMock())

    # 1) Config flow via SOURCE_USER menu -> companion
    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert menu["type"] is FlowResultType.MENU
    assert menu["menu_options"] == ["companion", "cloud"]
    init = await hass.config_entries.flow.async_configure(
        menu["flow_id"], {"next_step_id": "companion"}
    )
    assert init["type"] is FlowResultType.FORM
    assert init["step_id"] == "companion"
    # Empty prefixes rejected
    res_bad = await hass.config_entries.flow.async_configure(
        init["flow_id"],
        {CONF_MQTT_PREFIXES: " , "},
    )
    assert res_bad["type"] is FlowResultType.FORM
    assert res_bad["step_id"] == "companion"
    assert res_bad["errors"] == {"base": "empty_prefixes"}

    # Valid prefixes create Companion entry
    res_ok = await hass.config_entries.flow.async_configure(
        init["flow_id"],
        {CONF_MQTT_PREFIXES: "zigbee2mqtt, danfoss2mqtt"},
    )
    assert res_ok["type"] is FlowResultType.CREATE_ENTRY
    assert res_ok["data"] == {
        CONF_CONNECTION_MODE: CONNECTION_MODE_MQTT_COMPANION,
        CONF_MQTT_PREFIXES: ["zigbee2mqtt", "danfoss2mqtt"],
    }

    # 2) Persistent virtual rooms Store + async_setup_entry / async_unload_entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_MODE: CONNECTION_MODE_MQTT_COMPANION,
            CONF_MQTT_PREFIXES: ["zigbee2mqtt", "danfoss2mqtt"],
        },
        unique_id="mqtt_companion:zigbee2mqtt,danfoss2mqtt",
    )
    entry.add_to_hass(hass)

    # Pre-seed storage with 1 virtual room to verify reload on setup
    pre_mgr = CompanionRoomManager(MqttCompanionCoordinator(hass))
    pre_mgr.add_virtual_room(
        CompanionRoomConfig(
            room_id="z2m-room-1",
            name="Classe Z2M",
            head_ids=["0x1111"],
            sensor_id="0x2222",
        )
    )
    await pre_mgr.async_save(hass, entry.entry_id)

    monkeypatch.setattr("custom_components.danfoss_ally_cloud.async_register_frontend", AsyncMock())
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    store = hass.data[DOMAIN][entry.entry_id]
    assert "z2m-room-1" in store["room_manager"].virtual_rooms
    assert store["room_manager"].virtual_rooms["z2m-room-1"].sensor_id == "0x2222"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_companion_climate_set_temperature_and_attributes(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Companion climate entities report mqtt_companion write_path and publish /set on Mosquitto."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.danfoss_ally_cloud.climate import DanfossHeadClimate

    pub = AsyncMock()
    monkeypatch.setattr(mqtt_mod, "async_publish", pub)

    comp = MqttCompanionCoordinator(hass, prefixes=("zigbee2mqtt", "danfoss2mqtt"))
    comp.process_mqtt_message(
        "zigbee2mqtt/bridge/devices",
        json.dumps(
            [
                {
                    "ieee_address": "0x842712fffe86dfbd",
                    "friendly_name": "Room Z2M",
                    "definition": {"vendor": "Danfoss", "model": "014G2461"},
                }
            ]
        ),
    )
    comp.process_mqtt_message(
        "zigbee2mqtt/Room Z2M",
        json.dumps(
            {
                "local_temperature": 18.5,
                "occupied_heating_setpoint": 19.0,
                "min_heat_setpoint_limit": 5.0,
                "max_heat_setpoint_limit": 24.0,
                "running_state": "heat",
            }
        ),
    )

    mgr = CompanionRoomManager(comp)
    store = build_companion_store(comp, mgr)
    entity = DanfossHeadClimate(store["coordinator"], "0x842712fffe86dfbd")

    attrs = entity.extra_state_attributes
    assert attrs["write_path"] == "mqtt_companion"
    assert attrs["mqtt_bridge"] == "zigbee2mqtt"

    await entity.async_set_temperature(temperature=20.5)
    pub.assert_awaited_once()
    _hass, topic, payload = pub.call_args.args[:3]
    assert topic == "zigbee2mqtt/Room Z2M/set"
    assert json.loads(payload) == {"occupied_heating_setpoint": 20.5}

    with pytest.raises(HomeAssistantError, match="refused"):
        await entity.async_set_temperature(temperature=30.0)


async def test_companion_switch_number_and_room_services(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Companion switch/number writes and companion_set_room / sync / delete services."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.danfoss_ally_cloud.const import (
        CONF_CONNECTION_MODE,
        CONF_MQTT_PREFIXES,
        CONNECTION_MODE_MQTT_COMPANION,
        DOMAIN,
    )
    from custom_components.danfoss_ally_cloud.number import HEAD_BOUNDS, DanfossHeadBound
    from custom_components.danfoss_ally_cloud.switch import SWITCHES, DanfossSwitch

    pub = AsyncMock()
    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr(mqtt_mod, "async_subscribe", AsyncMock(return_value=lambda: None))
    monkeypatch.setattr(mqtt_mod, "async_publish", pub)
    monkeypatch.setattr("custom_components.danfoss_ally_cloud.async_register_frontend", AsyncMock())

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_MODE: CONNECTION_MODE_MQTT_COMPANION,
            CONF_MQTT_PREFIXES: ["zigbee2mqtt"],
        },
        unique_id="mqtt_companion:zigbee2mqtt",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    store = hass.data[DOMAIN][entry.entry_id]
    comp: MqttCompanionCoordinator = store["companion"]
    comp.process_mqtt_message(
        "zigbee2mqtt/bridge/devices",
        json.dumps(
            [
                {
                    "ieee_address": "0x842712fffe86dfbd",
                    "friendly_name": "Chapelle-1",
                    "definition": {"vendor": "Danfoss", "model": "014G2461"},
                },
                {
                    "ieee_address": "0xa4c138f86da7457d",
                    "friendly_name": "Chapelle-Sensor",
                    "definition": {"vendor": "Danfoss", "model": "014G2480"},
                },
            ]
        ),
    )
    comp.process_mqtt_message(
        "zigbee2mqtt/Chapelle-Sensor",
        json.dumps({"temperature": 19.25, "humidity": 50.0, "battery": 95}),
    )

    # 1) Switch write (child_lock)
    sw = DanfossSwitch(store["coordinator"], "0x842712fffe86dfbd", SWITCHES[0], None, None, False)
    assert sw.extra_state_attributes["write_path"] == "mqtt_companion"
    await sw.async_turn_on()
    assert json.loads(pub.call_args.args[2]) == {"keypad_lockout": "lock"}

    # 2) Number write (upper bound)
    num = DanfossHeadBound(store["coordinator"], "0x842712fffe86dfbd", HEAD_BOUNDS[0], None)
    assert num.extra_state_attributes["write_path"] == "mqtt_companion"
    await num.async_set_native_value(23.5)
    assert json.loads(pub.call_args.args[2]) == {"max_heat_setpoint_limit": 23.5}

    # 3) Virtual room services (set -> sync -> delete)
    pub.reset_mock()
    res = await hass.services.async_call(
        DOMAIN,
        "companion_set_room",
        {
            "room_id": "chapelle",
            "name": "B-0 Chapelle",
            "head_ids": ["0x842712fffe86dfbd"],
            "sensor_id": "0xa4c138f86da7457d",
        },
        blocking=True,
        return_response=True,
    )
    assert res["room_id"] == "chapelle"
    assert "chapelle" in store["room_manager"].virtual_rooms
    # Telemetry sync pushed external_measured_room_sensor=1925 to Chapelle-1
    assert any(
        c.args[1] == "zigbee2mqtt/Chapelle-1/set"
        and json.loads(c.args[2]).get("external_measured_room_sensor") == 1925
        for c in pub.call_args_list
    )

    sync_res = await hass.services.async_call(
        DOMAIN, "companion_sync_rooms", {}, blocking=True, return_response=True
    )
    assert sync_res == {"synced": 1}

    del_res = await hass.services.async_call(
        DOMAIN,
        "companion_delete_room",
        {"room_id": "chapelle"},
        blocking=True,
        return_response=True,
    )
    assert del_res == {"room_id": "chapelle", "removed": True}
    assert "chapelle" not in store["room_manager"].virtual_rooms

    assert await hass.config_entries.async_unload(entry.entry_id)
