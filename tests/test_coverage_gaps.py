"""Targeted tests closing error-path and edge-case coverage gaps across
``frontend.py``, ``services.py``, ``websocket_api.py``, and ``operations.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.danfoss_ally_cloud import frontend, services, websocket_api
from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.api import (
    CloudError,
    ScheduleValidationError,
    UnknownTargetError,
)
from custom_components.danfoss_ally_cloud.const import (
    DATA_COORDINATOR,
    DATA_JOBS,
    DATA_SCHEDULES,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.writejob import JobManager

# --- frontend.py -------------------------------------------------------------------------------


async def test_frontend_error_paths_and_idempotency(hass: HomeAssistant) -> None:
    """Best-effort error paths and idempotency in frontend registration/cleanup."""
    # _async_resource_url falls back to ?v=0 on integration lookup failure
    with patch(
        "custom_components.danfoss_ally_cloud.frontend.async_get_integration",
        side_effect=RuntimeError("boom"),
    ):
        url = await frontend._async_resource_url(hass)
    assert url.endswith("?v=0")

    # _async_register_static_path: once registered, second call is a no-op
    hass.data[frontend._DATA_STATIC_REGISTERED] = True
    await frontend._async_register_static_path(hass)
    assert hass.data[frontend._DATA_STATIC_REGISTERED] is True

    # _async_remove_panel swallows errors from ha_frontend.async_remove_panel and resets flag
    hass.data[frontend._DATA_PANEL_REGISTERED] = True
    with patch(
        "homeassistant.components.frontend.async_remove_panel",
        side_effect=RuntimeError("panel gone"),
    ):
        frontend._async_remove_panel(hass)
    assert hass.data[frontend._DATA_PANEL_REGISTERED] is False

    # _async_register_resource & _async_remove_resource best-effort on failing storage collection
    class BrokenResources:
        loaded = False

        async def async_load(self) -> None:
            raise RuntimeError("storage read failed")

    fake_res = BrokenResources()
    with patch.object(frontend, "_resources_collection", return_value=fake_res):
        await frontend._async_register_resource(hass, url)
        await frontend._async_remove_resource(hass, url)

    # _async_remove_resource lazy-loads when loaded=False and deletes matching item
    deleted: list[str] = []

    class LazyResources:
        loaded = False

        async def async_load(self) -> None:
            self.loaded = True

        def async_items(self) -> list[dict]:
            return [{"id": "res1", "url": url}]

        async def async_delete_item(self, item_id: str) -> None:
            deleted.append(item_id)

    lazy = LazyResources()
    with patch.object(frontend, "_resources_collection", return_value=lazy):
        await frontend._async_remove_resource(hass, url)
    assert lazy.loaded is True and deleted == ["res1"]


# --- services.py -------------------------------------------------------------------------------


async def test_services_store_resolution_and_error_translation(hass: HomeAssistant) -> None:
    """_store error cases, idempotent registration, and OperationError -> ServiceValidationError."""
    services.async_register_services(hass)
    services.async_register_services(hass)  # idempotent second call

    # No account configured
    with pytest.raises(ServiceValidationError, match="no danfoss_ally_cloud account"):
        await hass.services.async_call(DOMAIN, "get_rooms", {}, blocking=True, return_response=True)

    # Multiple entries without config_entry_id
    hass.data[DOMAIN] = {
        "e1": {DATA_COORDINATOR: MagicMock(), DATA_JOBS: JobManager(), DATA_SCHEDULES: {}},
        "e2": {DATA_COORDINATOR: MagicMock(), DATA_JOBS: JobManager(), DATA_SCHEDULES: {}},
    }
    with pytest.raises(ServiceValidationError, match="several config entries"):
        await hass.services.async_call(DOMAIN, "get_rooms", {}, blocking=True, return_response=True)

    # Unknown config_entry_id
    with pytest.raises(ServiceValidationError, match="unknown entry"):
        await hass.services.async_call(
            DOMAIN,
            "get_rooms",
            {"config_entry_id": "missing"},
            blocking=True,
            return_response=True,
        )

    # Single entry for remaining service error translations
    hass.data[DOMAIN] = {
        "e1": {DATA_COORDINATOR: MagicMock(), DATA_JOBS: JobManager(), DATA_SCHEDULES: {}}
    }

    # Unknown job_id
    with pytest.raises(ServiceValidationError, match="unknown job"):
        await hass.services.async_call(
            DOMAIN,
            "get_write_job",
            {"job_id": "nope"},
            blocking=True,
            return_response=True,
        )

    op_err = ops.OperationError("cloud_refused", "boom")
    cases = [
        ("get_schedule", {"target": {"type": "room", "id": "1"}}, "get_schedule"),
        ("restore_schedule", {"target": {"type": "room", "id": "1"}}, "restore_schedule"),
        ("rename_room", {"target": {"type": "room", "id": "1"}, "name": "X"}, "rename_room"),
        ("delete_room", {"target": {"type": "room", "id": "1"}}, "delete_room"),
        (
            "set_relay_room",
            {"relay": "r1", "target": {"type": "room", "id": "1"}, "linked": True},
            "set_relay_room",
        ),
        (
            "attach_heads",
            {"target": {"type": "room", "id": "1"}, "devices": ["d1"]},
            "attach_heads",
        ),
        (
            "detach_heads",
            {"target": {"type": "room", "id": "1"}, "devices": ["d1"]},
            "detach_heads",
        ),
        ("cancel_vacation", {"home": "h1"}, "cancel_vacation"),
        ("end_vacation", {"home": "h1", "temperature": 15.0}, "end_vacation"),
    ]
    for svc_name, payload, op_name in cases:
        with (
            patch.object(ops, "ensure_admin", AsyncMock()),
            patch.object(ops, op_name, AsyncMock(side_effect=op_err)),
            pytest.raises(ServiceValidationError, match="boom"),
        ):
            await hass.services.async_call(
                DOMAIN,
                svc_name,
                payload,
                blocking=True,
                return_response=svc_name == "get_schedule",
            )


# --- websocket_api.py --------------------------------------------------------------------------


class _FakeConn:
    def __init__(self, is_admin: bool = True) -> None:
        self.user = SimpleNamespace(is_admin=is_admin)
        self.results: list[tuple[int, object]] = []
        self.errors: list[tuple[int, str, str]] = []

    def send_result(self, msg_id: int, payload: object) -> None:
        self.results.append((msg_id, payload))

    def send_error(self, msg_id: int, code: str, message: str) -> None:
        self.errors.append((msg_id, code, message))


async def test_websocket_no_account_and_handlers(hass: HomeAssistant) -> None:
    """WS handlers return unknown_target when unconfigured and forward results/errors cleanly."""
    conn = _FakeConn(is_admin=True)
    hass.data.pop(DOMAIN, None)

    # Sync read commands with no configured account
    for fn in (
        websocket_api.ws_rooms,
        websocket_api.ws_holiday,
        websocket_api.ws_relays,
        websocket_api.ws_overview,
    ):
        fn(hass, conn, {"id": 1})
    assert len(conn.errors) == 4
    assert all(code == "unknown_target" for _, code, _ in conn.errors)

    # Async read commands with no configured account (bypass async_response wrapper)
    for fn, msg in (
        (websocket_api.ws_room_get, {"id": 2, "target": {"type": "room", "id": "1"}}),
        (websocket_api.ws_local_survey, {"id": 3}),
        (
            websocket_api.ws_schedule_get,
            {"id": 4, "target": {"type": "room", "id": "1"}, "refresh": False},
        ),
    ):
        await fn.__wrapped__(hass, conn, msg)
    assert len(conn.errors) == 7

    # Configured store: test success + OperationError paths on local/schedule WS handlers
    hass.data[DOMAIN] = {
        "e1": {DATA_COORDINATOR: MagicMock(), DATA_JOBS: JobManager(), DATA_SCHEDULES: {}}
    }
    conn2 = _FakeConn(is_admin=True)

    with patch.object(ops, "local_survey", AsyncMock(return_value={"heads": []})):
        await websocket_api.ws_local_survey.__wrapped__(hass, conn2, {"id": 10})
    assert conn2.results[-1] == (10, {"heads": []})

    with patch.object(ops, "set_descaling", AsyncMock(return_value={"ok": True})):
        await websocket_api.ws_set_descaling.__wrapped__.__wrapped__(
            hass,
            conn2,
            {
                "id": 11,
                "target": {"type": "device", "id": "h1"},
                "day": "monday",
                "time": "10:00",
            },
        )
    assert conn2.results[-1] == (11, {"ok": True})

    with patch.object(ops, "set_override", AsyncMock(return_value={"ok": True})):
        await websocket_api.ws_set_override.__wrapped__.__wrapped__(
            hass, conn2, {"id": 12, "target": {"type": "device", "id": "h1"}, "temperature": 21.0}
        )
    assert conn2.results[-1] == (12, {"ok": True})

    with patch.object(ops, "clear_override", AsyncMock(return_value={"ok": True})):
        await websocket_api.ws_clear_override.__wrapped__.__wrapped__(
            hass, conn2, {"id": 13, "target": {"type": "device", "id": "h1"}}
        )
    assert conn2.results[-1] == (13, {"ok": True})

    with patch.object(ops, "set_window_detection", AsyncMock(return_value={"ok": True})):
        await websocket_api.ws_set_window_detection.__wrapped__.__wrapped__(
            hass, conn2, {"id": 14, "target": {"type": "device", "id": "h1"}, "enabled": True}
        )
    assert conn2.results[-1] == (14, {"ok": True})

    op_err = ops.OperationError("cloud_refused", "failed")
    with patch.object(ops, "get_schedule", AsyncMock(side_effect=op_err)):
        await websocket_api.ws_schedule_get.__wrapped__(
            hass, conn2, {"id": 15, "target": {"type": "room", "id": "1"}, "refresh": False}
        )
    with patch.object(ops, "set_schedule", AsyncMock(side_effect=op_err)):
        await websocket_api.ws_schedule_set.__wrapped__.__wrapped__(
            hass, conn2, {"id": 16, "target": {"type": "room", "id": "1"}, "days": {}}
        )
    with patch.object(ops, "restore_schedule", AsyncMock(side_effect=op_err)):
        await websocket_api.ws_schedule_restore.__wrapped__.__wrapped__(
            hass, conn2, {"id": 17, "target": {"type": "room", "id": "1"}}
        )
    assert [e[0] for e in conn2.errors] == [15, 16, 17]


# --- operations.py -----------------------------------------------------------------------------


async def test_operations_run_write_and_defer_verification(hass: HomeAssistant) -> None:
    """_run_write maps API errors to OperationError and _defer_verification swallows errors."""
    sched_err = ScheduleValidationError(
        [{"code": "overlap", "message": "slots overlap", "day": "monday"}]
    )
    with pytest.raises(ops.OperationError) as exc_info:
        await ops._run_write(AsyncMock(side_effect=sched_err))
    assert exc_info.value.code == "overlap" and exc_info.value.day == "monday"

    with pytest.raises(ops.OperationError) as exc_info:
        await ops._run_write(AsyncMock(side_effect=UnknownTargetError("missing")))
    assert exc_info.value.code == "unknown_target"

    with pytest.raises(ops.OperationError) as exc_info:
        await ops._run_write(AsyncMock(side_effect=CloudError("cloud ko")))
    assert exc_info.value.code == "cloud_refused"

    # _defer_verification invokes verify_job and never propagates exceptions
    scheduled: list = []
    with patch(
        "custom_components.danfoss_ally_cloud.operations.async_call_later",
        side_effect=lambda _h, _d, cb: scheduled.append(cb),
    ):
        jobs = JobManager()
        job = jobs.create("restore", {"type": "room", "id": "1"}, ["h1"])
        ops._defer_verification(hass, {DATA_JOBS: jobs}, job)

    assert len(scheduled) == 1
    with patch.object(ops, "verify_job", AsyncMock(side_effect=RuntimeError("boom"))):
        await scheduled[0](None)  # must not raise
    assert Context() is not None
