"""Batch C: viewing direction (DP 101) and orientation (DP 133) over Tuya cloud MQTT.

Both are closed candidates. Each opens only for a supervised trial on the designated isolated head
and has its own confirmation, never the gateway's echo: orientation by the head's flag 0x4014 read
back through the local tunnel, viewing direction by the per-device cloud route. Doubles only,
synthetic data.
"""

import contextlib
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import paho.mqtt.client as paho
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud import mqtt_write
from custom_components.danfoss_ally_cloud.api import (
    CloudError,
    CloudWriteError,
    GatewayKey,
    decode,
    writes,
)
from custom_components.danfoss_ally_cloud.api.local import tunnel
from custom_components.danfoss_ally_cloud.api.local.manager import Head, LocalTunnelManager
from custom_components.danfoss_ally_cloud.const import (
    CONF_CLOUD_MQTT_SUPERVISED_DPS,
    CONF_CLOUD_MQTT_SUPERVISED_HEAD,
    CONF_ENABLE_CLOUD_MQTT,
    CONF_ENABLE_LOCAL,
    DATA_CLOUD_MQTT,
    DATA_LOCAL,
    DATA_MQTT_SUPERVISED_DPS,
    DATA_MQTT_SUPERVISED_HEAD,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.mqtt_write import (
    CONFIRMED_BY_CLOUD,
    CONFIRMED_BY_TUNNEL,
    UNCHANGED,
    WriteNotConfirmed,
    async_mqtt_write,
    async_mqtt_write_orientation,
    async_mqtt_write_viewing_direction,
    trial_dp_armed,
)
from custom_components.danfoss_ally_cloud.select import DanfossOrientation
from custom_components.danfoss_ally_cloud.switch import DanfossViewingDirection

from .common import ENTRY_DATA, FakeCloudClient
from .common import head as _bare_head
from .test_coordinator_local import FakeManager
from .test_mqtt_client import _FakePaho

_ARMED = frozenset({101, 133})


def head(*args, **kw):
    """A synthetic isolated head whose cloud DPs carry both settings."""
    kw.setdefault("dps", {"101": False, "133": "Horizontal"})
    kw.setdefault("viewing_direction", False)
    kw.setdefault("orientation", "Horizontal")
    return _bare_head(*args, **kw)


@pytest.fixture(autouse=True)
def _fast_confirmation(monkeypatch):
    """No real waiting between two reads; one read at most after the publish."""
    for name in (
        "ORIENTATION_CONFIRM_INTERVAL",
        "ORIENTATION_CONFIRM_TIMEOUT",
        "VIEWING_CONFIRM_INTERVAL",
        "VIEWING_CONFIRM_TIMEOUT",
    ):
        monkeypatch.setattr(mqtt_write, name, 0.0)


class _Local:
    """Double of the local coordinator: the tunnel settings reads of one head, in order."""

    def __init__(self, flags):
        self._flags = list(flags)
        self.reads = 0

    async def async_refresh_settings(self, head_):
        self.reads += 1
        flag = self._flags.pop(0) if self._flags else None
        return None if flag is None else {"orientation": flag, "radiator_covered": False}


def _coordinator(device_dps=None):
    """Double of the cloud coordinator: per-device reads in order (dicts, None or exceptions)."""
    coordinator = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.client.async_get_device_dps = AsyncMock(side_effect=list(device_dps or []))
    return coordinator


def _link(can_publish=True):
    link = MagicMock()
    link.can_publish = MagicMock(return_value=can_publish)
    link.publish_dp = AsyncMock()
    link.await_confirmation = AsyncMock(return_value=True)  # an echo that must never be used
    return link


# --- value rules and gates ---------------------------------------------------------------------


def test_101_and_133_are_closed_candidates_with_their_own_confirmation():
    for dp in (101, 133):
        assert dp in writes.MQTT_CANDIDATE_DPS
        assert dp not in writes.MQTT_WRITE_DPS
        assert writes.mqtt_dp_open(dp) is False
        assert writes.mqtt_dp_open(dp, _ARMED) is True
    assert 133 in writes.MQTT_TUNNEL_CONFIRMED_DPS
    assert 101 in writes.MQTT_CLOUD_CONFIRMED_DPS
    assert writes.MQTT_CLOUD_CONFIRMED_DPS <= writes.MQTT_CANDIDATE_DPS


def test_viewing_direction_value_must_be_a_boolean_and_listed():
    assert writes.mqtt_write_value(101, True, _ARMED) is True
    with pytest.raises(CloudWriteError, match="supervised first write"):
        writes.mqtt_write_value(101, True)
    with pytest.raises(CloudWriteError, match="boolean"):
        writes.mqtt_write_value(101, 1, _ARMED)


@pytest.mark.parametrize("bad", ["vertical", "VERTICAL", "Upright", "", 1, True, None])
def test_orientation_value_must_be_exactly_the_apps_string(bad):
    assert writes.mqtt_write_value(133, "Vertical", _ARMED) == "Vertical"
    assert writes.mqtt_write_value(133, "Horizontal", _ARMED) == "Horizontal"
    with pytest.raises(CloudWriteError, match="Horizontal, Vertical"):
        writes.mqtt_write_value(133, bad, _ARMED)
    with pytest.raises(CloudWriteError, match="supervised first write"):
        writes.mqtt_write_value(133, "Vertical")


@pytest.mark.parametrize("dps", [{101: True}, {133: "Vertical"}, {30: True, 101: True}])
async def test_generic_mqtt_write_refuses_both_even_when_armed(dps):
    link = _link()
    with pytest.raises(HomeAssistantError, match="refused"):
        await async_mqtt_write(MagicMock(), link, head(), dps, supervised=_ARMED)
    link.publish_dp.assert_not_awaited()
    link.await_confirmation.assert_not_called()


def test_decode_reads_both_settings_from_the_cloud():
    raw = {"devId": "d", "category": "wkf", "productId": "03wvrwpv", "dps": {"101": True}}
    dev = decode.decode_device({**raw, "dps": {"101": True, "133": "Vertical"}})
    assert dev.viewing_direction is True and dev.orientation == "Vertical"
    dev = decode.decode_device({**raw, "dps": {"101": "true", "133": "vertical"}})
    assert dev.viewing_direction is None and dev.orientation is None  # never a guess


def test_trial_dp_armed_needs_option_head_isolation_and_model():
    dev = head("trial")
    coordinator = MagicMock()
    coordinator.group_of = MagicMock(return_value=None)
    data = {
        DATA_CLOUD_MQTT: True,
        DATA_MQTT_SUPERVISED_DPS: frozenset({133}),
        DATA_MQTT_SUPERVISED_HEAD: "trial",
    }
    assert trial_dp_armed(data, coordinator, dev, 133) is True
    assert trial_dp_armed(data, coordinator, dev, 101) is False  # not listed
    assert trial_dp_armed({**data, DATA_CLOUD_MQTT: False}, coordinator, dev, 133) is False
    assert trial_dp_armed(data, coordinator, head("other"), 133) is False
    assert trial_dp_armed(data, coordinator, head("trial", product_id="x"), 133) is False
    coordinator.group_of.return_value = "77"
    assert trial_dp_armed(data, coordinator, dev, 133) is False  # grouped


# --- orientation: confirmed by the tunnel only --------------------------------------------------


async def test_orientation_closed_by_default_reads_and_sends_nothing():
    local, link = _Local([False]), _link()
    with pytest.raises(HomeAssistantError, match="supervised first write"):
        await async_mqtt_write_orientation(local, _coordinator(), link, head(), "Vertical")
    assert local.reads == 0
    link.publish_dp.assert_not_awaited()


async def test_orientation_refuses_a_lowercase_value_before_anything():
    local, link = _Local([False]), _link()
    with pytest.raises(HomeAssistantError, match="refused"):
        await async_mqtt_write_orientation(
            local, _coordinator(), link, head(), "vertical", supervised=_ARMED
        )
    assert local.reads == 0


async def test_orientation_needs_the_gateway_address():
    with pytest.raises(HomeAssistantError, match="gateway address"):
        await async_mqtt_write_orientation(
            _Local([False]),
            _coordinator(),
            _link(),
            head(mesh_id=None),
            "Vertical",
            supervised=_ARMED,
        )


async def test_orientation_refused_when_the_tunnel_does_not_answer_first():
    local, link = _Local([None]), _link()
    with pytest.raises(HomeAssistantError, match="does not give its orientation flag"):
        await async_mqtt_write_orientation(
            local, _coordinator(), link, head(), "Vertical", supervised=_ARMED
        )
    link.publish_dp.assert_not_awaited()


async def test_orientation_refused_when_tunnel_and_cloud_disagree():
    """Flag true (vertical for Zigbee2MQTT) while the cloud says Horizontal: the mapping, the cloud
    or the head is wrong, and a confirmation would prove nothing."""
    local, link = _Local([True]), _link()
    with pytest.raises(HomeAssistantError, match="disagree"):
        await async_mqtt_write_orientation(
            local, _coordinator(), link, head(), "Horizontal", supervised=_ARMED
        )
    link.publish_dp.assert_not_awaited()


async def test_orientation_without_a_cloud_value_relies_on_the_tunnel():
    local, link = _Local([False, True]), _link()
    result = await async_mqtt_write_orientation(
        local, _coordinator(), link, head(orientation=None), "Vertical", supervised=_ARMED
    )
    assert result == CONFIRMED_BY_TUNNEL


async def test_orientation_already_at_the_value_publishes_nothing():
    local, link = _Local([False]), _link()
    result = await async_mqtt_write_orientation(
        local, _coordinator(), link, head(), "Horizontal", supervised=_ARMED
    )
    assert result == UNCHANGED
    link.publish_dp.assert_not_awaited()


async def test_orientation_confirmed_by_the_tunnel_read(monkeypatch):
    monkeypatch.setattr(mqtt_write, "ORIENTATION_CONFIRM_TIMEOUT", 60.0)
    local, link = _Local([False, False, True]), _link()  # before, still old, then the new flag
    coordinator = _coordinator()
    dev = head("dev-1", node_id="node-1", mesh_id="gw-1")
    result = await async_mqtt_write_orientation(
        local, coordinator, link, dev, "Vertical", supervised=_ARMED
    )
    assert result == CONFIRMED_BY_TUNNEL
    link.publish_dp.assert_awaited_once_with("gw-1", "node-1", {"133": "Vertical"})
    link.await_confirmation.assert_not_called()  # the echo plays no part
    assert local.reads == 3
    coordinator.note_commanded.assert_called_once_with(["dev-1"])
    coordinator.async_request_refresh.assert_awaited()


async def test_orientation_not_confirmed_when_the_flag_does_not_move():
    local, link = _Local([False, False]), _link()
    with pytest.raises(WriteNotConfirmed, match="does not show the value"):
        await async_mqtt_write_orientation(
            local, _coordinator(), link, head(), "Vertical", supervised=_ARMED
        )
    link.publish_dp.assert_awaited_once()


async def test_orientation_not_confirmed_when_the_head_stops_answering():
    local, link = _Local([False, None]), _link()
    with pytest.raises(WriteNotConfirmed):
        await async_mqtt_write_orientation(
            local, _coordinator(), link, head(), "Vertical", supervised=_ARMED
        )


async def test_a_failed_publish_counts_as_sent_not_confirmed():
    local, link = _Local([False]), _link()
    link.publish_dp.side_effect = OSError("broker gone")
    with pytest.raises(WriteNotConfirmed, match="broker gone"):
        await async_mqtt_write_orientation(
            local, _coordinator(), link, head(), "Vertical", supervised=_ARMED
        )


# --- viewing direction: confirmed by the per-device cloud route ---------------------------------


async def test_viewing_direction_closed_by_default():
    coordinator, link = _coordinator([{"101": False}]), _link()
    with pytest.raises(HomeAssistantError, match="supervised first write"):
        await async_mqtt_write_viewing_direction(coordinator, link, head(), True)
    coordinator.client.async_get_device_dps.assert_not_awaited()
    link.publish_dp.assert_not_awaited()


@pytest.mark.parametrize("first", [None, {"30": True}, {"101": "true"}, CloudError("down")])
async def test_viewing_direction_refused_when_the_cloud_does_not_give_it(first):
    coordinator, link = _coordinator([first]), _link()
    with pytest.raises(HomeAssistantError, match="does not give DP 101"):
        await async_mqtt_write_viewing_direction(coordinator, link, head(), True, supervised=_ARMED)
    link.publish_dp.assert_not_awaited()


async def test_viewing_direction_already_at_the_value_publishes_nothing():
    coordinator, link = _coordinator([{"101": True}]), _link()
    result = await async_mqtt_write_viewing_direction(
        coordinator, link, head(), True, supervised=_ARMED
    )
    assert result == UNCHANGED
    link.publish_dp.assert_not_awaited()


async def test_viewing_direction_confirmed_by_the_per_device_route(monkeypatch):
    monkeypatch.setattr(mqtt_write, "VIEWING_CONFIRM_TIMEOUT", 60.0)
    coordinator = _coordinator([{"101": False}, {"101": False}, {"101": True}])
    link = _link()
    dev = head("dev-1", node_id="node-1", mesh_id="gw-1")
    result = await async_mqtt_write_viewing_direction(
        coordinator, link, dev, True, supervised=_ARMED
    )
    assert result == CONFIRMED_BY_CLOUD
    link.publish_dp.assert_awaited_once_with("gw-1", "node-1", {"101": True})
    link.await_confirmation.assert_not_called()
    assert coordinator.client.async_get_device_dps.await_count == 3


async def test_viewing_direction_not_confirmed_when_the_cloud_keeps_the_old_value():
    coordinator, link = _coordinator([{"101": False}, {"101": False}]), _link()
    with pytest.raises(WriteNotConfirmed, match="per-device cloud route"):
        await async_mqtt_write_viewing_direction(coordinator, link, head(), True, supervised=_ARMED)


# --- tunnel read-back of one head's settings ----------------------------------------------------


def test_manager_read_settings_one_head(monkeypatch):
    link = MagicMock()
    manager = LocalTunnelManager(
        {"gw-1": GatewayKey("gw-1", "GW", "cle-synth", ip="10.0.0.1")}, open_link=lambda k: link
    )
    monkeypatch.setattr(tunnel, "read_settings", lambda lk, d, n: {"orientation": True})
    assert manager.read_settings(Head("dev-1", "node-1", "gw-1")) == {"orientation": True}
    link.close.assert_called_once()
    with pytest.raises(tunnel.LocalUnavailable):
        manager.read_settings(Head("dev-1", "node-1", "unknown-gw"))


class _SettingsManager(FakeManager):
    """FakeManager with the single-head settings read of batch C."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.read_settings_calls = 0
        self.read_settings_exc = None

    def read_settings(self, head_):
        self.read_settings_calls += 1
        if self.read_settings_exc is not None:
            raise self.read_settings_exc
        return self.settings.get(head_.dev_id)


async def test_refresh_settings_updates_one_head_and_survives_the_pass(hass: HomeAssistant):
    from custom_components.danfoss_ally_cloud.coordinator import DanfossLocalCoordinator

    manager = _SettingsManager()
    cloud = MagicMock()
    cloud.data = {}
    local = DanfossLocalCoordinator(hass, manager, cloud, 900)
    h = Head("dev-1", "node-1", "gw-1")

    assert await local.async_refresh_settings(h) is None  # no answer: nothing stored
    assert "dev-1" not in local.settings
    manager.read_settings_exc = OSError("gateway down")
    assert await local.async_refresh_settings(h) is None
    manager.read_settings_exc = None

    manager.settings["dev-1"] = {"orientation": True}
    assert await local.async_refresh_settings(h) == {"orientation": True}
    assert local.settings["dev-1"]["orientation"] is True
    assert local.settings["dev-1"]["read_at"] is not None

    # During a pass, a fresher single-head read is not overwritten by the pass's own result.
    local._surveying = True
    local._settings_read_back = set()
    manager.settings["dev-1"] = {"orientation": False}
    await local.async_refresh_settings(h)
    local._async_head_settings("dev-1", {"orientation": True})
    assert local.settings["dev-1"]["orientation"] is False
    local._surveying = False


async def test_a_read_back_during_a_pass_survives_the_pass_merge(hass: HomeAssistant):
    """A daily pass ending just after an orientation write must not put back the pre-write value
    over the single-head read-back, even when its loop callbacks come late (made no-ops here, the
    worst case: only the pass's own merge of what the worker collected runs)."""
    import threading

    from custom_components.danfoss_ally_cloud.coordinator import DanfossLocalCoordinator

    manager = _SettingsManager()
    cloud = MagicMock()
    cloud.data = {}
    local = DanfossLocalCoordinator(hass, manager, cloud, 900)
    local._async_head_settings = lambda *a: None  # type: ignore[method-assign]
    h = Head("dev-1", "node-1", "gw-1")

    local._surveying = True  # a pass is running
    manager.settings["dev-1"] = {"orientation": True}  # read back after the write
    await local.async_refresh_settings(h)
    manager.settings["dev-1"] = {"orientation": False}  # what the pass read before the write
    await local._async_survey_settings([h], threading.Event())
    local._surveying = False
    assert local.settings["dev-1"]["orientation"] is True


# --- entities (hass harness) --------------------------------------------------------------------

_GW = {"gw-1": GatewayKey("gw-1", "GW", "0123456789abcdef", ip="10.0.0.1")}


@pytest.fixture
def fake_paho(monkeypatch):
    _FakePaho.instances.clear()
    monkeypatch.setattr(paho, "Client", _FakePaho)
    return _FakePaho


def _fleet(**trial_kw):
    return FakeCloudClient(
        devices=[
            head("trial-head-id", "Test head", node_id="n1", **trial_kw),
            head("other-head-id", "Other head", node_id="n2"),
        ]
    )


async def _setup(hass: HomeAssistant, options, manager=None, fleet=None, entry=None):
    if entry is None:
        entry = MockConfigEntry(
            domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr", options=options
        )
        entry.add_to_hass(hass)
    manager = manager or _SettingsManager()
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fleet or _fleet()),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
        patch("custom_components.danfoss_ally_cloud.LocalTunnelManager", return_value=manager),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    if _FakePaho.instances:
        c = _FakePaho.instances[-1]
        c.on_connect(c, None, None, 0)
    return entry


_ARMED_OPTIONS = {
    CONF_ENABLE_CLOUD_MQTT: True,
    CONF_ENABLE_LOCAL: True,
    CONF_CLOUD_MQTT_SUPERVISED_DPS: ["101", "133"],
    CONF_CLOUD_MQTT_SUPERVISED_HEAD: "trial-head-id",
}


def _entities(hass, domain, cls):
    component = hass.data["entity_components"].get(domain)
    return [] if component is None else [e for e in component.entities if isinstance(e, cls)]


async def test_entities_exist_only_on_the_armed_trial_head(hass: HomeAssistant, fake_paho):
    await _setup(hass, _ARMED_OPTIONS)
    switches = _entities(hass, "switch", DanfossViewingDirection)
    selects = _entities(hass, "select", DanfossOrientation)
    assert [e._device_id for e in switches] == ["trial-head-id"]
    assert [e._device_id for e in selects] == ["trial-head-id"]


@pytest.mark.parametrize(
    "options",
    [
        {},  # the default: closed
        {**_ARMED_OPTIONS, CONF_ENABLE_CLOUD_MQTT: False},
        {**_ARMED_OPTIONS, CONF_CLOUD_MQTT_SUPERVISED_HEAD: ""},
        {**_ARMED_OPTIONS, CONF_CLOUD_MQTT_SUPERVISED_DPS: ["1"]},
    ],
)
async def test_no_entity_unless_armed(hass: HomeAssistant, fake_paho, options):
    await _setup(hass, options)
    assert _entities(hass, "switch", DanfossViewingDirection) == []
    assert _entities(hass, "select", DanfossOrientation) == []


async def test_orientation_select_needs_the_local_tunnel(hass: HomeAssistant, fake_paho):
    await _setup(hass, {**_ARMED_OPTIONS, CONF_ENABLE_LOCAL: False})
    assert _entities(hass, "select", DanfossOrientation) == []
    assert len(_entities(hass, "switch", DanfossViewingDirection)) == 1


async def test_disarming_removes_the_registry_entries(hass: HomeAssistant, fake_paho):
    entry = await _setup(hass, _ARMED_OPTIONS)
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("select", DOMAIN, "trial-head-id_orientation_setting")
    assert registry.async_get_entity_id("switch", DOMAIN, "trial-head-id_viewing_direction")
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.config_entries.async_update_entry(
        entry, options={**_ARMED_OPTIONS, "cloud_mqtt_supervised_dps": []}
    )
    await _setup(hass, {}, entry=entry)
    assert (
        registry.async_get_entity_id("select", DOMAIN, "trial-head-id_orientation_setting") is None
    )
    assert registry.async_get_entity_id("switch", DOMAIN, "trial-head-id_viewing_direction") is None


async def test_viewing_switch_state_and_write(hass: HomeAssistant, fake_paho):
    await _setup(hass, _ARMED_OPTIONS)
    switch = _entities(hass, "switch", DanfossViewingDirection)[0]
    assert switch.available and switch.is_on is False
    attrs = switch.extra_state_attributes
    assert attrs["write_path"] == "cloud_mqtt" and attrs["write_trial"] is True

    write = AsyncMock(return_value=CONFIRMED_BY_CLOUD)
    with patch(
        "custom_components.danfoss_ally_cloud.switch.async_mqtt_write_viewing_direction", write
    ):
        await switch.async_turn_on()
    write.assert_awaited_once()
    assert write.await_args.args[3] is True
    assert switch.extra_state_attributes["trial_result"] == "confirmed_by_cloud"

    failing = AsyncMock(side_effect=WriteNotConfirmed("not seen"))
    with (
        patch(
            "custom_components.danfoss_ally_cloud.switch.async_mqtt_write_viewing_direction",
            failing,
        ),
        pytest.raises(WriteNotConfirmed),
    ):
        await switch.async_turn_off()
    attrs = switch.extra_state_attributes
    assert attrs["trial_result"] == "not_confirmed" and attrs["trial_error"] == "not seen"


async def test_viewing_switch_unavailable_without_the_cloud_value(hass: HomeAssistant, fake_paho):
    await _setup(hass, _ARMED_OPTIONS, fleet=_fleet(viewing_direction=None, dps={}))
    switch = _entities(hass, "switch", DanfossViewingDirection)[0]
    assert switch.available is False  # never a default value


async def test_viewing_switch_unavailable_when_the_link_cannot_publish(
    hass: HomeAssistant, fake_paho
):
    await _setup(hass, _ARMED_OPTIONS)
    switch = _entities(hass, "switch", DanfossViewingDirection)[0]
    switch._link = _link(can_publish=False)
    assert switch.available is False
    with pytest.raises(HomeAssistantError, match="unavailable"):
        await switch.async_turn_on()


async def test_orientation_select_state_comes_from_the_tunnel(hass: HomeAssistant, fake_paho):
    manager = _SettingsManager()
    entry = await _setup(hass, _ARMED_OPTIONS, manager=manager)
    select = _entities(hass, "select", DanfossOrientation)[0]
    local = hass.data[DOMAIN][entry.entry_id][DATA_LOCAL]
    local.settings.pop("trial-head-id", None)
    assert select.available is False  # not read yet: no value, even with the cloud's DP 133

    local.settings["trial-head-id"] = {"orientation": True, "read_at": dt_util.utcnow()}
    assert select.available and select.current_option == "vertical"
    attrs = select.extra_state_attributes
    assert attrs["raw"] is True and attrs["cloud_value"] == "Horizontal"
    assert attrs["write_trial"] is True
    local.settings["trial-head-id"] = {"orientation": False, "read_at": dt_util.utcnow()}
    assert select.current_option == "horizontal"


async def test_orientation_select_write_and_untrusted_after_not_confirmed(
    hass: HomeAssistant, fake_paho
):
    entry = await _setup(hass, _ARMED_OPTIONS)
    select = _entities(hass, "select", DanfossOrientation)[0]
    local = hass.data[DOMAIN][entry.entry_id][DATA_LOCAL]
    read_at = dt_util.utcnow() - timedelta(minutes=1)
    local.settings["trial-head-id"] = {"orientation": False, "read_at": read_at}

    with pytest.raises(HomeAssistantError, match="unknown orientation"):
        await select.async_select_option("diagonal")

    write = AsyncMock(return_value=UNCHANGED)
    with patch("custom_components.danfoss_ally_cloud.select.async_mqtt_write_orientation", write):
        await select.async_select_option("horizontal")
    assert write.await_args.args[4] == "Horizontal"
    assert select.extra_state_attributes["trial_result"] == "unchanged"

    refused = AsyncMock(side_effect=HomeAssistantError("disagree"))
    with (
        patch("custom_components.danfoss_ally_cloud.select.async_mqtt_write_orientation", refused),
        pytest.raises(HomeAssistantError),
    ):
        await select.async_select_option("vertical")
    assert select.extra_state_attributes["trial_result"] == "refused"
    assert select.available  # nothing was sent: the value read before still stands

    failing = AsyncMock(side_effect=WriteNotConfirmed("flag did not move"))
    with (
        patch("custom_components.danfoss_ally_cloud.select.async_mqtt_write_orientation", failing),
        pytest.raises(WriteNotConfirmed),
    ):
        await select.async_select_option("vertical")
    assert select.available is False  # the value read before the frame is no longer trusted
    local.settings["trial-head-id"] = {"orientation": True, "read_at": dt_util.utcnow()}
    assert select.available and select.current_option == "vertical"

    with contextlib.suppress(Exception):
        select._link = _link(can_publish=False)
    with pytest.raises(HomeAssistantError, match="unavailable"):
        await select.async_select_option("horizontal")
