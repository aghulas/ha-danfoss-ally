"""Local tunnel manager: survey and write of the preheat state (attribute 0x0025).

Isolates the blocking I/O (tinytuya): the HA layer calls it in the executor. One thread per gateway,
best-effort (an unreachable head -> None, never an exception propagated to the global survey). The
link factory is injectable (``open_link``) for tests (a networkless double).
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..keys import GatewayKey
from . import tunnel

_LOGGER = logging.getLogger(__name__)


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

    def survey_preheat(self, heads: list[Head]) -> dict[str, bool | None]:
        """Read preheat (0x0025 bit 1) per head, one gateway per thread. Best-effort."""
        res: dict[str, bool | None] = {}
        lock = threading.Lock()
        by_gw: dict[str, list[Head]] = defaultdict(list)
        for h in heads:
            if h.gateway_id in self._gateways:
                by_gw[h.gateway_id].append(h)

        def worker(gw_id: str, mine: list[Head]) -> None:
            try:
                link = self._open_link(self._gateways[gw_id])
            except Exception as err:  # noqa: BLE001 - gateway unreachable: heads = None
                _LOGGER.debug("local tunnel: gateway %s unreachable (%s)", gw_id, err)
                with lock:
                    for h in mine:
                        res[h.dev_id] = None
                return
            try:
                for h in mine:
                    try:
                        v = tunnel.read_preheat(link, h.dev_id, h.node_id)
                    except Exception:  # noqa: BLE001 - isolate each head
                        v = None
                    with lock:
                        res[h.dev_id] = v
            finally:
                link.close()

        threads = [
            threading.Thread(target=worker, args=(g, m), daemon=True) for g, m in by_gw.items()
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=40)
        return res

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
