# Cloud-bridge relay room linkage — supervised trial plan (NOT RUN)

**Status: plan only, not run.** Nothing in this file has touched real hardware. Every live write below needs
Rémi's explicit go-ahead, **one go-ahead per write**, given at the keyboard.

What it covers: linking and unlinking one room to a boiler relay (`014G2400`) served by the `danfoss2mqtt` cloud
bridge, from the relay's page in the integration's side panel (`room_link`, contract
[`../companion-contract.md`](../companion-contract.md) §3). The general rules are in
[`../first-write-procedure.md`](../first-write-procedure.md).

⚠ **This changes the boiler's heat demand.** A linked room that asks for heat closes the relay and starts the
boiler. An unlinked room no longer does.

## What is written, and how it is checked

| Step | Who | What |
|---|---|---|
| Ask | Panel (admin) → WebSocket `relay/link_room` | Checks: relay known, `room_link` advertised, room listed for that relay on `bridge/relays`, not the relay's last linked room. Publishes `{"room_link": {"room_id", "linked"}}` on the relay's `/set`. Shows "Awaiting the bridge…" |
| Validate | Bridge | Gate open for this relay; fresh read of the relay's rooms (`m.life.solution.wkf.reference.room`); same checks against that read |
| Write | Bridge | One `m.life.solution.wkf.reference.edit` (`bind` / `unbind`), one room |
| Read back | Bridge | Re-reads the relay's rooms (up to 3 reads, 5 s apart), then republishes `bridge/relays` at once with what it read; logs "confirmed" or "NOT confirmed" |
| Show | Panel | Re-reads the overview every 3 s (2 min at most) and clears "Awaiting" only when `bridge/relays` shows the asked state |
| Independent read-back | MCP connector `danfoss-ally` | `danfoss_tuya_relais_pieces` on the same relay: does not go through the bridge, the broker or Home Assistant |

The MCP connector's own write (`danfoss_tuya_relais_piece_preparer`) uses the same endpoint and is reported
validated there. **Through this bridge it is not proven yet**: this trial is its first write.

## Builds needed (not released yet)

- `pydanfoss-cloud` with `relay_links` (branch `claude/relay-room-links`), in a release;
- add-on `danfoss2mqtt` with the options `relay_links_writes` / `relay_links_trial_relay` and a pin on that
  release;
- the integration with the relay page controls and `relay/link_room` (branch `claude/relay-room-linkage-334fb1`).

Check what actually runs on the Pi before the trial (a HACS update can replace a hand-deployed build).

## Preconditions

- **One driver of the live install**: no other session restarts Home Assistant or the add-on, changes options
  or deploys while the gate is open.
- **Trial relay `Relay T`**: online, with **at least two linked rooms** (the bridge and the panel refuse to
  unlink the last one).
- **Trial room `Room X`**: one of `Relay T`'s rooms that is **unlinked now**. Prefer a room whose heads ask for
  no heat right now (setpoint reached, or setback slot), so that linking it does not start the boiler during
  the trial. Note its heads' `pi_heating_demand` at the start.
- The MCP connector `danfoss-ally` answers `danfoss_tuya_relais_pieces` and `danfoss_tuya_relais_etat` for
  `Relay T` **before** anything is armed.
- The Danfoss app open on `Relay T`'s room list (to observe; check it is not logged out).
- A way back that does not depend on this code: the app's relay room list, or the MCP connector's
  `danfoss_tuya_relais_piece_preparer` (its own prepare → confirm).

## Steps

1. **Baseline (read only).**
   - MCP `danfoss_tuya_relais_pieces(Relay T)`: record every room and its link as `L0`.
   - MCP `danfoss_tuya_relais_etat(Relay T)`: record on/off.
   - Panel, relay page: the list must equal `L0`, read-only (the gate is still closed), with the
     read-only note.
   - App: same rooms linked.
   All three must agree. Stop if not.
2. **Arm** (add-on options, needs the go-ahead "arm"): `relay_links_writes: true`,
   `relay_links_trial_relay: <Relay T device id>`. Restart the add-on. Check:
   - the add-on log has one warning "relay room linkage writes OPEN (trial relay … only)";
   - `bridge/devices`: `Relay T` carries `danfoss.set_keys: ["room_link"]`, **every other relay `[]`**;
   - panel: `Relay T`'s page shows the heat-demand warning and the Link / Unlink buttons; another relay's
     page stays read-only.
3. **Write 1 — link `Room X`** (go-ahead "write 1"). On `Relay T`'s page, click **Link** on `Room X` and
   accept the confirmation.
   - Panel: `Room X` shows "Awaiting the bridge…", then "Linked" within about 20 s.
   - Add-on log: "room … linked to relay … (confirmed by a read of the relay's rooms)".
   - **Independent read-back**: MCP `danfoss_tuya_relais_pieces(Relay T)` shows `Room X` linked, every other
     room as in `L0`.
   - App: `Room X` checked.
   - `danfoss_tuya_relais_etat(Relay T)`: record on/off; a change is expected only if `Room X` asks for heat.
   Pass: all four agree on the new state and nothing else changed. A panel or bridge "linked" that the MCP
   read does not show is the "accepted but not applied" failure: **stop and restore from the app**.
4. **Write 2 — unlink `Room X`** (go-ahead "write 2"). Click **Unlink** on `Room X` and accept.
   Same checks as write 1, expecting `Room X` unlinked: the MCP read must equal `L0` again.
5. **Refusals (no cloud write, no go-ahead needed, still one at a time).**
   - On `Relay T`, the room that is the last linked one (if any) shows no Unlink button (it cannot be
     reached with ≥ 2 linked rooms; nothing to do then).
   - From Developer tools → MQTT, publish on another relay's `/set`:
     `{"room_link": {"room_id": "<one of its rooms>", "linked": true}}`. Expected: add-on log "relay linkage
     writes are closed", **no** MCP-visible change on that relay. Skip this check if Rémi prefers not to
     publish by hand on another relay.
6. **Disarm** (go-ahead "disarm"): `relay_links_writes: false`, `relay_links_trial_relay: ""`, restart the
   add-on. Check every relay advertises `[]` and the panel pages are read-only again.
7. **Final read-back**: MCP `danfoss_tuya_relais_pieces(Relay T)` equals `L0`; relay on/off as at baseline (or
   explained by the rooms' heat demand).
8. **Record** the result here (versions, delays per step, what each source showed), anonymised: no real device
   ids or room names in this repository.

## Stop and restore at once if

- the MCP read does not show the change within about a minute while the panel or the bridge does;
- any other room of `Relay T`, or any other relay, changes;
- the bridge logs "NOT confirmed" (read the relay through the MCP connector before anything else, never retry
  blindly);
- the boiler starts and the room's heads do not explain it;
- the app is logged out, or there is any doubt about restoring.

Restore through the app's relay room list (or the MCP connector's own prepare → confirm), back to `L0`, then
disarm.

## After a pass

- Open the gate to every relay only by a separate decision (`relay_links_trial_relay: ""`), recorded here.
- Update `CloudClient.async_relay_bind`'s docstring and the contract to say the bridge route is proven, in a
  pull request of its own.
