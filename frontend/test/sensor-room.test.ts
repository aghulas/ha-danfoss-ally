/**
 * Pièce Danfoss d'un capteur de pièce sur sa page (`sensor_room`) : logique pure et parcours
 * du panneau, sans DOM. Données synthétiques uniquement.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { DanfossAllyPanel, RELAY_WATCH_TRIES } from "../src/panel";
import {
  findSensor,
  sensorPendingConfirmed,
  sensorRoomAction,
  sensorRoomChoices,
} from "../src/sensor-room";
import type { FleetOverview, FleetSensor } from "../src/types";

const sensor = (extra: Partial<FleetSensor> = {}): FleetSensor => ({
  device_id: "s1",
  name: "Sonde test",
  online: true,
  room_id: null,
  temperature: 20.5,
  humidity: 40,
  battery: 90,
  cloud_room: null,
  cloud_rooms: [
    { room_id: "70", name: "Salle A", sensor_id: "s2" },
    { room_id: "71", name: "Salle B", sensor_id: null },
  ],
  room_writable: true,
  ...extra,
});

const overviewWith = (s: FleetSensor): FleetOverview =>
  ({
    homes: [
      {
        gid: "h1",
        name: "École",
        holiday_active: false,
        gateways: [],
        rooms: [],
        relays: [],
        sensors: [s],
      },
    ],
    totals: {},
  }) as unknown as FleetOverview;

function templateText(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (Array.isArray(value)) {
    return value.map(templateText).join("");
  }
  if (typeof value === "object" && "strings" in value && "values" in value) {
    const tpl = value as { strings: readonly string[]; values: unknown[] };
    return tpl.strings
      .map((s, i) => s + (i < tpl.values.length ? templateText(tpl.values[i]) : ""))
      .join("");
  }
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return "";
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("capteur — logique pure", () => {
  it("propose placer (aucune pièce) ou retirer (dans une pièce), jamais en lecture seule", () => {
    expect(sensorRoomAction(sensor(), true, null)).toBe("assign");
    expect(sensorRoomAction(sensor({ cloud_room: { room_id: "71", name: "Salle B" } }), true, null)).toBe(
      "remove",
    );
    expect(sensorRoomAction(sensor(), false, null)).toBeNull();
    expect(sensorRoomAction(sensor(), true, { sensor: "s1", room_id: "71" })).toBeNull();
    expect(sensorRoomAction(sensor({ cloud_room: undefined }), true, null)).toBeNull();
  });

  it("ne propose que les pièces sans autre capteur", () => {
    expect(sensorRoomChoices(sensor()).map((r) => r.room_id)).toEqual(["71"]);
    expect(sensorRoomChoices(sensor({ cloud_rooms: undefined }))).toEqual([]);
  });

  it("confirme seulement quand le pont a relu la pièce demandée", () => {
    const pending = { sensor: "s1", room_id: "71" };
    expect(sensorPendingConfirmed(overviewWith(sensor()), pending)).toBe(false);
    const placed = sensor({ cloud_room: { room_id: "71", name: "Salle B" } });
    expect(sensorPendingConfirmed(overviewWith(placed), pending)).toBe(true);
    expect(sensorPendingConfirmed(overviewWith(placed), { sensor: "s1", room_id: null })).toBe(false);
    expect(sensorPendingConfirmed(overviewWith(sensor()), { sensor: "s1", room_id: null })).toBe(true);
    expect(sensorPendingConfirmed(overviewWith(sensor({ cloud_room: undefined })), pending)).toBe(false);
    expect(sensorPendingConfirmed(null, pending)).toBe(false);
    expect(findSensor(overviewWith(sensor()), "ghost")).toBeUndefined();
  });
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Internals = any;

function panel(s: FleetSensor, callWS: (msg: Record<string, unknown>) => Promise<unknown>, admin = true) {
  const el: Internals = new DanfossAllyPanel();
  el.hass = { callWS, language: "en", user: { is_admin: admin } };
  el._overview = overviewWith(s);
  el._sleep = async () => {};
  return el;
}

describe("capteur — page du panneau", () => {
  it("rien sans pièce Danfoss publiée (backend plus ancien)", () => {
    const el = panel(sensor({ cloud_room: undefined }), async () => ({}));
    expect(el._renderSensorRoom(el._overview.homes[0].sensors[0])).toBe(
      el._renderSensorRoom(sensor({ cloud_room: undefined })),
    );
    expect(templateText(el._renderSensorRoom(sensor({ cloud_room: undefined })))).toBe("");
  });

  it("lecture seule sans annonce du pont ou sans droits d'administrateur", () => {
    for (const el of [
      panel(sensor({ room_writable: false }), async () => ({})),
      panel(sensor(), async () => ({}), false),
    ]) {
      const text = templateText(el._renderSensorRoom(el._overview.homes[0].sensors[0]));
      expect(text).toContain("Read-only");
      expect(text).toContain("In no room");
      expect(text).not.toContain("relay-room-action");
    }
  });

  it("avertit de l'effet sur la régulation et propose les pièces libres", () => {
    const el = panel(sensor(), async () => ({}));
    const text = templateText(el._renderSensorRoom(el._overview.homes[0].sensors[0]));
    expect(text).toContain("regulate on it");
    expect(text).toContain("Salle B");
    expect(text).not.toContain("Salle A");
    expect(text).toContain("Put in this room");
  });

  it("propose le retrait quand le capteur est dans une pièce", () => {
    const el = panel(sensor({ cloud_room: { room_id: "71", name: "Salle B" } }), async () => ({}));
    const text = templateText(el._renderSensorRoom(el._overview.homes[0].sensors[0]));
    expect(text).toContain("Salle B");
    expect(text).toContain("Take out of this room");
    expect(text).not.toContain("Put in this room");
  });

  it("signale qu'aucune pièce n'est libre", () => {
    const el = panel(sensor({ cloud_rooms: [{ room_id: "70", name: "Salle A", sensor_id: "s2" }] }), async () => ({}));
    const text = templateText(el._renderSensorRoom(el._overview.homes[0].sensors[0]));
    expect(text).toContain("already holds a sensor");
  });

  it("envoie après confirmation puis attend la relecture du pont", async () => {
    const calls: Record<string, unknown>[] = [];
    let reads = 0;
    const el = panel(sensor(), async (msg) => {
      calls.push(msg);
      if (msg.type === "danfoss_ally_cloud/overview") {
        reads += 1;
        return overviewWith(
          reads >= 2 ? sensor({ cloud_room: { room_id: "71", name: "Salle B" } }) : sensor(),
        );
      }
      return { status: "sent" };
    });
    let question = "";
    vi.stubGlobal("confirm", (q: string) => {
      question = q;
      return true;
    });
    el._sensorChoice = "71";
    await el._changeSensorRoom(el._overview.homes[0].sensors[0], "71");
    expect(question).toContain("Salle B");
    expect(calls[0]).toEqual({
      type: "danfoss_ally_cloud/sensor/set_room",
      sensor: "s1",
      room_id: "71",
    });
    expect(reads).toBe(2);
    expect(el._sensorPending).toBeNull();
    expect(el._sensorNote).toBeNull();
    expect(el._sensorChoice).toBe("");
    expect(el._overview.homes[0].sensors[0].cloud_room.room_id).toBe("71");
  });

  it("retire avec room_id null", async () => {
    const calls: Record<string, unknown>[] = [];
    const placed = sensor({ cloud_room: { room_id: "71", name: "Salle B" } });
    const el = panel(placed, async (msg) => {
      calls.push(msg);
      return msg.type === "danfoss_ally_cloud/overview" ? overviewWith(sensor()) : { status: "sent" };
    });
    vi.stubGlobal("confirm", () => true);
    await el._changeSensorRoom(placed, null);
    expect(calls[0]).toMatchObject({ room_id: null });
    expect(el._overview.homes[0].sensors[0].cloud_room).toBeNull();
  });

  it("n'envoie rien sans confirmation, sans choix, ni en lecture seule", async () => {
    const callWS = vi.fn(async () => ({}));
    const el = panel(sensor(), callWS);
    vi.stubGlobal("confirm", () => false);
    await el._changeSensorRoom(el._overview.homes[0].sensors[0], "71");
    vi.stubGlobal("confirm", () => true);
    await el._changeSensorRoom(el._overview.homes[0].sensors[0], "");
    await el._changeSensorRoom(sensor({ room_writable: false }), "71");
    expect(callWS).not.toHaveBeenCalled();
  });

  it("affiche le refus du backend sans rien supposer", async () => {
    const el = panel(sensor(), async () => {
      throw { code: "room_has_sensor", message: "taken" };
    });
    vi.stubGlobal("confirm", () => true);
    await el._changeSensorRoom(el._overview.homes[0].sensors[0], "71");
    expect(el._sensorNote).toContain("taken");
    expect(el._overview.homes[0].sensors[0].cloud_room).toBeNull();
  });

  it("signale un délai dépassé quand le pont ne confirme pas", async () => {
    let reads = 0;
    const el = panel(sensor(), async (msg) => {
      if (msg.type === "danfoss_ally_cloud/overview") {
        reads += 1;
        return overviewWith(sensor());
      }
      return { status: "sent" };
    });
    vi.stubGlobal("confirm", () => true);
    await el._changeSensorRoom(el._overview.homes[0].sensors[0], "71");
    expect(reads).toBe(RELAY_WATCH_TRIES);
    expect(el._sensorNote).toContain("not confirmed");
    expect(el._sensorPending).toBeNull();
  });
});
