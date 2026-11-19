"""Write-safety and payload tests (synthetic data, mocked client)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.danfoss_ally_cloud.api import (
    CloudWriteError,
    DanfossDevice,
    encode_setpoint,
    write_allowed,
)
from custom_components.danfoss_ally_cloud.switch import SWITCHES, DanfossSwitch


def _dev(product_id="03wvrwpv", mode="at_home"):
    return DanfossDevice(
        id="dev-synth-1",
        name="Salon",
        category="head",
        product_id=product_id,
        online=True,
        temperature=20.0,
        setpoint=20.0,
        mode=mode,
    )


def _coord(dev):
    coord = MagicMock()
    coord.data = {dev.id: dev}
    coord.client.async_write_setting = AsyncMock(return_value={"ok": True})
    coord.async_request_refresh = AsyncMock()
    return coord


def test_ecriture_autorisee():
    assert write_allowed(_dev("03wvrwpv")) is True
    assert write_allowed(_dev("autre")) is False
    assert write_allowed(_dev(None)) is False


def test_encode_setpoint_rounding_and_bounds():
    assert encode_setpoint(21.0, 5.0, 35.0) == 210
    assert encode_setpoint(21.2, 5.0, 35.0) == 210  # arrondi au pas 0,5
    assert encode_setpoint(21.3, 5.0, 35.0) == 215
    with pytest.raises(CloudWriteError):
        encode_setpoint(40.0, 5.0, 35.0)
    with pytest.raises(CloudWriteError):
        encode_setpoint("chaud", 5.0, 35.0)


async def test_switch_verrou_enfant_envoie_dp30_par_la_piece():
    dev = _dev()
    dev.mesh_id = "gw-mesh-1"
    coord = _coord(dev)
    coord.group_of = MagicMock(return_value="g-synth")
    coord.room_members = MagicMock(return_value=(dev.id,))
    coord.client.async_group_publish = AsyncMock(return_value=True)
    desc = next(d for d in SWITCHES if d.key == "child_lock")
    ent = DanfossSwitch(coord, dev.id, desc)
    await ent.async_turn_on()
    # Grouped head: the setting is published on its room (proven path), never settings.change.
    coord.client.async_group_publish.assert_awaited_once_with("g-synth", {"30": True})
    await ent.async_turn_off()
    coord.client.async_group_publish.assert_awaited_with("g-synth", {"30": False})
    coord.client.async_write_setting.assert_not_awaited()


async def test_switch_verrou_enfant_tete_isolee_sans_ecriture():
    dev = _dev()
    coord = _coord(dev)
    coord.group_of = MagicMock(return_value=None)
    desc = next(d for d in SWITCHES if d.key == "child_lock")
    ent = DanfossSwitch(coord, dev.id, desc)
    await ent.async_turn_on()
    # Isolated head (W-3): settings.change is accepted but never applied -> no write at all.
    coord.client.async_write_setting.assert_not_awaited()
