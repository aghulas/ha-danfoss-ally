/**
 * Pièces d'un relais de chaudière sur sa page (contrat companion §3, `room_link`).
 *
 * Logique pure, sans DOM : quelles pièces montrer, lesquelles peuvent être liées ou
 * déliées, et quand une demande est confirmée. L'état affiché est TOUJOURS celui que
 * le pont a relu (`bridge/relays` via `overview`), jamais celui demandé.
 */
import type { FleetOverview, FleetRelay, FleetRelayRoom } from "./types";

/** Demande en cours : envoyée au pont, pas encore relue dans `bridge/relays`. */
export interface RelayPending {
  relay: string;
  room_id: string;
  linked: boolean;
}

/** Ligne d'une pièce sur la page du relais. */
export interface RelayRoomRow extends FleetRelayRoom {
  /** Attend la relecture du pont. */
  pending: boolean;
  /** Geste possible maintenant, ou `null` (lecture seule, demande en cours, dernière pièce). */
  action: "link" | "unlink" | null;
  /** Dernière pièce liée : le pont refuse de la délier (la chaudière ne serait plus sollicitée). */
  last_linked: boolean;
}

/**
 * Lignes des pièces d'un relais, triées par le backend. `writable` : le pont annonce
 * `room_link` pour ce relais ET l'utilisateur est administrateur.
 */
export function relayRoomRows(
  relay: FleetRelay,
  writable: boolean,
  pending: RelayPending | null,
): RelayRoomRow[] {
  const rooms = relay.rooms ?? [];
  const linkedCount = rooms.filter((r) => r.linked).length;
  const busy = pending !== null && pending.relay === relay.device_id;
  return rooms.map((room) => {
    const isPending = busy && pending.room_id === room.room_id;
    const lastLinked = room.linked && linkedCount <= 1;
    let action: RelayRoomRow["action"] = null;
    if (writable && !busy && !lastLinked) {
      action = room.linked ? "unlink" : "link";
    }
    return { ...room, pending: isPending, action, last_linked: lastLinked };
  });
}

/** Le relais de cette vue d'ensemble, ou `undefined`. */
export function findRelay(overview: FleetOverview | null, relayId: string): FleetRelay | undefined {
  for (const home of overview?.homes ?? []) {
    const relay = home.relays.find((r) => r.device_id === relayId);
    if (relay) {
      return relay;
    }
  }
  return undefined;
}

/** Vrai quand la vue d'ensemble montre la pièce dans l'état demandé (relu par le pont). */
export function pendingConfirmed(overview: FleetOverview | null, pending: RelayPending): boolean {
  const room = findRelay(overview, pending.relay)?.rooms?.find((r) => r.room_id === pending.room_id);
  return room !== undefined && room.linked === pending.linked;
}
