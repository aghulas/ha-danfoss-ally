"""Client de l'API cloud (non publique, celle de l'application) Danfoss Ally — voie 1a.

Enveloppe asynchrone de la pile Tuya vendue (``_tuya``). Auth par compte de l'app (login
email/mot de passe) + matériel d'installation capturé une fois (sign_key, deviceId, chKey).
Expose : login, liste des maisons, liste des têtes décodées. Lecture seule pour la v0.1.

La ré-authentification est robuste : Tuya peut invalider la session quand l'app se reconnecte ;
sur une erreur de session, on relogge une fois puis on rejoue la requête.

SECRETS : sign_key, sid, ecode, chKey et le mot de passe ne sont JAMAIS journalisés.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from . import schedule
from ._tuya.http import ENDPOINTS, TuyaApiError, TuyaHttpClient, login
from .const import RES_TYPE_DEVICE, RES_TYPE_GROUP
from .decode import DanfossDevice, decoder, etat_tete

# DP publiables au niveau PIÈCE — liste blanche (contrat §4.2) : 118 confort, 109+119 réduit,
# 1 pré-chauffage, 30 verrou, 116 fenêtre, 18 borne haute, 2 mode (manual/at_home seulement).
_ROOM_DP_WHITELIST = frozenset({"118", "109", "119", "1", "30", "116", "18", "2"})
_ROOM_DP2_ALLOWED = frozenset({"manual", "at_home"})

_LOGGER = logging.getLogger(__name__)

# Codes d'erreur Tuya qui signalent une session à renouveler.
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
    """Erreur du canal cloud voie 1a (login refusé, session, refus du cloud)."""


class CloudAuthError(CloudError):
    """Identifiants ou secrets d'installation refusés (login impossible)."""


class CloudWriteError(CloudError):
    """Écriture refusée : valeur invalide, modèle non autorisé, ou refus du cloud."""


class UnknownTargetError(CloudError):
    """Cible (pièce ou tête) introuvable dans les maisons (contrat code `unknown_target`)."""


class ScheduleValidationError(CloudWriteError):
    """Programme invalide (R1) : refusé AVANT tout envoi. Porte les erreurs du contrat (§5.4)."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        codes = ", ".join(e.get("code", "?") for e in errors)
        super().__init__(f"programme invalide : {codes}")


def _is_session_error(err: TuyaApiError) -> bool:
    code = (str(err.code) if err.code is not None else "").upper()
    if code in _SESSION_ERRORS:
        return True
    msg = (err.msg or "").lower()
    return "session" in msg or "sign invalid" in msg or "token is expired" in msg


class CloudClient:
    """Accès cloud via l'API de l'application mobile (voie 1a)."""

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
        """Matériel de session courant (sid/ecode) — à persister dans l'entrée HA."""
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
        """Ouvre une session (login email/mot de passe) et prépare le client HTTP."""
        try:
            res = await asyncio.to_thread(self._login_sync)
        except TuyaApiError as err:
            raise CloudAuthError(f"login refusé : {err.code} {err.msg}") from err
        if not res.get("sid") or not res.get("ecode"):
            raise CloudAuthError("login sans sid/ecode : identifiants ou secrets invalides.")
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
        """Un seul essai de requête ``m.*`` dans l'executor, sous verrou.

        Laisse remonter ``TuyaApiError`` brut : l'orchestration (re-login + rejeu) se fait
        HORS du verrou, car ``asyncio.Lock`` n'est pas réentrant (un rejeu sous verrou
        tenu se bloquerait indéfiniment).
        """
        async with self._lock:
            await self._ensure_client()
            client = self._client
            assert client is not None
            return await asyncio.to_thread(
                client.request, api, version, body, extra_params=extra_params
            )

    async def _request(self, api: str, version: str, body=None, extra_params=None):
        """Requête ``m.*`` avec re-login unique sur erreur de session, puis rejeu."""
        try:
            return await self._request_once(api, version, body, extra_params)
        except TuyaApiError as err:
            if not _is_session_error(err):
                raise CloudError(f"cloud Tuya : {err.code} {err.msg}") from err
            _LOGGER.debug("session cloud invalide (%s) : re-login", err.code)
            await self.async_login()
            try:
                return await self._request_once(api, version, body, extra_params)
            except TuyaApiError as err2:
                raise CloudError(f"cloud Tuya : {err2.code} {err2.msg}") from err2

    async def async_get_homes(self) -> list[dict]:
        """Liste des maisons du compte (tuya.m.location.list). Renvoie [{gid, nom}]."""
        r = await self._request("tuya.m.location.list", "2.0", None)
        out: list[dict] = []
        for h in r if isinstance(r, list) else []:
            gid = h.get("groupId") or h.get("gid") or h.get("homeId")
            if gid is not None:
                out.append({"gid": gid, "nom": h.get("name")})
        return out

    async def async_list_devices(self) -> list[DanfossDevice]:
        """Toutes les têtes (et autres sous-appareils) des maisons du compte, décodées."""
        devices: list[DanfossDevice] = []
        seen: set[str] = set()
        for home in await self.async_get_homes():
            raw = await self._request(
                "tuya.m.my.group.device.list", "1.0", None, extra_params={"gid": home["gid"]}
            )
            for appareil in raw if isinstance(raw, list) else []:
                dev = decoder(appareil)
                if dev.id and dev.id not in seen:
                    seen.add(dev.id)
                    devices.append(dev)
        return devices

    async def async_list_raw(self) -> list[dict]:
        """Appareils bruts de toutes les maisons (devId, name, category, localKey, meshId, nodeId).

        Utile au repli local : la localKey des passerelles est dans le champ `localKey` (voie 1a).
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
        """Méta d'une passerelle (smartlife.m.device.get v4.0 → meta) : lan_ip, canal Zigbee."""
        r = await self._request("smartlife.m.device.get", "4.0", {"devId": dev_id})
        meta = (r.get("meta") or {}) if isinstance(r, dict) else {}
        return {
            "nom": r.get("name") if isinstance(r, dict) else None,
            "lan_ip": meta.get("lan_ip"),
            "canal": meta.get("zigChannel"),
        }

    async def async_write_setting(self, dev_id: str, pid: str, dps: dict) -> object:
        """Écrit des DP de réglage sur une TÊTE (tuya.m.custom.wkf.settings.change, resType 1).

        Mécanisme prouvé par capture (voir danfoss-ally-mcp) pour les DP de l'écran « Setting »
        (verrou enfant, détection fenêtre, consigne…). `dps` = {str(dp): valeur}. Une tête GROUPÉE
        en pièce se règle normalement par sa pièce (groupe) — non géré en v0.2.

        ⚠ L'effet réel sur la tête reste à confirmer en réel (certains réglages par cette voie
        n'avaient pas atteint toutes les têtes isolées lors des essais du MCP).
        """
        if not dev_id or not pid:
            raise CloudWriteError("devId/pid requis pour l'écriture.")
        body = {
            "devId": dev_id,
            "gwId": dev_id,
            "pid": pid,
            "resId": dev_id,
            "resType": 1,
            "settings": json.dumps(dps, separators=(",", ":")),
        }
        return await self._request("tuya.m.custom.wkf.settings.change", "1.0", body)

    # --- Écriture de consigne DURABLE au niveau PIÈCE (groupe), voie 1a « vraie » ---------------
    # Remplace l'approche fausse de PR #8 (DP du mode sur la tête). Voir api/const.py
    # (MODE_GROUP_SETPOINT_DP) : publier la consigne sur le GROUPE, puis réécrire un jour du
    # programme pour que les têtes reprennent la valeur dans leurs transitions.

    async def async_list_groups(self, gid: str | int) -> list[dict]:
        """Pièces (groupes Tuya) d'une maison (m.life.my.group.device.group.list v4.3).

        Renvoie [{group_id, nom, nb_tetes, pid}]. Une pièce multi-têtes se pilote par son GROUPE.
        """
        r = await self._request("m.life.my.group.device.group.list", "4.3", {"gid": gid})
        out: list[dict] = []
        for g in r if isinstance(r, list) else []:
            gid5 = g.get("id") or g.get("groupId")
            if gid5 is not None:
                out.append(
                    {
                        "group_id": gid5,
                        "nom": g.get("name"),
                        "nb_tetes": g.get("deviceNum"),
                        "pid": g.get("productId"),
                    }
                )
        return out

    async def async_group_members(self, gid: str | int) -> dict[str, list[str]]:
        """Têtes membres de chaque pièce (m.life.my.group.device.relation.list v3.2).

        Renvoie {group_id (str): [devId, ...]} : clé « 5 » = groupes-programme (type 5), leurs
        enfants « 6 » = têtes membres.
        """
        rel = await self._request("m.life.my.group.device.relation.list", "3.2", {"gid": gid})
        out: dict[str, list[str]] = {}
        for entry in rel.get("5", []) if isinstance(rel, dict) else []:
            group_id = str(entry.get("id"))
            children = (entry.get("children") or {}).get("6") or []
            out[group_id] = [c.get("id") for c in children if c.get("id")]
        return out

    async def async_resolve_group(self, dev_id: str) -> tuple[str, str | None] | None:
        """Trouve la pièce (groupe) d'une tête : (group_id, pid), ou None si non groupée.

        Une tête NON groupée n'a pas de méthode de consigne voie-1a prouvée (le connecteur passe
        alors par l'API officielle Danfoss) : l'appelant doit refuser plutôt que mentir.
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
        """Publie des DP sur une PIÈCE (groupe) : s.m.dev.group.dp.publish {dps, groupId}."""
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
        """Programme hebdomadaire brut (tuya.m.custom.wkf.week.timer.list) : [{loops, loopData}]."""
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
        """Réécrit UN jour du programme : delete puis create.

        ``periods`` = fenêtres de confort « HH:MM ». ``loops`` = masque d'un seul jour (bit 0 =
        dimanche). ``periods`` vide = jour éteint (pas de create). Deux appels v1.0, corps
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

    async def async_set_room_setpoint(self, dev_id: str, dps: dict, *, repush: bool = True) -> str:
        """Écrit une consigne DURABLE pour la pièce d'une tête (voie 1a « vraie »).

        1. résout la pièce (groupe) de la tête — refuse si la tête n'est pas groupée ;
        2. publie ``dps`` (ex. {"118": 60} confort, {"109": 60, "119": 60} réduit) sur le groupe ;
        3. si ``repush``, réécrit UN jour du programme à l'identique pour que les têtes reprennent
           la nouvelle consigne dans leurs transitions (sinon elles gardent l'ancienne).

        ⚠ Effet de pièce : toutes les têtes du groupe sont concernées, et le ré-envoi touche la
        vraie prog de chauffe. À valider en réel avant tout usage (voir CLAUDE.md, mémoires).
        Renvoie l'identifiant du groupe écrit.
        """
        resolved = await self.async_resolve_group(dev_id)
        if resolved is None:
            raise CloudWriteError(
                f"tête {dev_id} non groupée : consigne voie-1a non prouvée hors pièce."
            )
        group_id, pid = resolved
        await self.async_group_publish(group_id, dps)
        if repush and pid:
            data = await self.async_read_week_timer(group_id, pid)
            jour = schedule.premier_jour_confort(data)
            if jour is not None:
                await self.async_write_week_day(
                    group_id,
                    pid,
                    jour["loops"],
                    schedule.confort_periods(jour.get("loopData")),
                )
        return str(group_id)

    # --- Couche « contrat » (pièces, programme, état) bâtie sur les primitives ci-dessus --------

    async def async_room_structure(self) -> list[dict]:
        """Ossature des pièces (sans dps) : {id, name, home, product_id, members:[devId]}."""
        out: list[dict] = []
        for home in await self.async_get_homes():
            members = await self.async_group_members(home["gid"])
            for g in await self.async_list_groups(home["gid"]):
                group_id = str(g["group_id"])
                out.append(
                    {
                        "id": group_id,
                        "name": g.get("nom"),
                        "home": home.get("nom"),
                        "product_id": g.get("pid"),
                        "members": members.get(group_id, []),
                    }
                )
        return out

    async def async_list_rooms(self) -> list[dict]:
        """Pièces de toutes les maisons avec leurs têtes (contrat §1, §3.4)."""
        rooms: list[dict] = []
        for home in await self.async_get_homes():
            members = await self.async_group_members(home["gid"])
            raw = await self._request(
                "tuya.m.my.group.device.list", "1.0", None, extra_params={"gid": home["gid"]}
            )
            by_id = {d.get("devId"): d for d in (raw or []) if isinstance(d, dict)}
            for g in await self.async_list_groups(home["gid"]):
                group_id = str(g["group_id"])
                heads: list[dict] = []
                comfort: float | None = None
                setback: float | None = None
                for dev_id in members.get(group_id, []):
                    if dev_id not in by_id:
                        continue
                    dev = decoder(by_id[dev_id])
                    heads.append(etat_tete(dev, group_id))
                    comfort = comfort if comfort is not None else dev.consignes.get("confort")
                    setback = setback if setback is not None else dev.consignes.get("reduit")
                rooms.append(
                    {
                        "id": group_id,
                        "name": g.get("nom"),
                        "home": home.get("nom"),
                        "product_id": g.get("pid"),
                        "heads": heads,
                        "comfort": comfort,
                        "setback": setback,
                    }
                )
        return rooms

    async def _resolve_target(self, target: dict) -> dict:
        """Résout {type, id} en {res_id, res_type, pid, gw_id, name, comfort, setback}.

        Pièce : resType 2, gwId = group_id. Tête isolée : resType 1, gwId = meshId (forme rejouée
        en réel ; le contrat §4.1 indique devId — divergence connue).
        """
        kind = target.get("type")
        ident = str(target.get("id"))
        if kind == "room":
            for home in await self.async_get_homes():
                for g in await self.async_list_groups(home["gid"]):
                    if str(g["group_id"]) != ident:
                        continue
                    members = await self.async_group_members(home["gid"])
                    raw = await self._request(
                        "tuya.m.my.group.device.list",
                        "1.0",
                        None,
                        extra_params={"gid": home["gid"]},
                    )
                    by_id = {d.get("devId"): d for d in (raw or []) if isinstance(d, dict)}
                    comfort = setback = None
                    for dev_id in members.get(ident, []):
                        if dev_id in by_id:
                            dev = decoder(by_id[dev_id])
                            if comfort is None:
                                comfort = dev.consignes.get("confort")
                            if setback is None:
                                setback = dev.consignes.get("reduit")
                    return {
                        "res_id": ident,
                        "res_type": RES_TYPE_GROUP,
                        "pid": g.get("pid"),
                        "gw_id": ident,
                        "name": g.get("nom"),
                        "comfort": comfort,
                        "setback": setback,
                    }
        elif kind == "device":
            for home in await self.async_get_homes():
                raw = await self._request(
                    "tuya.m.my.group.device.list", "1.0", None, extra_params={"gid": home["gid"]}
                )
                for d in raw or []:
                    if isinstance(d, dict) and d.get("devId") == ident:
                        dev = decoder(d)
                        return {
                            "res_id": ident,
                            "res_type": RES_TYPE_DEVICE,
                            "pid": dev.product_id,
                            "gw_id": dev.mesh_id or ident,
                            "name": dev.nom,
                            "comfort": dev.consignes.get("confort"),
                            "setback": dev.consignes.get("reduit"),
                        }
        raise UnknownTargetError(f"cible introuvable : {target!r}")

    async def async_get_schedule(self, target: dict) -> dict:
        """Programme hebdomadaire d'une cible, décodé (contrat §3.2). Lecture seule."""
        res = await self._resolve_target(target)
        data = await self.async_read_week_timer(
            res["res_id"], res["pid"] or "", res_type=res["res_type"], gw_id=res["gw_id"]
        )
        return schedule.Schedule(
            target={"type": str(target.get("type")), "id": str(target.get("id"))},
            name=res.get("name"),
            comfort=res.get("comfort"),
            setback=res.get("setback"),
            days=schedule.decode_week_timer(data),
            read_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        ).to_dict()

    async def async_set_schedule_days(self, target: dict, days: dict) -> dict:
        """Valide (R1) puis écrit les jours fournis (delete+create par jour, via write_week_day)."""
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
        """Retour au programme (R4) : réécrit les SEPT jours, puis publie `at_home` EN DERNIER."""
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

    async def async_publish_room_dps(self, group_id, dps: dict) -> object:
        """Publie des DP de PIÈCE via LISTE BLANCHE (contrat §4.2) puis async_group_publish."""
        for key, value in dps.items():
            if str(key) not in _ROOM_DP_WHITELIST:
                raise CloudWriteError(f"DP de pièce non autorisé : {key}")
            if str(key) == "2" and value not in _ROOM_DP2_ALLOWED:
                raise CloudWriteError(f"DP 2 limité à manual/at_home (reçu {value!r})")
        return await self.async_group_publish(group_id, dps)

    async def async_validate(self) -> list[dict]:
        """Login + lecture de contrôle (maisons). Lève CloudAuthError/CloudError si échec."""
        await self.async_login()
        return await self.async_get_homes()

    async def async_close(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
            self._client = None
