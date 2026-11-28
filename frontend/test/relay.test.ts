/**
 * Pièces d'un relais de chaudière sur sa page (`room_link`) : logique pure et parcours
 * du panneau, sans DOM. Données synthétiques uniquement.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { DanfossAllyPanel, RELAY_WATCH_TRIES } from "../src/panel";
import { findRelay, pendingConfirmed, relayRoomRows } from "../src/relay";
import type { FleetOverview, FleetRelay, FleetRelayRoom } from "../src/types";

const rooms = (...linked: boolean[]): FleetRelayRoom[] =>
  linked.map((flag, i) => ({ room_id: String(70 + i), name: `Salle ${i}`, linked: flag }));

const relay = (extra: Partial<FleetRelay> = {}): FleetRelay => ({
  device_id: "r1",
  name: "Relais chaufferie",
  on: false,
  online: true,
  linked_rooms: 2,
  rooms: rooms(true, false, true),
  room_link_writable: true,
  ...extra,
});

const overviewWith = (r: FleetRelay): FleetOverview =>
  ({
    homes: [
      { gid: "h1", name: "École", holiday_active: false, gateways: [], rooms: [], relays: [r] },
    ],
    totals: {},
  }) as unknown as FleetOverview;

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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("relais — logique pure", () => {
  it("propose lier / délier seulement si accessible en écriture", () => {
    const rows = relayRoomRows(relay(), true, null);
    expect(rows.map((r) => r.action)).toEqual(["unlink", "link", "unlink"]);
    expect(relayRoomRows(relay(), false, null).every((r) => r.action === null)).toBe(true);
  });

  it("ne propose jamais de délier la dernière pièce liée", () => {
    const rows = relayRoomRows(relay({ rooms: rooms(true, false) }), true, null);
    expect(rows[0]).toMatchObject({ action: null, last_linked: true });
    expect(rows[1].action).toBe("link");
  });

  it("une demande en cours bloque tous les gestes du relais et marque sa pièce", () => {
    const rows = relayRoomRows(relay(), true, { relay: "r1", room_id: "71", linked: true });
    expect(rows.every((r) => r.action === null)).toBe(true);
    expect(rows.map((r) => r.pending)).toEqual([false, true, false]);
    // Une demande sur un autre relais ne bloque pas celui-ci.
    expect(relayRoomRows(relay(), true, { relay: "r2", room_id: "71", linked: true })[1].action).toBe(
      "link",
    );
  });

  it("confirme seulement quand le pont a relu l'état demandé", () => {
    const pending = { relay: "r1", room_id: "71", linked: true };
    expect(pendingConfirmed(overviewWith(relay()), pending)).toBe(false);
    expect(pendingConfirmed(overviewWith(relay({ rooms: rooms(true, true, true) })), pending)).toBe(
      true,
    );
    expect(pendingConfirmed(null, pending)).toBe(false);
    expect(findRelay(overviewWith(relay()), "ghost")).toBeUndefined();
  });
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Internals = any;

function panel(r: FleetRelay, callWS: (msg: Record<string, unknown>) => Promise<unknown>, admin = true) {
  const el: Internals = new DanfossAllyPanel();
  el.hass = { callWS, language: "en", user: { is_admin: admin } };
  el._overview = overviewWith(r);
  el._sleep = async () => {};
  return el;
}

describe("relais — page du panneau", () => {
  it("lecture seule sans annonce du pont ou sans droits d'administrateur", () => {
    for (const el of [
      panel(relay({ room_link_writable: false }), async () => ({})),
      panel(relay(), async () => ({}), false),
    ]) {
      const text = templateText(el._renderRelayRooms(el._overview.homes[0].relays[0]));
      expect(text).toContain("Read-only");
      expect(text).toContain("Salle 1");
      expect(text).not.toContain("relay-room-action");
    }
  });

  it("avertit que la demande de chauffe change, et propose les gestes", () => {
    const el = panel(relay(), async () => ({}));
    const text = templateText(el._renderRelayRooms(el._overview.homes[0].relays[0]));
    expect(text).toContain("changes the boiler's heat demand");
    expect(text).toContain("Unlink");
    expect(text).toContain("Link");
  });

  it("retombe sur les noms des pièces liées avec un backend plus ancien", () => {
    const el = panel(relay({ rooms: undefined, linked_room_names: ["Salle A"] }), async () => ({}));
    const text = templateText(el._renderRelayRooms(el._overview.homes[0].relays[0]));
    expect(text).toContain("Rooms driving this relay");
    expect(text).toContain("Salle A");
  });

  it("envoie après confirmation puis attend la relecture du pont", async () => {
    const calls: Record<string, unknown>[] = [];
    let reads = 0;
    const el = panel(relay(), async (msg) => {
      calls.push(msg);
      if (msg.type === "danfoss_ally_cloud/overview") {
        reads += 1;
        // Première relecture : pas encore appliqué ; seconde : appliqué.
        return overviewWith(relay({ rooms: reads >= 2 ? rooms(true, true, true) : rooms(true, false, true) }));
      }
      return { status: "sent" };
    });
    vi.stubGlobal("confirm", () => true);
    const target = el._overview.homes[0].relays[0];
    const done = el._toggleRelayRoom(target, target.rooms[1]);
    expect(el._relayPending).toBeNull(); // pas avant la réponse du backend
    await done;
    expect(calls[0]).toEqual({
      type: "danfoss_ally_cloud/relay/link_room",
      relay: "r1",
      room_id: "71",
      linked: true,
    });
    expect(reads).toBe(2);
    expect(el._relayPending).toBeNull();
    expect(el._relayNote).toBeNull();
    expect(el._overview.homes[0].relays[0].rooms[1].linked).toBe(true);
  });

  it("n'envoie rien sans confirmation", async () => {
    const callWS = vi.fn(async () => ({}));
    const el = panel(relay(), callWS);
    vi.stubGlobal("confirm", () => false);
    const target = el._overview.homes[0].relays[0];
    await el._toggleRelayRoom(target, target.rooms[1]);
    expect(callWS).not.toHaveBeenCalled();
  });

  it("affiche le refus du backend sans rien supposer", async () => {
    const el = panel(relay(), async () => {
      throw { code: "relay_link_unavailable", message: "closed" };
    });
    vi.stubGlobal("confirm", () => true);
    const target = el._overview.homes[0].relays[0];
    await el._toggleRelayRoom(target, target.rooms[1]);
    expect(el._relayNote).toContain("closed");
    expect(el._overview.homes[0].relays[0].rooms[1].linked).toBe(false);
  });

  it("signale un délai dépassé quand le pont ne confirme pas", async () => {
    let reads = 0;
    const el = panel(relay(), async (msg) => {
      if (msg.type === "danfoss_ally_cloud/overview") {
        reads += 1;
        return overviewWith(relay());
      }
      return { status: "sent" };
    });
    vi.stubGlobal("confirm", () => true);
    const target = el._overview.homes[0].relays[0];
    await el._toggleRelayRoom(target, target.rooms[1]);
    expect(reads).toBe(RELAY_WATCH_TRIES);
    expect(el._relayNote).toContain("not confirmed");
    expect(el._relayPending).toBeNull();
  });
});
