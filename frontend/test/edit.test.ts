import { describe, expect, it } from "vitest";

import {
  addRange,
  cloneDays,
  copyDay,
  deleteRange,
  firstFreeSlot,
  formatHHMM,
  modifiedDays,
  moveRange,
  rangesEqual,
  resizeRange,
  setRangeTime,
  snapMinutes,
  sortRanges,
} from "../src/edit";
import { DAY_KEYS } from "../src/schedule";
import type { DayKey, TimeRange } from "../src/types";

function r(start: string, end: string): TimeRange {
  return { start, end };
}

function emptyWeek(): Record<DayKey, TimeRange[]> {
  return { mon: [], tue: [], wed: [], thu: [], fri: [], sat: [], sun: [] };
}

describe("formatHHMM / snapMinutes", () => {
  it("formate les minutes en HH:MM", () => {
    expect(formatHHMM(0)).toBe("00:00");
    expect(formatHHMM(510)).toBe("08:30");
    expect(formatHHMM(1439)).toBe("23:59");
  });

  it("arrondit au pas de 5 min et borne dans [0, 23:59]", () => {
    expect(snapMinutes(508)).toBe(510);
    expect(snapMinutes(-10)).toBe(0);
    expect(snapMinutes(99999)).toBe(1439);
    expect(snapMinutes(1439)).toBe(1439); // 23:59 atteignable par arrondi
  });
});

describe("addRange", () => {
  it("place 08:00–17:00 sur un jour vide", () => {
    expect(addRange([])).toEqual([r("08:00", "17:00")]);
  });

  it("place la nouvelle plage dans un créneau libre, trié", () => {
    const next = addRange([r("08:00", "17:00")]);
    expect(next).toHaveLength(2);
    // créneau libre d'une heure avant 08:00 → 00:00–01:00, trié en tête.
    expect(next[0]).toEqual(r("00:00", "01:00"));
  });

  it("ne fait rien si la journée est pleine", () => {
    const full = [r("00:00", "23:59")];
    expect(addRange(full)).toBe(full);
  });
});

describe("firstFreeSlot", () => {
  it("trouve un trou entre deux plages", () => {
    expect(firstFreeSlot([r("00:00", "08:00"), r("12:00", "17:00")], 60)).toEqual({
      start: 480,
      end: 540,
    });
  });
  it("renvoie null si pas de place", () => {
    expect(firstFreeSlot([r("00:00", "23:59")], 60)).toBeNull();
  });
});

describe("deleteRange", () => {
  it("retire la plage visée", () => {
    expect(deleteRange([r("08:00", "12:00"), r("13:00", "17:00")], 0)).toEqual([
      r("13:00", "17:00"),
    ]);
  });
});

describe("moveRange", () => {
  it("déplace en conservant la durée, arrondi au pas de 5", () => {
    expect(moveRange([r("08:00", "12:00")], 0, 33)).toEqual([r("08:35", "12:35")]);
  });
  it("borne à 23:59 sans changer la durée", () => {
    expect(moveRange([r("22:00", "23:00")], 0, 600)).toEqual([r("22:59", "23:59")]);
  });
  it("borne à 00:00", () => {
    expect(moveRange([r("00:30", "01:30")], 0, -120)).toEqual([r("00:00", "01:00")]);
  });
});

describe("resizeRange", () => {
  it("redimensionne par la fin", () => {
    expect(resizeRange([r("08:00", "12:00")], 0, "end", 60)).toEqual([r("08:00", "13:00")]);
  });
  it("redimensionne par le début", () => {
    expect(resizeRange([r("08:00", "12:00")], 0, "start", -60)).toEqual([r("07:00", "12:00")]);
  });
  it("garde une durée minimale d'un pas", () => {
    expect(resizeRange([r("08:00", "08:30")], 0, "end", -120)).toEqual([r("08:00", "08:05")]);
    expect(resizeRange([r("08:00", "08:30")], 0, "start", 120)).toEqual([r("08:25", "08:30")]);
  });
});

describe("setRangeTime", () => {
  it("fixe directement une heure (saisie clavier)", () => {
    expect(setRangeTime([r("08:00", "12:00")], 0, "start", "07:15")).toEqual([
      r("07:15", "12:00"),
    ]);
    expect(setRangeTime([r("08:00", "12:00")], 0, "end", "18:00")).toEqual([
      r("08:00", "18:00"),
    ]);
  });
});

describe("sortRanges", () => {
  it("trie par heure de début", () => {
    expect(sortRanges([r("13:00", "17:00"), r("08:00", "12:00")])).toEqual([
      r("08:00", "12:00"),
      r("13:00", "17:00"),
    ]);
  });
});

describe("rangesEqual", () => {
  it("ignore l'ordre", () => {
    expect(rangesEqual([r("08:00", "12:00"), r("13:00", "17:00")], [r("13:00", "17:00"), r("08:00", "12:00")])).toBe(true);
  });
  it("détecte une différence", () => {
    expect(rangesEqual([r("08:00", "12:00")], [r("08:00", "12:30")])).toBe(false);
    expect(rangesEqual([], [r("08:00", "12:00")])).toBe(false);
  });
});

describe("cloneDays / copyDay", () => {
  it("clone sans partager les références", () => {
    const week = emptyWeek();
    week.mon = [r("08:00", "17:00")];
    const clone = cloneDays(week);
    clone.mon[0].start = "06:00";
    expect(week.mon[0].start).toBe("08:00");
  });

  it("copie un jour vers plusieurs jours (hors lui-même)", () => {
    const week = emptyWeek();
    week.mon = [r("08:00", "17:00")];
    const next = copyDay(week, "mon", ["tue", "wed", "mon"]);
    expect(next.tue).toEqual([r("08:00", "17:00")]);
    expect(next.wed).toEqual([r("08:00", "17:00")]);
    expect(next.tue).not.toBe(next.mon); // clones distincts
    expect(next.thu).toEqual([]);
  });
});

describe("modifiedDays", () => {
  it("ne retient que les jours réellement changés", () => {
    const original = emptyWeek();
    original.mon = [r("08:00", "17:00")];
    original.tue = [r("08:00", "17:00")];
    const draft = cloneDays(original);
    draft.tue = [r("09:00", "17:00")];
    draft.wed = [r("10:00", "11:00")];
    expect(modifiedDays(original, draft, DAY_KEYS)).toEqual(["tue", "wed"]);
  });

  it("liste vide si rien n'a changé", () => {
    const original = emptyWeek();
    original.mon = [r("08:00", "17:00")];
    expect(modifiedDays(original, cloneDays(original), DAY_KEYS)).toEqual([]);
  });
});
