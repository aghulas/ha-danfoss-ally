"""Tests des opérations partagées (services/WebSocket) : validation, garde admin, R3, lots."""

import pytest

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DATA_JOBS
from custom_components.danfoss_ally_cloud.writejob import JobManager

from .common import tete

_ROOM = {"type": "room", "id": "13000000"}
_HEADS = [{"device_id": "a", "schedule_active": True, "inconsistent": False}]


@pytest.fixture(autouse=True)
def _no_timer(monkeypatch):
    """Désactive la vérification différée (timer) : testée séparément via verify_job."""
    monkeypatch.setattr(ops, "_defer_verification", lambda *a, **k: None)


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def async_set_schedule_days(self, target, days):
        self.calls.append(("set", target, days))

    async def async_restore_schedule(self, target):
        self.calls.append(("restore", target))

    async def async_publish_room_dps(self, group_id, dps):
        self.calls.append(("publish", group_id, dps))

    async def async_set_room_setpoint(self, dev_id, dps, *, repush=True):
        self.calls.append(("setpoint", dev_id, dps))
        return "grp"


class _FakeCoord:
    def __init__(self, rooms):
        self.client = _FakeClient()
        self.rooms = rooms
        self.data = {}
        self.invalidated = []
        self.refreshed = False

    @property
    def rooms_by_id(self):
        return {r["id"]: r for r in self.rooms}

    def invalidate_schedule(self, target):
        self.invalidated.append(target)

    async def async_get_schedule(self, target, refresh=False):
        return {"target": target, "days": {"mon": [{"start": "08:30", "end": "17:30"}]}}

    async def async_request_refresh(self):
        self.refreshed = True


def _store(rooms=None):
    coord = _FakeCoord(rooms if rooms is not None else [{"id": "13000000", "heads": _HEADS}])
    return {DATA_COORDINATOR: coord, DATA_JOBS: JobManager()}, coord


# --- Validation (pure) ------------------------------------------------------------------------


def test_validate_payload_valide():
    out = ops.validate_payload({"mon": [{"start": "08:30", "end": "17:30"}]})
    assert out["valid"] is True
    assert out["errors"] == []
    assert out["transitions"] == {"mon": 2}


def test_validate_payload_invalide():
    out = ops.validate_payload({"mon": [{"start": "17:30", "end": "08:30"}]})
    assert out["valid"] is False
    assert out["errors"][0]["code"] == "empty_or_reversed"


# --- set_schedule : refus avant envoi, grouped_device, succès -> lot --------------------------


async def test_set_schedule_invalide_n_appelle_pas_le_client(hass):
    store, coord = _store()
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_schedule(hass, store, _ROOM, {"mon": [{"start": "17:30", "end": "08:30"}]})
    assert exc.value.code == "empty_or_reversed"
    assert coord.client.calls == []


async def test_set_schedule_tete_groupee_refusee(hass):
    store, coord = _store(rooms=[{"id": "13000000", "heads": [{"device_id": "a"}]}])
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_schedule(hass, store, {"type": "device", "id": "a"}, {"mon": []})
    assert exc.value.code == "grouped_device"
    assert coord.client.calls == []


async def test_set_schedule_succes_cree_un_lot_et_invalide_le_cache(hass):
    store, coord = _store()
    job = await ops.set_schedule(hass, store, _ROOM, {"mon": [{"start": "08:30", "end": "17:30"}]})
    assert job["kind"] == "set_schedule"
    assert job["status"] == "sent"
    assert [h["device_id"] for h in job["heads"]] == ["a"]
    assert coord.client.calls[0][0] == "set"
    assert coord.invalidated == [_ROOM]


async def test_restore_cree_un_lot_restore(hass):
    store, coord = _store()
    job = await ops.restore_schedule(hass, store, _ROOM)
    assert job["kind"] == "restore"
    assert coord.client.calls[0][0] == "restore"


# --- R3 : consigne de pièce déléguée à async_set_room_setpoint (#10, publie DP + reprog) -------


async def test_set_setpoint_confort_delegue_a_set_room_setpoint(hass):
    store, coord = _store()
    await ops.set_setpoint(hass, store, "13000000", "comfort", 20.0)
    assert coord.client.calls == [("setpoint", "a", {"118": 200})]  # tête de la pièce, 20,0 °C
    assert coord.invalidated == [{"type": "room", "id": "13000000"}]


async def test_set_setpoint_reduit_publie_109_et_119(hass):
    store, coord = _store()
    await ops.set_setpoint(hass, store, "13000000", "setback", 14.0)
    assert coord.client.calls == [("setpoint", "a", {"109": 140, "119": 140})]


# --- Garde administrateur -----------------------------------------------------------------------


async def test_ensure_admin_refuse_non_admin(hass, hass_read_only_user):
    with pytest.raises(ops.OperationError) as exc:
        await ops.ensure_admin(hass, hass_read_only_user.id)
    assert exc.value.code == "not_admin"


async def test_ensure_admin_accepte_admin_et_interne(hass, hass_admin_user):
    await ops.ensure_admin(hass, hass_admin_user.id)  # admin : ok
    await ops.ensure_admin(hass, None)  # appel interne : ok


# --- Vérification d'un lot (DP 172, R6) --------------------------------------------------------


async def test_verify_job_mode_dp172_applied_et_unreachable():
    store, coord = _store()
    coord.data = {"a": tete(dev_id="a", schedule_active=True)}  # "b" absent = injoignable
    jobs = store[DATA_JOBS]
    job = jobs.create("restore", _ROOM, ["a", "b"])
    await ops.verify_job(store, job)
    statuts = {h.device_id: h.status for h in job.heads}
    assert statuts["a"] == "applied"  # DP 172 bit 0 vrai
    assert statuts["b"] == "unreachable"
    assert job.status == "partial"
    assert coord.refreshed is True


async def test_verify_job_set_setpoint_applied():
    store, coord = _store()
    coord.data = {"a": tete(dev_id="a", schedule_active=True)}
    jobs = store[DATA_JOBS]
    job = jobs.create("set_setpoint", _ROOM, ["a"])
    await ops.verify_job(store, job)
    assert job.heads[0].status == "applied"


async def test_get_schedule_cible_inconnue_mappe_unknown_target():
    from custom_components.danfoss_ally_cloud.api import UnknownTargetError

    store, coord = _store()

    async def _raise(target, refresh=False):
        raise UnknownTargetError("nope")

    coord.async_get_schedule = _raise
    with pytest.raises(ops.OperationError) as exc:
        await ops.get_schedule(store, {"type": "room", "id": "x"})
    assert exc.value.code == "unknown_target"


async def test_set_schedule_cloud_refuse_mappe_cloud_refused(hass):
    from custom_components.danfoss_ally_cloud.api.client import CloudError

    store, coord = _store()

    async def _raise(target, days):
        raise CloudError("refus")

    coord.client.async_set_schedule_days = _raise
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_schedule(hass, store, _ROOM, {"mon": [{"start": "08:30", "end": "17:30"}]})
    assert exc.value.code == "cloud_refused"


async def test_verify_job_set_schedule_reste_unverified():
    store, coord = _store()
    coord.data = {"a": tete(dev_id="a", schedule_active=True)}
    jobs = store[DATA_JOBS]
    job = jobs.create("set_schedule", _ROOM, ["a"])
    await ops.verify_job(store, job)
    assert job.heads[0].status == "unverified"  # relecture locale non effectuée en cloud seul
