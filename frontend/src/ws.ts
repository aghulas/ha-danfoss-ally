/**
 * Accès aux commandes WebSocket de l'intégration (contrat §5.3).
 *
 * Règle du contrat : l'interface n'appelle QUE ces commandes, jamais le cloud.
 * Les commandes `info` et `rooms` ne seront implémentées qu'au lot 2 ; en leur
 * absence, ces fonctions se dégradent proprement (null / liste vide) au lieu de
 * remonter une erreur bloquante.
 */
import type { HassLike, Info, Room, Schedule, Target } from "./types";

/** Récupère la version/les droits côté serveur, ou `null` si la commande manque. */
export async function fetchInfo(hass: HassLike): Promise<Info | null> {
  try {
    return await hass.callWS<Info>({ type: "danfoss_ally_cloud/info" });
  } catch {
    return null;
  }
}

/** Liste les pièces, ou `[]` si la commande manque (lot 2 non déployé). */
export async function fetchRooms(hass: HassLike): Promise<Room[]> {
  try {
    const res = await hass.callWS<{ rooms?: Room[] }>({
      type: "danfoss_ally_cloud/rooms",
    });
    return res?.rooms ?? [];
  } catch {
    return [];
  }
}

/** Retrouve une pièce par son `group_id`, ou `undefined`. */
export function pickRoom(rooms: Room[], roomId: string | undefined): Room | undefined {
  if (!roomId) {
    return undefined;
  }
  return rooms.find((room) => room.id === roomId);
}

/**
 * Lit le programme d'une cible (contrat §5.3 `schedule/get`). `refresh` force une
 * relecture côté cloud. Renvoie `null` si la commande manque (lot 2 non déployé) ou
 * échoue : la carte se dégrade proprement.
 */
export async function fetchSchedule(
  hass: HassLike,
  target: Target,
  refresh = false,
): Promise<Schedule | null> {
  try {
    return await hass.callWS<Schedule>({
      type: "danfoss_ally_cloud/schedule/get",
      target,
      refresh,
    });
  } catch {
    return null;
  }
}
