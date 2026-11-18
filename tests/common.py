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


def relay(dev_id="relay-1", name="Boiler relay", on=True, **kw) -> DanfossDevice:
    base = dict(
        id=dev_id,
        name=name,
        category="relay",
        product_id="ypieax1h",
        mesh_id="gw-1",
        online=True,
        relay_on=on,
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
        relay_rooms=None,
        saturday_groups=None,
        device_get_dps=None,
        **kwargs,
    ) -> None:
        self._devices = [head()] if devices is None else devices
        # Per-device "fresh" DPs for the R-3 post-command refresh: {dev_id: {dp: value} | None}.
        # ``async_get_device_dps`` returns the mapped DPs (None = route carries nothing). Every call
        # is logged in ``device_get_calls`` so tests can assert the per-device reads are bounded.
        self._device_get_dps = device_get_dps or {}
        self.device_get_calls: list[str] = []
        self._validate_exc = validate_exc
        self._list_exc = list_exc
        self._groups = groups or []
        self._members = members or {}
        self._topology_exc = topology_exc
        self._holidays = holidays
        self._holidays_exc = holidays_exc
        self._relay_rooms = relay_rooms
        self._saturday_groups = set(saturday_groups or ())
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

    async def async_device_homes(self, dev_ids):
        # Single-home fixture: every device is in home "1" (list, like the real client).
        return {d: ["1"] for d in dev_ids}

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

    async def async_relay_rooms(self, dev_id):
        return list((self._relay_rooms or {}).get(dev_id, []))

    # Room management writes (B5): record calls in ``writes``.
    async def async_list_rooms(self, home_gid):
        # One type-4 room per schedule-group, same name (so name resolution matches).
        return [{"room_id": "room-5", "name": g.get("name")} for g in self._groups] or [
            {"room_id": "room-5", "name": "Salle 1"}
        ]

    async def async_room_id(self, home_gid, name):
        return "room-5"

    async def async_room_add(self, gid, name):
        self.writes.append(("room_add", gid, name))
        return "new-7"

    async def async_room_update(self, room_id, name):
        self.writes.append(("room_update", room_id, name))

    async def async_room_dismiss(self, room_id):
        self.writes.append(("room_dismiss", room_id))

    async def async_room_set_devices(self, room_id, dev_ids):
        self.writes.append(("room_set", room_id, list(dev_ids)))

    async def async_relay_bind(self, dev_id, room_id, linked):
        self.writes.append(("relay_bind", dev_id, room_id, bool(linked)))
        return {"ok": True}

    async def async_device_reset(self, dev_id, reset_factory=False):
        self.writes.append(("device_reset", dev_id, bool(reset_factory)))
        return {"ok": True}

    # Vacation writes (axis A): record calls in ``writes`` (no network).
    @staticmethod
    def _csv(room_ids):
        return room_ids if isinstance(room_ids, str) else ",".join(str(r) for r in room_ids)

    async def async_vacation_leave(
        self,
        home_id,
        start_date,
        start_time,
        end_date,
        end_time,
        temperature_tenths,
        room_ids,
        time_zone="Europe/Paris",
    ):
        self.writes.append(
            (
                "vac_leave",
                str(home_id),
                start_date,
                start_time,
                end_date,
                end_time,
                int(temperature_tenths),
                self._csv(room_ids),
                time_zone,
            )
        )
        return {"ok": True}

    async def async_vacation_athome(
        self, home_id, start_date, end_date, room_ids, time_zone="Europe/Paris"
    ):
        self.writes.append(
            ("vac_athome", str(home_id), start_date, end_date, self._csv(room_ids), time_zone)
        )
        return {"ok": True}

    async def async_vacation_cancel(self, home_id, time_zone="Europe/Paris"):
        self.writes.append(("vac_cancel", str(home_id), time_zone))
        return {"ok": True}

    async def async_vacation_leave_now(
        self, home_id, room_ids, temperature_tenths, time_zone="Europe/Paris"
    ):
        self.writes.append(
            ("vac_leave_now", str(home_id), self._csv(room_ids), int(temperature_tenths), time_zone)
        )
        return {"ok": True}

    # Schedule editing (schedule-editing layer): stub + write log.
    async def async_get_schedule(self, target):
        days = {d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
        # Groups configured with a Saturday program get a Saturday slot (at-home vacation guard).
        if str(target.get("id")) in self._saturday_groups:
            days["sat"] = [{"start": "08:00", "end": "18:00"}]
        return {
            "target": target,
            "name": "Salle 1",
            "comfort": 21.0,
            "setback": 14.0,
            "days": days,
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

    async def async_get_device_dps(self, dev_id):
        self.device_get_calls.append(dev_id)
        return self._device_get_dps.get(dev_id)

    async def async_close(self):
        self.closed = True
