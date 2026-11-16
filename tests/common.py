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


class FakeCloudClient:
    """Faux CloudClient : renvoie des têtes synthétiques et une topologie de pièces, sans réseau.

    ``groups`` : liste de pièces [{group_id, nom, pid, nb_tetes}]. ``members`` :
    {group_id: [devId]}. Par défaut aucune pièce : les têtes sont donc traitées comme isolées.
    """

    def __init__(
        self,
        *args,
        devices=None,
        validate_exc=None,
        list_exc=None,
        groups=None,
        members=None,
        topology_exc=None,
        **kwargs,
    ) -> None:
        self._devices = [tete()] if devices is None else devices
        self._validate_exc = validate_exc
        self._list_exc = list_exc
        self._groups = groups or []
        self._members = members or {}
        self._topology_exc = topology_exc
        self.closed = False

    async def async_validate(self):
        if self._validate_exc is not None:
            raise self._validate_exc
        return [{"gid": 1, "nom": "Maison"}]

    async def async_list_devices(self):
        if self._list_exc is not None:
            raise self._list_exc
        return list(self._devices)

    async def async_get_homes(self):
        return [{"gid": 1, "nom": "Maison"}]

    async def async_list_groups(self, gid):
        if self._topology_exc is not None:
            raise self._topology_exc
        return list(self._groups)

    async def async_group_members(self, gid):
        if self._topology_exc is not None:
            raise self._topology_exc
        return dict(self._members)

    async def async_close(self):
        self.closed = True
