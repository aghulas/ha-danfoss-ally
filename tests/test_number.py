"""number platform: room setpoints (comfort, setback) - durable path-1a write (R3)."""

from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.danfoss_ally_cloud import number
from custom_components.danfoss_ally_cloud.api.rooms import RoomState
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DOMAIN
from custom_components.danfoss_ally_cloud.number import SETPOINTS, DanfossRoomSetpoint


class _FakeClient:
    def __init__(self, exc=None):
        self.calls = []
        self._exc = exc

    async def async_set_group_setpoint(self, group_id, pid, dps, *, repush=True):
        self.calls.append((group_id, pid, dps, repush))
        if self._exc is not None:
            raise self._exc


class _FakeCoord:
    def __init__(self, rooms=None, client=None):
        self.rooms = rooms or {}
        self.client = client
        self.last_update_success = True
        self.refreshed = False
        self.commanded: list[str] = []
        self.members = {"77": ("h1", "h2")}

    def room_members(self, group_id):
        return self.members.get(group_id, ())

    def note_commanded(self, head_ids):
        self.commanded.extend(head_ids)

    async def async_request_refresh(self):
        self.refreshed = True


def _room(**kw) -> RoomState:
    base = dict(
        group_id="77",
        name="Salle",
        pid="03wvrwpv",
        head_count=2,
        online=True,
        temperature=19.5,
        setpoint=6.0,
        setpoints={"comfort": 6.0, "setback": 5.0},
        mode="at_home",
        heating=True,
        min_setpoint=5.0,
        max_setpoint=35.0,
    )
    base.update(kw)
    return RoomState(**base)


def _num(desc_key, room=None, client=None):
    room = room or _room()
    coord = _FakeCoord(rooms={room.group_id: room}, client=client)
    desc = next(d for d in SETPOINTS if d.key == desc_key)
    return DanfossRoomSetpoint(coord, room.group_id, desc), coord


async def _setup(room):
    coord = _FakeCoord(rooms={room.group_id: room})
    hass = SimpleNamespace(data={DOMAIN: {"e1": {DATA_COORDINATOR: coord}}})
    entry = SimpleNamespace(entry_id="e1")
    ajoutees = []
    await number.async_setup_entry(hass, entry, ajoutees.append)
    return ajoutees[0]


async def test_setup_creates_comfort_and_setback_verified_product():
    ents = await _setup(_room())
    assert {e.entity_description.key for e in ents} == {"comfort_setpoint", "setback_setpoint"}
    assert {e.unique_id for e in ents} == {"77_comfort_setpoint", "77_setback_setpoint"}


async def test_setup_aucune_pour_produit_non_verifie():
    assert await _setup(_room(pid="autre")) == []


def test_lecture_valeurs_bornes_et_disponibilite():
    conf, _ = _num("comfort_setpoint")
    red, _ = _num("setback_setpoint")
    assert conf.native_value == 6.0
    assert red.native_value == 5.0
    assert conf.native_min_value == 5.0
    assert conf.native_max_value == 35.0
    assert conf.available is True
    hors_ligne, _ = _num("comfort_setpoint", room=_room(online=False))
    assert hors_ligne.available is False


@pytest.mark.parametrize(
    ("key", "dps"),
    [
        ("comfort_setpoint", {"118": 65}),  # DP 118
        ("setback_setpoint", {"109": 65, "119": 65}),  # DP 109 + 119
    ],
)
async def test_ecrit_les_bons_dp_et_rafraichit(key, dps):
    client = _FakeClient()
    ent, coord = _num(key, client=client)
    await ent.async_set_native_value(6.5)
    assert client.calls == [("77", "03wvrwpv", dps, True)]
    assert coord.refreshed is True
    # R-3 (regression, real hardware 2026-11-19): the room's heads are marked commanded, like the
    # room climate's set_temperature, so the round-trip is not left to the bulk-route lag
    assert coord.commanded == ["h1", "h2"]


async def test_ecriture_refusee_ne_marque_pas_r3():
    from custom_components.danfoss_ally_cloud.api.client import CloudError

    ent, coord = _num("comfort_setpoint", client=_FakeClient(exc=CloudError("refused")))
    with pytest.raises(HomeAssistantError):
        await ent.async_set_native_value(6.5)
    assert coord.commanded == []


async def test_refuse_produit_non_verifie():
    client = _FakeClient()
    ent, _ = _num("comfort_setpoint", room=_room(pid="autre"), client=client)
    with pytest.raises(HomeAssistantError):
        await ent.async_set_native_value(6.5)
    assert client.calls == []
