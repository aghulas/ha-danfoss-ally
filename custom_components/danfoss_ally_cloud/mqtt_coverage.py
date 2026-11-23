"""Coverage measure of the Tuya cloud MQTT push (roadmap stage 3) — aggregates only, no send.

Answers the open question of docs/architecture.md: which heads and which DPs does the broker push,
and how often. A :class:`CoverageStats` is fed with every decoded inbound frame of the cloud-MQTT
link (``CloudMqttLink.on_frame``) and keeps, per head and per DP, a count, the first and last
instant, and the recent intervals. Nothing else is kept: no DP value, no payload.

The identifiers it indexes on (gateway devId, head node id) stay in memory only. The summary served
to the diagnostics names a head by its position in the diagnostics ``devices`` list and its display
name, never by an identifier. Nothing here is logged.

How to run the measure and read it: docs/cloud-mqtt-channel.md.
"""

from __future__ import annotations

import statistics
import threading
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .api import DanfossDevice
from .api import mqtt_publish as mp

# Intervals kept per series for the median (the most recent ones). Bounds the memory of a long run:
# a fleet of 100 heads reporting 20 DPs each stays under a few megabytes.
INTERVAL_SAMPLES = 256

# DPs the cloud read path decodes (``api.decode._apply_dps``). A head whose pushed reports never
# carry one of them could not be fed from the push alone (stage 4).
READ_DPS: tuple[str, ...] = (
    "2",  # mode
    "3",  # work_state (heating action)
    "16",  # temp_set
    "18",  # upper bound
    "24",  # measured temperature
    "25",  # window state
    "27",  # lower bound
    "30",  # child lock
    "34",  # battery
    "45",  # fault
    "114",  # manual setpoint
    "116",  # window detection
    "118",  # comfort setpoint
    "119",  # setback setpoint
    "120",  # pause setpoint
    "121",  # holiday setpoint
    "149",  # mounting mode
    "162",  # heat request
    "170",  # valve opening
    "171",  # active setpoint
    "172",  # operation mode (schedule / preheat bits)
    "184",  # software error code
)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


@dataclass
class _Series:
    """Reports of one thing (a head, or one DP of a head): count, first/last instant, intervals."""

    count: int = 0
    first: float = 0.0  # epoch seconds
    last: float = 0.0
    last_mono: float = 0.0
    longest: float = 0.0
    intervals: deque[float] = field(default_factory=lambda: deque(maxlen=INTERVAL_SAMPLES))

    def add(self, wall: float, mono: float) -> None:
        if self.count:
            gap = mono - self.last_mono
            self.intervals.append(gap)
            self.longest = max(self.longest, gap)
        else:
            self.first = wall
        self.count += 1
        self.last = wall
        self.last_mono = mono

    def summary(self) -> dict[str, Any]:
        return {
            "reports": self.count,
            "first": _iso(self.first),
            "last": _iso(self.last),
            "median_interval_s": (
                round(statistics.median(self.intervals), 1) if self.intervals else None
            ),
            "longest_interval_s": round(self.longest, 1) if self.intervals else None,
        }


@dataclass
class _Head:
    any: _Series = field(default_factory=_Series)
    dps: dict[str, _Series] = field(default_factory=dict)


class CoverageStats:
    """Aggregates of the inbound cloud-MQTT frames. Thread-safe: ``record`` runs on the MQTT
    client's thread, ``summary`` on the event loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = time.time()
        self._stopped: float | None = None
        self._frames = 0
        self._by_protocol: dict[str, int] = {}
        self._without_head = 0
        self._heads: dict[tuple[str, str], _Head] = {}

    def record(self, gateway_id: str, frame: mp.Frame) -> None:
        """Account one decoded inbound frame. Signature of ``CloudMqttLink.on_frame``."""
        wall, mono = time.time(), time.monotonic()
        data = frame.data if isinstance(frame.data, dict) else {}
        cid = data.get("cid")
        raw_dps = data.get("dps")
        dps = raw_dps if isinstance(raw_dps, dict) else {}
        with self._lock:
            if self._stopped is not None:
                return
            self._frames += 1
            proto = str(frame.protocol)
            self._by_protocol[proto] = self._by_protocol.get(proto, 0) + 1
            if not isinstance(cid, str) or not cid or not dps:
                # A frame about the gateway itself, or one that carries no DP report.
                self._without_head += 1
                return
            head = self._heads.setdefault((gateway_id, cid), _Head())
            head.any.add(wall, mono)
            for dp in dps:
                head.dps.setdefault(str(dp), _Series()).add(wall, mono)

    def mark_stopped(self) -> None:
        """Freeze the measure (the listen-only link reached its maximum duration, or was closed)."""
        with self._lock:
            if self._stopped is None:
                self._stopped = time.time()

    def summary(
        self, devices: Iterable[DanfossDevice], grouped_ids: Iterable[str] = ()
    ) -> dict[str, Any]:
        """Redacted aggregates. ``devices`` in the order of the diagnostics ``devices`` list, so
        ``device_index`` points at the matching entry there. No identifier in the result."""
        grouped = set(grouped_ids)
        with self._lock:
            end = self._stopped if self._stopped is not None else time.time()
            heads_out: list[dict[str, Any]] = []
            never_seen: list[dict[str, Any]] = []
            matched: set[tuple[str, str]] = set()
            fleet_dps: dict[str, dict[str, int]] = {}
            known = 0
            for index, dev in enumerate(devices):
                if not dev.is_head:
                    continue
                known += 1
                ident = {
                    "device_index": index,
                    "name": dev.name,
                    "online": dev.online,
                    "grouped": dev.id in grouped,
                }
                key = (dev.mesh_id or "", dev.node_id or "")
                head = self._heads.get(key)
                if head is None:
                    never_seen.append(ident)
                    continue
                matched.add(key)
                for dp, series in head.dps.items():
                    agg = fleet_dps.setdefault(dp, {"heads": 0, "reports": 0})
                    agg["heads"] += 1
                    agg["reports"] += series.count
                heads_out.append(
                    {
                        **ident,
                        **head.any.summary(),
                        "read_dps_missing": [dp for dp in READ_DPS if dp not in head.dps],
                        "dps": {
                            dp: head.dps[dp].summary() for dp in sorted(head.dps, key=_dp_order)
                        },
                    }
                )
            return {
                "started": _iso(self._started),
                "stopped": _iso(self._stopped) if self._stopped is not None else None,
                "duration_s": round(end - self._started),
                "frames": self._frames,
                "frames_by_protocol": dict(sorted(self._by_protocol.items())),
                "frames_without_head_report": self._without_head,
                "heads_known": known,
                "heads_seen": len(heads_out),
                "heads_never_seen": never_seen,
                # Senders that match no head of the last poll (a sensor, a relay, a head added
                # since): counted, never identified.
                "unknown_senders": len(set(self._heads) - matched),
                "dps": {dp: fleet_dps[dp] for dp in sorted(fleet_dps, key=_dp_order)},
                "read_dps_never_pushed": [dp for dp in READ_DPS if dp not in fleet_dps],
                "heads": heads_out,
            }


def _dp_order(dp: str) -> tuple[int, str]:
    return (int(dp), "") if dp.isdigit() else (1 << 30, dp)
