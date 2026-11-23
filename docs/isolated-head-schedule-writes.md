# Schedule and override services on an isolated head — investigation

Status: **read-only investigation of 2026-11-20.** Nothing was written, read or changed on the real
install for this note: it rests on the code at `a89e590`, on the validation records of this repo and
on the local write journal of the Home Assistant admin connector. Guards 1 and 2 of the proposals
were then implemented on the owner's decision and shipped in 1.3.0 (see "Implemented"); the tables
below describe the code **before** them. The other proposals and the trials are still open.

The question: what do `set_schedule`, `copy_schedule`, `restore_schedule`, `set_override` and
`clear_override` really do to an **isolated** head (a head in no schedule-group, target
`{type: "device"}`), and can they stay as they are?

## Short answer

- A schedule write over cloud HTTP to an isolated head is **proven once, in one situation**: a head
  that follows its schedule (one head, one day, 2026-11-17, read back through the tunnel).
- On an isolated head the cloud shows in `manual` mode it is **accepted and applied differently**:
  on 2026-11-19 three accepted calls left the head in manual mode at the cloud's comfort value,
  asking for heat, with no schedule. That situation is not rare: it is the cloud-side state of
  every isolated head parked on a flat frost-protection setpoint.
- `restore_schedule` has **never** been seen to work on an isolated head, and its last step uses a
  route already recorded as "accepted, never applied" for such a head.
- None of the three schedule services has any guard for these cases, and the write job cannot tell
  what happened.
- The preheat bit lost that evening on the trial head is **not a preheat write**: it is the head
  going to manual mode, which clears the whole attribute `0x0025`. Nothing in the payloads carries
  preheat. The second head's loss is not explained.

So: not safe as they are for an isolated head that is not following a schedule; see the proposals.

## What the code sends

All five services are admin-only (`ensure_admin`; a call with no user, as through the Supervisor,
is let through). Bodies below are the ones built in `api/client.py`.

### Schedule services (cloud HTTP)

| Step | Room target | Isolated head target |
|---|---|---|
| Addressing (`_resolve_target`) | `devId` = `resId` = `gwId` = group id, `resType` 2 | `devId` = `resId` = head, `gwId` = the head's gateway (`meshId`), `resType` 1 |
| `set_schedule`, per given day | `week.timer.delete` then, if slots remain, `week.timer.create` | same two calls |
| `copy_schedule` | reads the source from the cache or the cloud, then `set_schedule` on each target | same |
| `restore_schedule` | reads the cloud schedule, rewrites the seven days, then `s.m.dev.group.dp.publish {"2": "at_home"}` | reads the cloud schedule, rewrites the seven days, then `tuya.m.custom.wkf.settings.change` with `settings = {"2": "at_home"}`, `gwId` = gateway |

- The schedule body is `{devId, gwId, pid, resId, resType, loops}` plus `periods` on create. It
  carries no setpoint, no mode and no preheat.
- `restore_schedule` rewrites what the **cloud** holds. For a head whose cloud schedule is empty it
  sends seven deletes and no create.
- Its last step on an isolated head is the `settings.change` route with a one-key block. The
  contract (§4.2) records that route as accepted and never applied for an isolated head's DP 30 and
  DP 116, and the app capture shows the app only ever posts the whole block
  `{"1", "118", "119", "121"}` there, with `gwId` = the head. A lone `{"2"}` is not something the
  app was seen to send.

Guards on the three schedule services:

| Guard | Present |
|---|---|
| R1 (six transitions a day), slot syntax | yes |
| A grouped head targeted directly is refused (`grouped_device`) | yes |
| Verified product (`write_allowed`) | **no**, for rooms and heads alike |
| Head online | no |
| Head in a schedule mode | **no** (the isolated-head comfort `number` has that guard, `SCHEDULE_MODES`) |
| Tunnel reachable, for a read-back | no |

### Override services (local tunnel)

- `set_override`: one tunnel frame, DP 171 at the given value (hundredths of °C). Fire-and-forget:
  the value returned is the one published, nothing is read back. Guards: tunnel enabled, target of
  type `device`, known head, verified product, a node id and a gateway whose key was fetched, value
  within the head's bounds by 0.5. No difference between an isolated and a grouped head, and no
  look at the head's mode or schedule.
- `clear_override`: reads the weekly schedule through the tunnel, computes the setpoint it
  prescribes now, and sends that through DP 171. Refuses with `no_schedule` when the head has no
  transition at all. Same guards otherwise.

Neither sends anything to the cloud, and neither touches `0x0025`: the integration writes that
attribute only in `write_preheat`.

### What the write job can verify

`verify_job` runs once, 300 s after the call, on the cloud's bulk state:

- `set_schedule` (and each `copy_schedule` job): every head is marked `unverified`
  ("schedule not re-read"), **whether or not the tunnel is enabled**. The contract (§3.5) promises a
  tunnel re-read when the local fallback is on; it is not implemented.
- `restore`: `applied` if the cloud's DP 172 has the schedule bit, else `mismatch`. That is the
  cloud's view. For the heads concerned here the cloud's mode is known to be wrong (it showed
  `manual` on heads the tunnel read in mode 3), so the verdict cannot be trusted either way.
- A head that is offline is `unreachable`. Nothing is checked after the fifth minute, and the
  2026-11-19 effect came after it.

So a job can say "the cloud accepted". It cannot say the head has the schedule, and it cannot see a
late or different effect.

## The evening of 2026-11-19, from the journal

The admin connector's journal gives the exact calls. All six targeted **the same head**; no call of
that evening targeted any other head.

| Time | Call | Note |
|---|---|---|
| 21:39:59 | options change (arming the trial) | reloads the integration |
| 21:40:26 | `set_schedule`, Thursday 21:00–23:45 | a slot **already running** at the time of the write |
| 21:47:52 | `restore_schedule` | cloud schedule then: that one slot |
| 21:54:16 | `set_schedule`, Thursday emptied | a lone `week.timer.delete`; the cloud schedule is empty again |
| 21:55 | tunnel read (validation record) | manual, 21 °C, mode 0, preheat off, empty schedule, heat demand |
| 21:55:52 | `set_override` 5 °C | read after: setpoint 5, mode 3, preheat on, flat 21 °C schedule |
| ~21:58 | manual 5 °C set in the Danfoss app | mode 0, preheat off, empty schedule |
| 22:01:54 | `set_override` 5 °C | no change |
| 22:02:47 | Home Assistant restarted by another session | |
| 22:04:35 | options change (disarming) | reloads the integration |

Before the calls the head was: tunnel, mode 3 with a flat 5 °C schedule and preheat on; cloud, mode
`manual`, empty schedule, comfort 21 °C.

What this does and does not establish:

- The head changed about a minute after the **third** call and fourteen minutes after the first.
  The record of that evening reads it as a late effect of the first; the timing fits the third at
  least as well. One reading that fits everything seen: while the cloud holds the head in `manual`,
  it stores a schedule write without sending it; when the last slot was deleted it sent the head
  its own stored state, manual at its comfort value, and manual mode erases the schedule (R4).
  This is a **hypothesis**. The three calls cannot be told apart from these records.
- The cloud's mode was still `manual` after `restore_schedule`: its `at_home` label did not even
  change the display, which fits "accepted, never applied" for that route.
- The first write set a slot that was already running. Had it been applied, the head would have
  gone to comfort at once; that it did not, for thirteen minutes, is the firm part of the record.
- `set_override` on a head in manual mode was followed within a minute by mode 3 and a flat
  schedule at the manual value (21 °C), with the current setpoint at 5 °C. An override "until the
  next schedule change" has nothing to end it on a flat schedule, and at the next transition the
  head would have gone back to 21 °C. Whether DP 171 caused the change of mode or met it is not
  known: the next night the same change took hours.
- After that state, `clear_override` would have read the flat 21 °C schedule and sent 21 °C.

## Preheat

- **The trial head.** Attribute `0x0025` is one bitmap: bit 0 schedule, bit 1 preheat, 0 = manual
  (R6). Each time the head went to manual that evening the record shows "mode 0, preheat off", and
  each time it came back to mode 3 it shows "preheat on". The preheat switch reads bit 1, so it
  showed OFF while the head was in manual. That is a change of mode, not a preheat write, and the
  schedule payloads carry nothing that could write preheat. The head's own return overnight
  (manual at X, then mode 3 with a flat schedule at X and preheat on) is already recorded.
- **Heads P3 and P4 of `docs/preheat.md`.** One of them shows
  ON 21:56 and OFF 22:04, which is the trial head's sequence (mode 3 after the override, manual
  after the app). If P4 is the trial head — inferred from the times, not checked by identifier —
  its "revert" that night is the manual-to-flat-schedule settling above, **not** evidence that the
  cloud re-imposes DP 1. Its first OFF, at 21:40, coincides with the integration reload of 21:39:59
  and disagrees with the tunnel reads of 21:42–21:53; it is not explained.
- **The other head** (P3) was targeted by no call. Its OFF was first seen at 22:04, the first
  survey after the 22:02 restart and the 22:04 reload. Nothing in the code or the journal explains
  it. Whether it lost bit 1 alone or went to mode 0 is not in the records read here.
- The cloud's DP 1 stayed on for both heads all along, so the one-key `settings.change` of
  `restore_schedule` did not clear it.

## Verdict per service, for an isolated head

| Service | Head following its schedule | Head the cloud shows in `manual` (flat or empty schedule) |
|---|---|---|
| `set_schedule`, `copy_schedule` | Proven once (2026-11-17, one head, one day, tunnel read-back). Unverified by the job | **Accepted, applied differently**: not applied within 13 min, then manual at the cloud's comfort value with heat demand (cause among three calls unknown) |
| `restore_schedule` | Never tried | **Not working**: did not bring the head back; label step on a route recorded as never applied |
| `set_override` | Proven (2026-11-19 morning, lapses at the next schedule change) | Unknown and risky: no schedule change to end it; seen with a change of mode and a flat schedule at the old manual value |
| `clear_override` | Proven (same trial) | Sends whatever the flat schedule holds; refuses only an empty schedule |

Rooms are not concerned by any of this.

## Still unknown

1. Which of the three calls put the head in manual at 21 °C, and by what mechanism.
2. Whether an HTTP schedule write reaches an isolated head the cloud holds in `manual` at all.
3. What the app does to bring an isolated head back to its schedule, and how it edits such a
   head's schedule (no capture exists; the settings captures of 2026-11-19 suggest a DP publish
   over cloud MQTT, DP 2, but that is a guess).
4. Why the second head lost its preheat bit, and whether P4 is the trial head.
5. Whether DP 171 moves a head from manual to mode 3.
6. Whether the 2026-11-17 proof holds for several days at once, for an emptied day, and on another
   gateway.

## Proposals (1 and 2 implemented, see below)

### Guards

1. **`restore_schedule` refuses an isolated head** (new code, for instance
   `isolated_restore_unproven`). It has no proven route there and one failed trial.
2. **`set_schedule` and `copy_schedule` refuse an isolated head unless it follows a schedule**:
   online, and the cloud's mode in `at_home` / `leaving_home` — the guard the isolated-head comfort
   `number` already has (`SCHEDULE_MODES`). When the tunnel is enabled and the head answers, also
   require bit 0 of `0x0025` and at least one transition, since the cloud's mode is known to be
   wrong on some heads. New code, for instance `head_not_following_schedule`. This keeps the one
   proven case open and closes the one seen to go wrong.
   A stricter variant refuses every schedule write to an isolated head until trial S0 below has
   passed again; it costs the editor on isolated heads in the meantime.
3. **Verified product** on all three schedule services, for rooms and heads (the other writes have
   it). Not specific to isolated heads; can be a change of its own.
4. **`set_override` reads before it writes**: mode and schedule through the tunnel, refused with
   `no_schedule` when the head is in manual or has a flat or empty schedule; then the current
   setpoint read back instead of fire-and-forget. `clear_override` gets the same refusal on a flat
   schedule.
5. **The job says what it knows**: with the tunnel enabled, `verify_job` re-reads the written days
   and `0x0025` from the head (`applied` / `mismatch`), with a second pass at 15 min; without it,
   `unverified` as today. `restore` stops trusting the cloud's DP 172 when the tunnel can answer.

Guards 1 and 2 were the ones needed before a schedule editor or a climate write was offered on
isolated heads; 3, 4 and 5 are still open.

### Implemented (guards 1 and 2)

- `restore_schedule` refuses an isolated head: `isolated_restore_unproven`.
- `set_schedule` and `copy_schedule` refuse an isolated head with `head_not_following_schedule`
  unless it is online, in `at_home` / `leaving_home` for the cloud, not reported by the cloud's
  DP 172 without its schedule bit and, when the tunnel is enabled and the head answers, with bit 0
  of `0x0025` set (one read of at most 8 s). `copy_schedule` checks every target before it writes
  the first.
- A flat schedule cannot be told from a schedule with slots by `0x0025` alone (both read mode 3);
  on the heads seen so far the cloud shows such a head in `manual`, which the guard refuses.
- Not done: the frontend's own text for the two codes (until it has one it shows its generic
  "the change could not be sent"; services show the translated message), and the contract points
  on R4, R6 and §3.5 listed below.

### Docs to change with the guards

- `docs/interface-contract.md`: §4.1 ("confirmed on real hardware" holds for a head following its
  schedule only; add the 2026-11-19 result), R4 (the return to schedule is a rule for rooms), R6
  (manual clears the preheat bit with the schedule bit), §3.5 (what the job verifies today), §5.2
  and §5.4 (effects and the new codes).
- `docs/architecture.md`: write table, row "Weekly schedule", isolated head: "cloud HTTP, only for a
  head following its schedule"; the open question on the return to schedule, with the journal's
  timeline.
- `docs/first-write-procedure.md`: the warning on preparing a trial with a schedule write names the
  three calls and their times.
- `services.yaml` and translations: say that an isolated head must follow a schedule.

### Supervised trials

Common frame: daytime, the owner present with the Danfoss app, one driver of the install, **no
reload or restart of Home Assistant during the trial** (two reloads and a restart fell inside the
2026-11-19 window), a cloud-MQTT listen on the head's gateway for the whole trial (it shows what the
cloud sends to the head, and when — the only way to attribute an effect to a call), and the tunnel
as the independent read-back (`0x0025` raw, weekly schedule, current setpoint and its source). Not
on the two heads of the overnight preheat trial until that trial has been read.

- **S0 — the proven case, again.** A head following its schedule. One call: `set_schedule` adding
  one slot on a day other than today. Tunnel reads at +1, +5, +15 min. Baseline restored by one
  `set_schedule` emptying that day back to what it was, read back the same way.
- **S1 — the open case, one call.** An isolated head the cloud shows in `manual`, on a flat
  frost-protection schedule, nobody relying on it. One call only: `set_schedule` with one slot on a
  day **other than today**, so a late application cannot start heating. Tunnel and cloud
  (per-device route and `week.timer.list`) at +1, +5, +15, +30 min. Then stop.
- **S2 — the clear, alone**, only if S1 left the head unchanged for 30 min: `set_schedule` emptying
  that day. Same reads. A switch to manual at the cloud's comfort value here names the third call
  of 2026-11-19 as the cause.
- **S3 — `restore_schedule` alone**, another day, only if the owner still wants that service for
  isolated heads.
- **Stop rule and baseline** for S1–S3: heat demand or a current setpoint above the frost value →
  the owner sets manual at the frost value in the app at once (the only correction seen to work),
  then the head is read the next morning for its return to mode 3 with a flat schedule and preheat
  on.
- **App capture** (emulator, no write from the integration): editing the schedule of an isolated
  head, switching it to manual and back to its schedule. This is what would give a real route for
  `restore_schedule`, and it comes before any attempt to make that service work.
