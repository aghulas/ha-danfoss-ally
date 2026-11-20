"""Fixtures de test (pytest-homeassistant-custom-component)."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the custom integration in the tests."""
    yield


@pytest.fixture
def setpoints_as_candidates(monkeypatch):
    """Put the isolated-head comfort (118 + 16) and setback (119) DPs back among the cloud-MQTT
    candidates. They are proven since 2026-11-19/20, and the one candidate left (DP 1, preheat) has
    rules of its own, so the generic supervised-trial mechanics (closed by default, opened on the
    designated head only, trial marker) are exercised by making these candidates again for the
    duration of a test."""
    import custom_components.danfoss_ally_cloud as integration
    from custom_components.danfoss_ally_cloud import config_flow, number, switch
    from custom_components.danfoss_ally_cloud.api import writes

    demoted = frozenset({118, 16, 119})
    monkeypatch.setattr(writes, "MQTT_WRITE_DPS", writes.MQTT_WRITE_DPS - demoted)
    candidates = writes.MQTT_CANDIDATE_DPS | demoted
    for module in (writes, integration, config_flow, number, switch):
        monkeypatch.setattr(module, "MQTT_CANDIDATE_DPS", candidates)
