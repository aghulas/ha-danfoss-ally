"""Tests de la file des lots d'écriture (WriteJob) — pur, sans Home Assistant."""

from custom_components.danfoss_ally_cloud import writejob as wj

_TARGET = {"type": "room", "id": "13000000"}


def test_create_statut_sent_et_tetes_pending():
    mgr = wj.JobManager()
    job = mgr.create("set_schedule", _TARGET, ["a", "b"])
    assert job.status == wj.LOT_SENT
    assert [h.status for h in job.heads] == [wj.HEAD_PENDING, wj.HEAD_PENDING]
    assert mgr.get(job.job_id) is job


def test_applied_partial_unverified():
    mgr = wj.JobManager()
    job = mgr.create("restore", _TARGET, ["a", "b"])
    mgr.set_head(job, "a", wj.HEAD_APPLIED)
    mgr.set_head(job, "b", wj.HEAD_APPLIED)
    assert job.status == wj.LOT_APPLIED
    mgr.set_head(job, "b", wj.HEAD_UNREACHABLE)
    assert job.status == wj.LOT_PARTIAL
    job2 = mgr.create("set_schedule", _TARGET, ["a"])
    mgr.set_head(job2, "a", wj.HEAD_UNVERIFIED)
    assert job2.status == wj.LOT_UNVERIFIED


def test_fail_force_failed():
    mgr = wj.JobManager()
    job = mgr.create("set_schedule", _TARGET, ["a"])
    mgr.fail(job, "cloud refusé")
    assert job.status == wj.LOT_FAILED and job.heads[0].status == wj.HEAD_UNVERIFIED


def test_abonnes_et_desabonnement():
    mgr = wj.JobManager()
    recus = []
    unsub = mgr.subscribe(lambda j: recus.append(j.status))
    job = mgr.create("restore", _TARGET, ["a"])
    mgr.set_head(job, "a", wj.HEAD_APPLIED)
    unsub()
    mgr.set_head(job, "a", wj.HEAD_MISMATCH)
    assert recus == [wj.LOT_SENT, wj.LOT_APPLIED]


def test_garde_les_n_derniers_et_to_dict():
    mgr = wj.JobManager(max_jobs=3)
    ids = [mgr.create("x", _TARGET, []).job_id for _ in range(5)]
    restants = {j.job_id for j in mgr.recent()}
    assert len(restants) == 3 and ids[0] not in restants and ids[-1] in restants
    d = mgr.create("set_schedule", _TARGET, ["a"]).to_dict()
    assert set(d) == {"job_id", "kind", "target", "status", "created_at", "heads"}
    assert d["heads"][0] == {"device_id": "a", "status": "pending", "detail": None}
