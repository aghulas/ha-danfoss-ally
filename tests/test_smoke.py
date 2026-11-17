"""Smoke tests: the integration imports and the constants hold."""

from custom_components.danfoss_ally_cloud import const


def test_domain():
    assert const.DOMAIN == "danfoss_ally_cloud"


def test_dp_pieges():
    # Pitfalls from the official schema: do not swap them.
    assert const.DP_UPPER_TEMP == 18  # upper bound, not the setpoint
    assert const.DP_SETPOINT == 171  # current setpoint
    assert const.DP_PREHEAT == 1
    assert const.ZB_ATTR_PROGRAMMING_MODE == 0x0025


def test_platforms_not_empty():
    assert "climate" in const.PLATFORMS
