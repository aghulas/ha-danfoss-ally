"""Tests du publicateur MQTT (payloads purs + flux de publication, mqtt monkeypatché)."""

import json
from unittest.mock import AsyncMock, MagicMock

import homeassistant.components.mqtt as mqtt_mod

from custom_components.danfoss_ally_cloud.api import DanfossDevice
from custom_components.danfoss_ally_cloud.mqtt_publisher import (
    MqttPublisher,
    etat_payload,
    etat_z2m,
    nom_z2m,
)


def _dev(**kw):
    base = dict(
        id="dev-1",
        nom="Salon",
        categorie="tete",
        product_id="03wvrwpv",
        en_ligne=True,
        temperature=20.5,
        consigne=21.0,
        batterie=90.0,
        ouverture_vanne=0,
        fenetre_ouverte=False,
    )
    base.update(kw)
    return DanfossDevice(**base)


def _publisher(coordinator=None, mode="discovery"):
    return MqttPublisher(
        MagicMock(), coordinator or MagicMock(), mode, "cloud", "danfoss_ally_cloud"
    )


def test_etat_payload_exclut_none():
    dev = _dev(consigne=None)
    payload = etat_payload(dev)
    assert "consigne" not in payload
    # 0 et False sont conservés (différents de None)
    assert payload["ouverture_vanne"] == 0
    assert payload["fenetre_ouverte"] is False
    assert payload["temperature"] == 20.5


def test_discovery_configs():
    pub = _publisher()
    cfgs = pub.discovery_configs(_dev())
    topics = [c["topic"] for c in cfgs]
    assert len(cfgs) == 5  # 4 capteurs + 1 binaire
    assert "homeassistant/sensor/danfoss_dev-1_temperature/config" in topics
    assert "homeassistant/binary_sensor/danfoss_dev-1_fenetre/config" in topics
    temp = next(c["payload"] for c in cfgs if c["topic"].endswith("temperature/config"))
    assert temp["state_topic"] == "danfoss_ally_cloud/dev-1"
    assert temp["value_template"] == "{{ value_json.temperature }}"
    assert temp["availability_topic"] == "danfoss_ally_cloud/dev-1/availability"
    assert temp["device"]["identifiers"] == ["danfoss_ally_cloud_dev-1"]
    assert temp["unit_of_measurement"] == "°C"
    fen = next(c["payload"] for c in cfgs if c["topic"].endswith("fenetre/config"))
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
    assert "danfoss_ally_cloud/dev-1" in topics  # état
    assert "danfoss_ally_cloud/dev-1/availability" in topics  # disponibilité
    assert any(t.startswith("homeassistant/sensor/") for t in topics)  # discovery
    # l'état est un JSON valide
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


def test_etat_z2m_noms_proprietes():
    etat = etat_z2m(_dev(ouverture_vanne=40))
    assert etat["local_temperature"] == 20.5
    assert etat["occupied_heating_setpoint"] == 21.0
    assert etat["battery"] == 90.0
    assert etat["pi_heating_demand"] == 40
    assert etat["running_state"] == "heat"
    assert etat["window_open"] is False


def test_etat_z2m_running_state_idle():
    assert etat_z2m(_dev(ouverture_vanne=0))["running_state"] == "idle"


def test_nom_z2m_nettoie_les_topics():
    assert nom_z2m(_dev(nom="Salon/RDC+1")) == "Salon_RDC_1"
    assert nom_z2m(_dev(nom="")) == "dev-1"  # repli sur l'id


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
