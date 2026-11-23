# Requirements — per-room schedules and embedded frontend

Goal: let the user view and edit a room's weekly schedule from Home Assistant, without opening the
mobile app, with a dashboard card shipped by the integration. Reference for shapes and rules:
`docs/interface-contract.md` (R1 to R7). In case of contradiction, **the contract is authoritative**;
if it turns out wrong or incomplete, fix it first, in a separate commit.

Overall objective (reminder): parity with the app, everything in the public HACS release, write
reserved for administrators, schedule written per room via the cloud, local tunnel to verify.

## Progress (as of 2026-11-17)

The backend was delivered directly on `main`, outside the original batch numbering, by PR #10
(durable room setpoint), #12 (one `climate` per room) and #17 (schedule editing: `api/schedule.py`,
`operations.py`, `services.py` + `services.yaml`, `websocket_api.py`, `writejob.py`). The room
model, R1 validation, the actions (§5.2) and the WebSocket commands (§5.3) of the contract are
therefore **in place and compliant with the contract**.

- **Batches 0, 1, 2 — done** (merged into `main`). The sections below serve as the reference
  specification and historical record.
- **Batches 3, 4, 5 — done**: embedded frontend base, then the Schedule card, read and write
  (in releases since 0.2.0; the room card and the side panel followed in 0.6.0, contract §8).

Nothing of this document remains to be built. It is kept as the specification the contract and
the frontend were written against.

## Scope

In these requirements:
- batches 0 to 5 below: document upgrade, `api/` layer, Home Assistant wiring, frontend base,
  read-only then editable Schedule card.

Out of scope (do not start): holiday, comfort / setback override, room management, relays, full side
panel, MQTT publishing of schedules.

## Batch 0 — Document and thermostat upgrade

The trials of 2026-11-16 correct two statements in the repo.

1. `CLAUDE.md` and `docs/architecture.md` say that "`at_home` / `leaving_home` cloud → head in
   manual". The real mechanism is R4 and R5: it is the **switch to manual** that erases the
   schedule, and `at_home` / `leaving_home` are only labels. Correct both documents by pointing to
   the contract.
2. `docs/roadmap.md`: add the milestones of these requirements.
3. **Thermostat**: a change in progress (perhaps already merged) writes the active mode's setpoint
   (`at_home_setting`…) when the user changes the temperature. Per R3, without rewriting the
   schedule afterwards, the head will take the old value at the next transition. Check the state of
   this change in `main` and align it: either the mode setpoint is written only by the room's
   `number` entities (section 5.1 of the contract) with a schedule rewrite, or the thermostat does
   the same. Do not leave a mode-setpoint write without R3.

Deliverable: a documentation commit, and if needed a thermostat fix commit with its tests.

## Batch 1 — `api/` layer: rooms, schedule, real state

In `custom_components/danfoss_ally_cloud/api/` (this is also the `pydanfoss_cloud` library: no Home
Assistant dependency in this folder).

1. `schedule.py` (new), pure functions:
   - `Schedule` model / slots; conversion from the `week.timer.list` response (minutes → `HH:MM`,
     `loops` mask Sunday first) and to the `week.timer.create` body;
   - `count_transitions(day)` and `validate_days(days)` per R1, returning the contract errors (5.4).
2. `client.py`:
   - `async_list_rooms()`: rooms of all homes, with their heads (4.1 and section 1 of the contract);
   - `async_get_schedule(target)`; `async_set_schedule_days(target, days)` (validate, then `delete` +
     `create` per day); `async_restore_schedule(target)` (R4);
   - `async_publish_room_dps(group_id, dps)` with an **allowlist** of permitted DPs (118, 109 + 119,
     2 limited to `manual` and `at_home`, 1, 30, 116, 18); any other key is refused.
3. `decode.py`: `schedule_active`, `preheat` (DP 172), `mounting` (DP 149), `inconsistent`, on the
   existing device model.

Reference code to port (do not reinvent): `~/dev/danfoss-ally-mcp/danfoss_ally_mcp/tuya/pilote_tuya.py`
— `decoder_programme`, `_valider_fenetres`, `compter_transitions`, `programme_confirmer`, `pieces`,
`membres_par_piece`, `modes_tetes`, `_mode_piece_executer`. Its tests (`tests/test_tuya.py`) give the
edge cases. Intended difference: here no prepare → confirm token; safety comes from validation.

Tests (synthetic data only): each R1 rule has its cases — 3 separate slots (valid, 6), 4 slots
(refused), slot at `00:00`, touching slots, overlap, end at `23:59`; decoding of a real anonymised
response; `restore`: seven `delete`, the needed `create`s, then `{"2": "at_home"}` **last**; DP
allowlist.

## Batch 2 — Home Assistant wiring

1. **Coordinator**: rooms and head states on each refresh (no extra call, 4.3). Schedules are
   **not** re-read on every cycle: per-target cache, filled on demand and refreshed at most once per
   hour and after each write. The account is the user's: stay frugal.
2. **Devices**: one device per room; the entities of section 5.1 of the contract; `en` and `fr`
   translations.
3. **Actions** (5.2) in `services.yaml` + `strings.json`, with a response (`SupportsResponse`),
   admin control, and the contract errors as translated `ServiceValidationError`.
4. **WebSocket** (5.3) in `websocket_api.py`; same functions as the actions.
5. **Write jobs** (`WriteJob`): in-memory queue, events for `jobs/subscribe`; verification by DP 172
   for the mode, by the local tunnel for the schedule when `enable_local` is on (reading the
   schedule from the head: see `api/local/`), otherwise `unverified`. The local verification is
   deferred by 5 minutes and never blocks the call.
6. **Diagnostics**: rooms and states without real identifiers (extend the existing redaction).

Tests: existing `pytest-homeassistant-custom-component` harness; refusal of a non-administrator;
invalid `set_schedule` → no request sent; schedule rewrite after a setpoint change (R3); keep
coverage and mypy at the current level.

## Batch 3 — Frontend base

1. `frontend/` folder: TypeScript + Lit, built by Vite or Rollup to
   `custom_components/danfoss_ally_cloud/frontend/danfoss-ally-cloud.js` (a single file, with no
   dependency loaded on the fly). Unit tests (Vitest) for the pure logic.
2. **The compiled file is versioned** in the repo, so the HACS install works from any branch or
   tag. CI rebuilds and fails if the versioned file is not up to date.
3. Python-side registration (`frontend.py`): static path, Lovelace resource, cleanup when the last
   entry is removed; `http` and `frontend` dependencies in the manifest (and `lovelace` if resource
   registration requires it — to check on the targeted Home Assistant version; manifest keys in the
   order required by hassfest).
4. Version check (section 6 of the contract) with a reload prompt.
5. A minimal `danfoss-ally-schedule-card` that shows the chosen room's name and the version, with
   its config editor (room choice among `danfoss_ally_cloud/rooms`).
6. Demo page outside Home Assistant (`frontend/demo/`) with a fake `hass` object and test data, to
   develop the card without an instance.
7. README: installation, YAML mode, screenshot.

Criterion: the card appears in the card picker of a real Home Assistant after installation via HACS
(custom repository), with no manual step in storage mode.

## Batch 4 — Schedule card, read

- Seven-day grid, comfort slots positioned over 24 h, comfort and setback setpoints, room name.
- State of the room's heads: online, schedule active, inconsistent, mounting (icons + tooltip).
- "Refresh" button (`refresh: true`), last-read date.
- Light / dark theme via Home Assistant variables; keyboard-usable; `en` / `fr` texts translated by
  the frontend localization mechanism (no hard-coded text).
- Width: one dashboard column on mobile, no horizontal scroll.

## Batch 5 — Schedule card, write

- Day editing: add, move, resize, delete a slot (5-minute step; direct time entry possible,
  essential on keyboard and mobile).
- Immediate validation via `schedule/validate` and, locally, by the same R1 rule ported to
  TypeScript with its tests; the day's transition counter is shown ("4 / 6"); saving is impossible
  while a day is invalid.
- Copy a day to other days.
- Saving sends only the changed days; job tracking via `jobs/subscribe`: "sent", then per head
  "applied", "mismatch", "unreachable" or "unverified".
- "Back to schedule" button visible when a room's head no longer has its schedule active.
- Read-only for a non-administrator user.
- Discard unsaved changes; warn before leaving an edit in progress.

## Real-hardware validation

Automated tests are not enough: each writing batch is validated on a real install.
- A **test room** designated by the install's owner, with no comfort stakes.
- Before any real write: show what will be sent and wait for approval.
- After: re-read from the head (local tunnel) and note the delay; put the room back to its original
  state.
- Record the results in the pull request description (date, anonymised room, observation).

## Repo rules to respect

Those of `CLAUDE.md`: no secret or real identifier in the code, the tests, the logs or the
diagnostics; `ruff`, `mypy`, `pytest` green; one branch per batch; commit and push only on request;
messages in English. The repo is meant to become public: no data specific to an install.

## Order and dependencies

Batch 0 → batch 1 → batch 2, and batch 3 in parallel with batches 1 and 2 → batch 4 → batch 5.
Batches 1 and 3 touch no common file. One batch = one branch = one pull request, with its validation.
