"""Tests d'intégration des actions et des commandes WebSocket (harnais hass)."""

from unittest.mock import patch

import pytest
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.const import DOMAIN

from .common import ENTRY_DATA, FakeCloudClient, tete

_ROOMS = [
    {
        "id": "13000000",
        "name": "Salle 1",
        "home": "Maison",
        "product_id": "03wvrwpv",
        "members": ["a", "b"],
    }
]
_ROOM_TARGET = {"type": "room", "id": "13000000"}
_VALID_DAYS = {"mon": [{"start": "08:30", "end": "17:30"}]}
_INVALID_DAYS = {"mon": [{"start": "17:30", "end": "08:30"}]}


@pytest.fixture(autouse=True)
def _no_timer(monkeypatch):
    """Pas de timer de vérification différée dans ces tests (testé par ailleurs)."""
    monkeypatch.setattr(ops, "_defer_verification", lambda *a, **k: None)


@pytest.fixture
async def setup(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    fake = FakeCloudClient(devices=[tete("a", "Salle 1 #2"), tete("b", "Salle 1 #3")], rooms=_ROOMS)
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    yield hass, entry, fake
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


# --- Actions (services) ------------------------------------------------------------------------


async def test_service_get_rooms(setup):
    hass, _, _ = setup
    res = await hass.services.async_call(
        DOMAIN, "get_rooms", {}, blocking=True, return_response=True
    )
    assert res["rooms"][0]["id"] == "13000000"
    assert [h["device_id"] for h in res["rooms"][0]["heads"]] == ["a", "b"]


async def test_service_set_schedule_invalide_n_envoie_rien(setup):
    hass, _, fake = setup
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_schedule",
            {"target": _ROOM_TARGET, "days": _INVALID_DAYS},
            blocking=True,
            return_response=True,
        )
    assert fake.writes == []  # refus avant tout envoi (R1)


async def test_service_set_schedule_valide_cree_un_lot(setup):
    hass, _, fake = setup
    res = await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {"target": _ROOM_TARGET, "days": _VALID_DAYS},
        blocking=True,
        return_response=True,
    )
    assert res["kind"] == "set_schedule" and res["status"] == "sent"
    assert any(w[0] == "set" for w in fake.writes)


async def test_service_set_schedule_refuse_non_admin(setup, hass_read_only_user):
    hass, _, fake = setup
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_schedule",
            {"target": _ROOM_TARGET, "days": _VALID_DAYS},
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    assert fake.writes == []


async def test_service_get_schedule(setup):
    hass, _, _ = setup
    res = await hass.services.async_call(
        DOMAIN, "get_schedule", {"target": _ROOM_TARGET}, blocking=True, return_response=True
    )
    assert res["target"] == _ROOM_TARGET
    assert "mon" in res["days"]


async def test_service_copy_schedule(setup):
    hass, _, fake = setup
    res = await hass.services.async_call(
        DOMAIN,
        "copy_schedule",
        {"source": _ROOM_TARGET, "targets": [_ROOM_TARGET], "days": ["mon"]},
        blocking=True,
        return_response=True,
    )
    assert len(res["jobs"]) == 1
    assert any(w[0] == "set" for w in fake.writes)


async def test_service_get_write_job_inconnu(setup):
    hass, _, _ = setup
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "get_write_job", {"job_id": "inexistant"}, blocking=True, return_response=True
        )


async def test_service_entry_id_inconnu(setup):
    hass, _, _ = setup
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "get_rooms",
            {"config_entry_id": "zzz"},
            blocking=True,
            return_response=True,
        )


async def test_service_restore_puis_get_write_job(setup):
    hass, _, _ = setup
    job = await hass.services.async_call(
        DOMAIN, "restore_schedule", {"target": _ROOM_TARGET}, blocking=True, return_response=True
    )
    assert job["kind"] == "restore"
    got = await hass.services.async_call(
        DOMAIN, "get_write_job", {"job_id": job["job_id"]}, blocking=True, return_response=True
    )
    assert got["job_id"] == job["job_id"]


# --- Commandes WebSocket (handlers appelés en direct : le serveur HTTP n'est pas requis) -------
#
# Le harnais ne peut pas monter le serveur WebSocket ici (import de la pile HTTP en échec, hors de
# ce code). On appelle donc les handlers en direct avec une fausse connexion ; les handlers async
# planifient une tâche de fond que async_block_till_done exécute.

from types import SimpleNamespace  # noqa: E402

from homeassistant.exceptions import Unauthorized  # noqa: E402

from custom_components.danfoss_ally_cloud import websocket_api as ws  # noqa: E402


class _FakeConn:
    def __init__(self, is_admin: bool = True):
        self.user = SimpleNamespace(is_admin=is_admin)
        self.results: dict = {}
        self.errors: list = []
        self.messages: list = []
        self.subscriptions: dict = {}

    def send_result(self, msg_id, result=None):
        self.results[msg_id] = result

    def send_error(self, msg_id, code, message):
        self.errors.append((code, message))

    def send_message(self, message):
        self.messages.append(message)


async def test_ws_rooms_et_validate(setup):
    hass, _, _ = setup
    conn = _FakeConn()
    ws.ws_rooms(hass, conn, {"id": 1, "type": "danfoss_ally_cloud/rooms"})
    assert conn.results[1]["rooms"][0]["id"] == "13000000"

    ws.ws_schedule_validate(
        hass, conn, {"id": 2, "type": "danfoss_ally_cloud/schedule/validate", "days": _INVALID_DAYS}
    )
    assert conn.results[2]["valid"] is False
    assert conn.results[2]["errors"][0]["code"] == "empty_or_reversed"


async def test_ws_info_async(setup):
    hass, _, _ = setup
    conn = _FakeConn(is_admin=True)
    ws.ws_info(hass, conn, {"id": 3, "type": "danfoss_ally_cloud/info"})
    await hass.async_block_till_done()
    assert conn.results[3]["is_admin"] is True
    assert conn.results[3]["version"]
    assert conn.results[3]["local_enabled"] is False


async def test_ws_schedule_set_admin_et_refus(setup):
    hass, _, fake = setup
    admin = _FakeConn(is_admin=True)
    ws.ws_schedule_set(
        hass,
        admin,
        {
            "id": 4,
            "type": "danfoss_ally_cloud/schedule/set",
            "target": _ROOM_TARGET,
            "days": _VALID_DAYS,
        },
    )
    await hass.async_block_till_done()
    assert admin.results[4]["kind"] == "set_schedule"
    assert any(w[0] == "set" for w in fake.writes)

    # Non-administrateur : require_admin refuse (Unauthorized), rien n'est envoyé.
    fake.writes.clear()
    with pytest.raises(Unauthorized):
        ws.ws_schedule_set(
            hass,
            _FakeConn(is_admin=False),
            {
                "id": 5,
                "type": "danfoss_ally_cloud/schedule/set",
                "target": _ROOM_TARGET,
                "days": _VALID_DAYS,
            },
        )
    assert fake.writes == []


async def test_ws_jobs_subscribe(setup):
    hass, _, fake = setup
    conn = _FakeConn()
    ws.ws_jobs_subscribe(hass, conn, {"id": 6, "type": "danfoss_ally_cloud/jobs/subscribe"})
    assert 6 in conn.subscriptions  # abonnement enregistré
    assert 6 in conn.results  # accusé de réception


async def test_ws_schedule_get(setup):
    hass, _, _ = setup
    conn = _FakeConn()
    ws.ws_schedule_get(
        hass,
        conn,
        {
            "id": 7,
            "type": "danfoss_ally_cloud/schedule/get",
            "target": _ROOM_TARGET,
            "refresh": False,
        },
    )
    await hass.async_block_till_done()
    assert conn.results[7]["target"] == _ROOM_TARGET


async def test_ws_schedule_restore(setup):
    hass, _, fake = setup
    conn = _FakeConn()
    ws.ws_schedule_restore(
        hass, conn, {"id": 8, "type": "danfoss_ally_cloud/schedule/restore", "target": _ROOM_TARGET}
    )
    await hass.async_block_till_done()
    assert conn.results[8]["kind"] == "restore"
    assert any(w[0] == "restore" for w in fake.writes)


async def test_ws_sans_compte(hass):
    # Aucun compte configuré : _store renvoie None -> erreur, rien d'autre.
    conn = _FakeConn()
    ws.ws_rooms(hass, conn, {"id": 9, "type": "danfoss_ally_cloud/rooms"})
    assert conn.errors and conn.errors[0][0] == "unknown_target"
