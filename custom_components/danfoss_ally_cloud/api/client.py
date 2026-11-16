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

from ._tuya.http import ENDPOINTS, TuyaApiError, TuyaHttpClient, login
from .decode import DanfossDevice, decoder

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

    async def _request(
        self, api: str, version: str, body=None, extra_params=None, _retry: bool = True
    ):
        """Requête ``m.*`` dans l'executor, avec re-login unique sur erreur de session."""
        async with self._lock:
            await self._ensure_client()
            client = self._client
            assert client is not None
            try:
                return await asyncio.to_thread(
                    client.request, api, version, body, extra_params=extra_params
                )
            except TuyaApiError as err:
                if _retry and _is_session_error(err):
                    _LOGGER.debug("session cloud invalide (%s) : re-login", err.code)
                    await self.async_login()
                    return await self._request(api, version, body, extra_params, _retry=False)
                raise CloudError(f"cloud Tuya : {err.code} {err.msg}") from err

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

    async def async_validate(self) -> list[dict]:
        """Login + lecture de contrôle (maisons). Lève CloudAuthError/CloudError si échec."""
        await self.async_login()
        return await self.async_get_homes()

    async def async_close(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
            self._client = None
