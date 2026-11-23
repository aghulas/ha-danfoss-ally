# Roadmap

What is shipped, and what comes next. Release-by-release history is in `CHANGELOG.md`; this page
only keeps what still decides future work.

## Where the project stands (2026-11)

- **2.0.x — Bridge + Companion, stable since 2.0.0 (2026-11-22).** Home Assistant reads Zigbee2MQTT
  (heads on a Zigbee coordinator) and `danfoss2mqtt` (heads on Danfoss gateways, cloud path)
  through the local Mosquitto broker; the integration talks to the broker only
  (`docs/companion-contract.md`). Current: 2.0.3.
- **1.4.x — frozen.** The direct-cloud line (cloud HTTP + Tuya cloud MQTT + local tunnel inside the
  integration) gets no new feature. Its routing rules live on in `danfoss2mqtt`
  (`docs/architecture.md`).
- **`pydanfoss-cloud`** — the `api/` layer as a library, released from its own repository
  (`docs/publishing-pydanfoss-cloud.md`).
- **Not done yet: public HACS inclusion.** Installable as a custom repository.

Cross-cutting goal, unchanged: exercise the code on other installs (firmwares, product ids,
gateway models) to make the DP assumptions more reliable.

## Next

Ordered by what blocks what, not by date. No version number is attached until the work is scoped.

### 1. Finish the 2.x switch-over

- **Companion cutover on the live install** — disable the 1.x direct-cloud entry, stop the third
  provider's MQTT discovery, reclaim the entity ids. A manual, on-site step: `docs/v2-cutover.md`.
- **Real-hardware validation of Companion writes** with the owner present, per bridge
  (Zigbee2MQTT heads over the local broker, `danfoss2mqtt` heads over the gateway bridge):
  `docs/validation/real-validation-plan.md`.
- **Isolated heads over `danfoss2mqtt`** are read-only by design today. Decide whether the proven
  cloud-MQTT writes of the 1.x line (child lock, window detection, bounds, setpoints) are exposed
  through the bridge.
- **Test harness debts**: `via_device_id` (before Home Assistant 2027.8) and the `native_*`
  climate attributes.

### 2. Preheat that lasts

A preheat write through the tunnel alone is undone overnight by the value the cloud holds
(`docs/preheat.md`). In order:

1. show the divergence between the head and the cloud on the switch (read-only, can ship alone);
2. run trial A1 to its morning read (the pair "DP 1 publish + settings block" against a
   tunnel-only control, overnight), then A2 to A5;
3. only then make the switch's write a pair, and decide what an install without cloud MQTT gets.

DP 1 over cloud MQTT stays a closed candidate until then.

### 3. Cloud MQTT as a read source

Staged, each stage gated (`docs/cloud-mqtt-channel.md`):

| Stage | State |
|---|---|
| 1. Write path, child lock first | Shipped, validated 2026-11-19 |
| 2. More DPs, one supervised write each | Proven: 30, 116, 18, 27, 120, 118 + 16, 119. Candidates: 133 (trial passed, to promote), 101 (to run), 1 (see "Preheat that lasts") |
| 3. Measure inbound coverage | Tooling shipped (`cloud_mqtt_probe`); **the 24 h run on a real install is still to do** (§13) |
| 4. Push as a read source | Only if stage 3 shows full coverage. First concrete step: decode DP 199 inbound, reusing the tunnel decoder (§14) |
| 5. Hardening | Code and docs done (§12, "Link lifecycle"); the behaviour of an established connection across a real session renewal is still to observe |

Open captures that gate later moves (§10 and §14.5): the account topic (online / offline?), the
echo of a setting on an **isolated** head, DP 171 as a cloud-MQTT override.

### 4. Supervised trials still open

One setting at a time, owner on site (`docs/first-write-procedure.md`):

- **Promote DP 133** (orientation): trial passed both ways on 2026-11-20.
- **DP 101** (viewing direction): to run, the head's display being the proof.
- **Tunnel settings**: radiator covered, regulation speed and valve exercise were written and read
  back; decide their promotion. **Setpoint offset**: scale still unproven, to redo on a weekday in
  a comfort slot. External room sensor, external window, load balancing, adaptation run: not tried.
- **Hold over time** of tunnel-only settings: one setting held one night; nothing established for
  the others.
- **Schedule writes on an isolated head** (trials S0 to S3) and the app capture that would give
  `restore_schedule` a real route: `docs/isolated-head-schedule-writes.md`. Guards 3 to 5 of that
  note (verified product, override read-before-write, job verification through the tunnel) are
  not implemented.

### 5. Zigbee2MQTT heads: parity with the cloud's room functions

A head paired to Zigbee2MQTT loses what the gateway and the cloud did above it: the room, the
room sensor feed, load balancing, holidays, the re-imposition of settings. Inventory, state of the
Companion's first version and the proposal — a standalone room coordinator on MQTT, sibling of
`danfoss2mqtt`, in stages each gated by a supervised trial: `docs/z2m-cloud-parity.md`. Direction
approved on 2026-11-23; stage 0 (identify the existing sensor feed, gate the Companion's two
periodic feeds, fix the sensor keep-alive) comes first.

### 6. Publication

- Tagged releases are in place. Remaining: the **HACS inclusion pull request** (only the owner can
  submit it), once the cutover and the Companion write validation above are done.
- Keep the "unofficial" framing and the conservative polling defaults.

## Standing decisions

These are settled; they are listed so they are not reopened by accident.

### Device lifecycle: unbind shipped (gated), pairing out of scope

- **Unbind ("disconnect") — shipped, gated.** Any sub-device (head, sensor, relay) can be unbound
  with the `disconnect_head` service (`smartlife.m.device.reset` v3.0 `{devId, resetFactory}`). A
  gateway is refused. Triple gate: admin with no user-less call, the `enable_head_unbind` option
  (off by default), an explicit `confirm`. `resetFactory=false` keeps the device's identity;
  `true` is a factory reset (new devId, irreversible). **A real disconnect through Home Assistant
  is still to validate** (`docs/validation/real-validation-plan.md`, §2b); the option stays off
  until then.
- **Pairing — out of scope.** Opening the gateway's permit-join travels over Tuya cloud MQTT, not
  an HTTP call, and completing a pairing needs a physical action on the head. It would need the
  gateway MQTT channel and is a separate track.

### Post-command freshness (R-3): per-device refresh after a write (gated)

The bulk device list lags for minutes after a command. With `enable_post_command_refresh` (off by
default, it adds reads on the user's account) a commanded head is read through the per-device
route for 5 minutes and its fresh DPs are overlaid on the bulk state, after a 15 s settle delay
(the cloud takes a command into account in about 15 s; an earlier read returns the pre-command
state). Never optimistic: what is shown is what the cloud returns.

Still to observe on real hardware: the overlay's own effect. The per-device route is fresh (its
DPs are under `dataPointInfo.dps`, stamped at the second of the write), but the first validation
of this mechanism was in fact the settle-delay refresh of the bulk list, the overlay having been
inactive at the time.

### Not planned

- Any write of the mode DP (DP 2): `manual` erases the schedule (R4), the other values are labels
  (R5). Contract: `docs/interface-contract.md`.
- "Everything over cloud MQTT": rejected (no discovery, no read on demand, no preheat lever;
  `docs/cloud-mqtt-channel.md` §14).
- The official Danfoss OAuth2 path in the library or the integration (`docs/reuse.md`).
