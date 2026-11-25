# Trial A1 — Overnight Preheat Hold and Upstream Sync (2026-11-24 to 2026-11-25)

Record of trial A1 from `docs/preheat.md`. Evaluates whether a preheat write to attribute `0x0025`
through the local tunnel holds overnight against the Tuya cloud sync window (03:48–04:54), and
identifies how the gateway synchronises DP 1 with the cloud.

## Setup

- **Site**: École Sainte-Marie, Fontainebleau.
- **Gateway**: `C-1 Gateway #1` (`bf58f3be913650dc5fgu6o`, firmware protocol 2.3).
- **Target heads**: two isolated heads sharing the same schedule (Monday–Friday except Wednesday
  08:30–17:30 comfort 18 °C / setback 7 °C, Wednesday flat setback 7 °C):
  - **Témoin (Control)**: `C-0 Sanitaires Filles` (`bfdd28b7d83983e2e40e8t`, node `842712fffe86915b`).
  - **Alignée**: `C-0 Sanitaire Garçons` (`bf2e70a50d90f5b14b0pwm`, node `842712fffe86cbac`).
- **Concurrent telemetry**: Sonde Cloud MQTT 24h listening passively on `m1.tuyaeu.com:8883`
  (PID 66939, recording every inbound frame across the 10 gateways).

## Initial state (2026-11-24 ~18:30)

| Head | Tunnel `0x0025` | Mode | Cloud DP 1 (`switch`) |
|---|---|---|---|
| `C-0 Sanitaires Filles` | `true` (bit 1 = 1) | 3 | `true` |
| `C-0 Sanitaire Garçons` | `true` (bit 1 = 1) | 3 | `true` |

## Execution (2026-11-24 19:30–19:57)

1. **`C-0 Sanitaire Garçons` (Aligned candidate)**:
   - Written locally via tunnel: `pre_chauffage = False` (confirmed, status 0).
   - Cloud aligned via cloud MQTT publish `{"1": False}` and `settings.change` block
     `{"1": false, "118": 180, "119": 70, "121": 145}`.
   - Read back: tunnel `pre_chauffage: false`, mode `1`. Cloud DP 1 `false`.

2. **`C-0 Sanitaires Filles` (Control)**:
   - Written locally via tunnel: `pre_chauffage = False` at 19:57:20 (token `y_ZInSmYbMzPTSfGy4_3zw`).
   - Cloud DP 1 was NOT manually written to `false`.

## Upstream frame observation (2026-11-24 19:57:26)

At 19:57:26 UTC (18:57:26Z), exactly 6 seconds after the tunnel write on `C-0 Sanitaires Filles`,
the 24h passive probe recorded the following inbound frame on `smart/mb/in/bf58f3be913650dc5fgu6o`:

```json
{
  "devId": "bfdd28b7d83983e2e40e8t",
  "cid": "842712fffe86915b",
  "dps": {"1": false}
}
```

**Key Discovery**: Writing bit 1 of `0x0025` through the Zigbee tunnel causes the gateway to
autonomously push an upstream report to the Tuya cloud updating DP 1 to `false`. Over the entire
12h overnight period (30 124 frames captured), this was the **single DP 1 frame** received on the
entire 99-head fleet.

## Nocturnal sync & Morning readout (2026-11-25 08:40)

The nocturnal cloud sync executed at **03:53:00** on both heads:

| Head | Tunnel `0x0025` at 08:40 | Mode at 08:40 | Cloud `maj` | Cloud DP 1 at 08:40 | Outcome |
|---|---|---|---|---|---|
| `C-0 Sanitaires Filles` | **`false`** | 1 | 2026-11-25T03:53 | **`false`** | **HELD** — no reversion |
| `C-0 Sanitaire Garçons` | **`false`** | 1 | 2026-11-25T03:53 | **`false`** | **HELD** — no reversion |

Both heads held `pre_chauffage: false` (attribute `0x0025` bit 1 = 0, programming mode = 1).
No reversion occurred.

## Conclusions

1. **Local write durability**: An attribute `0x0025` write via the local tunnel is durable and
   survives the night when the gateway successfully relays the state upstream to the cloud.
2. **Reversion root cause clarified**: The past overnight reversions (where the tunnel reverted to
   `true`) occurred when the cloud's store held `true` and the gateway failed or had not yet
   reported the local change upstream before the nocturnal reconciliation batch.
3. **Automatic parity**: An explicit cloud MQTT publish of DP 1 is not strictly required if the
   gateway is online and relays the tunnel write. However, posting the settings block ensures the
   cloud's REST/app cache cannot diverge.
