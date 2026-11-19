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


# --- cloud-MQTT write path: proven DPs, candidates, supervised trial -----------------------------


def test_mqtt_dp_open_only_for_proven_or_supervised_candidates():
    from custom_components.danfoss_ally_cloud.api import writes

    assert writes.MQTT_WRITE_DPS.isdisjoint(writes.MQTT_CANDIDATE_DPS)
    for dp in writes.MQTT_WRITE_DPS:
        assert writes.mqtt_dp_open(dp) is True
    for dp in writes.MQTT_CANDIDATE_DPS:
        assert writes.mqtt_dp_open(dp) is False  # closed by default
        assert writes.mqtt_dp_open(dp, frozenset({dp})) is True
    # Neither proven nor candidate: never open, whatever is listed.
    assert writes.mqtt_dp_open(2, frozenset({2})) is False


def test_mqtt_write_value_messages_and_types():
    import pytest

    from custom_components.danfoss_ally_cloud.api import CloudWriteError, writes

    assert writes.mqtt_write_value(30, True) is True
    assert writes.mqtt_write_value(116, False) is False  # proven since 2026-11-19
    assert writes.mqtt_write_value(118, 205, frozenset({118})) == 205
    with pytest.raises(CloudWriteError, match="supervised first write"):
        writes.mqtt_write_value(118, 205)  # a candidate, closed by default
    with pytest.raises(CloudWriteError, match="not enabled"):
        writes.mqtt_write_value(2, "manual", frozenset({2}))
    with pytest.raises(CloudWriteError, match="boolean"):
        writes.mqtt_write_value(116, "true")


def test_mqtt_proven_and_candidate_sets():
    """The sets as established on real hardware: a DP moves from candidate to proven only after
    its own supervised write (docs/first-write-procedure.md)."""
    from custom_components.danfoss_ally_cloud.api import writes

    assert sorted(writes.MQTT_WRITE_DPS) == [18, 27, 30, 116, 120]
    assert sorted(writes.MQTT_CANDIDATE_DPS) == [16, 118, 119]


def test_mqtt_write_value_tenths_range_and_step():
    import pytest

    from custom_components.danfoss_ally_cloud.api import CloudWriteError, writes

    # Bounds and pause setpoint are proven: no trial needed.
    assert writes.mqtt_write_value(18, 345) == 345
    assert writes.mqtt_write_value(27, 50) == 50
    assert writes.mqtt_write_value(120, 55) == 55
    for dp, bad in ((18, 195), (18, 355), (27, 45), (27, 205), (120, 45), (18, 301)):
        with pytest.raises(CloudWriteError, match="out of range"):
            writes.mqtt_write_value(dp, bad)
    for bad in (30.0, "300", True):
        with pytest.raises(CloudWriteError, match="integer"):
            writes.mqtt_write_value(18, bad)
    # The remaining candidates follow the same value rule once opened, and stay closed otherwise.
    trial = frozenset({118, 16, 119})
    assert writes.mqtt_write_value(119, 170, trial) == 170
    with pytest.raises(CloudWriteError, match="out of range"):
        writes.mqtt_write_value(119, 45, trial)
    with pytest.raises(CloudWriteError, match="supervised first write"):
        writes.mqtt_write_value(119, 170)  # closed by default
