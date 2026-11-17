# Architecture

## Principle: cloud-first, local fallback

The cloud API covers most of the control. But we have established on real hardware cases where the
cloud **lies or does not act**, which must be handled locally:

- It is the **switch to manual mode** (DP 2 `manual`) that erases the head's schedule (R4).
  `at_home` / `leaving_home` published via DP 2 are only **labels** on the cloud side: the head
  keeps the setpoint from its schedule (R5). The comfort/setback switch and the return to schedule
  therefore go through rewriting the room's schedule, not a simple cloud write of the mode. Rules
  R1–R7 and calls: `docs/interface-contract.md`.
- Preheat: writing DP 1 on the cloud side only changes the gateway cache. The real lever is the
  Zigbee attribute **0x0025** (bit 0 schedule, bit 1 preheat), reachable only through the local
  tunnel.
- `update_time` is an event-driven registration timestamp: never infer freshness from it. `online`
  is authoritative for connectivity.

So: **cloud by default, local tunnel (optional) for the operations the cloud misses**. The same
integration fetches the gateway keys, so the local fallback stays internal, asking nothing more of
the user.

## Layers

- `api/client.py` — cloud API (path 1a): session, devices, DPs, rooms, schedules.
- `api/keys.py` — fetching the gateways' localKey (replaces emulator/Frida; verified on real
  hardware).
- `api/local/tunnel.py` — Zigbee tunnel DP 198→199 (tinytuya): real schedule, attribute 0x0025, real
  attributes.
- `coordinator.py` — conservative cloud polling + overlay of the local truths.
- Platforms: `climate` (setpoint, presets), `sensor` (battery, valve, heat request, fault code),
  `binary_sensor` (online, window), `number` (holiday, bounds), `switch` (child lock, window,
  preheat).
- `mqtt_publisher.py` — MQTT publishing, modes `discovery` / `zigbee2mqtt`, source `cloud` /
  `local`.
- `diagnostics.py` — strict secret redaction.

## Tuya session shared with the MCP connector (common deviceId)

The `danfoss_ally_cloud` integration and the MCP connector `danfoss-ally-mcp` use the **same
installation material captured from the app**: `deviceId`, `sign_key` and `chKey` (see README,
"Installation secrets"). On the Tuya server side, this triplet identifies **a single installation**,
hence **a single active session**. If both clients run in parallel against the real account, one's
connection **invalidates the other's session**: they log each other out, each triggering a
re-authentication in the other, hence a loop of reconnections and intermittent errors
(`session_expired`, refused calls) on both sides.

> The `tuya-mcp` connector (building F radiators) is **not** affected: it goes through the Smart
> Life sharing SDK with its own `terminal_id`.

### Operational rule (as long as a single set of secrets exists)

**Never run both at the same time against the real account.** One session holder at a time:

- as long as the MCP connector is serving (active Claude session on `danfoss-ally-mcp`), the
  integration stays **disabled** on the Home Assistant side;
- conversely, to use the integration continuously, stop using the MCP connector on this account.

Disabling the integration on the HA side unloads it **and** prevents it from reloading at startup,
which frees the session; a simple "reload" is not enough. Current state on the school's Pi: the
integration is `disabled_by: user` (disabled), so the MCP connector keeps control. This is a
**workaround**, not the target.

### Underlying track: a separate virtual installation for the integration

True coexistence requires giving the integration **its own set of secrets** (distinct `deviceId` /
`sign_key` / `chKey`), i.e. a **second virtual "installation"** of the app as far as the Tuya server
is concerned. Two installations = two independent sessions, which no longer log each other out.

Procedure, conceptually (manual step **to come**, not done here):

1. produce a new installation triplet using the signature repo `~/dev/danfoss-ally-signing-re` and
   the real app (capture / hook) — the operation needs **Rémi** and the app, it cannot be automated
   from this repo;
2. register this installation on the account as an additional mobile device (the server rejects an
   unknown `chKey`: the triplet must be a real installation ↔ account pair, not a fabricated value);
3. configure the integration with this distinct triplet, and reserve the original triplet for the
   MCP connector;
4. verify on real hardware that the two sessions coexist without logging each other out.

Until this capture is done, the operational rule above is the only guarantee against mutual
log-outs.

## Security

Session tokens and localKey are secrets: never in the logs, the diagnostics or the repository.
Conservative polling defaults (security of the user's real account). Robust re-authentication (Tuya
invalidates the session when the app reconnects).

## DP codes

Source of truth: `~/dev/danfoss-app-capture/dp_schema_officiel.md`. Pitfalls captured in `const.py`
(DP 18 = upper bound, 171 = setpoint, 114 = manual, 1 = preheat, 30 = child lock, 116 = window,
162 = heat request).
