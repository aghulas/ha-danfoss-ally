"""Cloud room sensor placed in a Danfoss room from the panel (``sensor_room``, danfoss2mqtt).

The Companion never writes the room itself: it checks the request against ``bridge/sensor_rooms``,
publishes ``sensor_room`` on the sensor's ``/set`` only while the bridge advertises it, and shows
the new room only once ``bridge/sensor_rooms`` carries it. Synthetic data only.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.components import mqtt as mqtt_mod
from homeassistant.core import HomeAssistant

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud import websocket_api
from custom_components.danfoss_ally_cloud.companion_adapter import build_companion_store
from custom_components.danfoss_ally_cloud.companion_rooms import CompanionRoomManager
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DOMAIN
from custom_components.danfoss_ally_cloud.mqtt_companion import MqttCompanionCoordinator
from custom_components.danfoss_ally_cloud.ops_common import OperationError

SENSOR = "bf_sensor_test"
OTHER = "bf_sensor_other"
HOME = "h1"
ROOMS = [{"room_id": "71", "name": "Salle B"}, {"room_id": "70", "name": "Salle A"}]


def _sensor_descriptor(dev_id: str, name: str, set_keys: list[str] | None) -> dict:
    ext: dict = {"dev_id": dev_id, "category": "sensor", "home_id": HOME}
    if set_keys is not None:
        ext["set_keys"] = set_keys
    return {
        "ieee_address": f"0x{dev_id}",
        "friendly_name": name,
        "definition": {"vendor": "Danfoss", "model": "014G2480"},
        "danfoss": ext,
    }


def _entries(mine: str | None = None, other: str | None = None) -> dict:
    return {
        SENSOR: {"home_id": HOME, "room_id": mine, "rooms": ROOMS},
        OTHER: {"home_id": HOME, "room_id": other, "rooms": ROOMS},
    }


def _store(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    *,
    set_keys: list[str] | None = ("sensor_room",),  # type: ignore[assignment]
    entries: dict | None = None,
) -> tuple[dict, MqttCompanionCoordinator, AsyncMock]:
    pub = AsyncMock()
    monkeypatch.setattr(mqtt_mod, "async_publish", pub)
    comp = MqttCompanionCoordinator(hass, ("danfoss2mqtt",))
    keys = list(set_keys) if set_keys is not None else None
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/devices",
        json.dumps(
            [
                _sensor_descriptor(SENSOR, "Sonde Test", keys),
                _sensor_descriptor(OTHER, "Sonde Autre", []),
            ]
        ),
    )
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/holidays", json.dumps({HOME: {"name": "Maison", "active": False}})
    )
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/sensor_rooms",
        json.dumps(entries if entries is not None else _entries()),
    )
    return build_companion_store(comp, CompanionRoomManager(comp)), comp, pub


def _overview_sensor(store: dict, dev_id: str = SENSOR) -> dict:
    sensors = [s for h in ops.overview_payload(store)["homes"] for s in h["sensors"]]
    return next(s for s in sensors if s["device_id"] == dev_id)


async def test_put_in_room_publishes_and_waits_for_the_bridge(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, comp, pub = _store(hass, monkeypatch)
    res = await ops.set_sensor_room(hass, store, SENSOR, "71")
    assert res == {"sensor": SENSOR, "room_id": "71", "status": "sent"}
    pub.assert_awaited_once()
    topic, payload = pub.await_args.args[1], pub.await_args.args[2]
    assert topic == "danfoss2mqtt/Sonde Test/set"
    assert json.loads(payload) == {"sensor_room": {"room_id": "71"}}
    # Nothing optimistic: still in no room until the bridge republishes bridge/sensor_rooms.
    assert _overview_sensor(store)["cloud_room"] is None
    comp.process_mqtt_message("danfoss2mqtt/bridge/sensor_rooms", json.dumps(_entries("71")))
    assert _overview_sensor(store)["cloud_room"] == {"room_id": "71", "name": "Salle B"}


async def test_take_out_publishes_null(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _comp, pub = _store(hass, monkeypatch, entries=_entries("70"))
    res = await ops.set_sensor_room(hass, store, SENSOR, None)
    assert res["room_id"] is None
    assert json.loads(pub.await_args.args[2]) == {"sensor_room": {"room_id": None}}


@pytest.mark.parametrize(
    ("kwargs", "sensor", "room_id", "code"),
    [
        ({"set_keys": None}, SENSOR, "71", "sensor_room_unavailable"),  # older bridge
        ({"set_keys": []}, SENSOR, "71", "sensor_room_unavailable"),  # gate closed
        ({}, "ghost", "71", "unknown_sensor"),
        ({"entries": {}}, SENSOR, "71", "sensor_room_unknown"),
        ({}, SENSOR, "99", "unknown_room"),
        ({}, SENSOR, None, "no_change"),
        ({"entries": _entries("71")}, SENSOR, "71", "no_change"),
        ({"entries": _entries("70")}, SENSOR, "71", "sensor_in_other_room"),
        ({"entries": _entries(None, "71")}, SENSOR, "71", "room_has_sensor"),
    ],
)
async def test_refused_before_anything_is_published(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict,
    sensor: str,
    room_id: str | None,
    code: str,
) -> None:
    store, _comp, pub = _store(hass, monkeypatch, **kwargs)
    with pytest.raises(OperationError) as err:
        await ops.set_sensor_room(hass, store, sensor, room_id)
    assert err.value.code == code
    pub.assert_not_awaited()


async def test_publish_failure_is_reported(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _comp, pub = _store(hass, monkeypatch)
    pub.side_effect = RuntimeError("broker down")
    with pytest.raises(OperationError) as err:
        await ops.set_sensor_room(hass, store, SENSOR, "71")
    assert err.value.code == "publish_failed"


async def test_direct_cloud_store_is_refused() -> None:
    coord = SimpleNamespace(data={})
    with pytest.raises(OperationError) as err:
        await ops.set_sensor_room(None, {DATA_COORDINATOR: coord}, SENSOR, "71")  # type: ignore[arg-type]
    assert err.value.code == "sensor_room_unsupported"


async def test_overview_carries_rooms_holders_and_the_writable_flag(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, comp, _pub = _store(hass, monkeypatch, entries=_entries(None, "70"))
    sensor = _overview_sensor(store)
    assert sensor["room_writable"] is True
    assert sensor["cloud_room"] is None
    assert sensor["cloud_rooms"] == [
        {"room_id": "70", "name": "Salle A", "sensor_id": OTHER},
        {"room_id": "71", "name": "Salle B", "sensor_id": None},
    ]
    assert _overview_sensor(store, OTHER)["room_writable"] is False
    # The bridge closes its gate: read-only again.
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/devices",
        json.dumps([_sensor_descriptor(SENSOR, "Sonde Test", [])]),
    )
    assert _overview_sensor(store)["room_writable"] is False


async def test_malformed_payloads_keep_the_last_one(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, comp, _pub = _store(hass, monkeypatch, entries=_entries("71"))
    for bad in ("not json", "[]", b"\xff"):
        comp.process_mqtt_message("danfoss2mqtt/bridge/sensor_rooms", bad)
    assert _overview_sensor(store)["cloud_room"]["room_id"] == "71"
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/sensor_rooms",
        json.dumps({SENSOR: {"home_id": HOME, "room_id": "", "rooms": [{"name": "x"}, 3]}, "x": 1}),
    )
    assert comp.sensor_cloud_rooms == {SENSOR: {"home_id": HOME, "room_id": None, "rooms": []}}


async def test_sensor_without_an_entry_has_no_room_fields(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _comp, _pub = _store(hass, monkeypatch, entries={})
    assert "cloud_rooms" not in _overview_sensor(store)


class _Conn:
    def __init__(self) -> None:
        self.user = SimpleNamespace(is_admin=True)
        self.results: list = []
        self.errors: list = []

    def send_result(self, msg_id: int, payload: object) -> None:
        self.results.append((msg_id, payload))

    def send_error(self, msg_id: int, code: str, message: str) -> None:
        self.errors.append((msg_id, code, message))


async def test_websocket_set_room(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _comp, pub = _store(hass, monkeypatch)
    hass.data[DOMAIN] = {"e1": store}
    conn = _Conn()
    handler = websocket_api.ws_sensor_set_room.__wrapped__.__wrapped__
    await handler(hass, conn, {"id": 1, "sensor": SENSOR, "room_id": "71"})
    assert conn.results == [(1, {"sensor": SENSOR, "room_id": "71", "status": "sent"})]
    await handler(hass, conn, {"id": 2, "sensor": SENSOR, "room_id": "99"})
    assert conn.errors[0][:2] == (2, "unknown_room")
    assert pub.await_count == 1
