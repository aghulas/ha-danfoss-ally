# Cloud-MQTT push coverage — how to measure and read it (roadmap stage 3)

Open question of `docs/architecture.md`: the Tuya cloud MQTT broker pushes DP reports, but for
**which heads**, **which DPs**, and **how often**? The answer decides stage 4 (the push as a read
source). This measure answers it without sending anything.

## What the option does

`cloud_mqtt_probe` (options, **off by default**):

- opens the cloud-MQTT link from the integration's own session and subscribes to the gateways'
  inbound topics. With `enable_cloud_mqtt` off, the link is **listen-only**: it has no send path
  (`can_publish` is false, `plan_dp` and `publish_dp` refuse), and no switch routes through it. With
  `enable_cloud_mqtt` on, both share the one connection the session allows;
- accounts every decoded frame per head and per DP: number of reports, first and last instant,
  median and longest interval (the median over the last 256 intervals of each series). It keeps
  **no DP value and no payload**;
- serves the result in the entry's **diagnostics**, under `cloud_mqtt_coverage`. A head is named by
  `device_index` (its position in the diagnostics `devices` list) and its display name; no device,
  node or gateway identifier appears. Nothing is logged;
- a listen-only link **closes itself after 48 h**, so a forgotten option does not keep a broker
  connection open on the account. The aggregates stay readable until the entry is reloaded.

The aggregates live in memory: **reloading the entry or restarting Home Assistant starts the measure
again** (changing any option reloads the entry).

## Running the measure

1. Pick an ordinary day of the heating season (schedules running).
2. Turn `cloud_mqtt_probe` on. The entry reloads; the "Cloud MQTT link" diagnostic sensor turns on.
3. Leave it for **24 h** without touching the options and without restarting Home Assistant.
4. Download the diagnostics (Settings → Devices & services → the entry → ⋮ → Download diagnostics).
5. Turn the option off.

## Reading the result

First the sibling block `cloud_mqtt_link`: `state`, `connects` / `disconnects` (a high count means
the link kept dropping: the gaps below are then the link's, not the heads'), `received` / `decoded`
(a gap between the two means frames this codec cannot read).

Then `cloud_mqtt_coverage`:

| Field | Meaning |
|---|---|
| `started`, `stopped`, `duration_s` | The window measured. Check it is the 24 h you expect |
| `frames`, `frames_by_protocol` | Everything decoded. Protocol `4` is a DP report |
| `frames_without_head_report` | Frames about a gateway itself, or carrying no DP |
| `heads_known`, `heads_seen` | Heads of the last cloud poll, and how many of them reported at least once |
| `heads_never_seen` | The heads that never reported, with `online` and `grouped`. An offline head is expected here; an **online** one is a coverage hole |
| `unknown_senders` | Senders matching no known head (sensor, relay, head added since): a count only |
| `dps` | Per DP: on how many heads it was seen, and the total of reports |
| `read_dps_never_pushed` | DPs the cloud read decodes that no head ever pushed |
| `heads[]` | Per head: `reports`, `first`, `last`, `median_interval_s`, `longest_interval_s`, `read_dps_missing`, and the same series per DP under `dps` |

Three questions to answer from it:

1. **Coverage.** Is every head that was online for the whole window in `heads[]`? Are the heads of
   `heads_never_seen` all offline? Does it hold for both grouped and isolated heads, and for every
   gateway?
2. **Content.** Do the reports carry the DPs the entities are built from: measured temperature (24),
   active setpoint (171), heating action (3), valve (170), mode (2), window (25), battery (34), and
   the settings (30, 116, 18, 27, 118, 119)? `read_dps_missing` lists, per head, what never came.
   A DP that changes rarely (battery, a setting) can be legitimately absent over 24 h: judge it on
   the DPs that did change that day.
3. **Cadence.** Per head, `longest_interval_s` is the longest silence. Compare it with the polling
   period (90 s by default) and with what the fleet did that day: a head that is idle reports
   little. The interesting series is temperature (24), which moves all day.

## What the measure must show to start stage 4

Stage 4 would feed the coordinator from the pushed reports, drop the post-command per-device read
and lengthen the polling period. It is worth starting only if, over a full day:

- **every head online for the whole window was seen**, grouped and isolated, on every gateway;
- **the fast-changing DPs are pushed** (24, 171, 3, 170, 2, 25): none of them in
  `read_dps_never_pushed`, and missing on a head only where that head's value did not change;
- **a change is pushed promptly**: for a head whose temperature moved, the median interval of DP 24
  is of the order of minutes, not hours;
- **the link holds**: few `disconnects`, `decoded` close to `received`.

If one of these fails, the push can still complement the polling (faster echo after a write) but not
replace it, and the polling period stays as it is. Stage 4 would in any case keep a slow poll as the
reference and as the source of `online`, and would need a first phase where pushed values are only
compared with polled ones before any entity reads them.

What this measure does not tell: whether a pushed value equals the value the cloud poll returns at
the same moment (no value is kept), and how the push behaves over a session rotation longer than the
window. Both belong to stage 4's own validation.
