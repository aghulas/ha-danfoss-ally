# v2 cutover — making the Companion the sole provider of the Danfoss heads

> **Goal:** end the state where every Danfoss head carries entities from **three** providers at once
> (the `_2` / `_3` entity-id suffixes) and leave the **v2 Companion** (`zigbee2mqtt` +
> `danfoss2mqtt`) as the single source of each head's `climate` / `sensor` / `binary_sensor` /
> `number` / `switch` entities, before shipping `2.0.0` stable.
>
> This is an **operational switch on the live Home Assistant**, so it is **Rémi's step**, not a
> session's. The integration side only *detects* the duplication and *guides* the switch (a Repairs
> warning, see §3); it never disables an entry or deletes another integration's entities on its own.

---

## 1. Why the heads are duplicated today

Every provider creates one `climate` (and the matching sensors) per physical head. Home Assistant
keeps them all because their **`unique_id`s differ**, and only disambiguates the visible
*entity-ids* with `_2` / `_3`. The providers seen on the real install (2026-11-22):

| # | Provider | Integration / platform | Head `unique_id` base | Rooms |
|---|---|---|---|---|
| 1 | **v2 Companion** (keep) | `danfoss_ally_cloud`, title *“Danfoss Ally Companion (zigbee2mqtt, danfoss2mqtt)”* | Tuya `dev_id` for **danfoss2mqtt** heads; the **Zigbee IEEE address** for **zigbee2mqtt** heads (`api/z2m_contract.py`) | native `group_id` (danfoss2mqtt) / virtual `room_id` (z2m) |
| 2 | **v1.x direct cloud** (remove) | `danfoss_ally_cloud`, title = account e-mail | Tuya `dev_id` | `group_<group_id>` |
| 3 | **Local bridge MQTT discovery** (remove) | `mqtt` / Mosquitto, from the **“Pont Danfoss local”** add-on (a separate private repository, **outside this repo**) | its own `danfoss_l_<devId>` discovery ids | — |

Plus MTrab's separate **`danfoss_ally`** integration — a *different domain*, unrelated to this
project; it is **out of scope** here (see §6).

Consequences worth knowing before the switch:

- For heads reached over **danfoss2mqtt**, the Companion and the v1.x cloud entry build the **same**
  `unique_id` (both = the Tuya `dev_id`). Home Assistant registers only the first, so those heads
  are not literally doubled between providers 1 and 2 — but they *do* conflict, and they are tripled
  by provider 3.
- For heads reached over **zigbee2mqtt**, the Companion keys on the **IEEE address**, which differs
  from the v1.x cloud `dev_id`, so those heads **are** duplicated (`…_2`) and then tripled (`…_3`).
- Removing a provider frees the plain entity-id (`climate.<room>`) but the Companion entity
  that was pushed to `…_2` **keeps its suffixed entity-id and its own history** — Home Assistant
  does not rename it back by itself. Reclaiming the clean id is a manual, optional step (§5).
- **Granularity differs by provider, and that is by design — not lost heads.** The Companion
  exposes one `climate` per *room* (the native `group_id` for danfoss2mqtt, the virtual `room_id`
  for zigbee2mqtt), while the v1.x cloud entry and the local bridge expose one per *physical head*.
  So the Companion's entity count can be **lower** than a per-head provider's for the same install;
  the Companion still tracks each head (per-head sensors and the supervised-head selectors), it just
  groups the `climate` control at room level. Before removing a per-head provider, decide whether you
  still need a per-head `climate` view (if so, keep one per-head provider, e.g. MTrab's separate
  domain, see §6) rather than assuming the heads disappeared.

## 2. Order of operations (overview)

```
Companion healthy ──▶ disable v1.x cloud entry ──▶ stop local-bridge discovery + purge retained
                 (§4)                        (§4)    topics (§4) ──▶ reclaim entity-ids (§5) ──▶ verify (§7)
```

Do them **one at a time**, checking the Companion still serves every head between steps. Nothing
here is destructive to the Companion; the only irreversible actions are the retained-topic purge
(§4.3) and any manual entity deletions (§5), both called out explicitly.

## 3. What the integration does for you (code side)

From this version, a **Companion** config entry raises a non-fixable **Repairs** warning —
*“Danfoss Ally: duplicate provider active”* — whenever a **v1.x direct-cloud** `danfoss_ally_cloud`
entry is **loaded at the same time** (`repairs.sync_provider_conflict`, re-evaluated on every
Companion update). It points at this document and **clears automatically within seconds** once the
old entry is disabled or removed. The account e-mail is never written into the issue (only a count),
per the no-secrets-in-diagnostics rule.

The warning deliberately covers only the part the integration can detect reliably — a second config
entry of **its own** domain. The external **“Pont Danfoss local”** MQTT-discovery add-on lives in
another repository and publishes under the `mqtt` platform, so it cannot be detected from inside the
integration without hard-coding that bridge's topic scheme; §4.3 handles it by hand.

## 4. The live switch (Rémi, on the Pi)

### 4.0 Pre-checks

- Confirm the Companion entry is loaded and healthy and that **every head** is present under it
  (Settings → Devices & services → *Danfoss Ally Companion*). The connectors can confirm:
  `ha_integrations` (entry states), `ha_entite` / `ha_entite_registre` (which entry owns each
  entity).
- Note, per head, **which entity-id the Companion currently owns** (`climate.<room>` or
  `climate.<room>_2`). You will need this for §5. The entity registry shows the owning
  `config_entry_id`.
- Take a Home Assistant backup first (`ha_sauvegarde_preparer` → confirm). Cheap insurance.

### 4.1 Disable the v1.x direct-cloud entry

Settings → Devices & services → the `danfoss_ally_cloud` entry **titled with the account e-mail**
(not the Companion) → **⋮ → Disable**, or **Delete** if you are sure you will not go back to the 1.x
line. Disabling is enough to stop it providing entities and to clear the Repairs warning; deleting
also drops its devices/entities.

- Connector equivalent: `ha_integrations` to find the entry, then the disable/remove write
  (`ha_integration_action_preparer` → `ha_ecriture_confirmer`).
- The Companion's Repairs warning should disappear on its own shortly after. If it lingers, reload
  the Companion entry.
- The v1.x entry owns the plain entity-ids for the **danfoss2mqtt** heads (it registered them
  first). Disabling it leaves those entities *restored / unavailable*; the clean ids are then free
  for the Companion to reclaim (§5).

### 4.2 Stop the local-bridge MQTT discovery

The **“Pont Danfoss local”** add-on publishes Home-Assistant MQTT discovery that creates the third
set of entities. **Stop the add-on** (Settings → Add-ons → *Pont Danfoss local* → **Stop**, and turn
off *Start on boot*). Stopping it halts new/updated discovery, but Home Assistant keeps entities
created from **retained** discovery topics until those topics are cleared — hence §4.3.

> **Do not confuse the local discovery bridge with the add-ons that feed the Companion.** The
> Companion's two inputs — the **Zigbee2MQTT** add-on and the **danfoss2mqtt** add-on — are *separate*
> add-ons that must stay running; only the **“Pont Danfoss local”** discovery bridge (provider 3) is
> stopped here. Check the slugs before stopping anything: the discovery bridge is its own add-on,
> distinct from `zigbee2mqtt` and from `danfoss2mqtt`.
>
> **If the discovery bridge also emits a Zigbee2MQTT-format stream** (some versions have a
> `z2m_output` option publishing under a separate base topic), confirm nothing consumes that stream
> before stopping the add-on — in particular that it is **not** the Companion's zigbee2mqtt input
> (that input should be the real Zigbee2MQTT add-on, not the bridge). If something does consume it,
> stopping the add-on would remove more than the duplicate discovery entities.
>
> The add-on's source is in a separate private repository, not here. If you want it to stop publishing a
> *subset* of heads rather than all, that is an edit there (an `EXCLUS`/exclusion set, as was done
> for the chapel heads), not in this integration.

### 4.3 Purge the retained discovery (and state) topics — **irreversible**

Only after §4.2. Clearing before the add-on is stopped is pointless — it republishes them.

List the retained topics first (connector `mqtt` → `mqtt_topics` / `mqtt_lire`, or
`mosquitto_sub -h <broker> -v -t 'homeassistant/#' -t 'danfoss_l/#' --retained-only`). For **each**
local-bridge head `devId` (`D` below) the add-on publishes, clear by sending an **empty retained**
message to:

```
# discovery (makes HA drop the entities)
homeassistant/climate/danfoss_l_<D>/config
homeassistant/binary_sensor/danfoss_l_<D>_demande/config
homeassistant/sensor/danfoss_l_<D>_batt/config
homeassistant/sensor/danfoss_l_<D>_valve/config
homeassistant/sensor/danfoss_l_<D>_vpile/config

# state (retained, cosmetic once discovery is gone)
danfoss_l/<D>/avail   danfoss_l/<D>/batt   danfoss_l/<D>/demande  danfoss_l/<D>/diag
danfoss_l/<D>/hvac    danfoss_l/<D>/preset danfoss_l/<D>/target   danfoss_l/<D>/temp
danfoss_l/<D>/valve   danfoss_l/<D>/vpile
```

A room sensor published by the bridge (`danfoss_l/sonde/<D>/…` + its `homeassistant/sensor/…`
discovery) follows the same pattern — but decide with the person whether that wired sensor is
actually being retired before clearing it (on this install the chapel sonde was kept).

- The real `devId`s are **not written into this repo** (secrets rule); read them live from the
  broker as above.
- Clear retained topics by publishing an **empty payload with the retain flag** (e.g.
  `mosquitto_pub -r -n -t '<topic>'`), topic by topic. Never clear a topic you have not just seen
  listed.
- After the purge, the `danfoss_l_…` devices drop out of Home Assistant. Any left as an empty
  device shell can be deleted from its device page.

## 5. Reclaim the clean entity-ids (optional, recommended)

After §4 the Companion is the only provider, but on the **zigbee2mqtt** heads it still owns the
`…_2` entity-ids, and the clean id sits *restored / unavailable*. To put the Companion back on the
clean ids and keep automations/dashboards working:

> **Who holds the clean id depends on the install's topology — it is not always the v1.x entry.**
> The plain `climate.<room>` id belongs to whichever provider registered it *first*. On an install
> where the local discovery bridge was the first provider, the clean ids are held by the **bridge
> (`mqtt` platform)**, not by the v1.x cloud entry — so they are not freed by disabling v1.x (§4.1),
> only once the bridge's entities are gone (after the §4.3 purge). Check each clean id's owner first
> (`ha_entite_registre` → the `config_entry_id` / platform of the entity holding the plain id), then
> free it from that owner. The step below is written for the common case; substitute the actual
> owner.

1. **Delete** the freed *restored / unavailable* entity that holds the clean id (it belongs to the
   provider you removed — the now-disabled v1.x entry, or the stopped local bridge once its retained
   topics are purged): entity page → **⋮ → Delete**, or connector `ha_entite_supprimer_preparer` →
   confirm. (If you *deleted* the v1.x entry in §4.1 rather than disabling it, and it was the owner,
   this is already done.)
2. **Rename** the Companion's `…_2` entity to the clean id: entity settings → *Entity ID*, or
   `ha_entite_renommer_preparer` → confirm. History follows the entity, so the Companion keeps its
   own recorded history under the clean id.

Do this per head you care about; there is no bulk tool and no need to rush — a suffixed id is
cosmetic, not a fault. Leaving them suffixed is a valid choice.

## 6. MTrab's `danfoss_ally` (out of scope)

MTrab's community integration is the **`danfoss_ally`** domain — separate from this project's
`danfoss_ally_cloud`. It is not part of this cutover. If it is also installed and you do not want its
copies, disable/remove it the same way (Settings → Devices & services), independently of the steps
above. The Repairs warning in §3 does **not** look at it (different domain).

## 7. Verify

- Settings → Devices & services: only the **Companion** `danfoss_ally_cloud` entry remains enabled;
  no e-mail-titled entry, no `mqtt`/`danfoss_l_…` Danfoss devices.
- Each head has **one** `climate` and its sensors, owned by the Companion
  (`ha_entite_registre` → `config_entry_id` = the Companion entry).
- The *“duplicate provider active”* Repairs warning is gone.
- A read and a supervised setpoint write on one head still behave as validated on 2026-11-22
  (`docs/validation/real-validation-plan.md`): z2m heads over the local broker, danfoss2mqtt heads over the
  gateway bridge.

## 8. Rollback

- Re-enabling the v1.x entry (§4.1) brings its entities back and the Repairs warning returns — a
  clean, reversible step.
- Restarting the “Pont Danfoss local” add-on republishes its retained discovery and recreates its
  entities.
- Entity-id renames (§5) are reversible from the same entity settings.
- The retained-topic purge (§4.3) is the one non-reversible action; the Home Assistant backup from
  §4.0 is the safety net.

---

*Related: `docs/companion-contract.md` (v2 architecture), `docs/validation/real-validation-plan.md`
(coherence validation), `docs/roadmap.md`.*
