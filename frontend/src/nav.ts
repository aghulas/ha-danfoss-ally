/**
 * Navigation du panneau (contrat §8.2) : logique pure, sans DOM ni Home Assistant.
 *
 * Le panneau a une adresse par niveau, sous son préfixe (`/danfoss-ally-cloud`) :
 * `""` ou `/` = le bâtiment (vue d'ensemble), `/room/<id>` = une pièce. Home Assistant
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
export type PanelView = { view: "fleet" } | { view: "room"; roomId: string };

/** Lit un `path` de panneau. Tout chemin inconnu ou mal formé retombe sur le bâtiment. */
export function parsePath(path: string | undefined | null): PanelView {
  const parts = (path ?? "").split("/").filter((p) => p !== "");
  if (parts.length === 2 && parts[0] === "room") {
    try {
      const roomId = decodeURIComponent(parts[1]);
      if (roomId) {
        return { view: "room", roomId };
      }
    } catch {
      // Encodage invalide : bâtiment.
    }
  }
  return { view: "fleet" };
}

/** `path` du bâtiment. */
export const FLEET_PATH = "";

/** `path` d'une pièce (`id` de la vue d'ensemble : groupe, ou tête pour une pièce d'une tête). */
export function roomPath(roomId: string): string {
  return `/room/${encodeURIComponent(roomId)}`;
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
