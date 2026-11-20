"""Local tunnel manager: survey and write of the preheat state (attribute 0x0025).

Isolates the blocking I/O (tinytuya): the HA layer calls it in the executor. One thread per gateway,
best-effort (an unreachable head -> None, never an exception propagated to the global survey). The
link factory is injectable (``open_link``) for tests (a networkless double).
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..keys import GatewayKey
from . import tunnel

_LOGGER = logging.getLogger(__name__)

# Upper bound of a preheat survey: a fixed margin plus the worst case of one head (two 12 s
# attempts, ``tunnel.request``) for the busiest gateway. Past it the survey is stopped and the heads
# not read yet are simply absent from the result (their switch stays unavailable).
SURVEY_BASE_TIMEOUT = 40.0
SURVEY_HEAD_TIMEOUT = 30.0


@dataclass(frozen=True)
class Head:
    """A head addressable through the tunnel: its devId, its Zigbee cid (node_id) and gateway."""

    dev_id: str
    node_id: str
    gateway_id: str


class LocalTunnelManager:
    """Opens tinytuya links to the gateways to read/write the real preheat state."""

    def __init__(
        self,
        gateways: dict[str, GatewayKey],
        open_link: Callable[[GatewayKey], Any] = tunnel.LocalLink,
    ) -> None:
        self._gateways = gateways
        self._open_link = open_link

    @property
    def gateway_ids(self) -> set[str]:
        return set(self._gateways)

    def survey_preheat(
        self,
        heads: list[Head],
        on_result: Callable[[str, bool | None], None] | None = None,
        stop: threading.Event | None = None,
    ) -> dict[str, bool | None]:
        """Read preheat (0x0025 bit 1) per head, one gateway per thread. Best-effort.

        Slow by nature: the heads of a gateway are read one after the other (a few seconds each when
        they answer, up to 24 s when they do not). ``on_result(dev_id, value)`` is called from the
        worker thread as soon as a head is read, so the caller can publish it without waiting for
        the whole site. ``stop`` aborts the survey: it returns at once with what was read so far,
        and each worker gives up after the head it is on (a tunnel request is not interruptible).
        No worker outlives the call for longer than that one request: nothing is written into the
        returned mapping afterwards.
        """
        stop = stop if stop is not None else threading.Event()
        res: dict[str, bool | None] = {}
        lock = threading.Lock()
        by_gw: dict[str, list[Head]] = defaultdict(list)
        for h in heads:
            if h.gateway_id in self._gateways:
                by_gw[h.gateway_id].append(h)

        def publish(dev_id: str, value: bool | None) -> None:
            with lock:
                if stop.is_set():
                    return
                res[dev_id] = value
            if on_result is not None:
                with contextlib.suppress(Exception):  # a listener never breaks the survey
                    on_result(dev_id, value)

        def worker(gw_id: str, mine: list[Head]) -> None:
            try:
                link = self._open_link(self._gateways[gw_id])
            except Exception as err:  # noqa: BLE001 - gateway unreachable: heads = None
                _LOGGER.debug("local tunnel: gateway %s unreachable (%s)", gw_id, err)
                for h in mine:
                    publish(h.dev_id, None)
                return
            try:
                for h in mine:
                    if stop.is_set():
                        return
                    try:
                        v = tunnel.read_preheat(link, h.dev_id, h.node_id)
                    except Exception:  # noqa: BLE001 - isolate each head
                        v = None
                    publish(h.dev_id, v)
            finally:
                link.close()

        threads = [
            threading.Thread(target=worker, args=(g, m), daemon=True) for g, m in by_gw.items()
        ]
        busiest = max((len(m) for m in by_gw.values()), default=0)
        deadline = time.monotonic() + SURVEY_BASE_TIMEOUT + SURVEY_HEAD_TIMEOUT * busiest
        for t in threads:
            t.start()
        for t in threads:
            while t.is_alive() and not stop.is_set() and time.monotonic() < deadline:
                t.join(timeout=0.2)
        with lock:
            stop.set()  # timed out or aborted: late workers stop and publish nothing more
            return dict(res)

    def survey_heads(self, heads: list[Head]) -> dict[str, dict[str, Any]]:
        """Full read-only survey of each head through the tunnel, summarized per head.

        One gateway per thread, best-effort (an unreachable head -> ``{"unreachable": True}``,
        never an exception propagated). Returns a mapping ``dev_id -> summary`` (comfort slots,
        comfort/setback setpoints, decoded attributes); see ``tunnel.summarize_head``.
        """
        raw = tunnel.survey(self._gateways, heads)
        return {dev_id: tunnel.summarize_head(entry) for dev_id, entry in raw.items()}

    def read_preheat(self, head: Head) -> bool | None:
        """Read ONE head's real preheat (0x0025 bit 1) through the tunnel. None without a response.

        Used right after a preheat write to reflect the head's actual state without waiting for the
        next full survey (~8 s per head, minutes for a whole site). Raises LocalUnavailable on an
        unknown gateway.
        """
        if head.gateway_id not in self._gateways:
            raise tunnel.LocalUnavailable(f"unknown gateway: {head.gateway_id}")
        link = self._open_link(self._gateways[head.gateway_id])
        try:
            return tunnel.read_preheat(link, head.dev_id, head.node_id)
        finally:
            link.close()

    def read_programming_mode(
        self, head: Head, *, duration: float = 8, attempts: int = 1
    ) -> int | None:
        """Read ONE head's raw 0x0025 (bit 0 schedule, bit 1 preheat). None without a response.

        A short, single-attempt read by default: it serves as a guard before a schedule write
        (is the head really following a schedule?), where a head that does not answer must not
        hold the call for long. Raises LocalUnavailable on an unknown gateway.
        """
        if head.gateway_id not in self._gateways:
            raise tunnel.LocalUnavailable(f"unknown gateway: {head.gateway_id}")
        link = self._open_link(self._gateways[head.gateway_id])
        try:
            return tunnel.read_programming_mode(
                link, head.dev_id, head.node_id, duration=duration, attempts=attempts
            )
        finally:
            link.close()

    def write_preheat(self, head: Head, active: bool) -> bool:
        """Enable/disable preheat (reads 0x0025, writes the bit, schedule preserved).

        True if the head accepts (status 0). Raises LocalError/LocalUnavailable otherwise.
        """
        if head.gateway_id not in self._gateways:
            raise tunnel.LocalUnavailable(f"unknown gateway: {head.gateway_id}")
        link = self._open_link(self._gateways[head.gateway_id])
        try:
            mode = tunnel.read_programming_mode(link, head.dev_id, head.node_id)
            if mode is None:
                raise tunnel.LocalError("attribute 0x0025 unreadable (head unreachable)")
            status = tunnel.write_preheat(link, head.dev_id, head.node_id, active, mode)
            return status == 0
        finally:
            link.close()

    def set_override(self, head: Head, celsius: float) -> int:
        """One-off "now" setpoint override via DP 171 (contract §4.4). Returns the published raw
        value (hundredths of °C). Raises LocalError (value out of range) / LocalUnavailable."""
        if head.gateway_id not in self._gateways:
            raise tunnel.LocalUnavailable(f"unknown gateway: {head.gateway_id}")
        link = self._open_link(self._gateways[head.gateway_id])
        try:
            return tunnel.write_setpoint(link, head.dev_id, head.node_id, celsius)
        finally:
            link.close()

    def read_schedule(self, head: Head) -> dict[str, list[dict[str, Any]]]:
        """Read the head's 7-day weekly schedule through the tunnel (read-only).

        Returns ``{weekday: [{"h": "HH:MM", "c": setpoint}]}``. Raises LocalUnavailable on an
        unknown gateway."""
        if head.gateway_id not in self._gateways:
            raise tunnel.LocalUnavailable(f"unknown gateway: {head.gateway_id}")
        link = self._open_link(self._gateways[head.gateway_id])
        try:
            return tunnel.read_schedule(link, head.dev_id, head.node_id)
        finally:
            link.close()

    def write_window_detection(self, head: Head, enabled: bool) -> Any:
        """Write open-window detection (DP 116) through the local tunnel. Returns the published
        value. Raises LocalError/LocalUnavailable. The authoritative read is attribute 0x4051
        (``tunnel.read_window_detection`` / the local survey)."""
        if head.gateway_id not in self._gateways:
            raise tunnel.LocalUnavailable(f"unknown gateway: {head.gateway_id}")
        link = self._open_link(self._gateways[head.gateway_id])
        try:
            return tunnel.write_setting_dp(
                link, head.dev_id, head.node_id, "window_detection", bool(enabled)
            )
        finally:
            link.close()

    def descale(self, head: Head, day: str, hour: str) -> bool:
        """Set the weekly valve descaling day/time (0x4010/0x4011).

        ``day`` = a tunnel weekday name ("monday"..."sunday"); ``hour`` = "HH:MM".
        True if the head accepts (status 0). Raises LocalError (bad day/no response) or
        LocalUnavailable (unknown gateway).
        """
        if head.gateway_id not in self._gateways:
            raise tunnel.LocalUnavailable(f"unknown gateway: {head.gateway_id}")
        link = self._open_link(self._gateways[head.gateway_id])
        try:
            status = tunnel.write_descale(link, head.dev_id, head.node_id, day, hour)
            return status == 0
        finally:
            link.close()
