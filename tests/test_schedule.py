"""Tests des aides programme (pures, sans réseau) : décodage et ré-envoi d'un jour."""

from custom_components.danfoss_ally_cloud.api import schedule


def test_hhmm():
    assert schedule.hhmm(0) == "00:00"
    assert schedule.hhmm(510) == "08:30"
    assert schedule.hhmm(1050) == "17:30"
    assert schedule.hhmm(1439) == "23:59"


def test_jour_du_loop():
    assert schedule.jour_du_loop("1000000") == "dimanche"  # bit 0 = dimanche
    assert schedule.jour_du_loop("0100000") == "lundi"
    assert schedule.jour_du_loop("0000001") == "samedi"


def test_confort_periods_convertit_et_filtre():
    loop_data = [
        {"startTime": 510, "endTime": 1050, "mode": "at_home"},
        {"startTime": 1050, "endTime": 1320, "mode": "leaving_home"},  # réduit : ignoré
        {"startTime": 360, "endTime": 420},  # mode absent : confort implicite
    ]
    assert schedule.confort_periods(loop_data) == [
        {"startTime": "08:30", "endTime": "17:30"},
        {"startTime": "06:00", "endTime": "07:00"},
    ]


def test_confort_periods_vide():
    assert schedule.confort_periods(None) == []
    assert schedule.confort_periods([]) == []
    assert schedule.confort_periods([{"startTime": 0, "endTime": 10, "mode": "leaving_home"}]) == []


def test_premier_jour_confort():
    data = [
        {"loops": "1000000", "loopData": []},  # dimanche vide
        {"loops": "0000001", "loopData": [{"startTime": 0, "endTime": 10, "mode": "leaving_home"}]},
        {"loops": "0100000", "loopData": [{"startTime": 510, "endTime": 1050, "mode": "at_home"}]},
    ]
    jour = schedule.premier_jour_confort(data)
    assert jour is not None and jour["loops"] == "0100000"


def test_premier_jour_confort_aucun():
    assert schedule.premier_jour_confort([{"loops": "1000000", "loopData": []}]) is None
    assert schedule.premier_jour_confort(None) is None
