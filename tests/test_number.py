"""Plateforme number : consignes confort/réduit d'une pièce, gardées par produit vérifié."""

from types import SimpleNamespace

from custom_components.danfoss_ally_cloud import number
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DOMAIN


class _Coord:
    def __init__(self, rooms):
        self.rooms = rooms


async def _setup(rooms):
    store = {DATA_COORDINATOR: _Coord(rooms)}
    hass = SimpleNamespace(data={DOMAIN: {"e1": store}})
    entry = SimpleNamespace(entry_id="e1")
    added: list = []
    await number.async_setup_entry(hass, entry, added.extend)
    return added


async def test_aucune_piece():
    assert await _setup([]) == []


async def test_produit_verifie_expose_confort_et_reduit():
    rooms = [
        {
            "id": "13000000",
            "name": "Salle 1",
            "product_id": "03wvrwpv",
            "comfort": 21.0,
            "setback": 14.0,
        }
    ]
    added = await _setup(rooms)
    assert {e._kind for e in added} == {"comfort", "setback"}
    assert len(added) == 2


async def test_produit_non_verifie_ignore():
    rooms = [
        {
            "id": "13000001",
            "name": "Salle 2",
            "product_id": "autre",
            "comfort": None,
            "setback": None,
        }
    ]
    assert await _setup(rooms) == []
