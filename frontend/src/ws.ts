/**
 * Accès aux commandes WebSocket de l'intégration (contrat §5.3).
 *
 * Règle du contrat : l'interface n'appelle QUE ces commandes, jamais le cloud.
 * Les commandes `info` et `rooms` ne seront implémentées qu'au lot 2 ; en leur
 * absence, ces fonctions se dégradent proprement (null / liste vide) au lieu de
 * remonter une erreur bloquante.
 */
import type {
  DayKey,
  FleetOverview,
  HassLike,
  Info,
  Room,
  Schedule,
  Target,
  TimeRange,
  ValidateResponse,
  WriteJob,
} from "./types";

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

/**
 * Vue d'ensemble de la flotte (contrat §5.3 `overview`, §3.6). Renvoie `null` si
 * la commande manque (backend 0.5.x) ou échoue : le panneau se dégrade proprement.
 */
export async function fetchOverview(hass: HassLike): Promise<FleetOverview | null> {
  try {
    return await hass.callWS<FleetOverview>({ type: "danfoss_ally_cloud/overview" });
  } catch {
    return null;
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

/** Erreur typée d'une commande d'écriture (code stable du contrat §5.4). */
export class ScheduleCommandError extends Error {
  public readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
    this.name = "ScheduleCommandError";
  }
}

function toCommandError(err: unknown): ScheduleCommandError {
  // Home Assistant renvoie `{ code, message }` sur un échec de commande WS.
  if (err && typeof err === "object" && "code" in err) {
    const e = err as { code?: unknown; message?: unknown };
    return new ScheduleCommandError(
      typeof e.code === "string" ? e.code : "unknown",
      typeof e.message === "string" ? e.message : String(e.code),
    );
  }
  return new ScheduleCommandError("unknown", err instanceof Error ? err.message : String(err));
}

/**
 * Valide un ensemble de jours côté serveur (contrat §5.3 `schedule/validate`).
 * Renvoie `null` si la commande manque : l'interface retombe alors sur sa
 * validation locale (R1 portée en TS).
 */
export async function validateSchedule(
  hass: HassLike,
  days: Partial<Record<DayKey, TimeRange[]>>,
): Promise<ValidateResponse | null> {
  try {
    return await hass.callWS<ValidateResponse>({
      type: "danfoss_ally_cloud/schedule/validate",
      days,
    });
  } catch {
    return null;
  }
}

/**
 * Écrit les jours fournis (contrat §5.3 `schedule/set`, administrateur). Lève une
 * `ScheduleCommandError` au code stable en cas de refus (droits, R1, cloud…).
 */
export async function setSchedule(
  hass: HassLike,
  target: Target,
  days: Partial<Record<DayKey, TimeRange[]>>,
): Promise<WriteJob> {
  try {
    return await hass.callWS<WriteJob>({
      type: "danfoss_ally_cloud/schedule/set",
      target,
      days,
    });
  } catch (err) {
    throw toCommandError(err);
  }
}

/** Réécrit les sept jours puis publie `at_home` (contrat §5.3 `schedule/restore`, R4). */
export async function restoreSchedule(hass: HassLike, target: Target): Promise<WriteJob> {
  try {
    return await hass.callWS<WriteJob>({
      type: "danfoss_ally_cloud/schedule/restore",
      target,
    });
  } catch (err) {
    throw toCommandError(err);
  }
}

/**
 * S'abonne au flux des lots d'écriture (contrat §5.3 `jobs/subscribe`). Renvoie
 * une fonction de désabonnement. Sans connexion WS (démo, tests), l'abonnement
 * ne fait rien et la fonction renvoyée est un no-op.
 */
export async function subscribeJobs(
  hass: HassLike,
  callback: (job: WriteJob) => void,
): Promise<() => void> {
  if (!hass.connection) {
    return () => {};
  }
  try {
    return await hass.connection.subscribeMessage<WriteJob>(callback, {
      type: "danfoss_ally_cloud/jobs/subscribe",
    });
  } catch {
    return () => {};
  }
}

/** Réponse de `relay/link_room` : la demande est partie vers le pont, pas encore appliquée. */
export interface RelayLinkSent {
  relay: string;
  room_id: string;
  linked: boolean;
  status: "sent";
}

/**
 * Demande au pont de lier / délier une pièce d'un relais (contrat companion §3,
 * `relay/link_room`, administrateur). ⚠ Change la demande de chauffe de la chaudière.
 * Lève une `ScheduleCommandError` au code stable en cas de refus ; un succès veut dire
 * « envoyé » : le nouvel état n'existe qu'une fois relu dans `overview`.
 */
export async function linkRelayRoom(
  hass: HassLike,
  relay: string,
  roomId: string,
  linked: boolean,
): Promise<RelayLinkSent> {
  try {
    return await hass.callWS<RelayLinkSent>({
      type: "danfoss_ally_cloud/relay/link_room",
      relay,
      room_id: roomId,
      linked,
    });
  } catch (err) {
    throw toCommandError(err);
  }
}
