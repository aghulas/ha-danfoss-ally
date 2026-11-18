import { describe, expect, it } from "vitest";

import {
  DAY_KEYS,
  dayBars,
  formatReadAt,
  isSetbackOnly,
  parseHHMM,
  summarizeHeads,
} from "../src/schedule";
import type { HeadState } from "../src/types";

describe("DAY_KEYS", () => {
  it("couvre les 7 jours, lundi d'abord", () => {
    expect(DAY_KEYS).toEqual(["mon", "tue", "wed", "thu", "fri", "sat", "sun"]);
  });
});

describe("parseHHMM", () => {
  it("convertit une heure valide en minutes depuis minuit", () => {
    expect(parseHHMM("00:00")).toBe(0);
    expect(parseHHMM("08:30")).toBe(510);
    expect(parseHHMM("23:59")).toBe(1439);
  });

  it("rejette les heures mal formées ou hors bornes", () => {
    expect(parseHHMM("8:30")).toBeNull();
    expect(parseHHMM("24:00")).toBeNull();
    expect(parseHHMM("12:60")).toBeNull();
    expect(parseHHMM("abc")).toBeNull();
    expect(parseHHMM("")).toBeNull();
  });
});

describe("dayBars", () => {
  it("positionne une plage sur la piste 24 h", () => {
    const bars = dayBars([{ start: "06:00", end: "12:00" }]);
    expect(bars).toHaveLength(1);
    expect(bars[0].leftPct).toBeCloseTo(25, 5);
    expect(bars[0].widthPct).toBeCloseTo(25, 5);
    expect(bars[0].start).toBe("06:00");
  });

  it("trie les plages et ignore les plages vides ou inversées", () => {
    const bars = dayBars([
      { start: "13:30", end: "17:30" },
      { start: "08:30", end: "12:00" },
      { start: "10:00", end: "10:00" }, // vide -> ignorée
      { start: "18:00", end: "09:00" }, // inversée -> ignorée
    ]);
    expect(bars.map((b) => b.start)).toEqual(["08:30", "13:30"]);
  });

  it("couvre les bornes 00:00 et 23:59", () => {
    const bars = dayBars([{ start: "00:00", end: "23:59" }]);
    expect(bars[0].leftPct).toBe(0);
    expect(bars[0].widthPct).toBeCloseTo((1439 / 1440) * 100, 5);
  });
});

describe("isSetbackOnly", () => {
  it("est vrai quand aucune plage valide", () => {
    expect(isSetbackOnly([])).toBe(true);
    expect(isSetbackOnly([{ start: "10:00", end: "10:00" }])).toBe(true);
  });
  it("est faux dès qu'une plage valide existe", () => {
    expect(isSetbackOnly([{ start: "08:00", end: "17:00" }])).toBe(false);
  });
});

describe("formatReadAt", () => {
  it("renvoie null pour une valeur absente ou invalide", () => {
    expect(formatReadAt(null, "fr")).toBeNull();
    expect(formatReadAt(undefined, "fr")).toBeNull();
    expect(formatReadAt("pas-une-date", "fr")).toBeNull();
  });
  it("renvoie une chaîne non vide pour un horodatage valide", () => {
    expect(formatReadAt("2026-11-16T15:36:00+01:00", "fr")).toBeTypeOf("string");
    expect((formatReadAt("2026-11-16T15:36:00+01:00", "en") ?? "").length).toBeGreaterThan(0);
  });
});

function head(partial: Partial<HeadState>): HeadState {
  return {
    device_id: "d",
    name: "tête",
    room_id: "13000000",
    online: true,
    mode_displayed: "at_home",
    schedule_active: true,
    preheat: false,
    mounting: false,
    inconsistent: false,
    battery: null,
    valve_opening: null,
    heat_request: null,
    window_open: null,
    window_detection: null,
    child_lock: null,
    faults: [],
    ...partial,
  };
}

describe("summarizeHeads", () => {
  it("compte les états des têtes", () => {
    const s = summarizeHeads([
      head({ online: true, schedule_active: true }),
      head({ online: false, schedule_active: false, inconsistent: true }),
      head({ online: true, schedule_active: null, mounting: true }),
    ]);
    expect(s).toEqual({
      total: 3,
      online: 2,
      scheduleActive: 1,
      inconsistent: 1,
      mounting: 1,
    });
  });
});
