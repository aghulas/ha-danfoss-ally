# What fed `external_measured_room_sensor` before the Companion (investigation)

**Date of the observation:** 2026-11-21. **Investigation:** 2026-11-23, read-only (broker
observation, code and deployment-log reading; no write to the heads, the host or any account).
Anonymised: site and project names replaced by neutral labels.

## The question

On 2026-11-21 the four Zigbee2MQTT heads of the trial area ("Area X" in
[`2026-11-real-hardware-validation.md`](2026-11-real-hardware-validation.md)) were regulating on an
**external room sensor**: `external_measured_room_sensor = 1403` (= 14.03 °C) on each head, read
from their Zigbee2MQTT state. This was **before** the Companion's own sensor feed existed.
`docs/z2m-cloud-parity.md` §4 point 2 flagged the risk: if the Companion's
`companion_feed_external_sensor` feed is later turned on for that area, **two producers** would
write the same head attribute. The producer had to be identified first.

## The producer

**A Home Assistant automation belonging to a separate on-site pilot project** — the same project
whose local Danfoss-gateway bridge publishes the `danfoss_l/…` topics noted as a "false friend" in
the main report (not our integration). The automation:

- triggers on a time pattern (every ~30 min) and on the room sensor's state;
- reads the room's wall sensor (a Danfoss `014G2480` room sensor on the local coordinator),
  multiplies by 100, and publishes `{"external_measured_room_sensor": <t×100>}` to
  `<z2m-prefix>/<head>/set` for each of the four area heads;
- guards: nothing sent if the sensor is stale (threshold raised 20 → 35 min on 2026-11-21, to match
  the measured radio-link gaps) or outside 5–35 °C; 5 s between heads; `−8000` to clear.

`1403` is therefore the room sensor at **14.03 °C**, pushed by that automation. A sibling automation
in the same project pushed `load_room_mean` the same way (the load-balancing feed). This is exactly
the pair of functions the gateway used to provide above a head, and that the Companion now
reproduces with its two options (`companion_feed_external_sensor`, `companion_feed_load_mean`).

## Coexistence / how it was stopped

**The two-producer risk is already resolved.** On **2026-11-23** both pilot automations (the
sensor feed and the load-mean feed) were **removed** by the owner — deleted from Home Assistant via
the config API and their definitions removed from the pilot project's repository — precisely because
the Companion integration now pushes the room sensor and balances the room. So there is no longer a
second producer for these attributes.

Confirmed read-only on the broker on 2026-11-23: no `/set/external_measured_room_sensor` **command**
traffic was observed on the production prefix (`zigbee2mqtt/`, the Area X heads); the only
busy foreign topic tree is `danfoss_l/…`, which is the pilot's local **gateway** bridge, not the
sensor feed. (`external_measured_room_sensor` and `load_room_mean` still appear inside each head's
own **state** JSON and in the Zigbee2MQTT discovery configs — those are reports and command-topic
declarations, not a producer writing to `/set`.)

**If a feed ever needs to be stopped again** (either producer): disable or delete the automation in
its project, or turn off the Companion option. A head on `radiator_covered: off` keeps the last
value for ~3 h, then falls back to its own internal sensor; to clear at once, publish a single
`external_measured_room_sensor = −8000`.

## Rule going forward

Before turning on `companion_feed_external_sensor` (or `companion_feed_load_mean`) for an area,
check that no other producer writes the same attribute to those heads — the two pilot automations
are the known ones, and they are gone. One producer per head attribute (stage 3 / stage 6 of
[`../z2m-cloud-parity.md`](../z2m-cloud-parity.md) §7, each behind its supervised trial).
