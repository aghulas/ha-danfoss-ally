/**
 * Navigation du panneau (contrat §8.2) : logique pure, sans DOM ni Home Assistant.
 *
 * Le panneau a une adresse par niveau, sous son préfixe (`/danfoss-ally-cloud`) :
 * `""` ou `/` = le bâtiment (vue d'ensemble), `/room/<id>` = une pièce,
 * `/device/<id>` = un élément (tête, relais, passerelle), `/room/<id>/device/<id>` = une
 * tête atteinte depuis sa pièce (même page, le fil d'Ariane garde la pièce). Home Assistant
 * donne au panneau sa `route` (`{ prefix, path }`) ; ce module ne fait que lire et
 * écrire le `path`, et retrouver une pièce dans la vue d'ensemble.
 */
import type { FleetHome, FleetOverview, FleetRoom } from "./types";

/** Route que Home Assistant passe à un panneau personnalisé. */
export interface PanelRoute {
  prefix: string;
  path: string;
}

/** Niveau affiché par le panneau. */
export type PanelView =
  | { view: "fleet" }
  | { view: "room"; roomId: string }
  | { view: "element"; deviceId: string; roomId?: string };

/** Lit un `path` de panneau. Tout chemin inconnu ou mal formé retombe sur le bâtiment. */
export function parsePath(path: string | undefined | null): PanelView {
  const parts = (path ?? "").split("/").filter((p) => p !== "");
  try {
    const ids = parts.map((p, i) => (i % 2 === 1 ? decodeURIComponent(p) : p));
    if (ids.length === 2 && ids[0] === "room" && ids[1]) {
      return { view: "room", roomId: ids[1] };
    }
    if (ids.length === 2 && ids[0] === "device" && ids[1]) {
      return { view: "element", deviceId: ids[1] };
    }
    if (ids.length === 4 && ids[0] === "room" && ids[2] === "device" && ids[1] && ids[3]) {
      return { view: "element", roomId: ids[1], deviceId: ids[3] };
    }
  } catch {
    // Encodage invalide : bâtiment.
  }
  return { view: "fleet" };
}

/** `path` du bâtiment. */
export const FLEET_PATH = "";

/** `path` d'une pièce (`id` de la vue d'ensemble : groupe, ou tête pour une pièce d'une tête). */
export function roomPath(roomId: string): string {
  return `/room/${encodeURIComponent(roomId)}`;
}

/** `path` d'un élément ; avec `roomId`, la tête garde sa pièce dans le fil d'Ariane. */
export function elementPath(deviceId: string, roomId?: string): string {
  const tail = `/device/${encodeURIComponent(deviceId)}`;
  return roomId ? `${roomPath(roomId)}${tail}` : tail;
}

/** Retrouve une pièce et sa maison dans la vue d'ensemble, ou `null`. */
export function findRoom(
  overview: FleetOverview | null,
  roomId: string,
): { home: FleetHome; room: FleetRoom } | null {
  for (const home of overview?.homes ?? []) {
    const room = home.rooms.find((r) => r.id === roomId);
    if (room) {
      return { home, room };
    }
  }
  return null;
}
