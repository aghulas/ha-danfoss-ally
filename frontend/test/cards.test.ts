/**
 * Tests de comportement des deux cartes (revue de la PR 112), sans DOM : les
 * éléments sont instanciés mais jamais connectés (Lit ne rend donc rien), et on
 * pilote leurs méthodes comme le feraient les gestes de l'utilisateur.
 * Données synthétiques uniquement.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { DanfossAllyRoomCard } from "../src/room-card";
import { DanfossAllyScheduleCard } from "../src/schedule-card";
import type { DayKey, HassLike, Schedule, TimeRange, WriteJob } from "../src/types";

const r = (start: string, end: string): TimeRange => ({ start, end });

function schedule(roomId: string, mon: TimeRange[], readAt = "2026-01-05T08:00:00Z"): Schedule {
  return {
    target: { type: "room", id: roomId },
    name: `Salle ${roomId}`,
    comfort: 21,
    setback: 16,
    days: { mon, tue: [], wed: [], thu: [], fri: [], sat: [], sun: [] },
    max_transitions_per_day: 6,
    source: "cloud",
    read_at: readAt,
  };
}

const job = (roomId: string, status: WriteJob["status"] = "sent"): WriteJob => ({
  job_id: "job-1",
  kind: "set_schedule",
  target: { type: "room", id: roomId },
  status,
  created_at: "2026-01-05T08:01:00Z",
  heads: [],
});

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

type Handler = (msg: Record<string, unknown>) => unknown;

/** `hass` synthétique : une réponse par type de commande, journal des appels. */
function fakeHass(
  handlers: Record<string, Handler>,
  isAdmin = true,
): { hass: HassLike; calls: Record<string, unknown>[] } {
  const calls: Record<string, unknown>[] = [];
  const hass: HassLike = {
    callWS: (async (msg: Record<string, unknown>) => {
      calls.push(msg);
      const type = String(msg.type).replace("danfoss_ally_cloud/", "");
      if (type === "info") {
        return { version: "0.0.0", local_enabled: false, is_admin: isAdmin };
      }
      const handler = handlers[type];
      if (!handler) {
        throw new Error(`unknown_command ${type}`);
      }
      return handler(msg);
    }) as HassLike["callWS"],
  };
  return { hass, calls };
}

// Accès aux membres privés : ces tests jouent le rôle des gestes utilisateur.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Internals = any;

async function loadedScheduleCard(
  hass: HassLike,
  roomId = "13000000",
  embedded = false,
): Promise<Internals> {
  const el = new DanfossAllyScheduleCard() as Internals;
  el.embedded = embedded;
  el.setConfig({ room_id: roomId });
  el.hass = hass;
  el._loaded = true; // ce que fait `updated()` au premier `hass`
  await el._load();
  return el;
}

/** Aplatit un `TemplateResult` Lit en texte (statique + valeurs), sans DOM. */
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

const flush = async (): Promise<void> => {
  for (let i = 0; i < 5; i += 1) {
    await Promise.resolve();
  }
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("carte programme — enregistrement", () => {
  it("n'affiche après enregistrement que les jours réellement envoyés", async () => {
    const pending = deferred<WriteJob>();
    const { hass, calls } = fakeHass({
      rooms: () => ({ rooms: [] }),
      "schedule/get": () => schedule("13000000", [r("08:00", "12:00")]),
      "schedule/validate": () => ({ valid: true, errors: [], transitions: {} }),
      "schedule/set": () => pending.promise,
    });
    const el = await loadedScheduleCard(hass);
    el._beginEdit();
    el._setDay("mon", [r("09:00", "12:00")]);
    const saving = el._save();
    // Geste tardif pendant l'envoi : il n'est PAS parti, il ne doit donc ni
    // modifier le brouillon ni apparaître comme programme enregistré.
    el._setDay("mon", [r("10:00", "11:00")]);
    el._setDay("tue", [r("06:00", "07:00")]);
    pending.resolve(job("13000000"));
    await saving;

    const sent = calls.find((c) => c.type === "danfoss_ally_cloud/schedule/set");
    expect(sent?.days).toEqual({ mon: [r("09:00", "12:00")] });
    expect(el._error).toBeNull();
    expect(el._schedule.days.mon).toEqual([r("09:00", "12:00")]);
    expect(el._schedule.days.tue).toEqual([]);
  });

  it("un changement de pièce pendant l'envoi ne pollue pas la nouvelle pièce", async () => {
    const pending = deferred<WriteJob>();
    const { hass } = fakeHass({
      rooms: () => ({ rooms: [] }),
      "schedule/get": (msg) => {
        const id = (msg.target as { id: string }).id;
        return schedule(id, id === "13000000" ? [r("08:00", "12:00")] : [r("14:00", "18:00")]);
      },
      "schedule/validate": () => ({ valid: true, errors: [], transitions: {} }),
      "schedule/set": () => pending.promise,
    });
    const el = await loadedScheduleCard(hass);
    el._beginEdit();
    el._setDay("mon", [r("09:00", "12:00")]);
    const saving = el._save();
    el.setConfig({ room_id: "13000001" });
    pending.resolve(job("13000000"));
    await saving;
    await flush();

    // L'écriture de la pièce A a réussi : pas d'erreur fantôme sur la pièce B,
    // ni lot ni programme de A affichés sous B.
    expect(el._error).toBeNull();
    expect(el._job).toBeNull();
    expect(el._saving).toBe(false);
    expect(el._schedule.days.mon).toEqual([r("14:00", "18:00")]);
  });

  it("un double clic n'envoie qu'une écriture", async () => {
    const pending = deferred<WriteJob>();
    const { hass, calls } = fakeHass({
      rooms: () => ({ rooms: [] }),
      "schedule/get": () => schedule("13000000", [r("08:00", "12:00")]),
      "schedule/validate": () => ({ valid: true, errors: [], transitions: {} }),
      "schedule/set": () => pending.promise,
    });
    const el = await loadedScheduleCard(hass);
    el._beginEdit();
    el._setDay("mon", [r("09:00", "12:00")]);
    const first = el._save();
    const second = el._save();
    pending.resolve(job("13000000"));
    await Promise.all([first, second]);
    expect(calls.filter((c) => c.type === "danfoss_ally_cloud/schedule/set")).toHaveLength(1);
  });

  it("un jour invalide (R1 : 4 plages séparées) n'est jamais envoyé", async () => {
    const { hass, calls } = fakeHass({
      rooms: () => ({ rooms: [] }),
      "schedule/get": () => schedule("13000000", []),
      "schedule/validate": () => ({ valid: true, errors: [], transitions: {} }),
      "schedule/set": () => job("13000000"),
    });
    const el = await loadedScheduleCard(hass);
    el._beginEdit();
    el._setDay("mon", [
      r("01:00", "02:00"),
      r("03:00", "04:00"),
      r("05:00", "06:00"),
      r("07:00", "08:00"),
    ]);
    await el._save();
    expect(calls.some((c) => c.type === "danfoss_ally_cloud/schedule/set")).toBe(false);
    expect(el._editing).toBe(true);
  });

  it("un refus du serveur reste affiché comme un échec, sans état optimiste", async () => {
    const { hass } = fakeHass({
      rooms: () => ({ rooms: [] }),
      "schedule/get": () => schedule("13000000", [r("08:00", "12:00")]),
      "schedule/validate": () => ({ valid: true, errors: [], transitions: {} }),
      "schedule/set": () => {
        throw { code: "cloud_refused", message: "refus" };
      },
    });
    const el = await loadedScheduleCard(hass);
    el._beginEdit();
    el._setDay("mon", [r("09:00", "12:00")]);
    await el._save();
    expect(el._error).not.toBeNull();
    expect(el._editing).toBe(true);
    expect(el._job).toBeNull();
    expect(el._schedule.days.mon).toEqual([r("08:00", "12:00")]);
  });
});

describe("carte programme — glisser-déposer", () => {
  function dragSetup(el: Internals): Map<string, (ev: unknown) => void> {
    const handlers = new Map<string, (ev: unknown) => void>();
    vi.stubGlobal("addEventListener", (type: string, fn: (ev: unknown) => void) => {
      handlers.set(type, fn);
    });
    vi.stubGlobal("removeEventListener", (type: string) => {
      handlers.delete(type);
    });
    el._beginEdit();
    return handlers;
  }

  const pointerDown = (x: number, pointerId: number): unknown => ({
    clientX: x,
    pointerId,
    preventDefault: () => {},
    stopPropagation: () => {},
    currentTarget: {
      closest: () => ({ getBoundingClientRect: () => ({ width: 1440 }) }),
      setPointerCapture: () => {},
    },
  });

  async function card(): Promise<Internals> {
    const { hass } = fakeHass({
      rooms: () => ({ rooms: [] }),
      "schedule/get": () => schedule("13000000", [r("08:00", "12:00"), r("14:00", "18:00")]),
      "schedule/validate": () => ({ valid: true, errors: [], transitions: {} }),
    });
    return loadedScheduleCard(hass);
  }

  it("un glisser annulé (pointercancel) rend la plage telle qu'avant le geste", async () => {
    const el = await card();
    const handlers = dragSetup(el);
    el._onBarPointerDown("mon", 0, "move", pointerDown(100, 1));
    handlers.get("pointermove")?.({ clientX: 160, pointerId: 1 });
    expect(el._draft.mon[0]).toEqual(r("09:00", "13:00"));
    expect(handlers.has("pointercancel")).toBe(true);
    handlers.get("pointercancel")?.({ pointerId: 1 });
    expect(el._draft.mon).toEqual([r("08:00", "12:00"), r("14:00", "18:00")]);
    expect(el._modified).toEqual([]);
    expect(handlers.has("pointermove")).toBe(false);
  });

  it("un glisser terminé (pointerup) garde la plage déplacée", async () => {
    const el = await card();
    const handlers = dragSetup(el);
    el._onBarPointerDown("mon", 0, "move", pointerDown(100, 1));
    handlers.get("pointermove")?.({ clientX: 160, pointerId: 1 });
    handlers.get("pointerup")?.({ pointerId: 1 });
    expect(el._draft.mon[0]).toEqual(r("09:00", "13:00"));
    expect(el._modified).toEqual(["mon"]);
  });

  it("la barre saisie déplace SA plage, même si le brouillon n'est pas trié", async () => {
    const el = await card();
    const handlers = dragSetup(el);
    // Saisie clavier : la première plage passe après la seconde, et une plage
    // inversée (non dessinée) s'intercale. Brouillon non trié, comme en vrai.
    el._draft = { ...el._draft, mon: [r("20:00", "22:00"), r("13:00", "12:00"), r("14:00", "18:00")] };
    const bars: { strings: readonly string[]; values: unknown[] }[] = [];
    const walk = (value: unknown): void => {
      if (Array.isArray(value)) {
        value.forEach(walk);
      } else if (value && typeof value === "object" && "strings" in value) {
        const tpl = value as { strings: readonly string[]; values: unknown[] };
        if (tpl.strings[0].includes('class="bar edit"')) {
          bars.push(tpl);
        }
        tpl.values.forEach(walk);
      }
    };
    walk(el._renderEditDay("mon"));
    expect(bars).toHaveLength(2);
    // Première barre dessinée = 14:00–18:00 ; sa poignée centrale est le 2e écouteur.
    const grips = bars[0].values.filter((v) => typeof v === "function") as ((ev: unknown) => void)[];
    grips[1](pointerDown(100, 1));
    handlers.get("pointermove")?.({ clientX: 160, pointerId: 1 });
    handlers.get("pointerup")?.({ pointerId: 1 });
    expect(el._draft.mon).toContainEqual(r("15:00", "19:00"));
    expect(el._draft.mon).toContainEqual(r("20:00", "22:00"));
    expect(el._draft.mon).toContainEqual(r("13:00", "12:00"));
  });

  it("un autre doigt qui se lève ne termine pas le glisser en cours", async () => {
    const el = await card();
    const handlers = dragSetup(el);
    el._onBarPointerDown("mon", 0, "move", pointerDown(100, 1));
    handlers.get("pointerup")?.({ pointerId: 2 });
    handlers.get("pointermove")?.({ clientX: 400, pointerId: 2 });
    expect(el._draft.mon[0]).toEqual(r("08:00", "12:00"));
    handlers.get("pointermove")?.({ clientX: 160, pointerId: 1 });
    expect(el._draft.mon[0]).toEqual(r("09:00", "13:00"));
  });
});

describe("carte programme — validation serveur", () => {
  it("une réponse arrivée après la sortie d'édition est ignorée", async () => {
    const pending = deferred<unknown>();
    const { hass } = fakeHass({
      rooms: () => ({ rooms: [] }),
      "schedule/get": () => schedule("13000000", [r("08:00", "12:00")]),
      "schedule/validate": () => pending.promise,
    });
    const el = await loadedScheduleCard(hass);
    el._beginEdit();
    el._setDay("mon", [r("09:00", "12:00")]);
    const running = el._runServerValidate();
    el._leaveEdit(false);
    pending.resolve({
      valid: false,
      errors: [{ code: "overlap", message: "x", day: "mon" }],
      transitions: {},
    });
    await running;
    expect(el._serverValidation).toBeNull();
  });

  it("une réponse en retard ne remplace pas une réponse plus récente", async () => {
    const first = deferred<unknown>();
    const second = deferred<unknown>();
    const queue = [first, second];
    const { hass } = fakeHass({
      rooms: () => ({ rooms: [] }),
      "schedule/get": () => schedule("13000000", [r("08:00", "12:00")]),
      "schedule/validate": () => queue.shift()?.promise,
    });
    const el = await loadedScheduleCard(hass);
    el._beginEdit();
    el._setDay("mon", [r("09:00", "08:00")]);
    const a = el._runServerValidate();
    el._setDay("mon", [r("09:00", "12:00")]);
    const b = el._runServerValidate();
    second.resolve({ valid: true, errors: [], transitions: { mon: 2 } });
    await b;
    first.resolve({
      valid: false,
      errors: [{ code: "empty_or_reversed", message: "x", day: "mon" }],
      transitions: {},
    });
    await a;
    expect(el._serverValidation.valid).toBe(true);
  });
});

describe("carte programme — changement de pièce", () => {
  it("ne garde ni le programme ni le lot de l'ancienne pièce", async () => {
    const next = deferred<Schedule>();
    const { hass } = fakeHass({
      rooms: () => ({ rooms: [] }),
      "schedule/get": (msg) =>
        (msg.target as { id: string }).id === "13000000"
          ? schedule("13000000", [r("08:00", "12:00")])
          : next.promise,
    });
    const el = await loadedScheduleCard(hass);
    el._job = job("13000000", "applied");
    el.setConfig({ room_id: "13000001" });
    // Tant que la pièce B n'est pas lue, rien de la pièce A n'est montré ni éditable.
    expect(el._schedule).toBeNull();
    expect(el._job).toBeNull();
    el._beginEdit();
    expect(el._editing).toBe(false);
    next.resolve(schedule("13000001", [r("14:00", "18:00")]));
    await flush();
    expect(el._schedule.target.id).toBe("13000001");
  });

  it("une lecture en retard de l'ancienne pièce ne remplace pas la nouvelle", async () => {
    const slowA = deferred<Schedule>();
    const { hass } = fakeHass({
      rooms: () => ({ rooms: [] }),
      "schedule/get": (msg) =>
        (msg.target as { id: string }).id === "13000000"
          ? slowA.promise
          : schedule("13000001", [r("14:00", "18:00")]),
    });
    const el = new DanfossAllyScheduleCard() as Internals;
    el.setConfig({ room_id: "13000000" });
    el.hass = hass;
    el._loaded = true;
    const loadingA = el._load();
    el.setConfig({ room_id: "13000001" });
    await flush();
    slowA.resolve(schedule("13000000", [r("08:00", "12:00")]));
    await loadingA;
    expect(el._schedule.target.id).toBe("13000001");
  });
});

describe("carte programme — mode imbriqué", () => {
  it("garde un bouton de sortie quand le programme est indisponible", async () => {
    const { hass } = fakeHass({
      "schedule/get": () => {
        throw new Error("cloud_refused");
      },
    });
    const el = await loadedScheduleCard(hass, "13000000", true);
    expect(el._editing).toBe(false);
    const text = templateText(el.render());
    expect(text).toContain("Cancel");
    let closed = 0;
    el.addEventListener("schedule-edit-close", () => {
      closed += 1;
    });
    el._cancelEdit();
    expect(closed).toBe(1);
  });

  it("à l'annulation, ne renvoie pas de programme au parent ; à l'enregistrement, si", async () => {
    const { hass } = fakeHass({
      "schedule/get": () => schedule("13000000", [r("08:00", "12:00")]),
      "schedule/validate": () => ({ valid: true, errors: [], transitions: {} }),
      "schedule/set": () => job("13000000"),
    });
    const details: { schedule: Schedule | null; job: WriteJob | null }[] = [];
    const el = await loadedScheduleCard(hass, "13000000", true);
    el.addEventListener("schedule-edit-close", (ev: Event) => {
      details.push((ev as CustomEvent).detail);
    });
    expect(el._editing).toBe(true);
    el._cancelEdit();
    expect(details[0].schedule).toBeNull();

    el._beginEdit();
    el._setDay("mon", [r("09:00", "12:00")]);
    await el._save();
    expect(details[1].schedule?.days.mon).toEqual([r("09:00", "12:00")]);
    expect(details[1].job?.job_id).toBe("job-1");
  });
});

describe("carte pièce", () => {
  function roomHass(getSchedule: Handler): { hass: HassLike; calls: Record<string, unknown>[] } {
    return fakeHass({
      rooms: () => ({
        rooms: ["13000000", "13000001"].map((id) => ({
          id,
          name: `Salle ${id}`,
          product_id: "synthetic00",
          heads: [],
          comfort: 21,
          setback: 16,
        })),
      }),
      "schedule/get": getSchedule,
      "schedule/validate": () => ({ valid: true, errors: [], transitions: {} }),
    });
  }

  async function loadedRoomCard(hass: HassLike): Promise<Internals> {
    const el = new DanfossAllyRoomCard() as Internals;
    el.setConfig({ room_id: "13000000" });
    el.hass = hass;
    el._loaded = true;
    await el._load();
    return el;
  }

  it("annuler l'éditeur imbriqué ne remplace pas une lecture plus fraîche du parent", async () => {
    vi.stubGlobal("document", { createElement: () => new DanfossAllyScheduleCard() });
    const { hass } = roomHass(() => schedule("13000000", [r("08:00", "12:00")]));
    const el = await loadedRoomCard(hass);
    el._toggleEdit();
    const child = el._schedCard as Internals;
    child._loaded = true;
    await child._load();
    // Le parent relit entre-temps (bouton « actualiser », toujours visible).
    const fresh = schedule("13000000", [r("06:00", "07:00")], "2026-01-05T09:00:00Z");
    el._schedule = fresh;
    child._cancelEdit();
    expect(el._editing).toBe(false);
    expect(el._schedule).toBe(fresh);
  });

  it("changer de pièce ne laisse pas le programme de l'ancienne sous le nouveau nom", async () => {
    const next = deferred<Schedule>();
    const { hass } = roomHass((msg) =>
      (msg.target as { id: string }).id === "13000000"
        ? schedule("13000000", [r("08:00", "12:00")])
        : next.promise,
    );
    const el = await loadedRoomCard(hass);
    el._job = job("13000000", "failed");
    el.setConfig({ room_id: "13000001" });
    expect(el._schedule).toBeNull();
    expect(el._job).toBeNull();
    next.resolve(schedule("13000001", [r("14:00", "18:00")]));
    await flush();
    expect(el._schedule.target.id).toBe("13000001");
  });

  it("± n'envoie qu'une consigne par clic, au pas, et montre l'échec", async () => {
    const pending = deferred<void>();
    const sent: Record<string, unknown>[] = [];
    const { hass } = fakeHass({
      rooms: () => ({
        rooms: [
          {
            id: "13000000",
            name: "Salle",
            product_id: "synthetic00",
            heads: [],
            comfort: 21,
            setback: 16,
            setpoint: 20.5,
            mode: "at_home",
            writable: true,
            climate_entity_id: "climate.salle",
          },
        ],
      }),
      "schedule/get": () => schedule("13000000", []),
    });
    hass.callService = async (_d, _s, data) => {
      sent.push(data ?? {});
      await pending.promise;
    };
    const el = await loadedRoomCard(hass);
    const a = el._adjust(1);
    const b = el._adjust(1);
    pending.reject(new Error("refusé"));
    await Promise.all([a, b]);
    expect(sent).toEqual([{ entity_id: "climate.salle", temperature: 21 }]);
    expect(el._error).not.toBeNull();
    expect(el._room.setpoint).toBe(20.5);
  });
});

describe("abonnement aux lots", () => {
  function subscribingHass(): { hass: HassLike; active: () => number } {
    let active = 0;
    const { hass } = fakeHass({
      rooms: () => ({ rooms: [] }),
      "schedule/get": () => schedule("13000000", []),
    });
    hass.connection = {
      subscribeMessage: (async () => {
        active += 1;
        return () => {
          active -= 1;
        };
      }) as NonNullable<HassLike["connection"]>["subscribeMessage"],
    };
    return { hass, active: () => active };
  }

  for (const [name, Card] of [
    ["carte programme", DanfossAllyScheduleCard],
    ["carte pièce", DanfossAllyRoomCard],
  ] as const) {
    it(`${name} : se réabonne après un détachement / rattachement au DOM`, async () => {
      const { hass, active } = subscribingHass();
      const el = new Card() as Internals;
      // Pas de rendu sans DOM : on neutralise la racine de rendu et les mises à jour.
      el.createRenderRoot = () => ({});
      el.enableUpdating = () => {};
      el.setConfig({ room_id: "13000000" });
      el.hass = hass;
      el._loaded = true;
      await el._load();
      expect(active()).toBe(1);
      el.disconnectedCallback();
      expect(active()).toBe(0);
      el.connectedCallback();
      await flush();
      expect(active()).toBe(1);
    });
  }
});

describe("jours du programme", () => {
  it("couvre les sept jours (garde-fou des fabriques de test)", () => {
    const days: DayKey[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
    expect(Object.keys(schedule("1", []).days)).toEqual(days);
  });
});
