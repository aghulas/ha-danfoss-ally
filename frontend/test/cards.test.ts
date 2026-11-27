/**
 * Tests de comportement des deux cartes (revue de la PR 112), sans DOM : les
 * éléments sont instanciés mais jamais connectés (Lit ne rend donc rien), et on
 * pilote leurs méthodes comme le feraient les gestes de l'utilisateur.
 * Données synthétiques uniquement.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { DanfossAllyPanel } from "../src/panel";
import { DanfossAllyRoomCard } from "../src/room-card";
import { DanfossAllyRoomCardEditor } from "../src/room-card-editor";
import { DanfossAllyScheduleCard } from "../src/schedule-card";
import type { DayKey, HassLike, RoomCardConfig, Schedule, TimeRange, WriteJob } from "../src/types";
import { building } from "./area-fixture";

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

  it("pendant la première lecture, la carte dit qu'elle charge, pas « pièce inconnue »", async () => {
    const gate = deferred<{ rooms: unknown[] }>();
    const { hass } = fakeHass({
      rooms: () => gate.promise,
      "schedule/get": () => schedule("13000000", []),
    });
    const el = new DanfossAllyRoomCard() as Internals;
    el.setConfig({ room_id: "13000000" });
    el.hass = { ...hass, language: "en" };
    el._loaded = true;
    const load = el._load();
    let text = templateText(el.render());
    expect(text).toContain("Loading…");
    expect(text).not.toContain("Unknown room");
    expect(text).not.toContain("No thermostat");
    gate.resolve({ rooms: [] }); // lecture aboutie, pièce absente : là, elle est inconnue
    await load;
    text = templateText(el.render());
    expect(text).toContain("Unknown room (13000000)");
    expect(text).not.toContain("Loading…");
    // Changer de pièce remet la carte en chargement.
    el.setConfig({ room_id: "13000001" });
    expect(templateText(el.render())).toContain("Loading…");
  });

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

describe("carte pièce par zone", () => {
  function areaHass(isAdmin = true): {
    hass: HassLike;
    calls: Record<string, unknown>[];
    sent: Record<string, unknown>[];
  } {
    const sent: Record<string, unknown>[] = [];
    const { hass, calls } = fakeHass(
      {
        rooms: () => ({
          rooms: [
            {
              id: "13000000",
              name: "Salle Ally",
              product_id: "synthetic00",
              heads: [],
              comfort: 21,
              setback: 16,
              setpoint: 21,
              mode: "at_home",
              writable: true,
              climate_entity_id: "climate.bureau",
            },
          ],
        }),
        "schedule/get": (msg) => schedule((msg.target as { id: string }).id, []),
      },
      isAdmin,
    );
    Object.assign(hass, building());
    hass.callService = async (domain, service, data) => {
      sent.push({ domain, service, ...(data ?? {}) });
    };
    return { hass, calls, sent };
  }

  async function loaded(hass: HassLike, config: RoomCardConfig): Promise<Internals> {
    const el = new DanfossAllyRoomCard() as Internals;
    el.setConfig(config);
    el.hass = hass;
    el._loaded = true;
    await el._load();
    return el;
  }

  it("une zone qui contient une pièce Ally garde la pièce et son programme", async () => {
    const { hass, calls } = areaHass();
    const el = await loaded(hass, { area_id: "bureau" });
    expect(el._roomId).toBe("13000000");
    expect(el._room.name).toBe("Salle Ally");
    expect(el._schedule.target.id).toBe("13000000");
    expect(calls.filter((c) => c.type === "danfoss_ally_cloud/schedule/get")).toHaveLength(1);
    // Les lots de la pièce de la zone sont suivis.
    el._onJob(job("13000000"));
    expect(el._job?.target.id).toBe("13000000");
    // La ligne « autres thermostats » ne reprend pas le thermostat de la pièce.
    const text = templateText(el._renderAreaClimates(el._room));
    expect(text).toContain("bureau_tete");
    expect(text).not.toContain(">Bureau<");
  });

  it("une zone sans pièce Ally ne lit aucun programme et liste ses climates", async () => {
    const { hass, calls } = areaHass();
    const el = await loaded(hass, { area_id: "salon" });
    expect(el._roomId).toBeUndefined();
    expect(el._schedule).toBeNull();
    expect(calls.some((c) => c.type === "danfoss_ally_cloud/schedule/get")).toBe(false);
    const text = templateText(el._renderAreaClimates(undefined));
    expect(text).toContain("salon_fenetre");
    expect(text).toContain("salon_porte");
    expect(el._title(undefined)).toBe("Salon");
  });

  it("± sur un climate hors Ally : set_temperature au pas, un seul envoi à la fois", async () => {
    const { hass, sent } = areaHass();
    const el = await loaded(hass, { area_id: "salon", allow_foreign_writes: true });
    const a = el._adjustClimate("climate.salon_fenetre", 1);
    const b = el._adjustClimate("climate.salon_fenetre", 1);
    await Promise.all([a, b]);
    expect(sent).toEqual([
      {
        domain: "climate",
        service: "set_temperature",
        entity_id: "climate.salon_fenetre",
        temperature: 20.5,
      },
    ]);
  });

  it("aucune écriture générique sur un climate Ally, indisponible, ou sans droits", async () => {
    const admin = areaHass();
    const el = await loaded(admin.hass, { area_id: "bureau", allow_foreign_writes: true });
    await el._adjustClimate("climate.bureau", 1);
    await el._adjustClimate("climate.salon_porte", 1);
    expect(admin.sent).toEqual([]);

    const user = areaHass(false);
    const ro = await loaded(user.hass, { area_id: "salon", allow_foreign_writes: true });
    await ro._adjustClimate("climate.salon_fenetre", 1);
    expect(user.sent).toEqual([]);
  });

  it("sans `allow_foreign_writes`, la carte est en lecture seule pour les autres intégrations", async () => {
    const { hass, sent } = areaHass();
    const el = await loaded(hass, { area_id: "salon" });
    await el._adjustClimate("climate.salon_fenetre", 1);
    expect(sent).toEqual([]);
    expect(el._canWriteForeign).toBe(false);
  });

  it("une tête Ally vue par une autre intégration n'est jamais écrite, même autorisée", async () => {
    const { hass, sent } = areaHass();
    const entry = (hass.entities as Record<string, { platform?: string }>)["climate.salon_fenetre"];
    entry.platform = "danfoss_ally";
    const el = await loaded(hass, { area_id: "salon", allow_foreign_writes: true });
    await el._adjustClimate("climate.salon_fenetre", 1);
    expect(sent).toEqual([]);
  });

  it("sans `info`, le droit d'écrire vient de l'utilisateur du frontend", async () => {
    const { hass, sent } = areaHass();
    const el = await loaded(hass, { area_id: "salon", allow_foreign_writes: true });
    el._info = null;
    hass.user = { is_admin: false };
    await el._adjustClimate("climate.salon_fenetre", 1);
    expect(sent).toEqual([]);
    hass.user = { is_admin: true };
    await el._adjustClimate("climate.salon_fenetre", 1);
    expect(sent).toHaveLength(1);
  });

  it("un échec d'écriture s'affiche avec le nom du climate", async () => {
    const { hass } = areaHass();
    hass.callService = async () => {
      throw new Error("refusé");
    };
    const el = await loaded(hass, { area_id: "salon", allow_foreign_writes: true });
    await el._adjustClimate("climate.salon_fenetre", -1);
    expect(el._error).toContain("salon_fenetre");
    expect(el._busyClimate).toBeNull();
  });

  it("passer d'une zone à une autre jette le programme de l'ancienne pièce", async () => {
    const { hass } = areaHass();
    const el = await loaded(hass, { area_id: "bureau" });
    expect(el._schedule).not.toBeNull();
    el.setConfig({ area_id: "salon" });
    expect(el._schedule).toBeNull();
    await flush();
    expect(el._schedule).toBeNull();
  });

  it("montre le capteur de pièce de la zone et la régulation sur capteur externe", async () => {
    const { hass } = areaHass();
    const reg = hass as unknown as ReturnType<typeof building>;
    reg.devices["dev-s"] = { id: "dev-s", area_id: "salon" };
    reg.entities["sensor.salon_temperature"] = { entity_id: "sensor.salon_temperature", device_id: "dev-s" };
    reg.states["sensor.salon_temperature"] = {
      entity_id: "sensor.salon_temperature",
      state: "17.48",
      attributes: { device_class: "temperature" },
    };
    reg.entities["number.salon_fenetre_external_measured_room_sensor"] = {
      entity_id: "number.salon_fenetre_external_measured_room_sensor",
      device_id: "dev-z1",
    };
    reg.states["number.salon_fenetre_external_measured_room_sensor"] = {
      entity_id: "number.salon_fenetre_external_measured_room_sensor",
      state: "1736",
      attributes: {},
    };
    const el = await loaded(hass, { area_id: "salon" });
    const header = templateText(el._renderRoomSensors());
    expect(header).toContain("17.5 °C");
    expect(header).toContain("Room sensor");
    const rows = templateText(el._renderAreaClimates(undefined));
    // The head shows the temperature it regulates on, and its own reading, labelled.
    expect(rows).toContain("17.4 °C");
    expect(rows).toContain("head's own reading 19.5 °C");
    expect(rows).toContain("Regulates on an external room sensor");
  });

  it("sans capteur de pièce ni capteur externe, rien ne change", async () => {
    const { hass } = areaHass();
    const el = await loaded(hass, { area_id: "salon" });
    expect(templateText(el._renderRoomSensors())).toBe("");
    const rows = templateText(el._renderAreaClimates(undefined));
    expect(rows).not.toContain("external");
  });

  it("une zone inconnue le dit", async () => {
    const { hass } = areaHass();
    const el = await loaded(hass, { area_id: "grenier" });
    expect(el._title(undefined)).toContain("grenier");
  });
});

describe("éditeur de la carte pièce", () => {
  it("choisir une zone retire la pièce, et inversement", () => {
    const el = new DanfossAllyRoomCardEditor() as Internals;
    const emitted: RoomCardConfig[] = [];
    el.dispatchEvent = (ev: CustomEvent<{ config: RoomCardConfig }>) => {
      emitted.push(ev.detail.config);
      return true;
    };
    el.setConfig({ type: "custom:danfoss-ally-room-card", room_id: "13000000" });
    el._pick("area_id", "salon");
    el._pick("room_id", "13000001");
    expect(emitted).toEqual([
      { type: "custom:danfoss-ally-room-card", area_id: "salon" },
      { type: "custom:danfoss-ally-room-card", room_id: "13000001" },
    ]);
  });

  it("ne propose que les zones qui contiennent un climate", () => {
    const el = new DanfossAllyRoomCardEditor() as Internals;
    el.hass = { callWS: async () => ({}), ...building() };
    expect(el._areas.map((a: { area_id: string }) => a.area_id)).toEqual(["bureau", "salon"]);
  });
});

describe("panneau — autres zones", () => {
  it("résume les zones des climates d'autres intégrations, sans ceux de l'intégration", () => {
    const el = new DanfossAllyPanel() as Internals;
    el.hass = { callWS: async () => ({}), language: "en", ...building() };
    const text = templateText(el._renderOtherAreas());
    expect(text).toContain("Salon");
    expect(text).toContain("Bureau");
    expect(text).toContain("1 offline");
    expect(text).toContain("1 low battery");
    // Bureau : seule la tête Zigbee2MQTT compte (1×), pas le thermostat de pièce Ally.
    expect(text).toMatch(/Bureau[\s\S]*1×/);
  });

  it("le bouton masque la section, et le choix se garde dans le navigateur", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    });
    const el = new DanfossAllyPanel() as Internals;
    expect(el._showOtherAreas).toBe(false); // masquée par défaut
    el._toggleOtherAreas();
    expect(el._showOtherAreas).toBe(true);
    expect(new DanfossAllyPanel()["_showOtherAreas" as keyof DanfossAllyPanel]).toBe(true);
  });

  it("sans stockage (navigation privée), la section reste masquée", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    const el = new DanfossAllyPanel() as Internals;
    expect(el._showOtherAreas).toBe(false);
    el._toggleOtherAreas();
    expect(el._showOtherAreas).toBe(true);
  });
});

describe("panneau — navigation", () => {
  const fleetRoom = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
    id,
    name,
    kind: "group",
    head_count: 2,
    offline: 1,
    low_battery: 0,
    heating: true,
    window_open: false,
    inconsistent: 0,
    faults: 0,
    temperature: 19.5,
    setpoint: 21,
    ...extra,
  });
  const overview = {
    homes: [
      {
        gid: "h1",
        name: "École",
        holiday_active: false,
        gateways: [],
        relays: [],
        rooms: [
          fleetRoom("g1", "Salle 1"),
          fleetRoom("head-9", "Bureau", { kind: "single_head", head_count: 1, offline: 0 }),
        ],
      },
    ],
    totals: {},
  };

  function panel(route?: { prefix: string; path: string }): Internals {
    const el = new DanfossAllyPanel() as Internals;
    el.hass = { callWS: async () => ({}), language: "en" };
    el._overview = overview;
    if (route) {
      el.route = route;
      el.willUpdate(new Map([["route", undefined]]));
    }
    return el;
  }

  it("suit la route de Home Assistant et montre la page de la pièce", () => {
    const el = panel({ prefix: "/danfoss-ally-cloud", path: "/room/g1" });
    const text = templateText(el.render());
    expect(text).toContain("Building");
    expect(text).toContain("École");
    expect(text).toContain("Salle 1");
    expect(text).toContain("19.5 °C → 21 °C");
    expect(text).toContain("1 offline");
    expect(text).not.toContain("Other areas"); // bouton réservé au bâtiment
  });

  it("une tuile de pièce est un lien vers sa page", () => {
    const el = panel({ prefix: "/danfoss-ally-cloud", path: "" });
    expect(templateText(el.render())).toContain("/danfoss-ally-cloud/room/g1");
    expect(el._href("/room/a%2Fb")).toBe("/danfoss-ally-cloud/room/a%2Fb");
  });

  it("naviguer pousse une entrée d'historique et prévient Home Assistant", () => {
    const pushed: string[] = [];
    const events: string[] = [];
    vi.stubGlobal("history", { pushState: (_s: unknown, _t: string, url: string) => pushed.push(url) });
    vi.stubGlobal("window", { dispatchEvent: (ev: Event) => events.push(ev.type) });
    const el = panel({ prefix: "/danfoss-ally-cloud", path: "" });
    let prevented = false;
    el._navigate("/room/g1", { preventDefault: () => (prevented = true) });
    expect(prevented).toBe(true);
    expect(el._path).toBe("/room/g1");
    expect(pushed).toEqual(["/danfoss-ally-cloud/room/g1"]);
    expect(events).toEqual(["location-changed"]);
    // Même adresse : rien de plus.
    el._navigate("/room/g1");
    expect(pushed).toHaveLength(1);
  });

  it("un clic avec modificateur laisse le navigateur ouvrir le lien", () => {
    const el = panel({ prefix: "/p", path: "" });
    let prevented = false;
    el._navigate("/room/g1", { ctrlKey: true, preventDefault: () => (prevented = true) });
    expect(prevented).toBe(false);
    expect(el._path).toBe("");
  });

  it("hors Home Assistant (sans route), la navigation reste interne", () => {
    const el = panel();
    el._navigate("/room/g1");
    expect(el._path).toBe("/room/g1");
    expect(el._href("/room/g1")).toBe("#");
  });

  it("une pièce d'une seule tête a une page en lecture seule, sans carte pièce", () => {
    const el = panel({ prefix: "/p", path: "/room/head-9" });
    const text = templateText(el.render());
    expect(text).toContain("Bureau");
    expect(text).toContain("no room-level setting");
    expect(text).not.toContain("room-card-slot");
  });

  it("une pièce disparue ou une vue d'ensemble absente se dégrade, avec le fil d'Ariane", () => {
    const gone = panel({ prefix: "/p", path: "/room/gone" });
    expect(templateText(gone.render())).toContain("no longer in the fleet overview");
    const empty = panel({ prefix: "/p", path: "/room/g1" });
    empty._overview = null;
    const text = templateText(empty.render());
    expect(text).toContain("Building");
    expect(text).toContain("Fleet overview unavailable");
  });
});

describe("panneau — éléments", () => {
  const overview = {
    homes: [
      {
        gid: "h1",
        name: "École",
        holiday_active: false,
        gateways: [{ device_id: "gw1", name: "Passerelle", online: true, head_count: 2, relay_count: 1 }],
        relays: [{ device_id: "r1", name: "Relais chaufferie", on: true, online: false, linked_rooms: 2 }],
        rooms: [
          {
            id: "g1",
            name: "Salle 1",
            kind: "group",
            head_count: 1,
            offline: 0,
            low_battery: 0,
            heating: false,
            window_open: false,
            inconsistent: 0,
            faults: 0,
          },
        ],
      },
    ],
    totals: {},
  };
  const rooms = [
    {
      id: "g1",
      name: "Salle 1",
      heads: [
        {
          device_id: "a",
          name: "Salle 1 #1",
          room_id: "g1",
          online: true,
          mode_displayed: "at_home",
          schedule_active: false,
          preheat: null,
          mounting: false,
          inconsistent: false,
          battery: 80,
          valve_opening: 20,
          heat_request: null,
          window_open: true,
          window_detection: null,
          child_lock: null,
          faults: [{ code: "E14", label: "low battery" }],
        },
      ],
    },
  ];

  function panel(path: string, registries: Record<string, unknown> = {}): Internals {
    const el = new DanfossAllyPanel() as Internals;
    el.hass = { callWS: async () => ({}), language: "en", ...registries };
    el._overview = overview;
    el._rooms = rooms;
    el.route = { prefix: "/p", path };
    el.willUpdate(new Map([["route", undefined]]));
    return el;
  }

  it("le bâtiment relie relais et passerelles à leur page", () => {
    const text = templateText(panel("").render());
    expect(text).toContain("/p/device/r1");
    expect(text).toContain("/p/device/gw1");
  });

  it("la page d'une pièce liste ses têtes, chacune un lien", () => {
    const text = templateText(panel("/room/g1").render());
    expect(text).toContain("Elements");
    expect(text).toContain("/p/room/g1/device/a");
    expect(text).toContain("Battery 80%");
  });

  it("la page d'une tête montre son état connu et un lien vers sa pièce", () => {
    const text = templateText(panel("/device/a").render());
    expect(text).toContain("Thermostat");
    expect(text).toContain("/p/room/g1"); // fil d'Ariane vers la pièce réelle
    expect(text).toContain("Not following the schedule");
    expect(text).toContain("Window open");
    expect(text).toContain("Fault E14");
    expect(text).not.toContain("Calling for heat"); // champ `null` : rien n'est supposé
    expect(text).toContain("No Home Assistant device matches");
  });

  it("un relais hors ligne ne montre pas son dernier marche/arrêt", () => {
    const text = templateText(panel("/device/r1").render());
    expect(text).toContain("Boiler relay");
    expect(text).toContain("Offline");
    expect(text).not.toMatch(/>\s*On\s*</);
    expect(text).toContain("2 linked rooms");
  });

  it("une passerelle dit ce qu'elle porte", () => {
    expect(templateText(panel("/device/gw1").render())).toContain(
      "Carries 2 thermostat(s) and 1 relay(s)",
    );
  });

  it("les entités de l'appareil sont listées ; une indisponible le reste", () => {
    const el = panel("/device/a", {
      devices: { d1: { id: "d1", name: "Salle 1 #1", identifiers: [["danfoss_ally_cloud", "a"]] } },
      entities: {
        "number.off": { entity_id: "number.off", device_id: "d1", entity_category: "config" },
        "switch.pre": { entity_id: "switch.pre", device_id: "d1", entity_category: "config" },
      },
      states: {
        "number.off": {
          entity_id: "number.off",
          state: "0.5",
          attributes: { friendly_name: "Salle 1 #1 Offset", unit_of_measurement: "°C" },
        },
        "switch.pre": {
          entity_id: "switch.pre",
          state: "unavailable",
          attributes: { friendly_name: "Salle 1 #1 Preheat" },
        },
      },
    });
    const text = templateText(el.render());
    expect(text).toContain("Settings");
    expect(text).toContain("0.5 °C");
    expect(text).toMatch(/Preheat[\s\S]*Unavailable/);
    expect(text).not.toContain("No Home Assistant device");
  });

  it("une ligne d'entité ouvre la fenêtre d'entité de Home Assistant, sans rien écrire", () => {
    const el = panel("/device/a");
    const calls: unknown[] = [];
    el.hass.callWS = async (msg: unknown) => void calls.push(msg);
    el.hass.callService = async (...args: unknown[]) => void calls.push(args);
    const events: CustomEvent[] = [];
    el.dispatchEvent = (ev: CustomEvent) => (events.push(ev), true);
    el._moreInfo("switch.pre");
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("hass-more-info");
    expect(events[0].detail).toEqual({ entityId: "switch.pre" });
    expect(events[0].bubbles && events[0].composed).toBe(true);
    expect(calls).toEqual([]);
  });

  it("un élément disparu se dégrade avec le fil d'Ariane", () => {
    expect(templateText(panel("/device/gone").render())).toContain(
      "no longer in the fleet overview",
    );
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
