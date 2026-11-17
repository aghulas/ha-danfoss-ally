"""MQTT publisher tests (pure payloads + publish flow, mqtt monkeypatched)."""

import json
from unittest.mock import AsyncMock, MagicMock

import homeassistant.components.mqtt as mqtt_mod

from custom_components.danfoss_ally_cloud.api import DanfossDevice
from custom_components.danfoss_ally_cloud.mqtt_publisher import (
    MqttPublisher,
    name_z2m,
    state_payload,
    state_z2m,
)


def _dev(**kw):
    base = dict(
        id="dev-1",
        name="Salon",
        category="head",
        product_id="03wvrwpv",
        online=True,
        temperature=20.5,
        setpoint=21.0,
        battery=90.0,
        valve_opening=0,
        window_open=False,
    )
    base.update(kw)
    return DanfossDevice(**base)


def _publisher(coordinator=None, mode="discovery"):
    return MqttPublisher(
        MagicMock(), coordinator or MagicMock(), mode, "cloud", "danfoss_ally_cloud"
    )


def test_state_payload_excludes_none():
    dev = _dev(setpoint=None)
    payload = state_payload(dev)
    assert "setpoint" not in payload
    # 0 and False are kept (different from None)
    assert payload["valve_opening"] == 0
    assert payload["window_open"] is False
    assert payload["temperature"] == 20.5


def test_discovery_configs():
    pub = _publisher()
    cfgs = pub.discovery_configs(_dev())
    topics = [c["topic"] for c in cfgs]
    assert len(cfgs) == 5  # 4 capteurs + 1 binaire
    assert "homeassistant/sensor/danfoss_dev-1_temperature/config" in topics
    assert "homeassistant/binary_sensor/danfoss_dev-1_window/config" in topics
    temp = next(c["payload"] for c in cfgs if c["topic"].endswith("temperature/config"))
    assert temp["state_topic"] == "danfoss_ally_cloud/dev-1"
    assert temp["value_template"] == "{{ value_json.temperature }}"
    assert temp["availability_topic"] == "danfoss_ally_cloud/dev-1/availability"
    assert temp["device"]["identifiers"] == ["danfoss_ally_cloud_dev-1"]
    assert temp["unit_of_measurement"] == "°C"
    fen = next(c["payload"] for c in cfgs if c["topic"].endswith("window/config"))
    assert fen["payload_on"] == "ON" and fen["payload_off"] == "OFF"


async def test_publish_flow(monkeypatch):
    publie = AsyncMock()
    monkeypatch.setattr(mqtt_mod, "async_publish", publie)
    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))

    coordinator = MagicMock()
    coordinator.data = {"dev-1": _dev()}
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    pub = _publisher(coordinator)
    await pub.async_start()

    topics = [c.args[1] for c in publie.await_args_list]
    assert "danfoss_ally_cloud/dev-1" in topics  # state
    assert "danfoss_ally_cloud/dev-1/availability" in topics  # availability
    assert any(t.startswith("homeassistant/sensor/") for t in topics)  # discovery
    # the state is valid JSON
    etat = next(
        c.args[2] for c in publie.await_args_list if c.args[1] == "danfoss_ally_cloud/dev-1"
    )
    assert json.loads(etat)["temperature"] == 20.5
    coordinator.async_add_listener.assert_called_once()


async def test_publish_off_si_broker_absent(monkeypatch):
    publie = AsyncMock()
    monkeypatch.setattr(mqtt_mod, "async_publish", publie)
    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=False))
    coordinator = MagicMock()
    coordinator.data = {"dev-1": _dev()}
    pub = _publisher(coordinator)
    await pub.async_start()
    publie.assert_not_awaited()


# --- mode zigbee2mqtt -------------------------------------------------------------------------


def test_state_z2m_property_names():
    etat = state_z2m(_dev(valve_opening=40))
    assert etat["local_temperature"] == 20.5
    assert etat["occupied_heating_setpoint"] == 21.0
    assert etat["battery"] == 90.0
    assert etat["pi_heating_demand"] == 40
    assert etat["running_state"] == "heat"
    assert etat["window_open"] is False


def test_state_z2m_running_state_idle():
    assert state_z2m(_dev(valve_opening=0))["running_state"] == "idle"


def test_name_z2m_cleans_topics():
    assert name_z2m(_dev(name="Salon/RDC+1")) == "Salon_RDC_1"
    assert name_z2m(_dev(name="")) == "dev-1"  # repli sur l'id


def test_device_z2m_descripteur():
    d = _publisher().device_z2m(_dev(node_id="abc123"))
    assert d["friendly_name"] == "Salon"
    assert d["ieee_address"] == "0xabc123"
    assert d["definition"]["vendor"] == "Danfoss"
    assert any(e["property"] == "occupied_heating_setpoint" for e in d["definition"]["exposes"])


async def test_publish_flow_z2m(monkeypatch):
    publie = AsyncMock()
    monkeypatch.setattr(mqtt_mod, "async_publish", publie)
    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    coordinator = MagicMock()
    coordinator.data = {"dev-1": _dev()}
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    pub = _publisher(coordinator, mode="zigbee2mqtt")
    await pub.async_start()

    topics = [c.args[1] for c in publie.await_args_list]
    assert "danfoss_ally_cloud/bridge/state" in topics
    assert "danfoss_ally_cloud/bridge/devices" in topics
    assert "danfoss_ally_cloud/Salon" in topics
    assert "danfoss_ally_cloud/Salon/availability" in topics
    etat = next(
        c.args[2] for c in publie.await_args_list if c.args[1] == "danfoss_ally_cloud/Salon"
    )
    assert json.loads(etat)["local_temperature"] == 20.5
