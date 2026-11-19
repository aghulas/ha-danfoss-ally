"""Switch entity tests (fake coordinator, without starting Home Assistant).

async_setup_entry and the preheat write (self.hass.async_add_executor_job) belong to the hass
harness and are covered elsewhere; here we test the state logic and the guarded write.
"""

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.danfoss_ally_cloud import switch as switch_mod
from custom_components.danfoss_ally_cloud.api.local import tunnel
from custom_components.danfoss_ally_cloud.switch import (
    SWITCHES,
    DanfossPreheat,
    DanfossSwitch,
)

from .common import head


class _FakeCloudCoord:
    def __init__(self, data, client=None, last_update_success=True, groups=None):
        self.data = data
        self.client = client
        self.last_update_success = last_update_success
        self.refreshed = False
        self.groups = groups or {}  # head_id -> group_id
        self.commanded = []

    def group_of(self, head_id):
        return self.groups.get(head_id)

    def room_members(self, group_id):
        return tuple(h for h, g in self.groups.items() if g == group_id)

    def note_commanded(self, head_ids):
        self.commanded.extend(head_ids)

    async def async_request_refresh(self):
        self.refreshed = True


class _FakeLocalCoord:
    def __init__(self, data, manager=None, last_update_success=True):
        self.data = data
        self.manager = manager
        self.last_update_success = last_update_success


class _FakeManager:
    def __init__(self, gateways=("gw-1",), fail=None):
        self.gateway_ids = set(gateways)
        self.window_writes = []
        self.fail = fail

    def write_window_detection(self, head, enabled):
        if self.fail:
            raise self.fail
        self.window_writes.append((head, enabled))
        return enabled


class _FakeHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


class _FakeClient:
    def __init__(self):
        self.calls = []  # settings.change (must stay empty for the setting switches)
        self.group_calls = []
        self.device_dps = {}  # per-device route: {dev_id: {dp: value}} or an exception
        self.device_reads = []

    async def async_write_setting(self, dev_id, pid, dps, *, gw_id=None):
        self.calls.append((dev_id, pid, dps, gw_id))

    async def async_group_publish(self, group_id, dps):
        self.group_calls.append((group_id, dps))

    async def async_get_device_dps(self, dev_id):
        self.device_reads.append(dev_id)
        got = self.device_dps.get(dev_id)
        if isinstance(got, Exception):
            raise got
        return got


def _verrou_desc():
    return next(d for d in SWITCHES if d.key == "child_lock")


def _fenetre_desc():
    return next(d for d in SWITCHES if d.key == "window_detection")


class _FakeMqttLink:
    """Stand-in for CloudMqttLink: records publishes, no network."""

    def __init__(self, gateways=("gw-1",), connected=True, fail=None, confirm=True):
        self._gw = set(gateways)
        self._connected = connected
        self.fail = fail
        self.confirm = confirm
        self.published = []  # (mesh_id, node_id, dps)
        self.confirmations = []  # (node_id, dp, value)

    def can_publish(self, gateway_id):
        return self._connected and gateway_id in self._gw

    async def publish_dp(self, gateway_id, node_id, dps):
        if self.fail:
            raise self.fail
        self.published.append((gateway_id, node_id, dps))

    async def await_confirmation(self, node_id, dp, value, *, timeout_s):
        self.confirmations.append((node_id, dp, value))
        return self.confirm


def _switch(
    desc,
    dev,
    *,
    client=None,
    groups=None,
    local=None,
    mqtt=None,
    cloud_mqtt=False,
    supervised=frozenset(),
):
    coord = _FakeCloudCoord({dev.id: dev}, client=client or _FakeClient(), groups=groups)
    sw = DanfossSwitch(coord, dev.id, desc, local, mqtt, cloud_mqtt, supervised)
    sw.hass = _FakeHass()
    return sw, coord


# --- grouped head: the setting goes through the ROOM (group publish) ---------------------------


async def test_grouped_head_switch_available_with_room_scope():
    dev = head(child_lock=True)
    sw, _ = _switch(_verrou_desc(), dev, groups={dev.id: "g1", "dev-2": "g1"})
    assert sw.is_on is True
    assert sw.available is True
    assert sw.extra_state_attributes == {
        "write_path": "room",
        "write_scope": "room",
        "room_head_count": 2,
    }


async def test_grouped_head_lock_writes_through_room_publish():
    dev = head(child_lock=False)
    client = _FakeClient()
    sw, coord = _switch(_verrou_desc(), dev, client=client, groups={dev.id: "g1", "dev-2": "g1"})
    await sw.async_turn_on()
    await sw.async_turn_off()
    assert client.group_calls == [("g1", {"30": True}), ("g1", {"30": False})]
    assert client.calls == []  # never settings.change
    assert set(coord.commanded) == {dev.id, "dev-2"}  # whole room marked as commanded
    assert coord.refreshed is True


async def test_grouped_head_window_writes_through_room_even_with_local():
    dev = head()
    client = _FakeClient()
    mgr = _FakeManager()
    local = _FakeLocalCoord({dev.id: False}, manager=mgr)
    sw, _ = _switch(_fenetre_desc(), dev, client=client, groups={dev.id: "g1"}, local=local)
    await sw.async_turn_off()
    assert client.group_calls == [("g1", {"116": False})]
    assert mgr.window_writes == [] and client.calls == []


async def test_grouped_head_publish_error_raises():
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.danfoss_ally_cloud.api import CloudError

    class _Boom(_FakeClient):
        async def async_group_publish(self, group_id, dps):
            raise CloudError("refused")

    dev = head()
    sw, coord = _switch(_verrou_desc(), dev, client=_Boom(), groups={dev.id: "g1"})
    with pytest.raises(HomeAssistantError):
        await sw.async_turn_on()
    assert coord.refreshed is False


# --- isolated head: never settings.change; local tunnel or unavailable --------------------------


async def test_isolated_head_lock_unavailable_and_never_written():
    dev = head(child_lock=True)
    client = _FakeClient()
    mgr = _FakeManager()
    local = _FakeLocalCoord({dev.id: True}, manager=mgr)  # tunnel up: still no proven lock path
    sw, coord = _switch(_verrou_desc(), dev, client=client, local=local)
    assert sw.available is False
    assert sw.extra_state_attributes == {"write_path": "none"}
    await sw.async_turn_off()
    assert client.calls == [] and client.group_calls == [] and mgr.window_writes == []
    assert coord.refreshed is False


async def test_isolated_head_window_unavailable_without_local():
    dev = head()
    client = _FakeClient()
    sw, _ = _switch(_fenetre_desc(), dev, client=client)
    assert sw.available is False
    await sw.async_turn_on()
    assert client.calls == [] and client.group_calls == []


async def test_isolated_head_window_unavailable_if_head_silent_locally():
    dev = head()
    mgr = _FakeManager()
    # Tunnel on but the last survey got no answer from this head (gateway/head unreachable).
    sw, _ = _switch(_fenetre_desc(), dev, local=_FakeLocalCoord({dev.id: None}, manager=mgr))
    assert sw.available is False
    sw2, _ = _switch(
        _fenetre_desc(),
        dev,
        local=_FakeLocalCoord({dev.id: True}, manager=mgr, last_update_success=False),
    )
    assert sw2.available is False
    sw3, _ = _switch(
        _fenetre_desc(), dev, local=_FakeLocalCoord({dev.id: True}, manager=_FakeManager(("gw-x",)))
    )
    assert sw3.available is False


async def test_isolated_head_window_writes_through_local_tunnel():
    dev = head(window_detection=True)
    client = _FakeClient()
    mgr = _FakeManager()
    sw, coord = _switch(
        _fenetre_desc(), dev, client=client, local=_FakeLocalCoord({dev.id: False}, manager=mgr)
    )
    assert sw.available is True
    assert sw.extra_state_attributes == {"write_path": "local", "write_scope": "head"}
    await sw.async_turn_off()
    assert [(h.dev_id, h.node_id, h.gateway_id, v) for h, v in mgr.window_writes] == [
        (dev.id, dev.node_id, dev.mesh_id, False)
    ]
    assert client.calls == [] and client.group_calls == []
    assert coord.commanded == [dev.id] and coord.refreshed is True


async def test_isolated_head_window_local_failure_raises():
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.danfoss_ally_cloud.api.local import tunnel

    dev = head()
    mgr = _FakeManager(fail=tunnel.LocalError("no ack"))
    sw, coord = _switch(_fenetre_desc(), dev, local=_FakeLocalCoord({dev.id: True}, manager=mgr))
    with pytest.raises(HomeAssistantError):
        await sw.async_turn_on()
    assert coord.refreshed is False


async def test_switch_unavailable_for_unverified_product():
    dev = head(product_id="autre")
    sw, _ = _switch(_verrou_desc(), dev, groups={dev.id: "g1"})
    assert sw.available is False


async def test_switch_is_on_none_si_absent():
    coord = _FakeCloudCoord({})
    sw = DanfossSwitch(coord, "absent", _verrou_desc())
    assert sw.is_on is None
    assert sw.available is False


async def test_switch_turn_on_without_device_does_nothing():
    client = _FakeClient()
    coord = _FakeCloudCoord({}, client=client)
    sw = DanfossSwitch(coord, "absent", _verrou_desc())
    await sw.async_turn_on()
    assert client.calls == [] and client.group_calls == []


def test_preheat_is_on_et_available():
    dev = head()
    cloud = _FakeCloudCoord({dev.id: dev})
    local = _FakeLocalCoord({dev.id: True})
    ph = DanfossPreheat(local, cloud, dev.id)
    assert ph.is_on is True
    assert ph.available is True
    assert ph.device_info["model"] == dev.product_id


def test_preheat_unavailable_without_local_value():
    dev = head()
    cloud = _FakeCloudCoord({dev.id: dev})
    local = _FakeLocalCoord({})  # no reliable survey yet
    ph = DanfossPreheat(local, cloud, dev.id)
    assert ph.available is False
    assert ph.is_on is None


def test_preheat_unavailable_if_head_offline():
    dev = head(online=False)
    cloud = _FakeCloudCoord({dev.id: dev})
    local = _FakeLocalCoord({dev.id: False})
    ph = DanfossPreheat(local, cloud, dev.id)
    assert ph.available is False


def test_switches_catalog_not_empty():
    assert {d.key for d in switch_mod.SWITCHES} == {"child_lock", "window_detection"}


async def test_preheat_write_without_device_does_nothing():
    # Head gone from the cloud cache: the write (turn_on) returns before any I/O, without hass.
    cloud = _FakeCloudCoord({})
    local = _FakeLocalCoord({})
    ph = DanfossPreheat(local, cloud, "absent")
    await ph.async_turn_on()  # garde-fou : dev None -> return


class _PreheatManager:
    def __init__(self, accepted=True, fail=None, readback=None):
        self.accepted = accepted
        self.fail = fail
        self.readback = readback
        self.writes: list = []

    def write_preheat(self, head, active):
        if self.fail:
            raise self.fail
        self.writes.append((head.dev_id, active))
        return self.accepted


class _PreheatLocalCoord(_FakeLocalCoord):
    def __init__(self, data, manager):
        super().__init__(data, manager)
        self.refreshed_heads: list = []
        self.full_refresh = False

    async def async_refresh_head(self, head):
        self.refreshed_heads.append(head.dev_id)
        self.data = {**self.data, head.dev_id: self.manager.readback}
        return self.manager.readback

    async def async_request_refresh(self):
        self.full_refresh = True


def _preheat(manager, data=None):
    dev = head(mesh_id="gw-1", node_id="node-1")
    cloud = _FakeCloudCoord({dev.id: dev})
    local = _PreheatLocalCoord(data if data is not None else {dev.id: False}, manager)
    ph = DanfossPreheat(local, cloud, dev.id)
    ph.hass = _FakeHass()
    return ph, local, dev


async def test_preheat_write_reads_back_the_head_only():
    # Regression (real hardware 2026-11-19): after a validated 0x0025 write the switch followed
    # only at the next full survey (~13 min). Now the head is read back right away.
    ph, local, dev = _preheat(_PreheatManager(readback=True))
    await ph.async_turn_on()
    assert local.manager.writes == [(dev.id, True)]
    assert local.refreshed_heads == [dev.id]
    assert local.full_refresh is False  # no whole-site survey
    assert ph.is_on is True


async def test_preheat_state_is_the_read_back_not_the_written_value():
    # The head says False after the write: shown as False, never optimistic.
    ph, local, _ = _preheat(_PreheatManager(readback=False))
    await ph.async_turn_on()
    assert ph.is_on is False


async def test_preheat_unanswered_read_back_makes_switch_unavailable():
    ph, _, _ = _preheat(_PreheatManager(readback=None))
    await ph.async_turn_off()
    assert ph.available is False


async def test_preheat_write_rejected_raises_after_read_back():
    ph, local, dev = _preheat(_PreheatManager(accepted=False, readback=False))
    with pytest.raises(HomeAssistantError):
        await ph.async_turn_on()
    assert local.refreshed_heads == [dev.id]


async def test_preheat_tunnel_failure_raises():
    ph, local, _ = _preheat(_PreheatManager(fail=tunnel.LocalUnavailable("gw down")))
    with pytest.raises(HomeAssistantError):
        await ph.async_turn_on()
    assert local.refreshed_heads == []


# --- isolated head: dedicated-session cloud MQTT path (gated) -----------------------------------


async def test_isolated_head_cloud_mqtt_path_when_enabled():
    """Option ON + a connected link that knows the gateway -> PATH_MQTT, scope head."""
    dev = head(child_lock=True)  # no group -> isolated
    link = _FakeMqttLink(gateways=("gw-1",), connected=True)
    sw, _ = _switch(_verrou_desc(), dev, mqtt=link, cloud_mqtt=True)
    assert sw.available is True
    assert sw.extra_state_attributes == {"write_path": "cloud_mqtt", "write_scope": "head"}


async def test_isolated_head_cloud_mqtt_write_publishes_and_confirms():
    dev = head(child_lock=False)
    link = _FakeMqttLink(confirm=True)
    sw, coord = _switch(_verrou_desc(), dev, mqtt=link, cloud_mqtt=True)
    await sw.async_turn_on()
    assert link.published == [("gw-1", "node-1", {"30": True})]
    assert link.confirmations == [("node-1", 30, True)]  # waited for the inbound confirmation
    assert coord.commanded == [dev.id]  # marked commanded (no optimistic state set)
    assert coord.refreshed is True


@pytest.fixture
def dp116_as_candidate(monkeypatch):
    """Put DP 116 back among the candidates. Both switch DPs (30, 116) are proven on cloud MQTT
    since 2026-11-19, so the generic supervised-trial routing of a switch is exercised by making
    one of them a candidate again for the duration of a test."""
    from custom_components.danfoss_ally_cloud import switch as switch_mod
    from custom_components.danfoss_ally_cloud.api import writes

    monkeypatch.setattr(writes, "MQTT_WRITE_DPS", writes.MQTT_WRITE_DPS - {116})
    candidates = writes.MQTT_CANDIDATE_DPS | {116}
    monkeypatch.setattr(writes, "MQTT_CANDIDATE_DPS", candidates)
    monkeypatch.setattr(switch_mod, "MQTT_CANDIDATE_DPS", candidates)


async def test_a_candidate_dp_is_closed_on_cloud_mqtt_by_default(dp116_as_candidate):
    """A candidate, not proven: with the option on and the link connected it still does not route
    through MQTT until it is listed for a supervised trial (here: unavailable)."""
    dev = head(window_detection=True)  # isolated, no tunnel -> no path
    link = _FakeMqttLink(connected=True)
    sw, _ = _switch(_fenetre_desc(), dev, mqtt=link, cloud_mqtt=True)
    assert sw.extra_state_attributes == {"write_path": "none"}
    assert sw.available is False


async def test_window_dp116_falls_back_to_cloud_mqtt_when_the_tunnel_is_unavailable():
    """DP 116 is proven on cloud MQTT (2026-11-19): an isolated head with no usable tunnel gets a
    window-detection write through it, with no trial and no trial marker."""
    dev = head(window_detection=True)  # isolated, no tunnel
    link = _FakeMqttLink(confirm=True)
    sw, coord = _switch(_fenetre_desc(), dev, mqtt=link, cloud_mqtt=True)
    assert sw.available is True
    assert sw.extra_state_attributes == {"write_path": "cloud_mqtt", "write_scope": "head"}
    await sw.async_turn_off()
    assert link.published == [("gw-1", "node-1", {"116": False})]
    assert link.confirmations == [("node-1", 116, False)]
    assert coord.commanded == [dev.id] and coord.refreshed is True


async def test_window_dp116_needs_the_option_and_a_connected_link_for_the_fallback():
    dev = head(window_detection=True)  # isolated, no tunnel
    off, _ = _switch(_fenetre_desc(), dev, mqtt=_FakeMqttLink(confirm=True), cloud_mqtt=False)
    assert off.available is False and off.extra_state_attributes == {"write_path": "none"}
    down, _ = _switch(_fenetre_desc(), dev, mqtt=_FakeMqttLink(connected=False), cloud_mqtt=True)
    assert down.available is False and down.extra_state_attributes == {"write_path": "none"}


async def test_window_dp116_supervised_trial_routes_and_writes_via_cloud_mqtt(
    dp116_as_candidate,
):
    dev = head(window_detection=True)
    link = _FakeMqttLink(confirm=True)
    sw, coord = _switch(
        _fenetre_desc(), dev, mqtt=link, cloud_mqtt=True, supervised=frozenset({116})
    )
    assert sw.available is True
    assert sw.extra_state_attributes == {
        "write_path": "cloud_mqtt",
        "write_scope": "head",
        "write_trial": True,
    }
    await sw.async_turn_off()
    assert link.published == [("gw-1", "node-1", {"116": False})]
    assert link.confirmations == [("node-1", 116, False)]
    assert coord.commanded == [dev.id] and coord.refreshed is True


async def test_window_dp116_trial_takes_cloud_mqtt_even_when_the_tunnel_is_up(
    dp116_as_candidate,
):
    """During the supervised trial the DP goes through the channel under test; the tunnel stays
    free to read the result back."""
    dev = head(window_detection=True)
    mgr = _FakeManager()
    local = _FakeLocalCoord({dev.id: False}, manager=mgr)
    link = _FakeMqttLink(confirm=True)
    sw, _ = _switch(
        _fenetre_desc(),
        dev,
        local=local,
        mqtt=link,
        cloud_mqtt=True,
        supervised=frozenset({116}),
    )
    assert sw.extra_state_attributes["write_path"] == "cloud_mqtt"
    await sw.async_turn_off()
    assert link.published and mgr.window_writes == []


async def test_window_dp116_keeps_the_tunnel_first():
    """Proven on both channels: the tunnel write stays the route when the head answers locally,
    cloud MQTT is only the fallback and is not used."""
    dev = head(window_detection=True)
    mgr = _FakeManager()
    local = _FakeLocalCoord({dev.id: False}, manager=mgr)
    link = _FakeMqttLink(confirm=True)
    sw, _ = _switch(_fenetre_desc(), dev, local=local, mqtt=link, cloud_mqtt=True)
    assert sw.extra_state_attributes == {"write_path": "local", "write_scope": "head"}
    await sw.async_turn_off()
    assert link.published == [] and len(mgr.window_writes) == 1


async def test_supervised_trial_needs_the_cloud_mqtt_option(dp116_as_candidate):
    dev = head(window_detection=True)
    link = _FakeMqttLink(confirm=True)
    sw, _ = _switch(_fenetre_desc(), dev, mqtt=link, cloud_mqtt=False, supervised=frozenset({116}))
    assert sw.available is False and sw.extra_state_attributes == {"write_path": "none"}


async def test_proven_dp_is_not_marked_as_trial_even_if_listed():
    dev = head(child_lock=True)
    link = _FakeMqttLink()
    sw, _ = _switch(
        _verrou_desc(), dev, mqtt=link, cloud_mqtt=True, supervised=frozenset({30, 116})
    )
    assert sw.extra_state_attributes == {"write_path": "cloud_mqtt", "write_scope": "head"}


async def test_cloud_mqtt_write_without_echo_is_confirmed_by_the_per_device_read():
    dev = head(child_lock=False)
    client = _FakeClient()
    client.device_dps = {dev.id: {"30": True, "116": True}}
    link = _FakeMqttLink(confirm=False)
    sw, coord = _switch(_verrou_desc(), dev, client=client, mqtt=link, cloud_mqtt=True)
    await sw.async_turn_on()  # no error: the head's own route shows the written value
    assert client.device_reads == [dev.id]
    assert coord.refreshed is True


async def test_cloud_mqtt_write_without_echo_and_unreadable_head_raises():
    from custom_components.danfoss_ally_cloud.api import CloudError

    dev = head(child_lock=False)
    client = _FakeClient()
    client.device_dps = {dev.id: CloudError("synthetic")}
    link = _FakeMqttLink(confirm=False)
    sw, _ = _switch(_verrou_desc(), dev, client=client, mqtt=link, cloud_mqtt=True)
    with pytest.raises(HomeAssistantError, match="not confirmed"):
        await sw.async_turn_on()


async def test_cloud_mqtt_write_on_a_head_without_gateway_address_raises():
    from custom_components.danfoss_ally_cloud.mqtt_write import async_mqtt_write

    dev = head(child_lock=False, node_id=None)
    coord = _FakeCloudCoord({dev.id: dev}, client=_FakeClient())
    link = _FakeMqttLink()
    with pytest.raises(HomeAssistantError, match="gateway address"):
        await async_mqtt_write(coord, link, dev, {30: True})
    assert link.published == []


async def test_cloud_mqtt_write_refuses_a_closed_or_invalid_value_before_sending():
    from custom_components.danfoss_ally_cloud.mqtt_write import async_mqtt_write

    dev = head()
    coord = _FakeCloudCoord({dev.id: dev}, client=_FakeClient())
    link = _FakeMqttLink()
    with pytest.raises(HomeAssistantError, match="supervised first write"):
        await async_mqtt_write(coord, link, dev, {118: 205})  # candidate, not opened
    with pytest.raises(HomeAssistantError, match="not enabled"):
        await async_mqtt_write(coord, link, dev, {2: "manual"}, supervised=frozenset({2}))
    with pytest.raises(HomeAssistantError, match="boolean"):
        await async_mqtt_write(coord, link, dev, {30: 1})
    assert link.published == [] and link.confirmations == []


async def test_cloud_mqtt_write_unconfirmed_and_cloud_still_differs_raises():
    from homeassistant.exceptions import HomeAssistantError

    dev = head(child_lock=False)  # cloud re-read keeps child_lock False, != commanded True
    link = _FakeMqttLink(confirm=False)
    sw, coord = _switch(_verrou_desc(), dev, mqtt=link, cloud_mqtt=True)
    with pytest.raises(HomeAssistantError):
        await sw.async_turn_on()
    assert link.published  # it did send
    assert coord.refreshed is True  # tried a cloud re-read before failing


async def test_cloud_mqtt_ignored_when_option_off():
    """Gate OFF but link present -> isolated head is NOT routed to MQTT (stays unavailable)."""
    dev = head(child_lock=True)
    link = _FakeMqttLink()
    sw, _ = _switch(_verrou_desc(), dev, mqtt=link, cloud_mqtt=False)
    assert sw.available is False
    assert sw.extra_state_attributes["write_path"] == "none"


async def test_cloud_mqtt_unavailable_when_link_not_connected():
    dev = head(child_lock=True)
    link = _FakeMqttLink(connected=False)
    sw, _ = _switch(_verrou_desc(), dev, mqtt=link, cloud_mqtt=True)
    assert sw.available is False  # never optimistic when the link cannot send


async def test_grouped_head_prefers_room_over_cloud_mqtt():
    """A grouped head keeps the proven ROOM path even if the MQTT link is available."""
    dev = head(child_lock=False)
    client = _FakeClient()
    link = _FakeMqttLink()
    sw, _ = _switch(
        _verrou_desc(), dev, client=client, groups={dev.id: "g1"}, mqtt=link, cloud_mqtt=True
    )
    assert sw.extra_state_attributes["write_path"] == "room"
    await sw.async_turn_on()
    assert client.group_calls == [("g1", {"30": True})]
    assert link.published == []  # not sent over MQTT


async def test_cloud_mqtt_write_failure_raises_homeassistanterror():
    from homeassistant.exceptions import HomeAssistantError

    dev = head(child_lock=False)
    link = _FakeMqttLink(fail=RuntimeError("broker down"))
    sw, _ = _switch(_verrou_desc(), dev, mqtt=link, cloud_mqtt=True)
    with pytest.raises(HomeAssistantError):
        await sw.async_turn_on()


# --- routing with the non-blocking tunnel start: a head is known locally only once read ----------


async def test_window_routing_before_and_after_the_first_local_read():
    """The local survey now runs in the background and ``data`` starts empty. Until the head has
    been read there is no tunnel route: unavailable without the cloud-MQTT option, cloud MQTT
    (the proven fallback of DP 116) with it. Once read, the tunnel is the route again."""
    dev = head(window_detection=True)
    mgr = _FakeManager()
    local = _FakeLocalCoord({}, manager=mgr)  # survey running, nothing read yet
    link = _FakeMqttLink(confirm=True)

    plain, _ = _switch(_fenetre_desc(), dev, local=local, mqtt=link, cloud_mqtt=False)
    assert plain.available is False and plain.extra_state_attributes == {"write_path": "none"}
    await plain.async_turn_off()  # no route: nothing is sent anywhere
    assert link.published == [] and mgr.window_writes == []

    fallback, _ = _switch(_fenetre_desc(), dev, local=local, mqtt=link, cloud_mqtt=True)
    assert fallback.extra_state_attributes == {"write_path": "cloud_mqtt", "write_scope": "head"}

    local.data = {dev.id: False}  # the survey has read this head
    assert plain.available is True
    assert plain.extra_state_attributes == {"write_path": "local", "write_scope": "head"}
    # The tunnel takes over as soon as the head answers locally.
    assert fallback.extra_state_attributes == {"write_path": "local", "write_scope": "head"}


async def test_child_lock_on_cloud_mqtt_does_not_wait_for_the_local_survey():
    """A DP proven on cloud MQTT with no tunnel write (child lock) is routable at once."""
    dev = head(child_lock=False)
    local = _FakeLocalCoord({}, manager=_FakeManager())
    sw, _ = _switch(_verrou_desc(), dev, local=local, mqtt=_FakeMqttLink(), cloud_mqtt=True)
    assert sw.extra_state_attributes == {"write_path": "cloud_mqtt", "write_scope": "head"}
