"""Tests des entités switch (coordinateur canard, sans démarrer Home Assistant).

async_setup_entry et l'écriture pré-chauffage (self.hass.async_add_executor_job) relèvent du
harnais hass et sont couverts ailleurs ; ici on teste la logique d'état et l'écriture gardée.
"""

from custom_components.danfoss_ally_cloud import switch as switch_mod
from custom_components.danfoss_ally_cloud.switch import (
    SWITCHES,
    DanfossPreheat,
    DanfossSwitch,
)

from .common import tete


class _FakeCloudCoord:
    def __init__(self, data, client=None, last_update_success=True):
        self.data = data
        self.client = client
        self.last_update_success = last_update_success
        self.refreshed = False

    def group_of(self, head_id):
        return None

    async def async_request_refresh(self):
        self.refreshed = True


class _FakeLocalCoord:
    def __init__(self, data, manager=None, last_update_success=True):
        self.data = data
        self.manager = manager
        self.last_update_success = last_update_success


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def async_write_setting(self, dev_id, pid, dps):
        self.calls.append((dev_id, pid, dps))


def _verrou_desc():
    return next(d for d in SWITCHES if d.key == "verrou_enfant")


async def test_switch_is_on_et_available():
    dev = tete(verrouillage=True)
    coord = _FakeCloudCoord({dev.id: dev})
    sw = DanfossSwitch(coord, dev.id, _verrou_desc())
    assert sw.is_on is True
    assert sw.available is True


async def test_switch_is_on_none_si_absent():
    coord = _FakeCloudCoord({})
    sw = DanfossSwitch(coord, "absent", _verrou_desc())
    assert sw.is_on is None
    assert sw.available is False


async def test_switch_turn_on_ecrit_et_rafraichit():
    dev = tete(verrouillage=False)
    client = _FakeClient()
    coord = _FakeCloudCoord({dev.id: dev}, client=client)
    sw = DanfossSwitch(coord, dev.id, _verrou_desc())
    await sw.async_turn_on()
    assert client.calls == [(dev.id, dev.product_id, {"30": True})]
    assert coord.refreshed is True


async def test_switch_turn_off():
    dev = tete(verrouillage=True)
    client = _FakeClient()
    coord = _FakeCloudCoord({dev.id: dev}, client=client)
    sw = DanfossSwitch(coord, dev.id, _verrou_desc())
    await sw.async_turn_off()
    assert client.calls[-1] == (dev.id, dev.product_id, {"30": False})


async def test_switch_turn_on_sans_appareil_ne_fait_rien():
    client = _FakeClient()
    coord = _FakeCloudCoord({}, client=client)
    sw = DanfossSwitch(coord, "absent", _verrou_desc())
    await sw.async_turn_on()
    assert client.calls == []


def test_preheat_is_on_et_available():
    dev = tete()
    cloud = _FakeCloudCoord({dev.id: dev})
    local = _FakeLocalCoord({dev.id: True})
    ph = DanfossPreheat(local, cloud, dev.id)
    assert ph.is_on is True
    assert ph.available is True
    assert ph.device_info["model"] == dev.product_id


def test_preheat_indisponible_sans_valeur_locale():
    dev = tete()
    cloud = _FakeCloudCoord({dev.id: dev})
    local = _FakeLocalCoord({})  # pas encore de relevé fiable
    ph = DanfossPreheat(local, cloud, dev.id)
    assert ph.available is False
    assert ph.is_on is None


def test_preheat_indisponible_si_tete_hors_ligne():
    dev = tete(en_ligne=False)
    cloud = _FakeCloudCoord({dev.id: dev})
    local = _FakeLocalCoord({dev.id: False})
    ph = DanfossPreheat(local, cloud, dev.id)
    assert ph.available is False


def test_switches_catalogue_non_vide():
    assert {d.key for d in switch_mod.SWITCHES} == {"verrou_enfant", "detection_fenetre"}


async def test_preheat_ecrire_sans_appareil_ne_fait_rien():
    # Tête disparue du cache cloud : l'écriture (turn_on) sort avant toute I/O, sans hass.
    cloud = _FakeCloudCoord({})
    local = _FakeLocalCoord({})
    ph = DanfossPreheat(local, cloud, "absent")
    await ph.async_turn_on()  # garde-fou : dev None -> return
