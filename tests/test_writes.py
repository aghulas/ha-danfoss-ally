"""Tests de la sûreté d'écriture et des payloads (données synthétiques, client mocké)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.danfoss_ally_cloud.api import (
    CloudWriteError,
    DanfossDevice,
    ecriture_autorisee,
    encode_consigne,
)
from custom_components.danfoss_ally_cloud.climate import DanfossClimate
from custom_components.danfoss_ally_cloud.switch import SWITCHES, DanfossSwitch


def _dev(product_id="03wvrwpv", mode="at_home"):
    return DanfossDevice(
        id="dev-synth-1",
        nom="Salon",
        categorie="tete",
        product_id=product_id,
        en_ligne=True,
        temperature=20.0,
        consigne=20.0,
        mode=mode,
    )


def _coord(dev):
    coord = MagicMock()
    coord.data = {dev.id: dev}
    coord.client.async_write_setting = AsyncMock(return_value={"ok": True})
    coord.client.async_set_room_setpoint = AsyncMock(return_value="90000001")
    coord.async_request_refresh = AsyncMock()
    return coord


def test_ecriture_autorisee():
    assert ecriture_autorisee(_dev("03wvrwpv")) is True
    assert ecriture_autorisee(_dev("autre")) is False
    assert ecriture_autorisee(_dev(None)) is False


def test_encode_consigne_arrondi_et_bornes():
    assert encode_consigne(21.0, 5.0, 35.0) == 210
    assert encode_consigne(21.2, 5.0, 35.0) == 210  # arrondi au pas 0,5
    assert encode_consigne(21.3, 5.0, 35.0) == 215
    with pytest.raises(CloudWriteError):
        encode_consigne(40.0, 5.0, 35.0)
    with pytest.raises(CloudWriteError):
        encode_consigne("chaud", 5.0, 35.0)


async def test_climate_set_temperature_ecrit_consigne_piece():
    dev = _dev(mode="at_home")
    coord = _coord(dev)
    ent = DanfossClimate(coord, dev.id)
    await ent.async_set_temperature(temperature=21.0)
    coord.client.async_set_room_setpoint.assert_awaited_once_with(dev.id, {"118": 210})
    coord.client.async_write_setting.assert_not_awaited()  # plus de DP16/mode sur la tête
    coord.async_request_refresh.assert_awaited_once()


async def test_climate_refuse_modele_non_autorise():
    dev = _dev("autre")
    coord = _coord(dev)
    ent = DanfossClimate(coord, dev.id)
    await ent.async_set_temperature(temperature=21.0)
    coord.client.async_set_room_setpoint.assert_not_awaited()


async def test_switch_verrou_enfant_envoie_dp30():
    dev = _dev()
    coord = _coord(dev)
    desc = next(d for d in SWITCHES if d.key == "verrou_enfant")
    ent = DanfossSwitch(coord, dev.id, desc)
    await ent.async_turn_on()
    coord.client.async_write_setting.assert_awaited_once_with(dev.id, dev.product_id, {"30": True})
    await ent.async_turn_off()
    coord.client.async_write_setting.assert_awaited_with(dev.id, dev.product_id, {"30": False})
