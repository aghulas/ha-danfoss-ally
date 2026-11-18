"""Test helpers: a fake cloud client and synthetic heads (no real data)."""

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


def head(dev_id="dev-1", name="Salon", **kw) -> DanfossDevice:
    base = dict(
        id=dev_id,
        name=name,
        category="head",
        product_id="03wvrwpv",
        node_id="node-1",
        mesh_id="gw-1",
        online=True,
        temperature=20.5,
        setpoint=21.0,
        battery=90.0,
        valve_opening=30,
        window_open=False,
        child_lock=False,
        window_detection=True,
    )
    base.update(kw)
    return DanfossDevice(**base)


class FakeCloudClient:
    """Fake CloudClient: returns synthetic heads and a room topology, without a network.

    ``groups``: list of rooms [{group_id, name, pid, head_count}]. ``members``:
    {group_id: [devId]}. By default no room: heads are therefore treated as isolated.
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
        holidays=None,
        holidays_exc=None,
        **kwargs,
    ) -> None:
        self._devices = [head()] if devices is None else devices
        self._validate_exc = validate_exc
        self._list_exc = list_exc
        self._groups = groups or []
        self._members = members or {}
        self._topology_exc = topology_exc
        self._holidays = holidays
        self._holidays_exc = holidays_exc
        self.closed = False
        self.writes: list = []

    async def async_validate(self):
        if self._validate_exc is not None:
            raise self._validate_exc
        return [{"gid": 1, "name": "Maison"}]

    async def async_list_devices(self):
        if self._list_exc is not None:
            raise self._list_exc
        return list(self._devices)

    async def async_get_homes(self):
        return [{"gid": 1, "name": "Maison"}]

    async def async_list_groups(self, gid):
        if self._topology_exc is not None:
            raise self._topology_exc
        return list(self._groups)

    async def async_group_members(self, gid):
        if self._topology_exc is not None:
            raise self._topology_exc
        return dict(self._members)

    async def async_list_holidays(self):
        if self._holidays_exc is not None:
            raise self._holidays_exc
        return list(self._holidays) if self._holidays is not None else []

    # Schedule editing (schedule-editing layer): stub + write log.
    async def async_get_schedule(self, target):
        return {
            "target": target,
            "name": "Salle 1",
            "comfort": 21.0,
            "setback": 14.0,
            "days": {d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
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

    async def async_close(self):
        self.closed = True
