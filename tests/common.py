"""Utilitaires de test : faux client cloud et têtes synthétiques (aucune donnée réelle)."""

from __future__ import annotations

from custom_components.danfoss_ally_cloud.api import DanfossDevice
from custom_components.danfoss_ally_cloud.const import (
    CONF_CH_KEY,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_SIGN_KEY,
    CONF_USERNAME,
)

ENTRY_DATA = {
    CONF_USERNAME: "compte@exemple.fr",
    CONF_PASSWORD: "motdepasse-synth",
    CONF_COUNTRY_CODE: "33",
    CONF_SIGN_KEY: "com.danfoss.ally_11:22:33:44_aaaa_bbbb",
    CONF_DEVICE_ID: "devid-synth",
    CONF_CH_KEY: "deadbeef",
    CONF_REGION: "eu",
}


def tete(dev_id="dev-1", nom="Salon", **kw) -> DanfossDevice:
    base = dict(
        id=dev_id,
        nom=nom,
        categorie="tete",
        product_id="03wvrwpv",
        node_id="node-1",
        mesh_id="gw-1",
        en_ligne=True,
        temperature=20.5,
        consigne=21.0,
        batterie=90.0,
        ouverture_vanne=30,
        fenetre_ouverte=False,
        verrouillage=False,
        detection_fenetre=True,
    )
    base.update(kw)
    return DanfossDevice(**base)


_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class FakeCloudClient:
    """Faux CloudClient : renvoie des têtes synthétiques, sans réseau.

    `rooms` = ossature de pièces (liste {id, name, home, product_id, members}). Les écritures de
    programme / consigne sont journalisées dans `writes` (aucun réseau).
    """

    def __init__(
        self, *args, devices=None, rooms=None, validate_exc=None, list_exc=None, **kwargs
    ) -> None:
        self._devices = [tete()] if devices is None else devices
        self._structure = rooms or []
        self._validate_exc = validate_exc
        self._list_exc = list_exc
        self.closed = False
        self.writes: list = []

    async def async_validate(self):
        if self._validate_exc is not None:
            raise self._validate_exc
        return [{"gid": 1, "nom": "Maison"}]

    async def async_list_devices(self):
        if self._list_exc is not None:
            raise self._list_exc
        return list(self._devices)

    async def async_room_structure(self):
        return [dict(s) for s in self._structure]

    async def async_get_schedule(self, target):
        return {
            "target": target,
            "name": None,
            "comfort": 21.0,
            "setback": 14.0,
            "days": {d: [] for d in _DAYS},
            "max_transitions_per_day": 6,
            "source": "cloud",
            "read_at": "t",
        }

    async def async_set_schedule_days(self, target, days):
        self.writes.append(("set", target, days))
        return {}

    async def async_restore_schedule(self, target):
        self.writes.append(("restore", target))
        return {}

    async def async_publish_room_dps(self, group_id, dps):
        self.writes.append(("publish", group_id, dps))
        return {}

    async def async_close(self):
        self.closed = True
