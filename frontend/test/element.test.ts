/** Page élément du panneau (contrat §8.2) : logique pure. Données synthétiques. */
import { describe, expect, it } from "vitest";

import {
  deviceEntities,
  entityCount,
  findElement,
  haDeviceId,
  roomDeviceIdent,
  roomHeads,
  roomSensors,
  unplacedSensors,
} from "../src/element";
import { elementPath, parsePath } from "../src/nav";
import type { FleetOverview, FleetRoom, HassLike, HeadState, Room } from "../src/types";

const head = (id: string, name: string, online = true): HeadState => ({
  device_id: id,
  name,
  room_id: "g1",
  online,
  mode_displayed: "at_home",
  schedule_active: true,
  preheat: null,
  mounting: false,
  inconsistent: false,
  battery: 80,
  valve_opening: 20,
  heat_request: false,
  window_open: false,
  window_detection: null,
  child_lock: null,
  faults: [],
});

const fleetRoom = (id: string, name: string, extra: Partial<FleetRoom> = {}): FleetRoom => ({
  id,
  name,
  kind: "group",
  head_count: 2,
  offline: 0,
  low_battery: 0,
  heating: false,
  window_open: false,
  inconsistent: 0,
  faults: 0,
  ...extra,
});

const overview = {
  homes: [
    {
      gid: "h1",
      name: "École",
      holiday_active: false,
      gateways: [{ device_id: "gw1", name: "Passerelle", online: true, head_count: 3, relay_count: 1 }],
      relays: [{ device_id: "r1", name: "Relais", on: true, online: false, linked_rooms: 0 }],
      rooms: [
        fleetRoom("g1", "Salle 1"),
        fleetRoom("h9", "Bureau", {
          kind: "single_head",
          head_id: "h9",
          head_name: "Tête bureau",
          head_count: 1,
          online: false,
        }),
      ],
    },
  ],
  totals: {},
} as unknown as FleetOverview;

const rooms = [
  { id: "g1", name: "Salle 1", heads: [head("a", "Salle 1 #1"), head("b", "Salle 1 #2", false)] },
] as unknown as Room[];

describe("adresses des éléments", () => {
  it("`/device/<id>` et `/room/<id>/device/<id>` mènent à la page élément", () => {
    expect(parsePath(elementPath("a b"))).toEqual({ view: "element", deviceId: "a b" });
    expect(parsePath(elementPath("a", "g/1"))).toEqual({
      view: "element",
      deviceId: "a",
      roomId: "g/1",
    });
    expect(parsePath("/device")).toEqual({ view: "fleet" });
    expect(parsePath("/room/g1/device")).toEqual({ view: "fleet" });
    expect(parsePath("/room/g1/other/a")).toEqual({ view: "fleet" });
  });
});

describe("éléments d'une pièce", () => {
  it("pièce groupée : les têtes de `rooms`", () => {
    expect(roomHeads(overview.homes[0].rooms[0], rooms).map((h) => [h.id, h.online])).toEqual([
      ["a", true],
      ["b", false],
    ]);
    expect(roomHeads(overview.homes[0].rooms[0], [])).toEqual([]);
  });

  it("pièce d'une seule tête : la tête de la vue d'ensemble, sans état détaillé", () => {
    expect(roomHeads(overview.homes[0].rooms[1], rooms)).toEqual([
      { id: "h9", name: "Tête bureau", online: false, head: null },
    ]);
  });

  it("retrouve une tête, un relais, une passerelle, avec leur maison", () => {
    const h = findElement(overview, rooms, "b");
    expect(h?.kind === "head" && h.room.name).toBe("Salle 1");
    expect(findElement(overview, rooms, "h9")?.kind).toBe("head");
    const r = findElement(overview, rooms, "r1");
    expect(r?.kind).toBe("relay");
    expect(r?.online).toBe(false);
    expect(findElement(overview, rooms, "gw1")?.home.name).toBe("École");
    expect(findElement(overview, rooms, "nope")).toBeNull();
    expect(findElement(null, rooms, "a")).toBeNull();
  });
});

describe("capteurs de pièce", () => {
  const sensor = (id: string, room_id: string | null) => ({
    device_id: id,
    name: `Capteur ${id}`,
    online: true,
    room_id,
    temperature: 19.5,
    humidity: 48,
    battery: 80,
  });
  const withSensors = {
    ...overview,
    homes: [{ ...overview.homes[0], sensors: [sensor("s1", "g1"), sensor("s2", null), sensor("s3", "gone")] }],
  } as unknown as FleetOverview;
  const home = withSensors.homes[0];

  it("la pièce liste ses capteurs ; le bâtiment ceux sans pièce connue", () => {
    expect(roomSensors(home, "g1").map((s) => s.device_id)).toEqual(["s1"]);
    expect(unplacedSensors(home).map((s) => s.device_id)).toEqual(["s2", "s3"]);
    // Backend plus ancien : pas de champ `sensors`.
    expect(roomSensors(overview.homes[0], "g1")).toEqual([]);
    expect(unplacedSensors(overview.homes[0])).toEqual([]);
  });

  it("retrouve un capteur, avec sa pièce quand elle est connue", () => {
    const s1 = findElement(withSensors, rooms, "s1");
    expect(s1?.kind === "sensor" && s1.room?.name).toBe("Salle 1");
    const s2 = findElement(withSensors, rooms, "s2");
    expect(s2?.kind === "sensor" && s2.room).toBeNull();
  });
});

describe("entités de l'appareil HA", () => {
  const entity = (id: string, device: string, category: string | null, hidden = false) => ({
    entity_id: id,
    device_id: device,
    entity_category: category,
    hidden,
  });
  const st = (id: string, state: string, name: string, unit?: string) => ({
    entity_id: id,
    state,
    attributes: { friendly_name: name, ...(unit ? { unit_of_measurement: unit } : {}) },
  });
  const hass = {
    callWS: async () => ({}),
    devices: {
      d1: { id: "d1", name: "Salle 1 #1", identifiers: [["danfoss_ally_cloud", "a"]] },
      d2: { id: "d2", name: "Autre", identifiers: [["zha", "a"]] },
      d3: { id: "d3", name: "Salle 1", identifiers: [["danfoss_ally_cloud", "group_g1"]] },
    },
    entities: {
      "sensor.bat": entity("sensor.bat", "d1", "diagnostic"),
      "number.off": entity("number.off", "d1", "config"),
      "switch.pre": entity("switch.pre", "d1", "config"),
      "climate.h": entity("climate.h", "d1", null),
      "sensor.hid": entity("sensor.hid", "d1", null, true),
      "sensor.dis": entity("sensor.dis", "d1", null),
      "sensor.else": entity("sensor.else", "d2", null),
    },
    states: {
      "sensor.bat": st("sensor.bat", "86", "Salle 1 #1 Batterie", "%"),
      "number.off": st("number.off", "0.5", "Salle 1 #1 Décalage", "°C"),
      "switch.pre": st("switch.pre", "unavailable", "Salle 1 #1 Préchauffe"),
      "climate.h": st("climate.h", "heat", "Salle 1 #1"),
      "sensor.hid": st("sensor.hid", "1", "Caché"),
      "sensor.else": st("sensor.else", "1", "Ailleurs"),
    },
  } as unknown as HassLike;

  it("relie un élément à son appareil HA par l'identifiant de cette intégration", () => {
    expect(haDeviceId(hass, "a")).toBe("d1"); // pas d2 : autre domaine
    expect(haDeviceId(hass, roomDeviceIdent("g1"))).toBe("d3");
    expect(haDeviceId(hass, "zzz")).toBeNull();
    expect(haDeviceId(undefined, "a")).toBeNull();
  });

  it("groupe par catégorie, écarte masquées et désactivées, raccourcit les noms", () => {
    const groups = deviceEntities(hass, "d1");
    expect(groups.controls.map((r) => r.name)).toEqual(["Salle 1 #1"]);
    expect(groups.config.map((r) => r.name)).toEqual(["Décalage", "Préchauffe"]);
    expect(groups.diagnostic).toEqual([
      { entity_id: "sensor.bat", name: "Batterie", state: "86", unit: "%", available: true },
    ]);
    expect(entityCount(groups)).toBe(4);
  });

  it("une entité indisponible reste listée, marquée indisponible", () => {
    const pre = deviceEntities(hass, "d1").config.find((r) => r.entity_id === "switch.pre");
    expect(pre?.available).toBe(false);
  });

  it("appareil inconnu : aucun groupe rempli", () => {
    expect(entityCount(deviceEntities(hass, "nope"))).toBe(0);
    expect(entityCount(deviceEntities(undefined, "d1"))).toBe(0);
  });
});
