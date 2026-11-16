"""Tests de la file des lots d'écriture (WriteJob) — pur, sans Home Assistant."""

from custom_components.danfoss_ally_cloud import writejob as wj

_TARGET = {"type": "room", "id": "13000000"}


def test_create_statut_sent_et_tetes_pending():
    mgr = wj.JobManager()
    job = mgr.create("set_schedule", _TARGET, ["a", "b"])
    assert job.status == wj.LOT_SENT
    assert [h.status for h in job.heads] == [wj.HEAD_PENDING, wj.HEAD_PENDING]
    assert mgr.get(job.job_id) is job


def test_applied_quand_toutes_les_tetes_appliquees():
    mgr = wj.JobManager()
    job = mgr.create("restore", _TARGET, ["a", "b"])
    mgr.set_head(job, "a", wj.HEAD_APPLIED)
    mgr.set_head(job, "b", wj.HEAD_APPLIED)
    assert job.status == wj.LOT_APPLIED


def test_partial_quand_une_seule_appliquee():
    mgr = wj.JobManager()
    job = mgr.create("restore", _TARGET, ["a", "b"])
    mgr.set_head(job, "a", wj.HEAD_APPLIED)
    mgr.set_head(job, "b", wj.HEAD_UNREACHABLE)
    assert job.status == wj.LOT_PARTIAL


def test_unverified_quand_aucune_verifiee():
    mgr = wj.JobManager()
    job = mgr.create("set_schedule", _TARGET, ["a"])
    mgr.set_head(job, "a", wj.HEAD_UNVERIFIED)
    assert job.status == wj.LOT_UNVERIFIED


def test_fail_force_failed_et_vide_le_pending():
    mgr = wj.JobManager()
    job = mgr.create("set_schedule", _TARGET, ["a"])
    mgr.fail(job, "cloud refusé")
    assert job.status == wj.LOT_FAILED
    assert job.heads[0].status == wj.HEAD_UNVERIFIED


def test_abonnes_recoivent_les_evenements():
    mgr = wj.JobManager()
    recus = []
    unsub = mgr.subscribe(lambda j: recus.append((j.job_id, j.status)))
    job = mgr.create("restore", _TARGET, ["a"])
    mgr.set_head(job, "a", wj.HEAD_APPLIED)
    unsub()
    mgr.set_head(job, "a", wj.HEAD_MISMATCH)  # plus d'abonné
    assert recus == [(job.job_id, wj.LOT_SENT), (job.job_id, wj.LOT_APPLIED)]


def test_garde_les_cinquante_derniers():
    mgr = wj.JobManager(max_jobs=3)
    ids = [mgr.create("x", _TARGET, []).job_id for _ in range(5)]
    restants = {j.job_id for j in mgr.recent()}
    assert len(restants) == 3
    assert ids[0] not in restants and ids[-1] in restants


def test_to_dict_forme_contrat():
    mgr = wj.JobManager()
    job = mgr.create("set_schedule", _TARGET, ["a"])
    d = job.to_dict()
    assert set(d) == {"job_id", "kind", "target", "status", "created_at", "heads"}
    assert d["heads"][0] == {"device_id": "a", "status": "pending", "detail": None}
