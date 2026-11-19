import { describe, expect, it } from "vitest";

import { climateLine, headNameHint, isHealthy, isSingleHead, namedAfterHead } from "../src/fleet";
import type { FleetRoom } from "../src/types";

function room(partial: Partial<FleetRoom>): FleetRoom {
  return {
    id: "r",
    name: "Salle 1",
    head_count: 2,
    offline: 0,
    low_battery: 0,
    heating: false,
    window_open: false,
    inconsistent: 0,
    faults: 0,
    ...partial,
  };
}

const single = (partial: Partial<FleetRoom> = {}): FleetRoom =>
  room({
    id: "dev-1",
    kind: "single_head",
    head_count: 1,
    name: "A-1 Bureau",
    name_source: "room",
    room_id: "401",
    head_id: "dev-1",
    head_name: "A-1 Bureau",
    ...partial,
  });

describe("tuiles de pièce", () => {
  it("distingue une pièce d'une tête d'une pièce groupée (et d'un ancien backend)", () => {
    expect(isSingleHead(single())).toBe(true);
    expect(isSingleHead(room({ kind: "group" }))).toBe(false);
    expect(isSingleHead(room({}))).toBe(false);
  });

  it("santé : une tête seule en défaut ou batterie faible n'est pas OK", () => {
    expect(isHealthy(single())).toBe(true);
    expect(isHealthy(single({ faults: 1 }))).toBe(false);
    expect(isHealthy(single({ low_battery: 1 }))).toBe(false);
    expect(isHealthy(single({ offline: 1 }))).toBe(false);
    expect(isHealthy(room({ window_open: true }))).toBe(false);
  });

  it("montre le nom de la tête seulement s'il diffère de celui de la pièce", () => {
    expect(headNameHint(single())).toBeNull();
    expect(headNameHint(single({ head_name: "a-1  bureau" }))).toBeNull();
    expect(headNameHint(single({ head_name: "Tête fenêtre" }))).toBe("Tête fenêtre");
    expect(headNameHint(room({ head_name: "x" }))).toBeNull();
    expect(headNameHint(single({ name_source: "head", head_name: "Autre" }))).toBeNull();
  });

  it("signale une pièce nommée d'après sa tête (repli)", () => {
    expect(namedAfterHead(single({ name_source: "head", room_id: null }))).toBe(true);
    expect(namedAfterHead(single())).toBe(false);
    expect(namedAfterHead(room({ name_source: "head" }))).toBe(false);
  });

  it("ligne de climat : mesure → consigne, dégradée proprement", () => {
    expect(climateLine(room({ temperature: 19.5, setpoint: 20 }))).toBe("19.5 °C → 20 °C");
    expect(climateLine(room({ temperature: null, setpoint: 17 }))).toBe("– → 17 °C");
    expect(climateLine(room({ temperature: 21.25 }))).toBe("21.3 °C");
    expect(climateLine(room({}))).toBeNull();
  });
});
