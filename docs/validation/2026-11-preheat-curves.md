# Real-hardware validation — preheat (P-1, P-2, P-3)

**Date:** 2026-11-19 (Thursday) morning.
Real-hardware validation on a large real install (~99 heads, two homes). Anonymised: room names,
identifiers and site details replaced by neutral labels.
Main report: [`2026-11-real-hardware-validation.md`](2026-11-real-hardware-validation.md) (labels
are shared with it). Plan: [`../real-validation-plan.md`](../real-validation-plan.md), §3.

## Labels used in this report

Letter labels are the same as in the main report. Numbered heads (Head 01…15) appear only here.

| Label | Role |
|---|---|
| Building 1 / Building 2 | The two Danfoss homes |
| Room A | Isolated test head (manipulated this morning) |
| Room B floor heads | Several heads on the same floor as Room B (manipulated this morning) |
| Head C | Building 2 head, 08:00 slot; has an orphan preheat entity |
| Head D | Building 2 head; repeated tunnel-only outages |
| Head E | Building 2 head (one of two in its room), 08:00 slot |
| Head G | Building 2 head, no schedule read |
| Head M | Preheat OFF, valve at 0 all morning |
| Head N | Building 2 head, 08:00 slot, valve almost always fully open |
| Head P | Preheat OFF (checked locally) |
| Head Q | Preheat OFF (Building 1) |
| Head R | Preheat ON (Building 1); used for the controlled trial |
| Room S | Three-head room at 5 °C (frost protection) |
| Room T | Four entities with orphan preheat switches |
| Head U | Preheat OFF, valve at 0 all morning |
| Head V | 07:00 slot; offline overnight |
| Room W | Four-head room (heads #1–#4) |
| Room X | Room with several heads (#1, #5 cited) |
| Head Y | Building 1 head on the Room B floor, manipulated this morning |
| Head Z | Building 1 head; offline overnight |
| Heads 01–15 | Other heads, neutral numbering |

---

Read-only, with no write at all on the Pi or on the heads. This file complements the main report,
kept by the validation session, and details §3 of the plan.

## Sources

- **Preheat state (the real lever, 0x0025)**: HA history of the `switch.*_pre_heating` entities of
  the `danfoss_ally_cloud` integration, fed by the local tunnel survey
  (`DanfossLocalCoordinator.survey_preheat`). Spot check with
  `danfoss_local_tete("<Head P>")`: `pre_chauffage: false`, Thursday slot 08:30–17:30,
  comfort 20, setback 14.
- **Curves**: HA history (`/api/history/period`, read through the Supervisor proxy) of the
  integration's `sensor.*_valve_opening*` and `sensor.*_temperature*`, from 18/11 16:00 to
  19/11 10:30. All times are local time (UTC+1).
- **Independent cross-check**: `binary_sensor.*_pre_heating` of MTrab's `danfoss_ally`
  integration, which reports the cloud flag "preheat in progress".
- **Schedules**: `danfoss_tuya_programmes` (all floors of both buildings except Head G's).
  - Thursday, comfort slot at **08:30** everywhere.
  - Exceptions: **08:00** for Head C, Head N, both heads of Head E's room and three other heads on
    the same floor; **07:00** for Head V.

Method: the **first heating start** is the first valve reading ≥ 10 % since midnight (the valve
stayed at 0–1 % all evening). Then **lead = slot start − heating start**. The valve is only read
about every 5 minutes, hence a precision of ±5 min.

## Result

| Step | Verdict | Summary |
|---|---|---|
| **P-1** preheat ON → anticipated heating | ✅ | 70 usable heads with preheat ON. The valve opens **52 to 448 min before the slot (median 252 min, ~4 h 10)**. The cloud "Pre-Heating" flag turns ON at the same time, within a few minutes. Rooms reach ~21 °C around 07:00–08:00, so before 08:30. |
| **P-2** preheat OFF → heating at the slot | ✅ (2 clear heads) | Head P and Head Q: valve at 1 % until **08:34**, i.e. the 08:30 slot + 4 min (reading step), with no anticipated ramp and no cloud flag. The other OFF heads are not conclusive (see below). |
| **P-3** switch unavailable when the tunnel does not answer | ✅ partial | Several per-head cases: the preheat switch goes `unavailable` while `online` stays `on` and the head's other cloud switches (child lock, window detection) stay available. So it never lies with a fake ON/OFF. No total tunnel outage observed in the window. |

### Per-head table (representative sample)

| Head | Preheat (switch, night) | Thursday slot | 1st start (valve ≥ 10 %) | Lead | Cloud flag ON | T 06:00 → 08:30 | Verdict |
|---|---|---|---|---|---|---|---|
| Head 01 | ON | 08:30 | 03:39 | 291 min | 03:36 | 17.7 → 21.0 | P-1 ✅ |
| Head D | ON | 08:30 | 06:04 | 146 min | 06:06 | 17.0 → 21.1 | P-1 ✅ |
| Head E | ON | 08:00 | 04:03 | 237 min | 04:29 | — | P-1 ✅ |
| Head 02 | ON | 08:30 | 04:07 | 263 min | 04:29 | 17.5 → 21.9 | P-1 ✅ |
| Head 03 | ON | 08:30 | 04:58 | 212 min | 05:14 | 17.8 → 20.9 | P-1 ✅ |
| Head 04 | ON | 08:30 | 04:16 | 254 min | 04:29 | 17.3 → 21.1 | P-1 ✅ |
| Head 05 | ON | 08:30 | 04:22 | 248 min | 04:29 | 17.4 → 21.9 | P-1 ✅ |
| Head 06 | ON | 08:30 | 05:25 | 185 min | 06:06 | — | P-1 ✅ |
| Head 07 | ON | 08:30 | 01:36 | 414 min | 02:59 | 17.7 → 21.0 | P-1 ✅ (very early) |
| Head 08 | ON | 08:30 | 03:39 | 291 min | 03:36 | 18.1 → 22.1 | P-1 ✅ |
| Head 09 | ON | 08:30 | 05:45 | 165 min | 06:06 | 16.1 → 20.7 | P-1 ✅ |
| Room W #4 | ON | 08:30 | 04:46 | 224 min | 04:44 | — | P-1 ✅ |
| Room X #1 | ON | 08:30 | 03:27 | 303 min | 03:36 | 16.9 → 19.9 | P-1 ✅ |
| Head 10 | ON | 08:30 | 05:12 | 198 min | 05:14 | 17.5 → 21.8 | P-1 ✅ |
| Head 11 | ON | 08:30 | 05:13 | 197 min | 05:14 | 17.2 → 21.0 | P-1 ✅ |
| Head R | ON | 08:30 | 06:18 | 132 min | 06:21 | 16.8 → 21.8 | P-1 ✅ |
| **Head P** | **OFF** (local: `pre_chauffage=false`) | 08:30 | **08:34** | −4 min | never | 14.2 → 15.4 → 19.1 at 10:00 | **P-2 ✅** |
| **Head Q** | **OFF** | 08:30 | **08:34** | −4 min | never | 16.6 → 17.5 → 22.1 at 10:00 | **P-2 ✅** |
| Head M | OFF | 08:30 | — (valve 0 all morning) | — | never | 15.2 → 16.5 | not conclusive |
| Head U | OFF | 08:30 | — (valve 0) | — | never | 14.8 → 14.9 | not conclusive |
| Room S #1/#2 | OFF / unavailable | 08:30 | — (valve 0) | — | never | ~14.6–15 | not conclusive |

Full list, 99 heads: the reading can be reproduced with the queries of the Sources section. Leads
range from 52 min (Room X #5, offline until 07:09) to 469 min (washroom and hand-basin heads on the
Room B floor, open from 00:40).

### P-2: why only two heads

Thirteen switches are OFF, which matches 7 heads, the rest being MTrab's `switch.*_pre_heat`
duplicates.
- **Head P** and **Head Q** are the only OFF heads that had a real heat demand at the slot. They
  start at 08:34, four minutes after the slot, with no anticipation. By contrast, the ON heads of the
  same building and the same gateway start between 03:00 and 06:20.
- **Head M** and **Head U** have the valve at 0 before and after 08:30: there is no demand, probably
  because the comfort setpoint is low. So no conclusion can be drawn.
- **Room S #1/#2/#3** have a 5 °C setpoint (frost protection): no demand either. In addition, #1's
  switch is unavailable from 00:46 to 09:50, and #3's is permanently unavailable.
- Limit: these heads were already OFF before the window started (at least since 18/11 13:11). So P-2
  validates the **head's behaviour and the reading** of the switch, **not the write path** (switch
  toggle → 0x0025). See the trial proposal below.

### P-3: unavailabilities observed (18/11 13:00 → 19/11 10:30)

- **Global outages** at 13:08, 14:59, 15:12 and 20:08 on 18/11, then at 09:08 on 19/11, each for 2
  to 4 minutes. All the integration's entities (`online`, child lock…) drop at the same time: these
  are integration reloads or HA restarts, not a tunnel-specific signal.
- **Tunnel-specific outages, head by head**: the preheat switch is `unavailable` while
  `binary_sensor.*_online` is `on` and `switch.*_child_lock` and
  `switch.*_open_window_detection_2` stay available. This matches the
  `coordinator.data[id] is None` path of `switch.py:156`.
  - Head D: 07:34–07:51, 08:24–08:33, 08:58–09:08, 09:26–10:07, 10:23–10:25.
  - Heads 12 / 13 / 14 (same gateway as Head D): same windows, which suggests missed answers from
    that gateway. Head 14 and Head 15 are still unavailable at 10:23.
  - Room S #1: 00:46 → 09:50 (the whole morning).
  - Head Y: 00:46–02:28, 03:02–04:45, 06:10–07:01, 07:17–08:24 (head manipulated during the
    morning, but the outages start before).
  - Room W #1/#2/#3: alternating available/unavailable all night, from about 17 min to a few
    hours.
  - Head V: preheat unavailable from 18/11 13:11 to 19/11 06:44. It was `online` until 23:04:
    first a local read failure, then the head goes offline.
- **Case consistent with `online`**: Room X #5 (21:33 → 07:09) and Head Z (23:08 → 09:32). Here,
  `online=off` makes the whole head unavailable, preheat included.
- None of these windows shows a fake ON/OFF: either the switch has a value read locally, or it is
  unavailable.
- **Not observed**: a total tunnel outage (`survey_preheat` failure, `UpdateFailed`), which would
  make all preheat switches unavailable while leaving the other entities available. Covering it
  would need a provoked trial, for example by turning off `enable_local` or cutting access to a
  gateway. That would be a write, to be decided by the owner and the validation session.

## Points to exclude or interpret with care

- **Room A**: valve open at 07:09, cloud flag at 07:06, i.e. 80 min lead. This looks like normal
  preheat, but the room was manipulated between 08:30 and 10:30: it is excluded from the verdict.
- **Room B floor heads** (several rooms, washrooms, hand basins, stairs): heads manipulated this
  morning. Their behaviour before 08:30 is consistent with P-1, but they are excluded from the
  figures.
- **Head N**: valve at 98–100 % without interruption since the afternoon of 18/11. It probably does
  not reach its setpoint. This is not a preheat signal: excluded.
- **Head V**: offline until 06:42 for a 07:00 slot, valve at 99 % as soon as it reconnects. Not
  conclusive.
- **Head G**: no schedule read, excluded.

## Side observations (out of scope, to follow up)

- **Preheat very early**: the median is ~4 h. One floor of Building 2 (including Head 07) and the
  washroom heads of two floors of Building 1 open from 00:40–01:50, i.e. up to 7 h 50 ahead.
  - In several rooms, the temperature only rises clearly **between 06:00 and 07:00**, whatever time
    the valve opened. Rooms are then at ~21 °C around 07:00, i.e. 1 h 30 before the slot.
  - Hypothesis: the boiler room only supplies hot water from ~06:00 (to check on the boiler side).
    The head's adaptive algorithm then "learns" a very slow rise and anticipates more and more.
    This is an energy and tuning issue, not an integration bug.
- **Orphan entities**: `switch.<room_t>_{1..4}_pre_heating`,
  `switch.<head_c>_pre_heating` (the live entity is `…_pre_heating_2`) and
  `switch.<room_s>_3_pre_heating` are restored as `unavailable` with no matching head in the
  integration (99 heads mapped). They should be cleaned up, and not be confused with P-3.

## Controlled trial proposal (not executed at the time of writing, to be approved by the owner)

Goal: validate the **write path** (switch → 0x0025) and P-2 on an occupied room.
Proposed window: the night of Thursday 19 to Friday 20/11, Friday slot 08:30.

| Action (by the validation session, the only one that writes) | Head | Expected on Friday |
|---|---|---|
| `switch.turn_off` on `switch.<head_r>_pre_heating` | Head R (ON today, start 06:18) | valve closed until ~08:30, no cloud flag |
| `switch.turn_on` on `switch.<head_q>_pre_heating` | Head Q (OFF today, start 08:34) | anticipated opening before 08:30, cloud flag ON |

- Immediate check after each toggle: `danfoss_local_tete` must re-read `pre_chauffage` with the new
  value.
- Restore on Friday after 09:00: put back both original values.
- Risk: Head R's room will be colder when occupants arrive on Friday (≈17 °C at 08:30 instead of
  ~21.8 °C). Better to pick a room that is little used early, if the owner prefers.

(The main report records that this trial was then started at 10:58 with the owner's approval.)
