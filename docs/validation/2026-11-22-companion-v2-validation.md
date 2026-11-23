# Companion V2 (Bridge + Companion) — real-hardware validation

**Date:** 2026-11-22. Build: releases `2.0.0-alpha.x` (the Bridge + Companion architecture, see
[`../companion-contract.md`](../companion-contract.md)). Real-hardware session on a large install
(about 100 Danfoss devices across two homes), owner present, one explicit go-ahead per write.
Anonymised: room names, identifiers and site details replaced by neutral labels.

The **Companion** is the single Home Assistant entry "Danfoss Ally Companion
(zigbee2mqtt, danfoss2mqtt)". It speaks only to the local Mosquitto broker. Two bridges feed it,
both in the Zigbee2MQTT device dialect:

- **zigbee2mqtt** — heads on the local Zigbee coordinator (no gateway, no cloud);
- **danfoss2mqtt** — the standalone add-on backed by `pydanfoss-cloud`, for heads on the Danfoss
  gateways (cloud path 1a).

## Labels used in this report

| Label | Role |
|---|---|
| Area X | Virtual Companion room over **four Zigbee2MQTT heads** and one Zigbee2MQTT room sensor (same area as `2026-11-real-hardware-validation.md`) |
| Room G | A **grouped** head on a Danfoss gateway, in a multi-head room — reached over the **danfoss2mqtt cloud** path |
| Head I | An **isolated** head on a gateway (no room) |

Entity ids are written with placeholders, e.g. `climate.<area_x>`.

---

## §0 — Read chain, both bridges ✅

- **danfoss2mqtt** publishes `danfoss2mqtt/bridge/state = online` and `danfoss2mqtt/bridge/devices`
  (about 100 devices: heads `014G2461`, room sensors `014G2480`, relays `014G2400`), plus a full
  per-device state in the Z2M dialect. The Companion derives fresh entities from it.
- **zigbee2mqtt** publishes its heads and the room sensor the same way.

Both read chains are healthy; the Companion shows fresh state from each bridge.

## §1 — Write, zigbee2mqtt local fan-out (Area X) ✅

Lever: `climate.set_temperature` on the **virtual room** climate `climate.<area_x>` (Companion
room fan-out, stage 2.4). Setpoint **14 → 15 → 14 °C**.

- Verified on an **independent Zigbee2MQTT head** of the room (read straight from its
  `zigbee2mqtt/<head>` state, not through the Companion), setpoint followed the fan-out.
- Restored to the baseline (14 °C).

**Verdict ✅** — room setpoint fan-out works over the local channel.

## §2 — Write, danfoss2mqtt cloud path (Room G) ✅

Lever: `climate.set_temperature` on a **grouped** gateway head `climate.<room_g>`. Comfort setpoint
**21 → 15 → 21 °C**.

- Verified on the bridge's echo (the danfoss2mqtt daemon reports the head's new state). Cloud
  path 1a round-trips.
- Restored to the baseline (21 °C).

**Verdict ✅** — a room-level setpoint round-trips over the cloud channel.

### Mode-aware setpoint — a UX nuance to carry (not blocking)

On a gateway head that **follows a schedule**, `climate.set_temperature` writes the room's **comfort**
setpoint, not the currently effective one, while the card shows the `active_setpoint` (the setback
value when the schedule is in its reduced slot). So one can believe they are writing the displayed
target while actually writing comfort. **Read the head's `setpoints` before and after a write** to
restore the right value. (This is the same active-vs-comfort distinction recorded as R-1 in
`2026-11-real-hardware-validation.md`; the daemon fix — `occupied_heating_setpoint` = the **active**
setpoint — landed the same evening in `pydanfoss-cloud` PR #1.)

## §3 — Cloud-path write safety ✅

The standalone danfoss2mqtt daemon routes `/set` only through proven cloud paths and declines the
rest **loudly**, with no optimistic state:

- **Isolated head refused.** A setpoint on **Head I** (isolated, no room) is **refused** —
  *"not grouped: path-1a setpoint not proven outside a room"*. Nothing is published to the head; the
  entity does not show a changed value. (Consistent with the project rule: path-1a setpoint is
  proven only at the room level; an isolated gateway head is **read-only** through the Companion.)
- **Non-routable field ignored and logged.** A field the bridge cannot route (`keypad_lockout`) is
  **ignored and logged**, not silently accepted (behaviour of
  [`ha-danfoss-ally` #141](https://github.com/aghulas/ha-danfoss-ally/pull/141)).

No residue was left on any head, including after a Home Assistant restart triggered by another
session mid-session.

**Verdict ✅** — the cloud bridge refuses what it cannot prove and declines fields it cannot route,
exactly as the contract requires ("unavailable rather than lying").

## Scope and limits

- **Isolated gateway head = read-only** through the Companion: the standalone danfoss2mqtt bridge
  is cloud-only and routes only `occupied_heating_setpoint` of a **grouped** head to the head.
  Child lock, window detection, preheat, room sensor and schedule are declined (the local tunnel
  and Tuya cloud MQTT are not wired into the standalone bridge). By design.
- **`bridge/rooms` / `bridge/holidays`** were absent (no retained topic) during the session — the
  daemon did not pass them to `publish_fleet`. Fixed the same evening (`pydanfoss-cloud` PR #1);
  end-to-end consumption still to re-check on real hardware for the 2.0.0 stable cutover.
- **Entity coexistence:** per head, the V2 Companion entities coexist with a v1.x cloud entry and
  MTrab's `danfoss_ally` (suffixes `_2`/`_3`). A cutover plan (disable the v1.x entry and the
  duplicates) is required before 2.0.0 stable — shipped as the Repairs warning
  `sync_provider_conflict` and [`../v2-cutover.md`](../v2-cutover.md)
  ([`ha-danfoss-ally` #142](https://github.com/aghulas/ha-danfoss-ally/pull/142)).
- **Infra:** the SSH path to the host was unstable during the session (prepare-step timeouts,
  Supervisor 502) while MQTT stayed reachable — to watch for writes, not a code issue.

## Summary

| Leg | Channel | Result |
|---|---|---|
| Read | zigbee2mqtt | ✅ fresh state |
| Read | danfoss2mqtt (cloud 1a) | ✅ fresh state, ~100 devices |
| Write setpoint (room fan-out) | zigbee2mqtt | ✅ 14→15→14, verified on an independent head, restored |
| Write setpoint (grouped head) | danfoss2mqtt (cloud 1a) | ✅ 21→15→21, verified on the bridge echo, restored |
| Setpoint on isolated head | danfoss2mqtt | ✅ refused (not grouped) |
| Non-routable field | danfoss2mqtt | ✅ ignored and logged (#141) |
| Residue | — | ✅ none, even after a foreign HA restart |

Both read paths and both write paths are proven; the cloud path's safety (isolated-head refusal,
field decline, no optimistic state) holds. All baselines were restored.
