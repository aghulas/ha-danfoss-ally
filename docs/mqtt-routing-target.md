# Target routing — how much can go through cloud MQTT

A design study, not a plan of record. It answers one question: **can the cloud MQTT channel carry
everything, so the integration drops cloud HTTP and the local tunnel?** The honest answer is **no —
not as a single channel** — but a large share of the *reads* can move there. This document sets the
**target routing** operation by operation, says what must be **proven** before each move, and names
what stays on HTTP or the tunnel for good.

It builds on `docs/architecture.md` (the current routing and the "three channels, one router"
principle), `docs/interface-contract.md` (the cases R1–R7 where the cloud lies or does not act), and
`docs/cloud-mqtt-interface.md` (what two real listen-only captures showed on the channel).

## 1. What the cloud MQTT channel is, and is not

From the captures and the codec (`api/mqtt_client.py`, `api/mqtt_publish.py`):

- It is the **app's own control-and-telemetry path**: a setting changed in the app travels here, as
  a DP publish, and the head's reports come back on the same channel.
- It is **event-driven**: reports are **per-DP deltas**, never a full state on demand. There is a DP
  query (protocol 31) seen only in static analysis, never exercised.
- **DP 199 is the richest thing on it**: ~63 % of the traffic is the head's **raw Zigbee frame** —
  the very bytes the local tunnel reads on the LAN (programming mode `0x0025`, setpoint source,
  adaptation, and the `0x40xx` attributes when something reads them). The cloud receives it too.
- It **rides the same Tuya session** as cloud HTTP (same `sign_key`/`chKey`, a distinct `deviceId`).
  It is **not** a more reliable transport than HTTP: one connection at a time, invalidated by the
  same drift, opt-in with backoff and a clean shutdown.

So MQTT is strong for *streaming state* and *pushing a command*, weak for *asking a question now*
and *knowing the shape of the fleet*.

## 2. The four hard blockers against a single MQTT channel

1. **No discovery, no `online`.** No gateway-level or account-level frame was ever observed: no
   device list, no home/room structure, no online/offline event. The fleet is still bootstrapped
   from the HTTP device list, and `online` lives only there.
2. **No read on demand.** MQTT pushes deltas. "What is this head's state right now?" has no MQTT
   answer without a snapshot mechanism; the per-device HTTP route is the fresh read.
3. **Preheat has no cloud DP.** The real lever is the Zigbee attribute `0x0025` bit 1, reached only
   through the tunnel. Cloud DP 1 is a gateway-cache write, **proven not to reach the head**
   (2026-11-20; `docs/cloud-mqtt-preheat-proposal.md`). No capture changes this.
4. **"MQTT accepts" is not "the head acts".** The project's non-negotiable: a channel is proven for
   an operation only by a supervised write read back from an **independent** source. Several write
   DPs are proven on MQTT; most settings are not, and a publish that the broker accepts earns no
   trust on its own.

These are the same reasons `docs/architecture.md` gives for keeping three channels. A single MQTT
channel would have to defeat all four; none is a tuning detail.

## 3. The realistic target: a router that leans on MQTT for reads

Not one channel — the **same router, with more reads sourced from the push**, HTTP kept for
discovery and fresh reads, the tunnel kept for preheat and the unproven attribute writes. The target
per operation:

### Reads

| What | Today | Target | Move needs |
|---|---|---|---|
| Fleet discovery, home/room structure | Cloud HTTP | **Cloud HTTP (unchanged)** | — nothing on MQTT announces the fleet |
| `online` / connectivity | Cloud HTTP (`online`) | **Cloud HTTP**, maybe helped by the account topic | Establish that the account topic carries online/offline (§5) |
| Fleet state (temp, mode, valve, battery, window, faults) | Cloud HTTP bulk list (conservative poll) | **Cloud MQTT push overlaid on a slow HTTP baseline** | Decode the pushed DPs (24/169, 3, 25/173, 34…) into the overlay; keep a slow HTTP poll as the floor and for heads that stay quiet |
| Tunnel-grade state (programming mode, setpoint source, adaptation, window state, `0x40xx`) | Local tunnel survey (LAN) | **Cloud MQTT via DP 199**, tunnel as fallback | Decode DP 199 inbound (reuse `api/local/tunnel.py` `decode_frame`), and accept that the push is **opportunistic**: it carries an attribute only when something reads it, so the tunnel stays the on-demand reader |
| A head just commanded | Cloud HTTP per-device route | **Cloud MQTT echo** (already matched), HTTP re-read as fallback | Already the model; widen to more DPs as they are decoded |
| App message center | Cloud HTTP `smartlife.m.msg.list` | **Cloud HTTP (unchanged)** | — not on the gateway topics |

The headline move is row 3+4: **most of the read overlay from the push**, cutting the LAN tunnel
survey and the HTTP bulk poll down to a floor and a fallback. This is faithful to the principle —
each read still comes from a source proven to carry it — and it is where the fragility of polling a
real account is reduced.

### Writes

The write side barely moves, because the discipline for proving a write is unchanged and most
settings are not proven on MQTT. The target is to **keep routing each write to its proven channel**
and to grow the MQTT column only through the existing supervised-trial procedure.

| Operation | Today (isolated head) | Target | Move needs |
|---|---|---|---|
| Comfort / setback setpoint | Cloud MQTT (proven) + HTTP settings block | **Unchanged** | — already MQTT |
| Pause setpoint, bounds, child lock, window detection | Cloud MQTT (proven) | **Unchanged** | — already MQTT |
| Preheat | Local tunnel (`0x0025`) | **Local tunnel (unchanged)** | — no cloud DP exists (blocker 3) |
| Radiator covered, setpoint offset, regulation speed, valve exercise, external sensor, external window, load balancing, adaptation on/off | Local tunnel, closed trial | **Local tunnel**, opened per DP as its trial passes | These are `0x40xx` manufacturer attributes; a cloud DP equivalent is not established. Moving any to MQTT = a **new candidate DP + its own supervised trial** (§4) |
| Weekly schedule | Cloud HTTP (schedule-following head only) | **Cloud HTTP (unchanged)** | — no MQTT schedule write seen |
| Holiday, room management, relay binding | Cloud HTTP | **Cloud HTTP (unchanged)** | — account/room scope, not a head DP |
| Setpoint override (now) | Local tunnel (DP 171) | Local tunnel; **cloud MQTT DP 171 is a candidate** | DP 171 publish is seen outbound (§6.1 of the interface map); a supervised trial read back by the tunnel would prove it, and would let an isolated head take an override without the LAN |

### Writes deliberately **not** routed to MQTT

- **Mode (DP 2).** The app's mode change does travel as DP 2 on the channel (observed), but DP 2
  `manual` erases the schedule (R4) and `at_home`/`leaving_home` are labels (R5). The integration
  writes no DP 2 on any channel; the capture does not change that.
- Anything whose only confirmation would be the **echo** of the channel written (the preheat trap):
  it needs an independent read-back or it stays closed.

## 4. The rule that gates every move to MQTT

Unchanged from `docs/architecture.md` — restated because it is what makes "more via MQTT" safe:

- **One DP at a time.** A DP is a **candidate** (`api.writes.MQTT_CANDIDATE_DPS`), closed, until a
  supervised write on the one designated head, **read back from a source independent of MQTT**,
  promotes it to proven (`MQTT_WRITE_DPS`) in a change of its own.
- A **read** moved to MQTT needs the same honesty: the decoded push value is shown only where it is
  understood, and a DP whose scale or meaning is not established reads unknown with the raw value as
  an attribute, exactly as the tunnel survey does today.
- No optimistic state. After a write the entity shows what the channel returns; after a read it
  shows what was decoded, dated.

## 5. Open questions this study leaves

To be settled before the corresponding move, each by a real capture or a supervised trial:

| Question | What settles it | Unlocks |
|---|---|---|
| Does the account topic (`<partnerIdentity>/mb/<uid>`) carry online/offline, room changes, session eviction? | A listen-only subscription to it (a change to the connector's listener, which subscribes to gateway topics only today) | Cheaper `online`, less HTTP polling |
| Does the gateway forward to the cloud the answer to **every** tunnel read, including the weekly schedule? | A listen during a `get_local_survey` with schedules | How much of the tunnel survey can be sourced from the push |
| Is DP 171 (override) proven as an MQTT write on an isolated head? | A supervised trial, read back by the tunnel | An isolated-head "now" override without the LAN |
| Does a setting's echo differ between an isolated and a grouped head? | The targeted app-change capture repeated on an **isolated** head (the first was grouped) | Confidence in the push overlay for isolated heads |
| Does the DP query (protocol 31) return a full snapshot? | A supervised write-path trial of its own (a query is a publish on the outbound topic) | A read-on-demand over MQTT — would weaken blocker 2 |

## 6. Verdict

- **"Everything over MQTT" is rejected**: blockers 1–3 are structural (discovery, read-on-demand,
  preheat), and blocker 4 forbids trusting unproven writes.
- **"More over MQTT" is the target**, and it is a *read* story: decode the push — above all DP 199 —
  into the overlay, keep a slow HTTP baseline and the tunnel as the on-demand reader, and let the
  account topic and DP 171 be proven next. The writes stay on their proven channels and grow only
  through the supervised trial.
- First concrete step, lowest risk, highest value: **decode DP 199 inbound from the cloud push**
  (reusing the tunnel decoder), feeding the read overlay without the LAN tunnel. Everything else in
  §5 is a capture or a trial that gates a later move.
