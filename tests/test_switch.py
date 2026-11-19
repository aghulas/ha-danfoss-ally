"""Switch entity tests (fake coordinator, without starting Home Assistant).

async_setup_entry and the preheat write (self.hass.async_add_executor_job) belong to the hass
harness and are covered elsewhere; here we test the state logic and the guarded write.
"""

import pytest

from custom_components.danfoss_ally_cloud import switch as switch_mod
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

    async def async_write_setting(self, dev_id, pid, dps, *, gw_id=None):
        self.calls.append((dev_id, pid, dps, gw_id))

    async def async_group_publish(self, group_id, dps):
        self.group_calls.append((group_id, dps))


def _verrou_desc():
    return next(d for d in SWITCHES if d.key == "child_lock")


def _fenetre_desc():
    return next(d for d in SWITCHES if d.key == "window_detection")


def _switch(desc, dev, *, client=None, groups=None, local=None):
    coord = _FakeCloudCoord({dev.id: dev}, client=client, groups=groups)
    sw = DanfossSwitch(coord, dev.id, desc, local)
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
