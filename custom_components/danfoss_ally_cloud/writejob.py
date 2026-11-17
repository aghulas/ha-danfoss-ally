"""Write tracking (`WriteJob`): in-memory queue, events for `jobs/subscribe`.

A job is born "sent" (the cloud accepted); the (deferred, never blocking) verification moves each
head from `pending` to `applied` / `mismatch` / `unreachable` / `unverified`, then the job to
`applied` / `partial` / `unverified` (contract §3.5). `failed` = the cloud refused the call.

Jobs are not persisted: the last 50 are kept in memory.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

MAX_JOBS = 50

HEAD_PENDING = "pending"
HEAD_APPLIED = "applied"
HEAD_MISMATCH = "mismatch"
HEAD_UNREACHABLE = "unreachable"
HEAD_UNVERIFIED = "unverified"

LOT_SENT = "sent"
LOT_APPLIED = "applied"
LOT_PARTIAL = "partial"
LOT_UNVERIFIED = "unverified"
LOT_FAILED = "failed"


@dataclass
class HeadResult:
    device_id: str
    status: str = HEAD_PENDING
    detail: str | None = None

    def to_dict(self) -> dict:
        return {"device_id": self.device_id, "status": self.status, "detail": self.detail}


@dataclass
class WriteJob:
    job_id: str
    kind: str
    target: dict
    status: str = LOT_SENT
    created_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())
    heads: list[HeadResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "target": self.target,
            "status": self.status,
            "created_at": self.created_at,
            "heads": [h.to_dict() for h in self.heads],
        }


def _lot_status(heads: list[HeadResult]) -> str:
    statuses = {h.status for h in heads}
    if not statuses or statuses == {HEAD_APPLIED}:
        return LOT_APPLIED
    if statuses <= {HEAD_UNVERIFIED, HEAD_PENDING}:
        return LOT_UNVERIFIED
    if HEAD_APPLIED in statuses:
        return LOT_PARTIAL
    return LOT_UNVERIFIED


class JobManager:
    """In-memory queue of write jobs, with subscribers (`jobs/subscribe`)."""

    def __init__(self, max_jobs: int = MAX_JOBS) -> None:
        self._jobs: OrderedDict[str, WriteJob] = OrderedDict()
        self._max = max_jobs
        self._subscribers: list[Callable[[WriteJob], None]] = []

    def subscribe(self, callback: Callable[[WriteJob], None]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def _unsub() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return _unsub

    def _emit(self, job: WriteJob) -> None:
        for cb in list(self._subscribers):
            cb(job)

    def create(self, kind: str, target: dict, head_ids: list[str]) -> WriteJob:
        job = WriteJob(
            job_id=uuid.uuid4().hex,
            kind=kind,
            target=target,
            heads=[HeadResult(device_id=d) for d in head_ids],
        )
        self._jobs[job.job_id] = job
        while len(self._jobs) > self._max:
            self._jobs.popitem(last=False)
        self._emit(job)
        return job

    def get(self, job_id: str) -> WriteJob | None:
        return self._jobs.get(job_id)

    def recent(self) -> list[WriteJob]:
        return list(self._jobs.values())

    def set_head(
        self, job: WriteJob, device_id: str, status: str, detail: str | None = None
    ) -> None:
        for h in job.heads:
            if h.device_id == device_id:
                h.status = status
                h.detail = detail
        self._recompute(job)

    def fail(self, job: WriteJob, detail: str | None = None) -> None:
        job.status = LOT_FAILED
        for h in job.heads:
            if h.status == HEAD_PENDING:
                h.status = HEAD_UNVERIFIED
                h.detail = detail
        self._emit(job)

    def _recompute(self, job: WriteJob) -> None:
        if job.status != LOT_FAILED:
            job.status = _lot_status(job.heads)
        self._emit(job)
