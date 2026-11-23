# Real-hardware validation — preheat DP 1 over cloud MQTT, publish + settings-block pair

> **Provenance.** Salvaged from a local WIP commit (`0836c91`, "record the publish + settings
> block result", 2026-11-20) that never landed on `main`; the source branch
> `claude/preheat-pair-result` was recovered into this standalone note and then dropped.
> The run used build **1.2.1-rc1**, a release line that was **abandoned**. DP 1 preheat over
> cloud MQTT therefore remains a **closed candidate** (`api.writes.MQTT_CANDIDATE_DPS`); the
> proven preheat route stays the local Zigbee tunnel (`0x0025`). This note records a single
> positive field observation so it is not lost — it is **not** a promotion of the route.

Context: see `docs/cloud-mqtt-preheat-proposal.md` for the closed candidate, its stages A/B, and
the assessment; and `docs/preheat-tunnel-durability.md` for the overnight-hold question.

## Supervised write of the pair: publish + settings block (2026-11-20, 1.2.1-rc1)

Same isolated head as stages A and B, build 1.2.1-rc1, trial armed on that head only. Run by the
session in charge of the durability check (`docs/preheat-tunnel-durability.md`); figures as it
reported them.

| Instant | `0x0025` raw (tunnel) | weekly schedule, current setpoint | cloud DP 1 | switch in Home Assistant |
|---|---|---|---|---|
| before, 10:22 | 1 | flat 5 °C, 5 °C | false | off |
| `switch.turn_on` at 10:29:26, returned OK after 50.1 s | | | | |
| after, about 10:31 | **3** | unchanged | true | on |

- **Passed, once.** The call returned without "not confirmed": the tunnel read showed bit 1 set
  inside the call. Bit 0 kept; schedule and current setpoint unchanged; no tunnel write from
  anyone. Where the bare publish of stage B left the head untouched for 15 minutes, the publish
  followed by the settings block made the head take the value in under a minute.
- So the settings block (`settings.change`) is what was missing. Whether the block **alone**,
  without the MQTT publish, would do the same was not tried.
- Not read in this run: cloud DP 172, the gateway's frames (no listen ran), the exact delay
  (bounded by the 50 s call: one read before, the two sends, then a read every 10 s).
- Limits: one head, one gateway, one firmware, one direction (OFF to ON), a flat schedule. The
  restore (ON to OFF through the same write) and the overnight hold are still to be read.
- DP 1 stays a closed candidate until those are in; promotion is a change of its own, and it
  must also settle what `docs/preheat-tunnel-durability.md` raises: a preheat write through the
  tunnel alone was seen undone overnight, which the cloud-side block may be the remedy for.

## Status

- **Closed candidate**, not promoted. The 1.2.1 line that carried this trial was abandoned.
- Still to read before any promotion: the restore (ON → OFF) through the same write, and whether
  the value holds overnight; whether `settings.change` alone (no MQTT publish) suffices.
- The local tunnel remains the only proven preheat route.
