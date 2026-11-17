import { describe, expect, it } from "vitest";

import {
  MAX_TRANSITIONS_PER_DAY,
  countTransitions,
  validateDay,
  validateDays,
} from "../src/validate";
import type { TimeRange } from "../src/types";

/** Raccourci : plage `HH:MM`–`HH:MM`. */
function r(start: string, end: string): TimeRange {
  return { start, end };
}

describe("MAX_TRANSITIONS_PER_DAY", () => {
  it("vaut 6 (R1)", () => {
    expect(MAX_TRANSITIONS_PER_DAY).toBe(6);
  });
});

describe("validateDay — R1 (cas limites du contrat §2)", () => {
  it("3 plages séparées = 6 transitions, valide", () => {
    const res = validateDay([
      r("06:00", "08:00"),
      r("10:00", "12:00"),
      r("14:00", "16:00"),
    ]);
    expect(res.transitions).toBe(6);
    expect(res.valid).toBe(true);
    expect(res.impliedMidnight).toBe(true);
  });

  it("4 plages séparées = 8 transitions, refusé (too_many_transitions)", () => {
    const res = validateDay([
      r("06:00", "07:00"),
      r("09:00", "10:00"),
      r("12:00", "13:00"),
      r("15:00", "16:00"),
    ]);
    expect(res.transitions).toBe(8);
    expect(res.valid).toBe(false);
    expect(res.errors.map((e) => e.code)).toContain("too_many_transitions");
  });

  it("plage commençant à 00:00 n'ajoute pas de transition de début ni de minuit implicite", () => {
    const res = validateDay([r("00:00", "08:00")]);
    // début 00:00 non compté, fin 08:00 comptée → 1 ; pas de minuit implicite.
    expect(res.transitions).toBe(1);
    expect(res.impliedMidnight).toBe(false);
    expect(res.valid).toBe(true);
  });

  it("plages qui se touchent : la fin partagée n'est pas comptée deux fois", () => {
    const res = validateDay([r("08:00", "12:00"), r("12:00", "17:00")]);
    // débuts 08:00 + 12:00 = 2 ; fins : 12:00 (une plage y commence → ignorée), 17:00 = 1 → total 3.
    expect(res.transitions).toBe(3);
    expect(res.valid).toBe(true);
  });

  it("chevauchement → overlap", () => {
    const res = validateDay([r("08:00", "13:00"), r("12:00", "17:00")]);
    expect(res.valid).toBe(false);
    expect(res.errors.map((e) => e.code)).toContain("overlap");
  });

  it("plage finissant à 23:59 est acceptée", () => {
    const res = validateDay([r("08:00", "23:59")]);
    expect(res.transitions).toBe(2);
    expect(res.valid).toBe(true);
  });

  it("journée entière de confort 00:00–23:59 = 1 transition", () => {
    const res = validateDay([r("00:00", "23:59")]);
    expect(res.transitions).toBe(1);
    expect(res.impliedMidnight).toBe(false);
    expect(res.valid).toBe(true);
  });

  it("jour vide : 0 transition, valide, pas de minuit implicite", () => {
    const res = validateDay([]);
    expect(res.transitions).toBe(0);
    expect(res.impliedMidnight).toBe(false);
    expect(res.valid).toBe(true);
  });
});

describe("validateDay — forme des plages (§5.4)", () => {
  it("heure mal formée → invalid_time", () => {
    expect(validateDay([r("8:30", "17:00")]).errors.map((e) => e.code)).toContain(
      "invalid_time",
    );
    expect(validateDay([r("08:30", "24:00")]).errors.map((e) => e.code)).toContain(
      "invalid_time",
    );
  });

  it("début ≥ fin → empty_or_reversed", () => {
    expect(validateDay([r("17:00", "08:00")]).errors.map((e) => e.code)).toContain(
      "empty_or_reversed",
    );
    expect(validateDay([r("10:00", "10:00")]).errors.map((e) => e.code)).toContain(
      "empty_or_reversed",
    );
  });

  it("reporte le jour dans l'erreur", () => {
    expect(validateDay([r("17:00", "08:00")], "mon").errors[0].day).toBe("mon");
  });

  it("une plage mal formée n'empêche pas de compter les plages valides", () => {
    const res = validateDay([r("06:00", "08:00"), r("bad", "09:00")]);
    expect(res.transitions).toBe(2);
    expect(res.valid).toBe(false);
  });
});

describe("countTransitions", () => {
  it("borne : trois plages séparées plafonnent le décompte à 6", () => {
    const { count } = countTransitions([
      { start: 360, end: 480 },
      { start: 600, end: 720 },
      { start: 840, end: 960 },
    ]);
    expect(count).toBe(6);
  });

  it("minuit implicite seulement si aucune plage ne commence à 00:00", () => {
    expect(countTransitions([{ start: 0, end: 480 }]).impliedMidnight).toBe(false);
    expect(countTransitions([{ start: 480, end: 1020 }]).impliedMidnight).toBe(true);
    expect(countTransitions([]).impliedMidnight).toBe(false);
  });
});

describe("validateDays", () => {
  it("agrège la validité et les transitions par jour", () => {
    const res = validateDays({
      mon: [r("08:00", "17:00")],
      tue: [r("06:00", "07:00"), r("09:00", "10:00"), r("12:00", "13:00"), r("15:00", "16:00")],
      wed: [],
    });
    expect(res.valid).toBe(false);
    expect(res.transitions.mon).toBe(2);
    expect(res.transitions.tue).toBe(8);
    expect(res.transitions.wed).toBe(0);
    expect(res.byDay.tue.valid).toBe(false);
    expect(res.byDay.mon.valid).toBe(true);
  });
});
