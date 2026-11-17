"""Client for the Danfoss Ally cloud API (the non-public one, used by the app) - path 1a.

Async wrapper around the vendored Tuya stack (``_tuya``). Auth via the app account (email/password
login) + installation material captured once (sign_key, deviceId, chKey). Exposes: login, list of
homes, list of decoded heads. Read-only for v0.1.

Re-authentication is robust: Tuya can invalidate the session when the app reconnects; on a session
error we log in once more then replay the request.

SECRETS: sign_key, sid, ecode, chKey and the password are NEVER logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from . import schedule
from ._tuya.http import ENDPOINTS, TuyaApiError, TuyaHttpClient, login
from .const import RES_TYPE_DEVICE, RES_TYPE_GROUP
from .decode import DanfossDevice, decode_device

_LOGGER = logging.getLogger(__name__)

# Tuya error codes that signal a session to renew.
_SESSION_ERRORS = frozenset(
    {
        "SIGN_INVALID",
        "APP_SESSION_EXPIRED",
        "SESSION_EXPIRED",
        "USER_SESSION_INVALID",
        "RING_SIGN_ERROR",
        "ILLEGAL_CLIENT_ID",
    }
)


class CloudError(RuntimeError):
    """Error on the path-1a cloud channel (login refused, session, cloud refusal)."""


class CloudAuthError(CloudError):
    """Credentials or installation secrets refused (login impossible)."""


class CloudWriteError(CloudError):
    """Write refused: invalid value, model not allowed, or cloud refusal."""


class UnknownTargetError(CloudError):
    """Target (room or head) not found in the homes (contract code `unknown_target`)."""


class ScheduleValidationError(CloudWriteError):
    """Invalid schedule (R1): refused BEFORE any send. Carries the contract errors (§5.4)."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        codes = ", ".join(e.get("code", "?") for e in errors)
        super().__init__(f"invalid schedule: {codes}")


def _is_session_error(err: TuyaApiError) -> bool:
    code = (str(err.code) if err.code is not None else "").upper()
    if code in _SESSION_ERRORS:
        return True
    msg = (err.msg or "").lower()
    return "session" in msg or "sign invalid" in msg or "token is expired" in msg


class CloudClient:
    """Cloud access via the mobile app's API (path 1a)."""

    def __init__(
        self,
        username: str,
        password: str,
        country_code: str,
        sign_key: str,
        device_id: str,
        ch_key: str,
        region: str = "eu",
        *,
        sid: str | None = None,
        ecode: str | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._country_code = country_code
        self._sign_key = sign_key
        self._device_id = device_id
        self._ch_key = ch_key
        self._endpoint = ENDPOINTS.get(region.lower(), ENDPOINTS["eu"])
        self._sid = sid
        self._ecode = ecode
        self._client: TuyaHttpClient | None = None
        self._lock = asyncio.Lock()

    @property
    def session(self) -> dict[str, str | None]:
        """Current session material (sid/ecode) - to persist in the HA entry."""
        return {"sid": self._sid, "ecode": self._ecode}

    def _build_client(self) -> TuyaHttpClient:
        return TuyaHttpClient(
            self._sign_key,
            self._sid or "",
            self._ecode or "",
            self._ch_key,
            self._device_id,
            endpoint=self._endpoint,
        )

    def _login_sync(self) -> dict:
        return login(
            self._username,
            self._password,
            self._country_code,
            self._sign_key,
            self._device_id,
            self._ch_key,
            endpoint=self._endpoint,
        )

    async def async_login(self) -> None:
        """Open a session (email/password login) and prepare the HTTP client."""
        try:
            res = await asyncio.to_thread(self._login_sync)
        except TuyaApiError as err:
            raise CloudAuthError(f"login refused: {err.code} {err.msg}") from err
        if not res.get("sid") or not res.get("ecode"):
            raise CloudAuthError("login without sid/ecode: invalid credentials or secrets.")
        self._sid = res["sid"]
        self._ecode = res["ecode"]
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
        self._client = self._build_client()

    async def _ensure_client(self) -> None:
        if self._client is None:
            if self._sid and self._ecode:
                self._client = self._build_client()
            else:
                await self.async_login()

    async def _request_once(self, api: str, version: str, body, extra_params):
        """A single attempt of an ``m.*`` request in the executor, under the lock.

        Lets ``TuyaApiError`` propagate raw: the orchestration (re-login + replay) happens
        OUTSIDE the lock, because ``asyncio.Lock`` is not reentrant (a replay while holding the
        lock would deadlock forever).
        """
        async with self._lock:
            await self._ensure_client()
            client = self._client
            assert client is not None
            return await asyncio.to_thread(
                client.request, api, version, body, extra_params=extra_params
            )

    async def _request(self, api: str, version: str, body=None, extra_params=None):
        """``m.*`` request with a single re-login on a session error, then replay."""
        try:
            return await self._request_once(api, version, body, extra_params)
        except TuyaApiError as err:
            if not _is_session_error(err):
                raise CloudError(f"Tuya cloud: {err.code} {err.msg}") from err
            _LOGGER.debug("invalid cloud session (%s): re-login", err.code)
            await self.async_login()
            try:
                return await self._request_once(api, version, body, extra_params)
            except TuyaApiError as err2:
                raise CloudError(f"Tuya cloud: {err2.code} {err2.msg}") from err2

    async def async_get_homes(self) -> list[dict]:
        """List of the account's homes (tuya.m.location.list). Returns [{gid, name}]."""
        r = await self._request("tuya.m.location.list", "2.0", None)
        out: list[dict] = []
        for h in r if isinstance(r, list) else []:
            gid = h.get("groupId") or h.get("gid") or h.get("homeId")
            if gid is not None:
                out.append({"gid": gid, "name": h.get("name")})
        return out

    async def async_list_devices(self) -> list[DanfossDevice]:
        """All heads (and other sub-devices) of the account's homes, decoded."""
        devices: list[DanfossDevice] = []
        seen: set[str] = set()
        for home in await self.async_get_homes():
            raw = await self._request(
                "tuya.m.my.group.device.list", "1.0", None, extra_params={"gid": home["gid"]}
            )
            for device in raw if isinstance(raw, list) else []:
                dev = decode_device(device)
                if dev.id and dev.id not in seen:
                    seen.add(dev.id)
                    devices.append(dev)
        return devices

    async def async_list_raw(self) -> list[dict]:
        """Raw devices of all homes (devId, name, category, localKey, meshId, nodeId).

        Useful for the local fallback: the gateways' localKey is in the `localKey` field (path 1a).
        """
        out: list[dict] = []
        seen: set[str] = set()
        for home in await self.async_get_homes():
            raw = await self._request(
                "tuya.m.my.group.device.list", "1.0", None, extra_params={"gid": home["gid"]}
            )
            for d in raw if isinstance(raw, list) else []:
                dev_id = d.get("devId") if isinstance(d, dict) else None
                if dev_id and dev_id not in seen:
                    seen.add(dev_id)
                    out.append(d)
        return out

    async def async_device_meta(self, dev_id: str) -> dict:
        """Gateway meta (smartlife.m.device.get v4.0 -> meta): lan_ip, Zigbee channel."""
        r = await self._request("smartlife.m.device.get", "4.0", {"devId": dev_id})
        meta = (r.get("meta") or {}) if isinstance(r, dict) else {}
        return {
            "name": r.get("name") if isinstance(r, dict) else None,
            "lan_ip": meta.get("lan_ip"),
            "channel": meta.get("zigChannel"),
        }

    async def async_write_setting(self, dev_id: str, pid: str, dps: dict) -> object:
        """Write setting DPs on a HEAD (tuya.m.custom.wkf.settings.change, resType 1).

        Mechanism proven by capture (see danfoss-ally-mcp) for the "Setting" screen DPs (child lock,
        window detection, setpoint...). `dps` = {str(dp): value}. A head GROUPED into a room is
        normally set through its room (group) - not handled in v0.2.

        ⚠ The real effect on the head is still to confirm on real hardware (some settings via this
        path had not reached every isolated head in the MCP trials).
        """
        if not dev_id or not pid:
            raise CloudWriteError("devId/pid required for the write.")
        body = {
            "devId": dev_id,
            "gwId": dev_id,
            "pid": pid,
            "resId": dev_id,
            "resType": 1,
            "settings": json.dumps(dps, separators=(",", ":")),
        }
        return await self._request("tuya.m.custom.wkf.settings.change", "1.0", body)

    # --- DURABLE setpoint write at ROOM level (group), the "real" path 1a ------------------------
    # Replaces the wrong approach of PR #8 (mode DP on the head). See api/const.py
    # (MODE_GROUP_SETPOINT_DP): publish the setpoint on the GROUP, then rewrite one schedule day so
    # the heads pick up the value in their transitions.

    async def async_list_groups(self, gid: str | int) -> list[dict]:
        """Rooms (Tuya groups) of a home (m.life.my.group.device.group.list v4.3).

        Returns [{group_id, name, head_count, pid}]. A multi-head room is driven by its GROUP.
        """
        r = await self._request("m.life.my.group.device.group.list", "4.3", {"gid": gid})
        out: list[dict] = []
        for g in r if isinstance(r, list) else []:
            gid5 = g.get("id") or g.get("groupId")
            if gid5 is not None:
                out.append(
                    {
                        "group_id": gid5,
                        "name": g.get("name"),
                        "head_count": g.get("deviceNum"),
                        "pid": g.get("productId"),
                    }
                )
        return out

    async def async_group_members(self, gid: str | int) -> dict[str, list[str]]:
        """Member heads of each room (m.life.my.group.device.relation.list v3.2).

        Returns {group_id (str): [devId, ...]}: key "5" = schedule groups (type 5), their children
        "6" = member heads.
        """
        rel = await self._request("m.life.my.group.device.relation.list", "3.2", {"gid": gid})
        out: dict[str, list[str]] = {}
        for entry in rel.get("5", []) if isinstance(rel, dict) else []:
            group_id = str(entry.get("id"))
            children = (entry.get("children") or {}).get("6") or []
            out[group_id] = [c.get("id") for c in children if c.get("id")]
        return out

    async def async_resolve_group(self, dev_id: str) -> tuple[str, str | None] | None:
        """Find a head's room (group): (group_id, pid), or None if not grouped.

        An UNGROUPED head has no proven path-1a setpoint method (the connector then goes through the
        official Danfoss API): the caller must refuse rather than lie.
        """
        for home in await self.async_get_homes():
            gid = home["gid"]
            members = await self.async_group_members(gid)
            group_id = next((g for g, devs in members.items() if dev_id in devs), None)
            if group_id is None:
                continue
            pid = next(
                (
                    g["pid"]
                    for g in await self.async_list_groups(gid)
                    if str(g["group_id"]) == str(group_id)
                ),
                None,
            )
            return (group_id, pid)
        return None

    async def async_group_publish(self, group_id: str | int, dps: dict) -> object:
        """Publish DPs on a ROOM (group): s.m.dev.group.dp.publish {dps, groupId}."""
        return await self._request(
            "s.m.dev.group.dp.publish",
            "1.0",
            {"dps": json.dumps(dps, separators=(",", ":")), "groupId": int(group_id)},
        )

    async def async_read_week_timer(
        self,
        res_id: str | int,
        pid: str,
        *,
        res_type: int = RES_TYPE_GROUP,
        gw_id: str | int | None = None,
    ) -> list[dict]:
        """Raw weekly schedule (tuya.m.custom.wkf.week.timer.list): [{loops, loopData}]."""
        body = {
            "devId": str(res_id),
            "gwId": str(gw_id or res_id),
            "pid": pid,
            "resId": str(res_id),
            "resType": res_type,
        }
        r = await self._request("tuya.m.custom.wkf.week.timer.list", "1.0", body)
        data = r.get("data") if isinstance(r, dict) else r
        return data if isinstance(data, list) else []

    async def async_write_week_day(
        self,
        res_id: str | int,
        pid: str,
        loops: str,
        periods: list[dict],
        *,
        res_type: int = RES_TYPE_GROUP,
        gw_id: str | int | None = None,
    ) -> None:
        """Rewrite ONE schedule day: delete then create.

        ``periods`` = comfort windows "HH:MM". ``loops`` = single-day mask (bit 0 = Sunday).
        Empty ``periods`` = day off (no create). Two v1.0 calls, body
        {devId, gwId, loops, pid, resId, resType}.
        """
        base = {
            "devId": str(res_id),
            "gwId": str(gw_id or res_id),
            "pid": pid,
            "resId": str(res_id),
            "resType": res_type,
        }
        await self._request("tuya.m.custom.wkf.week.timer.delete", "1.0", {**base, "loops": loops})
        if periods:
            await self._request(
                "tuya.m.custom.wkf.week.timer.create",
                "1.0",
                {**base, "loops": loops, "periods": json.dumps(periods)},
            )

    async def async_set_group_setpoint(
        self, group_id: str | int, pid: str | None, dps: dict, *, repush: bool = True
    ) -> None:
        """DURABLE setpoint on a ROOM whose group is already known (the "real" path 1a).

        1. publish ``dps`` (e.g. {"118": 60} comfort, {"109": 60, "119": 60} setback) on the group;
        2. if ``repush`` and ``pid`` known, rewrite ONE schedule day verbatim so the heads pick up
           the new setpoint in their transitions (otherwise they keep the old one).

        ⚠ Room-wide effect: all heads of the group are affected, and the re-send touches the real
        heating schedule. To validate on real hardware before any use (see CLAUDE.md, memories).
        """
        await self.async_group_publish(group_id, dps)
        if repush and pid:
            data = await self.async_read_week_timer(group_id, pid)
            day = schedule.first_comfort_day(data)
            if day is not None:
                await self.async_write_week_day(
                    group_id,
                    pid,
                    day["loops"],
                    schedule.comfort_periods(day.get("loopData")),
                )

    async def async_set_room_setpoint(self, dev_id: str, dps: dict, *, repush: bool = True) -> str:
        """DURABLE setpoint for a head's room, resolving its group first.

        Resolves the head's room (group) - refuses if the head is not grouped - then delegates to
        ``async_set_group_setpoint``. Returns the written group's id. The room climate, which
        already knows its group, calls ``async_set_group_setpoint`` directly.
        """
        resolved = await self.async_resolve_group(dev_id)
        if resolved is None:
            raise CloudWriteError(
                f"head {dev_id} not grouped: path-1a setpoint not proven outside a room."
            )
        group_id, pid = resolved
        await self.async_set_group_setpoint(group_id, pid, dps, repush=repush)
        return str(group_id)

    # --- Weekly schedule editing (contract §3.2), built on the primitives above ------------------

    async def _resolve_target(self, target: dict) -> dict:
        """Resolve {type, id} into {res_id, res_type, pid, gw_id, name}.

        Room: resType 2, gwId = group_id. Isolated head: resType 1, gwId = meshId (form replayed on
        real hardware; contract §4.1 says devId - known divergence).
        """
        kind = target.get("type")
        ident = str(target.get("id"))
        if kind == "room":
            for home in await self.async_get_homes():
                for g in await self.async_list_groups(home["gid"]):
                    if str(g["group_id"]) == ident:
                        return {
                            "res_id": ident,
                            "res_type": RES_TYPE_GROUP,
                            "pid": g.get("pid"),
                            "gw_id": ident,
                            "name": g.get("name"),
                        }
        elif kind == "device":
            for home in await self.async_get_homes():
                raw = await self._request(
                    "tuya.m.my.group.device.list", "1.0", None, extra_params={"gid": home["gid"]}
                )
                for d in raw or []:
                    if isinstance(d, dict) and d.get("devId") == ident:
                        dev = decode_device(d)
                        return {
                            "res_id": ident,
                            "res_type": RES_TYPE_DEVICE,
                            "pid": dev.product_id,
                            "gw_id": dev.mesh_id or ident,
                            "name": dev.name,
                        }
        raise UnknownTargetError(f"target not found: {target!r}")

    async def async_get_schedule(self, target: dict) -> dict:
        """Weekly schedule of a target, decoded (contract §3.2). Read-only."""
        res = await self._resolve_target(target)
        data = await self.async_read_week_timer(
            res["res_id"], res["pid"] or "", res_type=res["res_type"], gw_id=res["gw_id"]
        )
        return schedule.Schedule(
            target={"type": str(target.get("type")), "id": str(target.get("id"))},
            name=res.get("name"),
            days=schedule.decode_week_timer(data),
            read_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        ).to_dict()

    async def async_set_schedule_days(self, target: dict, days: dict) -> dict:
        """Validate (R1) then write the given days (delete+create per day, via write_week_day)."""
        errors = schedule.validate_days(days)
        if errors:
            raise ScheduleValidationError(errors)
        res = await self._resolve_target(target)
        written: list[str] = []
        for day, ranges in days.items():
            if day not in schedule.DAYS:
                continue
            await self.async_write_week_day(
                res["res_id"],
                res["pid"] or "",
                schedule.day_to_loop(day),
                schedule.to_periods(ranges),
                res_type=res["res_type"],
                gw_id=res["gw_id"],
            )
            written.append(day)
        return {"target": target, "days_written": written}

    async def async_restore_schedule(self, target: dict) -> dict:
        """Back to schedule (R4): rewrite all SEVEN days, then publish `at_home` LAST."""
        res = await self._resolve_target(target)
        current = await self.async_get_schedule(target)
        days = current["days"]
        for day in schedule.DAYS:
            await self.async_write_week_day(
                res["res_id"],
                res["pid"] or "",
                schedule.day_to_loop(day),
                schedule.to_periods(days.get(day) or []),
                res_type=res["res_type"],
                gw_id=res["gw_id"],
            )
        if res["res_type"] == RES_TYPE_GROUP:
            await self.async_group_publish(res["res_id"], {"2": "at_home"})
        else:
            await self.async_write_setting(res["res_id"], res["pid"] or "", {"2": "at_home"})
        return {"target": target, "restored": True}

    async def async_validate(self) -> list[dict]:
        """Login + a control read (homes). Raises CloudAuthError/CloudError on failure."""
        await self.async_login()
        return await self.async_get_homes()

    async def async_close(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
            self._client = None
