"""Tests de la récupération des localKey des passerelles (client simulé, clés synthétiques)."""

from custom_components.danfoss_ally_cloud.api import async_fetch_gateway_keys


class _FakeClient:
    def __init__(self, raw, meta):
        self._raw = raw
        self._meta = meta

    async def async_list_raw(self):
        return self._raw

    async def async_device_meta(self, dev_id):
        return self._meta.get(dev_id, {})


async def test_fetch_gateway_keys_filtre_et_ip():
    raw = [
        {"devId": "gw-1", "name": "A-0 Gateway", "category": "wg2", "localKey": "cle-synth-1"},
        {"devId": "gw-2", "name": "B-0 Gateway", "category": "wg2", "localKey": ""},  # sans clé
        {"devId": "tete-1", "name": "Salon", "category": "wk", "localKey": ""},  # tête, exclue
    ]
    meta = {"gw-1": {"lan_ip": "10.77.20.226"}}
    keys = await async_fetch_gateway_keys(_FakeClient(raw, meta))
    assert set(keys) == {"gw-1"}  # gw-2 (sans clé) et la tête exclues
    assert keys["gw-1"].local_key == "cle-synth-1"
    assert keys["gw-1"].ip == "10.77.20.226"
    assert keys["gw-1"].nom == "A-0 Gateway"
