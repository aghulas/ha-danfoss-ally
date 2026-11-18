"""Head unbind ("disconnect") — fakes only, no network, synthetic data.

Covers the client payload (``smartlife.m.device.reset`` v3.0 ``{devId, resetFactory}``) and the
triple-gated ``disconnect_head`` operation (opt-in flag + verified head + explicit confirm, admin
enforced by the service layer).
"""

from unittest.mock import patch

import pytest

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.api.client import CloudClient, CloudWriteError
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DATA_HEAD_UNBIND

from .common import head, relay
from .test_client_async import FakeHttp

_HTTP = "custom_components.danfoss_ally_cloud.api.client.TuyaHttpClient"
_DEV = {"type": "device", "id": "a"}


# --- client payload ----------------------------------------------------------------------------


def _client():
    return CloudClient("u", "p", "33", "sk", "dev", "ck", sid="s", ecode="e")


@pytest.mark.parametrize("wipe", [False, True])
async def test_device_reset_payload(wipe):
    fake = FakeHttp({"smartlife.m.device.reset": {"ok": True}})
    with patch(_HTTP, return_value=fake):
        await _client().async_device_reset("devX", wipe)
    api, version, body, _ = fake.calls[0]
    assert api == "smartlife.m.device.reset"
    assert version == "3.0"
    assert body == {"devId": "devX", "resetFactory": wipe}


async def test_device_reset_requires_dev_id():
    with pytest.raises(CloudWriteError):
        await _client().async_device_reset("")


# --- operations --------------------------------------------------------------------------------


class _FakeClient:
    def __init__(self):
        self.reset_calls: list = []

    async def async_device_reset(self, dev_id, reset_factory=False):
        self.reset_calls.append((dev_id, reset_factory))
        return {"ok": True}


class _FakeCoord:
    def __init__(self, client, data):
        self.client = client
        self.data = data
        self.refreshed = 0
        self.invalidated = 0

    def invalidate_topology(self):
        self.invalidated += 1

    async def async_request_refresh(self):
        self.refreshed += 1


def _store(coord, *, enabled=True):
    return {DATA_COORDINATOR: coord, DATA_HEAD_UNBIND: enabled}


def _coord(**devices):
    return _FakeCoord(_FakeClient(), devices or {"a": head("a", "A")})


async def test_disconnect_success_keeps_identity():
    coord = _coord()
    res = await ops.disconnect_head(None, _store(coord), _DEV, confirm=True)
    assert coord.client.reset_calls == [("a", False)]
    assert (
        res["mode"] == "disconnect" and res["wipe_data"] is False and res["irreversible"] is False
    )
    # the head left the account -> topology invalidated then refreshed
    assert coord.invalidated == 1 and coord.refreshed == 1


async def test_disconnect_wipe_is_irreversible():
    coord = _coord()
    res = await ops.disconnect_head(None, _store(coord), _DEV, wipe_data=True, confirm=True)
    assert coord.client.reset_calls == [("a", True)]
    assert res["mode"] == "disconnect_and_wipe" and res["irreversible"] is True


async def test_disconnect_refused_when_option_disabled():
    coord = _coord()
    with pytest.raises(ops.OperationError) as e:
        await ops.disconnect_head(None, _store(coord, enabled=False), _DEV, confirm=True)
    assert e.value.code == "unbind_disabled"
    assert coord.client.reset_calls == []  # nothing sent


async def test_disconnect_requires_explicit_confirm():
    coord = _coord()
    with pytest.raises(ops.OperationError) as e:
        await ops.disconnect_head(None, _store(coord), _DEV)  # confirm defaults to False
    assert e.value.code == "confirmation_required"
    assert coord.client.reset_calls == []


async def test_disconnect_refuses_non_device_target():
    coord = _coord()
    with pytest.raises(ops.OperationError) as e:
        await ops.disconnect_head(None, _store(coord), {"type": "room", "id": "g1"}, confirm=True)
    assert e.value.code == "device_only"
    assert coord.client.reset_calls == []


async def test_disconnect_refuses_unknown_device():
    coord = _coord()
    with pytest.raises(ops.OperationError) as e:
        await ops.disconnect_head(
            None, _store(coord), {"type": "device", "id": "ghost"}, confirm=True
        )
    assert e.value.code == "unknown_target"


async def test_disconnect_accepts_relay():
    # Widened scope (mirrors MCP connector PR #7): a relay is an unbindable sub-device.
    coord = _coord(a=relay("a", "Relay"))
    res = await ops.disconnect_head(None, _store(coord), _DEV, confirm=True)
    assert coord.client.reset_calls == [("a", False)]
    assert res["category"] == "relay"


async def test_disconnect_accepts_sensor():
    coord = _coord(a=head("a", "Sensor", category="sensor"))
    res = await ops.disconnect_head(None, _store(coord), _DEV, confirm=True)
    assert coord.client.reset_calls == [("a", False)]
    assert res["category"] == "sensor"


async def test_disconnect_accepts_unverified_product():
    # No verified-product gate on unbind (category-generic call): an unknown product is accepted.
    coord = _coord(a=head("a", "A", product_id="other"))
    await ops.disconnect_head(None, _store(coord), _DEV, confirm=True)
    assert coord.client.reset_calls == [("a", False)]


async def test_disconnect_refuses_gateway():
    # A gateway is the one refused category: unbinding it would drop all its heads.
    coord = _coord(a=head("a", "Gateway", category="gateway"))
    with pytest.raises(ops.OperationError) as e:
        await ops.disconnect_head(None, _store(coord), _DEV, confirm=True)
    assert e.value.code == "gateway_target"
    assert coord.client.reset_calls == []


async def test_ensure_admin_refuses_user_less_call_when_internal_disallowed():
    # disconnect_head passes allow_internal=False: an automation/script with no user is refused.
    with pytest.raises(ops.OperationError) as e:
        await ops.ensure_admin(None, None, allow_internal=False)
    assert e.value.code == "not_admin"
    # default (shared by other writes) still allows the internal call
    await ops.ensure_admin(None, None)
