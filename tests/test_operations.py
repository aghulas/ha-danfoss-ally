"""Tests des opérations partagées (services/WebSocket) : pièces, validation, écriture, lots."""

import pytest

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DATA_JOBS, DATA_SCHEDULES
from custom_components.danfoss_ally_cloud.writejob import JobManager

from .common import tete

_ROOM = {"type": "room", "id": "13000000"}


@pytest.fixture(autouse=True)
def _no_timer(monkeypatch):
    """Désactive la vérification différée (timer) : testée séparément via verify_job."""
    monkeypatch.setattr(ops, "_defer_verification", lambda *a, **k: None)


class _RoomState:
    def __init__(self, nom, pid, consignes):
        self.nom = nom
        self.pid = pid
        self.consignes = consignes


class _FakeClient:
    def __init__(self):
        self.calls = []
        self.schedule_reads = 0

    async def async_get_schedule(self, target):
        self.schedule_reads += 1
        return {"target": target, "days": {"mon": [{"start": "08:30", "end": "17:30"}]}}

    async def async_set_schedule_days(self, target, days):
        self.calls.append(("set", target, days))

    async def async_restore_schedule(self, target):
        self.calls.append(("restore", target))


class _Coord:
    def __init__(self, grouped=True):
        self.client = _FakeClient()
        self.data = {
            "a": tete("a", "Salle 1 #2", schedule_active=True),
            "b": tete("b", "Salle 1 #3", schedule_active=False, mode="at_home"),
        }
        self.rooms = {
            "13000000": _RoomState("Salle 1", "03wvrwpv", {"confort": 21.0, "reduit": 14.0})
        }
        self._group = {"a": "13000000", "b": "13000000"} if grouped else {}
        self.refreshed = False

    def group_of(self, head_id):
        return self._group.get(head_id)

    async def async_request_refresh(self):
        self.refreshed = True


def _store(grouped=True):
    coord = _Coord(grouped)
    return {DATA_COORDINATOR: coord, DATA_JOBS: JobManager(), DATA_SCHEDULES: {}}, coord


# --- Lecture -----------------------------------------------------------------------------------


def test_rooms_payload_pieces_et_tetes():
    store, _ = _store()
    rooms = ops.rooms_payload(store)["rooms"]
    assert len(rooms) == 1
    room = rooms[0]
    assert room["id"] == "13000000" and room["name"] == "Salle 1"
    assert room["comfort"] == 21.0 and room["setback"] == 14.0
    assert {h["device_id"] for h in room["heads"]} == {"a", "b"}
    assert any(h["inconsistent"] for h in room["heads"])  # b : at_home + DP172 0


async def test_get_schedule_cache_puis_refresh():
    store, coord = _store()
    await ops.get_schedule(store, _ROOM)
    await ops.get_schedule(store, _ROOM)
    assert coord.client.schedule_reads == 1  # servi par le cache
    await ops.get_schedule(store, _ROOM, refresh=True)
    assert coord.client.schedule_reads == 2


def test_validate_payload():
    assert ops.validate_payload({"mon": [{"start": "08:30", "end": "17:30"}]})["valid"] is True
    out = ops.validate_payload({"mon": [{"start": "17:30", "end": "08:30"}]})
    assert out["valid"] is False and out["errors"][0]["code"] == "empty_or_reversed"


# --- Écriture ----------------------------------------------------------------------------------


async def test_set_schedule_invalide_n_appelle_pas_le_client():
    store, coord = _store()
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_schedule(None, store, _ROOM, {"mon": [{"start": "17:30", "end": "08:30"}]})
    assert exc.value.code == "empty_or_reversed"
    assert coord.client.calls == []


async def test_set_schedule_tete_groupee_refusee():
    store, coord = _store()
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_schedule(None, store, {"type": "device", "id": "a"}, {"mon": []})
    assert exc.value.code == "grouped_device"
    assert coord.client.calls == []


async def test_set_schedule_succes_cree_un_lot():
    store, coord = _store()
    job = await ops.set_schedule(None, store, _ROOM, {"mon": [{"start": "08:30", "end": "17:30"}]})
    assert job["kind"] == "set_schedule" and job["status"] == "sent"
    assert {h["device_id"] for h in job["heads"]} == {"a", "b"}
    assert coord.client.calls[0][0] == "set"


async def test_restore_cree_un_lot():
    store, coord = _store()
    job = await ops.restore_schedule(None, store, _ROOM)
    assert job["kind"] == "restore" and coord.client.calls[0][0] == "restore"


# --- Vérification (DP 172, R6) et garde admin --------------------------------------------------


async def test_verify_job_restore_dp172():
    store, coord = _store()
    job = store[DATA_JOBS].create("restore", _ROOM, ["a", "b", "z"])  # z absent = injoignable
    await ops.verify_job(store, job)
    statuts = {h.device_id: h.status for h in job.heads}
    assert (
        statuts["a"] == "applied" and statuts["b"] == "mismatch" and statuts["z"] == "unreachable"
    )
    assert coord.refreshed is True


async def test_verify_job_set_schedule_unverified():
    store, _ = _store()
    job = store[DATA_JOBS].create("set_schedule", _ROOM, ["a"])
    await ops.verify_job(store, job)
    assert job.heads[0].status == "unverified"


async def test_ensure_admin(hass, hass_admin_user, hass_read_only_user):
    await ops.ensure_admin(hass, hass_admin_user.id)
    await ops.ensure_admin(hass, None)
    with pytest.raises(ops.OperationError) as exc:
        await ops.ensure_admin(hass, hass_read_only_user.id)
    assert exc.value.code == "not_admin"
