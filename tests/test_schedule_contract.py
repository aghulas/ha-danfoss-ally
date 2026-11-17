"""Tests de la couche « contrat » de schedule.py (jours anglais, R1, modèle) — synthétiques."""

from custom_components.danfoss_ally_cloud.api import schedule as sch


def _r(start, end):
    return {"start": start, "end": end}


def test_loop_dimanche_en_premier():
    assert sch.day_to_loop("sun") == "1000000"
    assert sch.day_to_loop("mon") == "0100000"
    assert sch.day_to_loop("sat") == "0000001"
    assert sch.loop_to_days("0100000") == ["mon"]


def test_decode_week_timer_minutes_vers_hhmm():
    data = [
        {"loops": "0100000", "loopData": [{"startTime": 510, "endTime": 1050, "mode": "at_home"}]}
    ]
    days = sch.decode_week_timer(data)
    assert days["mon"] == [_r("08:30", "17:30")]
    assert days["wed"] == []
    assert set(days) == set(sch.DAYS)


def test_transitions_trois_plages_separees_vaut_six():
    jour = [_r("06:00", "08:00"), _r("12:00", "14:00"), _r("18:00", "20:00")]
    n, minuit = sch.count_transitions(jour)
    assert n == 6 and minuit is True
    assert sch.validate_day("mon", jour) == []


def test_transitions_minuit_et_plages_qui_se_touchent():
    assert sch.count_transitions([_r("00:00", "08:00")]) == (1, False)
    assert sch.count_transitions([_r("08:00", "12:00"), _r("12:00", "17:00")])[0] == 3


def test_fin_a_2359_valide():
    assert sch.validate_day("mon", [_r("08:30", "23:59")]) == []


def test_quatre_plages_refusees():
    jour = [_r("02:00", "03:00"), _r("06:00", "07:00"), _r("10:00", "11:00"), _r("14:00", "15:00")]
    err = sch.validate_day("mon", jour)
    assert [e["code"] for e in err] == [sch.ERR_TOO_MANY] and err[0]["day"] == "mon"


def test_codes_erreur():
    assert sch.validate_day("mon", [_r("8:30", "17:30")])[0]["code"] == sch.ERR_INVALID_TIME
    assert sch.validate_day("mon", [_r("17:30", "08:30")])[0]["code"] == sch.ERR_EMPTY_OR_REVERSED
    chev = sch.validate_day("mon", [_r("08:00", "12:00"), _r("11:00", "14:00")])
    assert chev[0]["code"] == sch.ERR_OVERLAP


def test_validate_days_agrege_et_jour_vide_valide():
    days = {"mon": [_r("08:30", "17:30")], "wed": [], "fri": [_r("17:30", "08:30")]}
    err = sch.validate_days(days)
    assert len(err) == 1 and err[0]["day"] == "fri"


def test_transitions_per_day():
    assert sch.transitions_per_day({"mon": [_r("08:30", "17:30")], "tue": []}) == {
        "mon": 2,
        "tue": 0,
    }


def test_to_periods_trie():
    assert sch.to_periods([_r("18:00", "20:00"), _r("08:30", "12:00")]) == [
        {"startTime": "08:30", "endTime": "12:00"},
        {"startTime": "18:00", "endTime": "20:00"},
    ]


def test_schedule_to_dict_forme_contrat():
    d = sch.Schedule(
        target={"type": "room", "id": "13000000"},
        name="Salle 1",
        comfort=21.0,
        setback=14.0,
        days={"mon": [_r("08:30", "17:30")]},
        read_at="2026-11-16T15:36:00+01:00",
    ).to_dict()
    assert d["max_transitions_per_day"] == 6 and d["source"] == "cloud"
    assert set(d["days"]) == set(sch.DAYS)
    assert d["days"]["mon"] == [_r("08:30", "17:30")] and d["days"]["sun"] == []
