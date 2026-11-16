"""Tests du coordinateur : construction des pièces et cache du programme (lot 2)."""

from custom_components.danfoss_ally_cloud.coordinator import DanfossCoordinator

from .common import tete


class _FakeClient:
    def __init__(self):
        self.list_calls = 0
        self.structure_calls = 0
        self.schedule_calls = 0

    async def async_list_devices(self):
        self.list_calls += 1
        return [
            tete(dev_id="a", nom="Salle 1 #2", **{"mode": "at_home"}, product_id="03wvrwpv"),
            tete(dev_id="b", nom="Salle 1 #3"),
        ]

    async def async_room_structure(self):
        self.structure_calls += 1
        return [
            {
                "id": "13000000",
                "name": "Salle 1",
                "home": "Maison",
                "product_id": "03wvrwpv",
                "members": ["a", "b"],
            }
        ]

    async def async_get_schedule(self, target):
        self.schedule_calls += 1
        return {"target": target, "days": {"mon": []}, "read_at": "t"}


def _coord(hass):
    return DanfossCoordinator(hass, _FakeClient(), 90)


async def test_build_rooms_superpose_les_etats(hass):
    coord = _coord(hass)
    await coord._async_update_data()
    assert len(coord.rooms) == 1
    room = coord.rooms[0]
    assert room["id"] == "13000000" and room["name"] == "Salle 1"
    assert [h["device_id"] for h in room["heads"]] == ["a", "b"]
    # consignes confort/réduit lues dans les dps des têtes (tete() : 21.0 / néant)
    assert coord.rooms_by_id["13000000"]["heads"][0]["mode_displayed"] == "at_home"


async def test_structure_en_cache_pas_relue_chaque_cycle(hass):
    coord = _coord(hass)
    await coord._async_update_data()
    await coord._async_update_data()
    assert coord.client.list_calls == 2  # états relus
    assert coord.client.structure_calls == 1  # ossature mise en cache


async def test_schedule_cache_puis_invalidation(hass):
    coord = _coord(hass)
    target = {"type": "room", "id": "13000000"}
    await coord.async_get_schedule(target)
    await coord.async_get_schedule(target)  # servi par le cache
    assert coord.client.schedule_calls == 1
    await coord.async_get_schedule(target, refresh=True)  # forcé
    assert coord.client.schedule_calls == 2
    coord.invalidate_schedule(target)
    await coord.async_get_schedule(target)  # cache vidé -> relu
    assert coord.client.schedule_calls == 3
