"""Coverage measure of the cloud-MQTT push: aggregates, redaction, listen-only wiring.

Synthetic data only; paho is faked (no network).
"""

import json
import types
from unittest.mock import AsyncMock, patch

import paho.mqtt.client as paho
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.danfoss_ally_cloud import mqtt_coverage as cov
from custom_components.danfoss_ally_cloud.api import GatewayKey
from custom_components.danfoss_ally_cloud.api import mqtt_publish as mp
from custom_components.danfoss_ally_cloud.const import (
    CLOUD_MQTT_PROBE_MAX_SECONDS,
    CONF_CLOUD_MQTT_PROBE,
    CONF_ENABLE_CLOUD_MQTT,
    DATA_MQTT_COVERAGE,
    DATA_MQTT_LINK,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .common import ENTRY_DATA, FakeCloudClient, head, relay
from .test_mqtt_client import _FakePaho

KEY = "0123456789abcdef"  # synthetic 16-char localKey
_GW = {"gw-1": GatewayKey("gw-1", "GW", KEY, ip="10.0.0.1")}


def _frame(cid, dps, protocol=4):
    data = {} if cid is None else {"cid": cid, "dps": dps}
    return mp.Frame(pv="2.3", seq=1, origin=1, body={"data": data, "protocol": protocol, "t": 0})


class _Clock:
    """Deterministic wall and monotonic clocks for the collector."""

    def __init__(self, monkeypatch):
        self.now = 1_800_000_000.0
        monkeypatch.setattr(cov.time, "time", lambda: self.now)
        monkeypatch.setattr(cov.time, "monotonic", lambda: self.now - 1_700_000_000.0)

    def tick(self, seconds):
        self.now += seconds


def test_series_counts_first_last_median_and_longest(monkeypatch):
    clock = _Clock(monkeypatch)
    stats = cov.CoverageStats()
    for gap in (0, 60, 60, 600):  # reports at t, t+60, t+120, t+720
        clock.tick(gap)
        stats.record("gw-1", _frame("node-1", {"24": 205}))
    out = stats.summary([head()])
    h = out["heads"][0]
    assert h["reports"] == 4
    assert h["median_interval_s"] == 60.0 and h["longest_interval_s"] == 600.0
    assert h["first"] < h["last"]
    assert h["dps"]["24"]["reports"] == 4
    assert out["frames"] == 4 and out["frames_by_protocol"] == {"4": 4}
    assert out["duration_s"] == 720


def test_single_report_has_no_interval(monkeypatch):
    _Clock(monkeypatch)
    stats = cov.CoverageStats()
    stats.record("gw-1", _frame("node-1", {"24": 205}))
    h = stats.summary([head()])["heads"][0]
    assert h["reports"] == 1
    assert h["median_interval_s"] is None and h["longest_interval_s"] is None


def test_per_dp_series_and_missing_read_dps(monkeypatch):
    clock = _Clock(monkeypatch)
    stats = cov.CoverageStats()
    stats.record("gw-1", _frame("node-1", {"24": 205, "170": 30}))
    clock.tick(30)
    stats.record("gw-1", _frame("node-1", {"24": 206}))
    out = stats.summary([head()])
    h = out["heads"][0]
    assert list(h["dps"]) == ["24", "170"]  # numeric order
    assert h["dps"]["24"]["reports"] == 2 and h["dps"]["170"]["reports"] == 1
    assert "24" not in h["read_dps_missing"] and "171" in h["read_dps_missing"]
    assert out["dps"] == {"24": {"heads": 1, "reports": 2}, "170": {"heads": 1, "reports": 1}}
    assert "171" in out["read_dps_never_pushed"] and "24" not in out["read_dps_never_pushed"]


def test_heads_never_seen_unknown_senders_and_non_report_frames(monkeypatch):
    _Clock(monkeypatch)
    stats = cov.CoverageStats()
    seen = head("dev-1", "Seen", node_id="node-1")
    silent = head("dev-2", "Silent", node_id="node-2", online=False)
    other_gw = head("dev-3", "Other gateway", node_id="node-1", mesh_id="gw-2")
    stats.record("gw-1", _frame("node-1", {"24": 205}))
    stats.record("gw-1", _frame("node-9", {"1": True}))  # matches no head of the poll
    stats.record("gw-1", _frame(None, None, protocol=20))  # no cid: about the gateway itself
    stats.record("gw-1", _frame("node-1", {}))  # cid without DP
    out = stats.summary([relay(), seen, silent, other_gw], grouped_ids={"dev-1"})
    assert out["heads_known"] == 3 and out["heads_seen"] == 1
    # device_index points into the diagnostics ``devices`` list (the relay is index 0).
    assert out["heads"][0]["device_index"] == 1 and out["heads"][0]["grouped"] is True
    assert out["heads_never_seen"] == [
        {"device_index": 2, "name": "Silent", "online": False, "grouped": False},
        {"device_index": 3, "name": "Other gateway", "online": True, "grouped": False},
    ]
    assert out["unknown_senders"] == 1
    assert out["frames"] == 4 and out["frames_without_head_report"] == 2
    assert out["frames_by_protocol"] == {"20": 1, "4": 3}


def test_interval_memory_is_bounded(monkeypatch):
    clock = _Clock(monkeypatch)
    stats = cov.CoverageStats()
    for _ in range(cov.INTERVAL_SAMPLES + 50):
        clock.tick(10)
        stats.record("gw-1", _frame("node-1", {"24": 1}))
    series = stats._heads[("gw-1", "node-1")].any
    assert series.count == cov.INTERVAL_SAMPLES + 50
    assert len(series.intervals) == cov.INTERVAL_SAMPLES


def test_mark_stopped_freezes_the_measure(monkeypatch):
    clock = _Clock(monkeypatch)
    stats = cov.CoverageStats()
    stats.record("gw-1", _frame("node-1", {"24": 1}))
    clock.tick(100)
    stats.mark_stopped()
    clock.tick(1000)
    stats.record("gw-1", _frame("node-1", {"24": 1}))  # ignored after the stop
    out = stats.summary([head()])
    assert out["frames"] == 1 and out["duration_s"] == 100 and out["stopped"] is not None


def test_summary_carries_no_identifier(monkeypatch):
    _Clock(monkeypatch)
    stats = cov.CoverageStats()
    stats.record("gw-synth-topic", _frame("cid-synth-0001", {"24": 205}))
    stats.record("gw-synth-topic", _frame("cid-synth-0002", {"24": 205}))
    dev = head("devid-synth-0001", "Salon", node_id="cid-synth-0001", mesh_id="gw-synth-topic")
    dump = json.dumps(stats.summary([dev]))
    for secret in ("gw-synth-topic", "cid-synth-0001", "cid-synth-0002", "devid-synth-0001"):
        assert secret not in dump
    assert "205" not in dump  # no DP value either


# --- wiring: option, listen-only link, diagnostics, self-closing ---------------------------------


@pytest.fixture
def fake_paho(monkeypatch):
    _FakePaho.instances.clear()
    monkeypatch.setattr(paho, "Client", _FakePaho)
    return _FakePaho


async def _setup(hass: HomeAssistant, options):
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr", options=options
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=FakeCloudClient()),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _inbound(client, cid, dps):
    raw = mp.encode_frame(KEY, {"cid": cid, "dps": dps}, seq=5, origin=9, protocol=4)
    client.on_message(client, None, types.SimpleNamespace(topic="smart/mb/in/gw-1", payload=raw))


async def test_probe_off_by_default_opens_nothing(hass: HomeAssistant, fake_paho):
    entry = await _setup(hass, {})
    data = hass.data[DOMAIN][entry.entry_id]
    assert data[DATA_MQTT_LINK] is None and data[DATA_MQTT_COVERAGE] is None
    assert fake_paho.instances == []
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert "cloud_mqtt_coverage" not in diag


async def test_probe_alone_is_listen_only_and_feeds_diagnostics(hass: HomeAssistant, fake_paho):
    entry = await _setup(hass, {CONF_CLOUD_MQTT_PROBE: True})
    data = hass.data[DOMAIN][entry.entry_id]
    link = data[DATA_MQTT_LINK]
    assert link is not None and link.listen_only is True
    c = fake_paho.instances[-1]
    c.on_connect(c, None, None, 0)
    assert link.connected is True
    # No send path: neither availability nor plan nor publish.
    assert link.can_publish("gw-1") is False
    with pytest.raises(mp.FrameError):
        link.plan_dp("gw-1", "node-1", {"30": True})
    with pytest.raises(mp.FrameError):
        await link.publish_dp("gw-1", "node-1", {"30": True})
    assert c.published == []

    # The isolated head's child lock stays unavailable: the probe opens no write path.
    from custom_components.danfoss_ally_cloud.switch import PATH_NONE, DanfossSwitch

    sw = next(
        e
        for e in hass.data["entity_components"]["switch"].entities
        if isinstance(e, DanfossSwitch) and e.entity_description.key == "child_lock"
    )
    assert sw._write_path(sw.device) == PATH_NONE

    _inbound(c, "node-1", {"24": 205, "170": 12})
    # A message this codec cannot read: received, not decoded.
    c.on_message(c, None, types.SimpleNamespace(topic="smart/mb/in/gw-1", payload=b"x"))
    diag = await async_get_config_entry_diagnostics(hass, entry)
    block = diag["cloud_mqtt_coverage"]
    assert block["link"] == {
        "connected": True,
        "listen_only": True,
        "connects": 1,
        "disconnects": 0,
        "received": 2,
        "decoded": 1,
    }
    assert block["heads_seen"] == 1 and block["heads"][0]["device_index"] == 0
    assert set(block["heads"][0]["dps"]) == {"24", "170"}
    dump = json.dumps(block)
    assert "node-1" not in dump and "gw-1" not in dump and "dev-1" not in dump
    assert c.published == []


async def test_listen_only_link_closes_itself_after_the_maximum_duration(
    hass: HomeAssistant, fake_paho
):
    entry = await _setup(hass, {CONF_CLOUD_MQTT_PROBE: True})
    c = fake_paho.instances[-1]
    c.on_connect(c, None, None, 0)
    async_fire_time_changed(
        hass, dt_util.utcnow() + dt_util.dt.timedelta(seconds=CLOUD_MQTT_PROBE_MAX_SECONDS + 5)
    )
    await hass.async_block_till_done()
    assert c.loop_stopped and c.disconnected
    data = hass.data[DOMAIN][entry.entry_id]
    assert data[DATA_MQTT_LINK].connected is False
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["cloud_mqtt_coverage"]["stopped"] is not None  # the aggregates stay readable


async def test_probe_with_write_option_shares_one_writable_link(hass: HomeAssistant, fake_paho):
    entry = await _setup(hass, {CONF_CLOUD_MQTT_PROBE: True, CONF_ENABLE_CLOUD_MQTT: True})
    data = hass.data[DOMAIN][entry.entry_id]
    link = data[DATA_MQTT_LINK]
    assert len(fake_paho.instances) == 1  # one connection per session
    assert link.listen_only is False and data[DATA_MQTT_COVERAGE] is not None
    c = fake_paho.instances[-1]
    c.on_connect(c, None, None, 0)
    assert link.can_publish("gw-1") is True
    _inbound(c, "node-1", {"30": True})
    assert (
        data[DATA_MQTT_COVERAGE].summary(
            hass.data[DOMAIN][entry.entry_id]["coordinator"].data.values()
        )["frames"]
        == 1
    )
    # Not self-closing: the write path owns the link's lifetime.
    async_fire_time_changed(
        hass, dt_util.utcnow() + dt_util.dt.timedelta(seconds=CLOUD_MQTT_PROBE_MAX_SECONDS + 5)
    )
    await hass.async_block_till_done()
    assert not c.loop_stopped


async def test_write_option_alone_has_no_coverage(hass: HomeAssistant, fake_paho):
    entry = await _setup(hass, {CONF_ENABLE_CLOUD_MQTT: True})
    data = hass.data[DOMAIN][entry.entry_id]
    assert data[DATA_MQTT_LINK].listen_only is False and data[DATA_MQTT_COVERAGE] is None
