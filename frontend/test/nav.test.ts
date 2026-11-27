/** Navigation du panneau (contrat §8.2) : logique pure. Données synthétiques. */
import { describe, expect, it } from "vitest";

import { FLEET_PATH, findRoom, parsePath, roomPath } from "../src/nav";
import type { FleetOverview, FleetRoom } from "../src/types";

const room = (id: string, name: string): FleetRoom => ({
  id,
  name,
  head_count: 2,
  offline: 0,
  low_battery: 0,
  heating: false,
  window_open: false,
  inconsistent: 0,
  faults: 0,
});

const overview: FleetOverview = {
  homes: [
    { gid: "h1", name: "École", holiday_active: false, gateways: [], relays: [], rooms: [room("g1", "Salle 1")] },
    { gid: "h2", name: "Annexe", holiday_active: false, gateways: [], relays: [], rooms: [room("g2", "Hall")] },
  ],
  totals: {
    homes: 2,
    gateways: 0,
    rooms: 2,
    heads: 4,
    offline: 0,
    low_battery: 0,
    heating: 0,
    faults: 0,
    relays_on: 0,
  },
};

describe("navigation du panneau", () => {
  it("le chemin vide, `/` ou inconnu est le bâtiment", () => {
    for (const path of [undefined, null, "", "/", "/nope", "/room", "/room/", "/room/a/b"]) {
      expect(parsePath(path)).toEqual({ view: "fleet" });
    }
  });

  it("`/room/<id>` est une pièce, identifiant décodé", () => {
    expect(parsePath("/room/g1")).toEqual({ view: "room", roomId: "g1" });
    expect(parsePath("/room/g1/")).toEqual({ view: "room", roomId: "g1" });
    expect(parsePath(roomPath("a/b c"))).toEqual({ view: "room", roomId: "a/b c" });
  });

  it("un encodage invalide retombe sur le bâtiment", () => {
    expect(parsePath("/room/%E0%A4%A")).toEqual({ view: "fleet" });
  });

  it("le chemin du bâtiment est vide et celui d'une pièce est encodé", () => {
    expect(FLEET_PATH).toBe("");
    expect(roomPath("a/b")).toBe("/room/a%2Fb");
  });

  it("retrouve une pièce et sa maison dans la vue d'ensemble", () => {
    const found = findRoom(overview, "g2");
    expect(found?.home.name).toBe("Annexe");
    expect(found?.room.name).toBe("Hall");
    expect(findRoom(overview, "gone")).toBeNull();
    expect(findRoom(null, "g1")).toBeNull();
  });
});
