"""Relay room linkage from the panel through the danfoss2mqtt bridge (``room_link``).

The Companion never writes the linkage itself: it checks the request, publishes ``room_link`` on
the relay's ``/set`` only while the bridge advertises it, and shows the new state only once
``bridge/relays`` carries it. Synthetic data only.
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

RELAY = "bf_relay_test"


def _relay_descriptor(set_keys: list[str] | None) -> dict:
    ext: dict = {"dev_id": RELAY, "category": "relay"}
    if set_keys is not None:
        ext["set_keys"] = set_keys
    return {
        "ieee_address": f"0x{RELAY}",
        "friendly_name": "Relais Test",
        "definition": {"vendor": "Danfoss", "model": "014G2400"},
        "danfoss": ext,
    }


def _rooms(*linked: bool) -> list[dict]:
    return [
        {"room_id": str(70 + i), "name": f"Salle {i}", "linked": flag}
        for i, flag in enumerate(linked)
    ]


def _store(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    *,
    set_keys: list[str] | None = ("room_link",),  # type: ignore[assignment]
    rooms: list[dict] | None = None,
) -> tuple[dict, MqttCompanionCoordinator, AsyncMock]:
    pub = AsyncMock()
    monkeypatch.setattr(mqtt_mod, "async_publish", pub)
    comp = MqttCompanionCoordinator(hass, ("danfoss2mqtt",))
    keys = list(set_keys) if set_keys is not None else None
    comp.process_mqtt_message("danfoss2mqtt/bridge/devices", json.dumps([_relay_descriptor(keys)]))
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/holidays", json.dumps({"h1": {"name": "Maison", "active": False}})
    )
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/relays",
        json.dumps({RELAY: rooms if rooms is not None else _rooms(True, False, True)}),
    )
    return build_companion_store(comp, CompanionRoomManager(comp)), comp, pub


def _overview_relay(store: dict) -> dict:
    relays = [r for h in ops.overview_payload(store)["homes"] for r in h["relays"]]
    return next(r for r in relays if r["device_id"] == RELAY)


async def test_link_publishes_room_link_and_state_waits_for_the_bridge(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, comp, pub = _store(hass, monkeypatch)
    res = await ops.link_relay_room(hass, store, RELAY, "71", True)
    assert res == {"relay": RELAY, "room_id": "71", "linked": True, "status": "sent"}
    pub.assert_awaited_once()
    topic, payload = pub.await_args.args[1], pub.await_args.args[2]
    assert topic == "danfoss2mqtt/Relais Test/set"
    assert json.loads(payload) == {"room_link": {"room_id": "71", "linked": True}}
    # Nothing optimistic: the room stays unlinked until the bridge republishes bridge/relays.
    room = next(r for r in _overview_relay(store)["rooms"] if r["room_id"] == "71")
    assert room["linked"] is False
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/relays", json.dumps({RELAY: _rooms(True, True, True)})
    )
    room = next(r for r in _overview_relay(store)["rooms"] if r["room_id"] == "71")
    assert room["linked"] is True


async def test_unlink_publishes(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _comp, pub = _store(hass, monkeypatch)
    await ops.link_relay_room(hass, store, RELAY, "72", False)
    assert json.loads(pub.await_args.args[2]) == {"room_link": {"room_id": "72", "linked": False}}


@pytest.mark.parametrize(
    ("kwargs", "relay", "room_id", "linked", "code"),
    [
        ({"set_keys": None}, RELAY, "71", True, "relay_link_unavailable"),  # older bridge
        ({"set_keys": []}, RELAY, "71", True, "relay_link_unavailable"),  # gate closed
        ({}, "ghost", "71", True, "unknown_relay"),
        ({}, RELAY, "99", True, "unknown_room"),
        ({}, RELAY, "70", True, "no_change"),
        ({"rooms": _rooms(True, False)}, RELAY, "70", False, "last_linked_room"),
    ],
)
async def test_refused_before_anything_is_published(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict,
    relay: str,
    room_id: str,
    linked: bool,
    code: str,
) -> None:
    store, _comp, pub = _store(hass, monkeypatch, **kwargs)
    with pytest.raises(OperationError) as err:
        await ops.link_relay_room(hass, store, relay, room_id, linked)
    assert err.value.code == code
    pub.assert_not_awaited()


async def test_publish_failure_is_reported(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _comp, pub = _store(hass, monkeypatch)
    pub.side_effect = RuntimeError("broker down")
    with pytest.raises(OperationError) as err:
        await ops.link_relay_room(hass, store, RELAY, "71", True)
    assert err.value.code == "publish_failed"


async def test_direct_cloud_store_is_refused() -> None:
    coord = SimpleNamespace(data={}, relay_rooms={})
    with pytest.raises(OperationError) as err:
        await ops.link_relay_room(None, {DATA_COORDINATOR: coord}, RELAY, "71", True)  # type: ignore[arg-type]
    assert err.value.code == "relay_link_unsupported"


async def test_overview_lists_every_room_and_the_writable_flag(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, comp, _pub = _store(hass, monkeypatch)
    relay = _overview_relay(store)
    assert relay["room_link_writable"] is True
    assert [(r["room_id"], r["linked"]) for r in relay["rooms"]] == [
        ("70", True),
        ("71", False),
        ("72", True),
    ]
    assert relay["linked_rooms"] == 2
    # The bridge closes its gate: read-only again.
    comp.process_mqtt_message("danfoss2mqtt/bridge/devices", json.dumps([_relay_descriptor([])]))
    assert _overview_relay(store)["room_link_writable"] is False


class _Conn:
    def __init__(self) -> None:
        self.user = SimpleNamespace(is_admin=True)
        self.results: list = []
        self.errors: list = []

    def send_result(self, msg_id: int, payload: object) -> None:
        self.results.append((msg_id, payload))

    def send_error(self, msg_id: int, code: str, message: str) -> None:
        self.errors.append((msg_id, code, message))


async def test_websocket_link_room(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _comp, pub = _store(hass, monkeypatch)
    hass.data[DOMAIN] = {"e1": store}
    conn = _Conn()
    handler = websocket_api.ws_relay_link_room.__wrapped__.__wrapped__
    await handler(hass, conn, {"id": 1, "relay": RELAY, "room_id": "71", "linked": True})
    assert conn.results == [
        (1, {"relay": RELAY, "room_id": "71", "linked": True, "status": "sent"})
    ]
    await handler(hass, conn, {"id": 2, "relay": RELAY, "room_id": "99", "linked": True})
    assert conn.errors[0][:2] == (2, "unknown_room")
    assert pub.await_count == 1
