"""DP decoding tests (synthetic data only - no real data or key)."""

from custom_components.danfoss_ally_cloud.api import decode


def _head(dps, online=True, **kw):
    base = {
        "devId": "dev-synth-1",
        "name": "Salon",
        "category": "wk",
        "productId": "03wvrwpv",
        "nodeId": "node-synth",
        "meshId": "gw-synth",
        "moduleMap": {"zigbee": {"isOnline": online}},
        "dps": dps,
    }
    base.update(kw)
    return base


def test_decode_head_complete():
    dps = {
        "1": True,
        "2": "at_home",
        "3": "Heat",
        "24": 215,  # 21.5 °C
        "16": 210,  # setpoint 21.0 °C
        "34": 95,  # batterie 95 %
        "170": 40,  # ouverture vanne 40 %
        "162": True,  # demande de chaleur
        "25": "close",  # window closed
        "30": False,  # verrou enfant
        "116": True,  # window detection enabled
        "18": 280,  # borne haute 28.0
        "27": 60,  # borne basse 6.0
        "45": 0,  # no fault
    }
    d = decode.decode_device(_head(dps))
    assert d.is_head and d.category == "head"
    assert d.online is True
    assert d.temperature == 21.5
    assert d.setpoint == 21.0
    assert d.setpoints["setpoint"] == 21.0
    assert d.battery == 95
    assert d.valve_opening == 40
    assert d.heat_request is True
    assert d.window_open is False
    assert d.child_lock is False
    assert d.window_detection is True
    assert d.max_setpoint == 28.0
    assert d.min_setpoint == 6.0
    assert d.mode == "at_home"
    assert d.state == "Heat"
    assert d.faults == []


def test_decode_setpoints_per_mode():
    dps = {"118": 210, "119": 170, "114": 190, "120": 160, "121": 150}
    d = decode.decode_device(_head(dps))
    assert d.setpoints == {
        "comfort": 21.0,
        "setback": 17.0,
        "manual": 19.0,
        "pause": 16.0,
        "holiday": 15.0,
    }


def test_decode_active_setpoint_from_occupied_setpoint():
    # Real-hardware R-1 (2026-11-18): on a reduced slot the head still reports the comfort setpoint
    # on DP 16 (temp_set, 210 -> 21.0) but the ACTIVE one on DP 171 (OccupiedSetpoint, centi-°C).
    # The active setpoint wins.
    dps = {"2": "leaving_home", "16": 210, "171": 1400}
    d = decode.decode_device(_head(dps))
    assert d.setpoint == 14.0  # DP 171 (1400 centi-°C), not the comfort 21.0 from DP 16
    assert d.mode == "leaving_home"


def test_decode_active_setpoint_from_mode_when_no_occupied():
    # DP 171 absent but mode + settings present: the active setpoint is the current mode's setting
    # (setback via DP 119), not the comfort DP 16 (that would be the R-1 bug).
    dps = {"2": "leaving_home", "16": 210, "118": 210, "119": 140}
    d = decode.decode_device(_head(dps))
    assert d.setpoint == 14.0


def test_decode_active_setpoint_falls_back_to_temp_set():
    # No DP 171 and no per-mode setting for the current mode: DP 16 (temp_set) is the last resort.
    d = decode.decode_device(_head({"16": 195}))
    assert d.setpoint == 19.5


def test_decode_heating_follows_work_state():
    # work_state (DP 3) is authoritative over the valve: NoHeat with a cracked valve = idle (R-1).
    assert decode.decode_device(_head({"3": "NoHeat", "170": 1})).heating is False
    assert decode.decode_device(_head({"3": "Heat", "170": 0})).heating is True
    # DP 3 absent: fall back to the valve opening.
    assert decode.decode_device(_head({"170": 40})).heating is True
    assert decode.decode_device(_head({"170": 0})).heating is False
    # Neither DP 3 nor a valve reading: unknown.
    assert decode.decode_device(_head({})).heating is None


def test_decode_offline():
    d = decode.decode_device(_head({"24": 200}, online=False))
    assert d.online is False
    assert d.temperature == 20.0


def test_decode_window_open():
    d = decode.decode_device(_head({"25": "open"}))
    assert d.window_open is True


def test_decode_fault_e14_low_battery():
    # bit 13 = E14 "low battery" (8192) - confirmed on real hw 2026-11-06 (decode.FAULT_BITS).
    d = decode.decode_device(_head({"45": 8192}))
    assert len(d.faults) == 1
    assert d.faults[0]["code"] == "E14"
    assert d.faults[0]["bit"] == 13


def test_decode_fault_multiple_bits():
    # E6 (bit 5) + E14 (bit 13) = 32 + 8192 = 8224
    erreurs = decode.decode_fault(8224)
    codes = {e["code"] for e in erreurs}
    assert codes == {"E6", "E14"}


def test_decode_fault_accepts_text_code():
    erreurs = decode.decode_fault("E10")
    assert erreurs[0]["code"] == "E10"


def test_categorie_mapping():
    assert decode.category_of("wk") == "head"
    assert decode.category_of("kg") == "relay"
    assert decode.category_of("wg2") == "gateway"
    assert decode.category_of("inconnu") == "other"


def test_dp_inconnu_reste_dans_dps():
    d = decode.decode_device(_head({"999": "mystere", "24": 200}))
    assert d.dps["999"] == "mystere"


def test_decode_operation_mode_dp172():
    assert decode.decode_operation(1) == (True, False)
    assert decode.decode_operation(3) == (True, True)
    assert decode.decode_operation(0) == (False, False)
    assert decode.decode_operation("2") == (False, True)
    assert decode.decode_operation(None) == (None, None)


def test_decode_schedule_active_montage_incoherence():
    d = decode.decode_device(_head({"172": 1, "149": True}))
    assert d.schedule_active is True and d.preheat is False and d.mounting is True
    assert decode.decode_device(_head({"2": "at_home", "172": 0})).inconsistent is True
    assert decode.decode_device(_head({"2": "at_home", "172": 1})).inconsistent is False
    assert decode.decode_device(_head({"2": "at_home"})).inconsistent is False


def test_head_state_contract_shape():
    d = decode.decode_device(_head({"2": "at_home", "172": 1, "149": False}))
    assert decode.head_state(d, room_id="13000000") == {
        "device_id": "dev-synth-1",
        "name": "Salon",
        "room_id": "13000000",
        "online": True,
        "mode_displayed": "at_home",
        "schedule_active": True,
        "preheat": False,
        "mounting": False,
        "inconsistent": False,
        # Status fields (axis D): absent DPs decode to None / [] (nothing fabricated).
        "battery": None,
        "valve_opening": None,
        "heat_request": None,
        "window_open": None,
        "window_detection": None,
        "child_lock": None,
        "faults": [],
    }
