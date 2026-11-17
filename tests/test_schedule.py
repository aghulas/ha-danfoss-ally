"""Schedule-helper tests (pure, no network): decoding and re-sending a day."""

from custom_components.danfoss_ally_cloud.api import schedule


def test_hhmm():
    assert schedule.hhmm(0) == "00:00"
    assert schedule.hhmm(510) == "08:30"
    assert schedule.hhmm(1050) == "17:30"
    assert schedule.hhmm(1439) == "23:59"


def test_day_from_loop():
    assert schedule.day_from_loop("1000000") == "sunday"  # bit 0 = dimanche
    assert schedule.day_from_loop("0100000") == "monday"
    assert schedule.day_from_loop("0000001") == "saturday"


def test_comfort_periods_converts_and_filters():
    loop_data = [
        {"startTime": 510, "endTime": 1050, "mode": "at_home"},
        {"startTime": 1050, "endTime": 1320, "mode": "leaving_home"},  # setback: ignored
        {"startTime": 360, "endTime": 420},  # mode absent: implicit comfort
    ]
    assert schedule.comfort_periods(loop_data) == [
        {"startTime": "08:30", "endTime": "17:30"},
        {"startTime": "06:00", "endTime": "07:00"},
    ]


def test_comfort_periods_empty():
    assert schedule.comfort_periods(None) == []
    assert schedule.comfort_periods([]) == []
    assert schedule.comfort_periods([{"startTime": 0, "endTime": 10, "mode": "leaving_home"}]) == []


def test_first_comfort_day():
    data = [
        {"loops": "1000000", "loopData": []},  # dimanche vide
        {"loops": "0000001", "loopData": [{"startTime": 0, "endTime": 10, "mode": "leaving_home"}]},
        {"loops": "0100000", "loopData": [{"startTime": 510, "endTime": 1050, "mode": "at_home"}]},
    ]
    jour = schedule.first_comfort_day(data)
    assert jour is not None and jour["loops"] == "0100000"


def test_first_comfort_day_none():
    assert schedule.first_comfort_day([{"loops": "1000000", "loopData": []}]) is None
    assert schedule.first_comfort_day(None) is None
