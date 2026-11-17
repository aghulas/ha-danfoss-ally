import { describe, expect, it } from "vitest";

import type { HassLike, Room } from "../src/types";
import { fetchInfo, fetchRooms, pickRoom } from "../src/ws";

const ROOMS: Room[] = [
  {
    id: "13000000",
    name: "Salle 1",
    home: "Maison",
    product_id: "synthetic00",
    comfort: 21,
    setback: 14,
    heads: [],
  },
];

function hassWith(
  handler: (msg: Record<string, unknown>) => Promise<unknown>,
): HassLike {
  return { callWS: handler as HassLike["callWS"] };
}

describe("fetchInfo", () => {
  it("renvoie l'info quand la commande existe", async () => {
    const hass = hassWith(async () => ({
      version: "0.1.0",
      local_enabled: false,
      is_admin: true,
    }));
    expect(await fetchInfo(hass)).toEqual({
      version: "0.1.0",
      local_enabled: false,
      is_admin: true,
    });
  });

  it("se dégrade en null quand la commande manque (lot 2 non déployé)", async () => {
    const hass = hassWith(async () => {
      throw new Error("unknown_command");
    });
    expect(await fetchInfo(hass)).toBeNull();
  });
});

describe("fetchRooms", () => {
  it("renvoie la liste des pièces", async () => {
    const hass = hassWith(async () => ({ rooms: ROOMS }));
    expect(await fetchRooms(hass)).toEqual(ROOMS);
  });

  it("se dégrade en liste vide si la commande échoue", async () => {
    const hass = hassWith(async () => {
      throw new Error("unknown_command");
    });
    expect(await fetchRooms(hass)).toEqual([]);
  });

  it("se dégrade en liste vide si la réponse n'a pas de `rooms`", async () => {
    const hass = hassWith(async () => ({}));
    expect(await fetchRooms(hass)).toEqual([]);
  });
});

describe("pickRoom", () => {
  it("retrouve une pièce par son group_id", () => {
    expect(pickRoom(ROOMS, "13000000")?.name).toBe("Salle 1");
  });

  it("renvoie undefined pour un id inconnu ou vide", () => {
    expect(pickRoom(ROOMS, "99999999")).toBeUndefined();
    expect(pickRoom(ROOMS, "")).toBeUndefined();
    expect(pickRoom(ROOMS, undefined)).toBeUndefined();
  });
});
