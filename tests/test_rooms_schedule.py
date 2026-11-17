"""Tests des méthodes d'édition de programme de CloudClient (bâties sur les primitives #10/#12)."""

import json

import pytest

from custom_components.danfoss_ally_cloud.api import ScheduleValidationError, UnknownTargetError
from custom_components.danfoss_ally_cloud.api.client import CloudClient

_HOMES = [{"groupId": 1, "name": "Maison"}]
_GROUPS = [{"id": 13000000, "name": "Salle 1", "deviceNum": 2, "productId": "03wvrwpv"}]
_DEVICES = [
    {
        "devId": "dev-a",
        "name": "Salle 1 #2",
        "category": "wk",
        "productId": "03wvrwpv",
        "meshId": "gw",
    }
]
_WEEK = {"data": [{"loops": "0100000", "loopData": [{"startTime": 510, "endTime": 1050}]}]}


class _Req:
    def __init__(self):
        self.calls = []
        self.responses = {
            "tuya.m.location.list": _HOMES,
            "m.life.my.group.device.group.list": _GROUPS,
            "tuya.m.my.group.device.list": _DEVICES,
            "tuya.m.custom.wkf.week.timer.list": _WEEK,
            "tuya.m.custom.wkf.week.timer.delete": {},
            "tuya.m.custom.wkf.week.timer.create": {},
            "s.m.dev.group.dp.publish": {},
        }

    async def __call__(self, api, version, body=None, extra_params=None):
        self.calls.append({"api": api, "body": body})
        return self.responses.get(api, {})

    def by_api(self, api):
        return [c for c in self.calls if c["api"] == api]


def _client():
    c = CloudClient("u", "p", "33", "sk", "devid", "chkey")
    req = _Req()
    c._request = req  # type: ignore[assignment]
    return c, req


async def test_get_schedule_forme_contrat():
    c, _ = _client()
    s = await c.async_get_schedule({"type": "room", "id": "13000000"})
    assert s["target"] == {"type": "room", "id": "13000000"}
    assert s["name"] == "Salle 1"
    assert s["days"]["mon"] == [{"start": "08:30", "end": "17:30"}]
    assert isinstance(s["read_at"], str) and s["read_at"]


async def test_cible_inconnue():
    c, _ = _client()
    with pytest.raises(UnknownTargetError):
        await c.async_get_schedule({"type": "room", "id": "99999999"})


async def test_set_schedule_invalide_n_envoie_rien():
    c, req = _client()
    with pytest.raises(ScheduleValidationError) as exc:
        await c.async_set_schedule_days(
            {"type": "room", "id": "13000000"}, {"mon": [{"start": "17:30", "end": "08:30"}]}
        )
    assert exc.value.errors[0]["code"] == "empty_or_reversed"
    assert req.calls == []


async def test_set_schedule_un_jour_delete_puis_create():
    c, req = _client()
    await c.async_set_schedule_days(
        {"type": "room", "id": "13000000"}, {"mon": [{"start": "08:30", "end": "17:30"}]}
    )
    dels = req.by_api("tuya.m.custom.wkf.week.timer.delete")
    creates = req.by_api("tuya.m.custom.wkf.week.timer.create")
    assert len(dels) == 1 and dels[0]["body"]["loops"] == "0100000"
    assert dels[0]["body"]["resType"] == 2 and dels[0]["body"]["gwId"] == "13000000"
    assert json.loads(creates[0]["body"]["periods"]) == [{"startTime": "08:30", "endTime": "17:30"}]


async def test_restore_sept_delete_puis_at_home_en_dernier():
    c, req = _client()
    await c.async_restore_schedule({"type": "room", "id": "13000000"})
    assert len(req.by_api("tuya.m.custom.wkf.week.timer.delete")) == 7
    assert len(req.by_api("tuya.m.custom.wkf.week.timer.create")) == 1
    dernier = req.calls[-1]
    assert dernier["api"] == "s.m.dev.group.dp.publish"
    assert json.loads(dernier["body"]["dps"]) == {"2": "at_home"}
