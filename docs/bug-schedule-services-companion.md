# Bug — schedule & vacation services crash under the Companion coordinator

**Status:** FIXED 2026-11-23 — found on 2.0.3, reproduced deterministically; resolved by routing
the schedule service ops through ``room_manager`` and refusing vacation writes cleanly on a
Companion entry. See **Resolution** below.
**Severity:** high — `set_schedule` / `get_schedule` / `restore_schedule` (and the vacation
services) are unusable whenever the entry runs on the **ponts + Companion** architecture
(`danfoss2mqtt` / `zigbee2mqtt` → Mosquitto → Companion). They raise HTTP 500 and change nothing.

## Symptom

Calling `danfoss_ally_cloud.set_schedule` on a native multi-head room returns:

```
500 Internal Server Error — Server got itself in trouble
```

The weekly schedule is left unchanged (verified by reading it back through the path-1a route).
`get_schedule` (SupportsResponse.ONLY) fails the same way for a caller that does ask for a
response; a caller that omits `return_response` is rejected earlier by core with a 400, so the
500 is masked.

## Environment

- Integration `danfoss_ally_cloud` **2.0.3**, Home Assistant 2026.11.2 (Python 3.14).
- Entry **"Danfoss Ally Companion (zigbee2mqtt, danfoss2mqtt)"**: the store's `DATA_COORDINATOR`
  is a `CompanionCoordinatorView`, not the legacy cloud `DanfossCoordinator`.
- Target: a native room grouping 2 heads (served through `danfoss2mqtt`). Payload
  `{"target": {"type": "room", "id": "<group_id>"}, "days": {"mon": [{"start": "08:30", "end": "22:30"}]}}`.

## Reproduction

1. On a Companion entry, call `danfoss_ally_cloud.set_schedule` with any room target and `days`.
2. → 500. Re-running the exact same call reproduces it every time (not transient).

## Root cause (confirmed from the traceback)

```
File ".../danfoss_ally_cloud/services.py", line 309, in set_schedule
    return await ops.set_schedule(hass, store, call.data["target"], call.data["days"])
File ".../danfoss_ally_cloud/operations.py", line 466, in set_schedule
    await _run_write(store[DATA_COORDINATOR].client.async_set_schedule_days, target, days)
AttributeError: 'CompanionCoordinatorView' object has no attribute 'client'
```

`operations.py` reaches for `coordinator.client.*` — the **legacy cloud API client**:

- `get_schedule` → `coordinator.client.async_get_schedule` (operations.py:371)
- `set_schedule` → `coordinator.client.async_set_schedule_days` (operations.py:466)
- `restore_schedule` → `coordinator.client.async_restore_schedule` (operations.py:489)
- vacation ops → `coordinator.client.async_vacation_*` (operations.py:261/307/320/340)
- `get_rooms` → `coordinator.client.async_list_rooms` / `async_get_homes` (operations.py:181/189)

Under the Companion architecture the store holds a `CompanionCoordinatorView`
(`companion_adapter.py`), built from `companion` + `room_manager`. It exposes `room_manager`,
`data`, `group_of`, `build_rooms`… but **no `.client`** — so every one of these ops throws
`AttributeError` → 500.

The setpoint path was already adapted and works: `DanfossRoomClimate.async_set_temperature`
(climate.py:279-285) does `getattr(self.coordinator, "room_manager", None)` and, when present,
calls `room_manager.async_set_room_setpoint(...)` instead of the cloud client. The schedule and
vacation service ops were **not** given the same branch.

The fan-out method already exists: `CompanionRoomManager.async_set_room_schedule(room_id, days, …)`
(companion_rooms.py:210) writes a `weekly_schedule` to each member head over MQTT. The service ops
just never call it.

## Affected services

`set_schedule`, `get_schedule`, `restore_schedule`, `copy_schedule` (uses `get_schedule` +
`set_schedule`), and `set_vacation` / `set_vacation_at_home` / `cancel_vacation` / `end_vacation` /
`get_holiday` / `get_rooms` / `get_room` — i.e. everything in `operations.py` that dereferences
`coordinator.client`. Only the climate `set_temperature` / `clear_override` paths, which already
branch on `room_manager`, work on a Companion entry.

## Proposed fix

In each `operations.py` op, branch on `getattr(coordinator, "room_manager", None)` (as
`async_set_temperature` does) and use the Companion path when present:

- `set_schedule` → `room_manager.async_set_room_schedule(room_id, days)` for a room target.
- `get_schedule` → read from the room config the manager already holds
  (`CompanionRoomConfig.schedule`) rather than the cloud client.
- `restore_schedule` → the Companion equivalent (re-push the stored schedule to the heads).

Alternatively, give `CompanionCoordinatorView` a `client`-shaped shim implementing
`async_get_schedule` / `async_set_schedule_days` / `async_restore_schedule` on top of
`room_manager`, so `operations.py` stays unchanged. Either way, add a regression test that runs
these services against a Companion store.

Note: `check_schedule_target` / `_head_ids` / `_check_not_grouped` use `coordinator.data` and
`coordinator.group_of`, which the view *does* provide (the 500 lands at the `.client` call, after
those pass), so only the `.client` dereferences need routing.

## Resolution (2026-11-23)

Implemented as the "branch on `room_manager`" option (matching `climate.async_set_temperature`):

- **`operations.set_schedule` / `restore_schedule`** branch on `getattr(coordinator, "room_manager",
  None)`. When present they fan out through
  `CompanionRoomManager.async_set_room_schedule(group_id, days)` instead of `coordinator.client`;
  the cloud path is untouched when it is absent. The shared tail (`note_commanded`,
  deferred `verify_job` → `async_request_refresh`) now also runs on a Companion entry because
  `CompanionCoordinatorView` gained no-op `note_commanded` / `async_request_refresh` methods (both
  are polling-coordinator concepts with no meaning for an MQTT push coordinator).
- **`operations.get_schedule`** reads the schedule the manager last fanned out
  (`CompanionRoomManager.get_room_schedule`), normalised to the cloud day keys so the payload shape
  matches `client.async_get_schedule`. `get_room` / `copy_schedule` ride on these.
- **`CompanionRoomManager`** now records the last fanned-out schedule per room (native *and*
  virtual) and `async_set_room_schedule` accepts both the cloud 3-letter day keys (`mon`…`sun`,
  which the service layer validates and passes) and the full English names used by existing virtual-
  room callers.
- **Vacation ops** (`set_vacation` / `set_vacation_at_home` / `cancel_vacation` / `end_vacation`)
  refuse with a clean contract error `vacation_companion_unsupported` (→ `ServiceValidationError`,
  not a 500): the Companion channel exposes no vacation/holiday write (`bridge/holidays` is
  read-only), so there is no route to port, and guessing one was out of scope.
- **`get_rooms` / `get_holiday`** already worked — they use `ops_views.rooms_payload` /
  `holidays_payload`, which read the view's `rooms` / `holidays` properties, not `.client`.

Known limitations (documented, not bugs): the Companion has no schedule read-back from the heads,
so `get_schedule` returns what the integration last wrote and is empty (and `restore_schedule`
raises `no_schedule_recorded`) until a schedule has been set in the current run; the record is
in-memory for native rooms (virtual rooms persist it on their config). Isolated-head schedule
writes stay room-only on a Companion entry.

Regression test: `tests/test_companion_schedule_services.py` runs set/get/restore against a native
`danfoss2mqtt` Companion room (asserting the weekly-schedule fan-out and no `AttributeError`/500)
and asserts the vacation ops raise the clean contract error.

## Field workaround (2026-11-23)

To extend the "Salle des professeurs" room to 22:30 that evening, the schedule was written through
the pilot's `danfoss-ally` MCP connector (path-1a, `danfoss_tuya_programme_preparer`), which writes
the same per-room weekly program directly over the Tuya custom API — independent of this
integration's service. Reading the program back (same path) confirmed it applied. The Companion
picks up the change on its next poll.
