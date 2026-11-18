import { describe, expect, it } from "vitest";

import {
  ADJUSTABLE_MODES,
  canAdjustSetpoint,
  isLowBattery,
  roomNeedsRestore,
  steppedSetpoint,
} from "../src/room";
import type { HeadState, Room } from "../src/types";

function head(partial: Partial<HeadState>): HeadState {
  return {
    device_id: "d",
    name: "tête",
    room_id: "r",
    online: true,
    mode_displayed: "at_home",
    schedule_active: true,
    preheat: false,
    mounting: false,
    inconsistent: false,
    battery: 90,
    valve_opening: 20,
    heat_request: false,
    window_open: false,
    window_detection: true,
    child_lock: false,
    faults: [],
    ...partial,
  };
}

function room(partial: Partial<Room>): Room {
  return {
    id: "r",
    name: "Salle",
    product_id: "03wvrwpv",
    comfort: 21,
    setback: 14,
    heads: [],
    temperature: 20,
    setpoint: 21,
    mode: "at_home",
    heating: true,
    online: true,
    writable: true,
    climate_entity_id: "climate.salle",
    ...partial,
  };
}

describe("isLowBattery", () => {
  it("vrai sur défaut E14/E15", () => {
    expect(isLowBattery(head({ battery: 90, faults: [{ code: "E14" }] }))).toBe(true);
    expect(isLowBattery(head({ battery: 90, faults: [{ code: "E15" }] }))).toBe(true);
  });
  it("vrai sous 10 %", () => {
    expect(isLowBattery(head({ battery: 8, faults: [] }))).toBe(true);
  });
  it("faux sinon (batterie correcte ou inconnue)", () => {
    expect(isLowBattery(head({ battery: 90, faults: [] }))).toBe(false);
    expect(isLowBattery(head({ battery: null, faults: [] }))).toBe(false);
  });
});

describe("canAdjustSetpoint", () => {
  it("vrai : produit vérifié, entité connue, mode confort/réduit, consigne présente", () => {
    expect(canAdjustSetpoint(room({ mode: "at_home" }))).toBe(true);
    expect(canAdjustSetpoint(room({ mode: "leaving_home" }))).toBe(true);
  });
  it("faux hors mode confort/réduit", () => {
    expect(canAdjustSetpoint(room({ mode: "manual" }))).toBe(false);
    expect(canAdjustSetpoint(room({ mode: "holiday" }))).toBe(false);
  });
  it("faux sans entité, non inscriptible, ou sans consigne", () => {
    expect(canAdjustSetpoint(room({ climate_entity_id: null }))).toBe(false);
    expect(canAdjustSetpoint(room({ writable: false }))).toBe(false);
    expect(canAdjustSetpoint(room({ setpoint: null }))).toBe(false);
  });
  it("les deux modes réglables sont confort et réduit", () => {
    expect([...ADJUSTABLE_MODES].sort()).toEqual(["at_home", "leaving_home"]);
  });
});

describe("steppedSetpoint", () => {
  it("ajoute / retire un pas de 0,5 °C, arrondi au pas", () => {
    expect(steppedSetpoint(21, 1)).toBe(21.5);
    expect(steppedSetpoint(21, -1)).toBe(20.5);
    expect(steppedSetpoint(20.5, 1)).toBe(21);
    expect(steppedSetpoint(18, -1)).toBe(17.5);
  });
});

describe("roomNeedsRestore", () => {
  it("vrai si une tête ne suit plus son programme", () => {
    expect(roomNeedsRestore(room({ heads: [head({ schedule_active: false })] }))).toBe(true);
  });
  it("faux sinon (actif ou inconnu)", () => {
    expect(roomNeedsRestore(room({ heads: [head({ schedule_active: true })] }))).toBe(false);
    expect(roomNeedsRestore(room({ heads: [head({ schedule_active: null })] }))).toBe(false);
  });
});
