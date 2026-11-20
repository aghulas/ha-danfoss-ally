"""Local coordinator tests (preheat survey), doubled manager, hass harness."""

import asyncio
import threading

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.danfoss_ally_cloud.coordinator import (
    DanfossCoordinator,
    DanfossLocalCoordinator,
)

from .common import FakeCloudClient, head


class FakeManager:
    """Double of LocalTunnelManager: one gateway gw-1, controlled survey/write."""

    def __init__(self, survey=None, releve_exc=None):
        self._survey = survey or {}
        self._exc = releve_exc
        self.ecrits: list = []

    @property
    def gateway_ids(self):
        return {"gw-1"}

    def survey_preheat(self, heads, on_result=None, stop=None):
        if self._exc is not None:
            raise self._exc
        res = {h.dev_id: self._survey.get(h.dev_id, True) for h in heads}
        for dev_id, value in res.items():
            if on_result is not None:
                on_result(dev_id, value)
        return res

    def write_preheat(self, head, actif):
        self.ecrits.append((head.dev_id, actif))
        return True

    def read_preheat(self, head):
        if self._exc is not None:
            raise self._exc
        return self._survey.get(head.dev_id)


def _cloud(hass, data):
    coord = DanfossCoordinator(hass, FakeCloudClient(), 90)
    coord.data = data
    return coord


async def test_heads_filtre_sur_passerelle(hass: HomeAssistant):
    cloud = _cloud(
        hass,
        {
            "dev-1": head("dev-1", mesh_id="gw-1", node_id="node-1"),
            "dev-2": head("dev-2", mesh_id="gw-absente", node_id="node-2"),
            "dev-3": head("dev-3", mesh_id="gw-1", node_id=None),  # pas de node_id
        },
    )
    local = DanfossLocalCoordinator(hass, FakeManager(), cloud, 900)
    assert [h.dev_id for h in local.heads()] == ["dev-1"]
    # The heads left out are named with their reason (get_local_survey accounts for every head).
    assert local.unaddressable() == {"dev-2": "no_gateway_key", "dev-3": "no_node_id"}


async def test_survey_returns_the_values(hass: HomeAssistant):
    cloud = _cloud(hass, {"dev-1": head("dev-1", mesh_id="gw-1", node_id="node-1")})
    local = DanfossLocalCoordinator(hass, FakeManager(survey={"dev-1": True}), cloud, 900)
    assert await local._async_update_data() == {"dev-1": True}


async def test_survey_without_head_returns_empty(hass: HomeAssistant):
    cloud = _cloud(hass, {})
    local = DanfossLocalCoordinator(hass, FakeManager(), cloud, 900)
    assert await local._async_update_data() == {}


async def test_survey_error_raises_updatefailed(hass: HomeAssistant):
    cloud = _cloud(hass, {"dev-1": head("dev-1", mesh_id="gw-1", node_id="node-1")})
    local = DanfossLocalCoordinator(
        hass, FakeManager(releve_exc=RuntimeError("tunnel ko")), cloud, 900
    )
    with pytest.raises(UpdateFailed):
        await local._async_update_data()


async def test_refresh_head_updates_only_that_head(hass: HomeAssistant):
    # Regression (real hardware 2026-11-19): after a preheat write the state followed only at the
    # next full survey (~13 min). The head is now read back alone, other heads untouched.
    from custom_components.danfoss_ally_cloud.api.local.manager import Head

    cloud = _cloud(hass, {})
    local = DanfossLocalCoordinator(hass, FakeManager(survey={"dev-1": False}), cloud, 900)
    local.data = {"dev-1": True, "dev-2": True}
    seen: list = []
    local.async_update_listeners = lambda: seen.append(dict(local.data))  # type: ignore[method-assign]
    assert await local.async_refresh_head(Head("dev-1", "node-1", "gw-1")) is False
    assert local.data == {"dev-1": False, "dev-2": True}
    assert seen == [{"dev-1": False, "dev-2": True}]  # listeners notified


async def test_refresh_head_failure_is_unknown_not_assumed(hass: HomeAssistant):
    from custom_components.danfoss_ally_cloud.api.local.manager import Head

    cloud = _cloud(hass, {})
    local = DanfossLocalCoordinator(
        hass, FakeManager(releve_exc=RuntimeError("tunnel ko")), cloud, 900
    )
    local.data = {"dev-1": True}
    assert await local.async_refresh_head(Head("dev-1", "node-1", "gw-1")) is None
    assert local.data == {"dev-1": None}  # unknown -> switch unavailable, never the written value


class GatedManager(FakeManager):
    """A survey that reads one head each time the test opens that head's gate (a slow site).

    Like the real manager: publishes each head through ``on_result`` as it is read and gives up as
    soon as ``stop`` is set. ``max_wait`` bounds a head, so a failing test leaves no thread behind.
    """

    def __init__(self, survey=None, max_wait=5.0):
        super().__init__(survey=survey)
        self.gates: dict[str, threading.Event] = {}
        self.read: dict[str, threading.Event] = {}
        self.started = threading.Event()
        self.finished = threading.Event()
        self.aborted = False
        self.calls = 0
        self._max_wait = max_wait

    def gate(self, dev_id):
        return self.gates.setdefault(dev_id, threading.Event())

    def was_read(self, dev_id):
        return self.read.setdefault(dev_id, threading.Event())

    def survey_preheat(self, heads, on_result=None, stop=None):
        self.calls += 1
        self.started.set()
        res = {}
        try:
            for h in heads:
                waited = 0.0
                while not self.gate(h.dev_id).wait(0.01):
                    waited += 0.01
                    if (stop is not None and stop.is_set()) or waited > self._max_wait:
                        self.aborted = True
                        return res
                res[h.dev_id] = self._survey.get(h.dev_id, True)
                if on_result is not None:
                    on_result(h.dev_id, res[h.dev_id])
                self.was_read(h.dev_id).set()
            return res
        finally:
            self.finished.set()


async def _wait(hass, event, seconds=3.0):
    """Wait for a thread-side event without blocking the loop, then let the loop run callbacks."""
    assert await hass.async_add_executor_job(event.wait, seconds)
    await hass.async_block_till_done()


def _two_heads(hass):
    return _cloud(
        hass,
        {
            "dev-1": head("dev-1", mesh_id="gw-1", node_id="node-1"),
            "dev-2": head("dev-2", name="Bureau", mesh_id="gw-1", node_id="node-2"),
        },
    )


async def test_nothing_is_known_before_the_first_survey(hass: HomeAssistant):
    """Before any read ``data`` is an empty mapping: no head has a state, none is assumed."""
    local = DanfossLocalCoordinator(hass, FakeManager(), _two_heads(hass), 900)
    assert local.data == {}


async def test_survey_publishes_each_head_as_it_is_read(hass: HomeAssistant):
    manager = GatedManager(survey={"dev-1": True, "dev-2": False})
    local = DanfossLocalCoordinator(hass, manager, _two_heads(hass), 900)
    seen: list = []
    local.async_add_listener(lambda: seen.append(dict(local.data)))
    task = hass.async_create_background_task(local.async_refresh(), "survey")

    await _wait(hass, manager.started)
    assert local.data == {} and seen == []  # survey running, nothing read: nothing shown

    manager.gate("dev-1").set()
    await _wait(hass, manager.was_read("dev-1"))
    assert local.data == {"dev-1": True}  # first head available, the second still unknown
    assert seen == [{"dev-1": True}]

    manager.gate("dev-2").set()
    await task
    assert local.data == {"dev-1": True, "dev-2": False}
    await local.async_shutdown()


async def test_only_one_survey_at_a_time(hass: HomeAssistant):
    """A refresh asked while a survey runs must not start a second one on the gateways."""
    manager = GatedManager(survey={"dev-1": True, "dev-2": True})
    local = DanfossLocalCoordinator(hass, manager, _two_heads(hass), 900)
    task = hass.async_create_background_task(local.async_refresh(), "survey")
    await _wait(hass, manager.started)
    manager.gate("dev-1").set()
    await _wait(hass, manager.was_read("dev-1"))

    # e.g. the scan interval elapsing during a long survey (recent HA serialises `async_refresh`
    # itself, older lines and the interval path do not): what is known is kept, nothing invented.
    assert await local._async_update_data() == {"dev-1": True}
    assert manager.calls == 1

    manager.gate("dev-2").set()
    await task
    assert manager.calls == 1 and local.data == {"dev-1": True, "dev-2": True}
    await local.async_shutdown()


async def test_read_back_during_survey_is_not_overwritten(hass: HomeAssistant):
    """A head written then read back while the survey runs keeps its read-back value: the survey
    read it BEFORE the write and must not put the old state back at the end."""
    from custom_components.danfoss_ally_cloud.api.local.manager import Head

    manager = GatedManager(survey={"dev-1": True, "dev-2": True})
    local = DanfossLocalCoordinator(hass, manager, _two_heads(hass), 900)
    task = hass.async_create_background_task(local.async_refresh(), "survey")
    await _wait(hass, manager.started)
    manager.gate("dev-1").set()
    await _wait(hass, manager.was_read("dev-1"))
    assert local.data == {"dev-1": True}

    manager._survey["dev-1"] = False  # the head now says OFF (it was just written)
    assert await local.async_refresh_head(Head("dev-1", "node-1", "gw-1")) is False
    manager.gate("dev-2").set()
    await task
    assert local.data == {"dev-1": False, "dev-2": True}
    await local.async_shutdown()


async def test_cancelled_survey_releases_the_gateways(hass: HomeAssistant):
    """Cancelling the refresh (entry unload, HA stop) aborts the survey instead of orphaning it."""
    manager = GatedManager()
    local = DanfossLocalCoordinator(hass, manager, _two_heads(hass), 900)
    task = hass.async_create_background_task(local.async_refresh(), "survey")
    await _wait(hass, manager.started)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await _wait(hass, manager.finished)
    assert manager.aborted is True
    assert local.data == {}
    await local.async_shutdown()
